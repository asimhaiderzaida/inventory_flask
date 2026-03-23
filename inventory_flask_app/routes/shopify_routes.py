"""Shopify integration blueprint — OAuth, product sync, webhook handling, order review."""
import json
import logging
import secrets
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, session, current_app, abort
)
from flask_login import login_required, current_user

from inventory_flask_app import db, csrf
from inventory_flask_app.models import (
    ProductInstance, ShopifyProduct, ShopifySyncLog, ShopifyOrder,
    Customer, TenantSettings, Notification, Order, SaleTransaction,
    SaleItem, Invoice, User, CustomerOrderTracking
)
from inventory_flask_app.utils.shopify_utils import (
    ShopifyClient, get_shopify_client, is_shopify_enabled,
    verify_webhook, build_description, build_title, build_tags,
    shorten_cpu, format_storage, log_sync, _get_setting, _set_setting,
)

logger = logging.getLogger(__name__)
shopify_bp = Blueprint('shopify_bp', __name__, url_prefix='/shopify')


# ─────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────

def _product_key(instance):
    """Build a stable product group key from make+model only (no grade).
    Returns None if make or model is blank — caller must guard against this.
    """
    p = instance.product
    make  = (getattr(p, 'make',  None) or '').strip()
    model = (getattr(p, 'model', None) or '').strip()
    if not make or not model:
        return None
    return f"{make}_{model}".replace(' ', '_').lower()


def _require_admin():
    if current_user.role != 'admin':
        abort(403)


def _find_or_add_variant(client, sp, instance, price=None):
    """Find a matching variant by RAM/Storage/CPU on an existing Shopify product,
    or add a new variant if none matches.

    Returns:
        (inventory_item_id, variant_id, was_existing)
        was_existing=True  → variant already existed, caller must increment inventory
        was_existing=False → new variant added with inventory_quantity=1
    """
    p = instance.product
    ram = p.ram or 'N/A'
    storage = format_storage(p.disk1size)
    cpu_short = shorten_cpu(p.cpu)

    prod_data = client.get(f"products/{sp.shopify_product_id}.json")
    variants = prod_data.get('product', {}).get('variants', [])
    logger.debug(f"_find_or_add_variant: looking for ram={ram!r} storage={storage!r} cpu={cpu_short!r} "
                f"among {len(variants)} variant(s) on product {sp.shopify_product_id}")

    def _norm(s):
        return str(s or '').strip().upper().replace(' ', '')

    for v in variants:
        if (_norm(v.get('option1')) == _norm(ram)
                and _norm(v.get('option2')) == _norm(storage)
                and _norm(v.get('option3')) == _norm(cpu_short)):
            logger.debug(f"_find_or_add_variant: MATCH found variant {v['id']}, inv_item={v['inventory_item_id']}")
            return str(v['inventory_item_id']), str(v['id']), True

    logger.debug(f"_find_or_add_variant: no match — creating new variant")
    # No matching variant — add one (inventory_quantity=1 is the implicit +1)
    grade = getattr(p, 'grade', '') or 'N/A'
    sku = f"{p.model or 'UNIT'}-{grade}-{instance.serial or ''}".replace(' ', '-')
    variant_price = str(price if price is not None else (instance.asking_price or 0))
    new_v = client.post(f"products/{sp.shopify_product_id}/variants.json", {
        'variant': {
            'option1': ram,
            'option2': storage,
            'option3': cpu_short,
            'price': variant_price,
            'sku': sku,
            'inventory_management': 'shopify',
            'inventory_quantity': 1,
            'requires_shipping': True,
        }
    })
    v = new_v.get('variant', {})
    return str(v.get('inventory_item_id', '')), str(v.get('id', '')), False


# ─────────────────────────────────────────────────────
# PHASE 2 — OAUTH FLOW
# ─────────────────────────────────────────────────────

@shopify_bp.route('/install')
@login_required
def install():
    """Start Shopify OAuth flow."""
    _require_admin()
    store_url   = current_app.config.get('SHOPIFY_STORE_URL', '')
    client_id   = current_app.config.get('SHOPIFY_CLIENT_ID', '')
    if not store_url or not client_id:
        flash("Shopify store URL / client ID not configured in .env", "danger")
        return redirect(url_for('shopify_bp.dashboard'))

    scope = (
        'read_products,write_products,'
        'read_inventory,write_inventory,'
        'read_orders,write_orders,'
        'read_customers,write_customers'
    )
    # Use explicit env override first; fall back to Flask's url_for (requires ProxyFix)
    redirect_uri = (
        current_app.config.get('SHOPIFY_REDIRECT_URI')
        or url_for('shopify_bp.oauth_callback', _external=True)
    )
    state = secrets.token_hex(16)
    session['shopify_oauth_state'] = state

    auth_url = (
        f"https://{store_url}/admin/oauth/authorize"
        f"?client_id={client_id}"
        f"&scope={scope}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return redirect(auth_url)


@shopify_bp.route('/connect_token', methods=['POST'])
@login_required
def connect_token():
    """Save a manually entered Admin API access token (Custom App flow)."""
    _require_admin()
    token = (request.form.get('access_token') or '').strip()
    if not token:
        flash("Access token cannot be empty.", "danger")
        return redirect(url_for('shopify_bp.dashboard'))

    # Test it immediately before saving
    store_url   = current_app.config.get('SHOPIFY_STORE_URL', '')
    api_version = current_app.config.get('SHOPIFY_API_VERSION', '2026-01')
    client = ShopifyClient(store_url, token, api_version)
    ok, result = client.test_connection()
    if not ok:
        flash(f"Token rejected by Shopify: {result}", "danger")
        return redirect(url_for('shopify_bp.dashboard'))

    _set_setting(current_user.tenant_id, 'shopify_access_token', token)
    _set_setting(current_user.tenant_id, 'enable_shopify_sync', 'true')
    _set_setting(current_user.tenant_id, 'shopify_push_enabled', 'true')
    _set_setting(current_user.tenant_id, 'shopify_pull_enabled', 'true')
    log_sync(current_user.tenant_id, 'manual_token_connect', 'push', 'success',
             f"Connected to store: {result}")
    flash(f"Connected to Shopify store: {result}", "success")
    return redirect(url_for('shopify_bp.dashboard'))


@shopify_bp.route('/callback')
@login_required
def oauth_callback():
    """Handle Shopify OAuth callback and exchange code for access token."""
    _require_admin()
    state = request.args.get('state', '')
    if state != session.pop('shopify_oauth_state', None):
        flash("OAuth state mismatch. Please try again.", "danger")
        return redirect(url_for('shopify_bp.dashboard'))

    code      = request.args.get('code', '')
    store_url = current_app.config.get('SHOPIFY_STORE_URL', '')
    client_id = current_app.config.get('SHOPIFY_CLIENT_ID', '')
    client_secret = current_app.config.get('SHOPIFY_CLIENT_SECRET', '')

    if not code:
        flash("No OAuth code received from Shopify.", "danger")
        return redirect(url_for('shopify_bp.dashboard'))

    try:
        import requests as _req
        resp = _req.post(
            f"https://{store_url}/admin/oauth/access_token",
            json={'client_id': client_id, 'client_secret': client_secret, 'code': code},
            timeout=15
        )
        resp.raise_for_status()
        access_token = resp.json().get('access_token', '')
        if not access_token:
            raise ValueError("No access_token in response")
    except Exception as e:
        logger.error(f"Shopify OAuth token exchange failed: {e}")
        flash(f"Failed to connect to Shopify: {e}", "danger")
        return redirect(url_for('shopify_bp.dashboard'))

    _set_setting(current_user.tenant_id, 'shopify_access_token', access_token)
    _set_setting(current_user.tenant_id, 'enable_shopify_sync', 'true')
    log_sync(current_user.tenant_id, 'oauth_connect', 'push', 'success', 'Connected via OAuth')
    flash("Shopify connected successfully!", "success")
    return redirect(url_for('shopify_bp.dashboard'))


# ─────────────────────────────────────────────────────
# PHASE 3 — DASHBOARD
# ─────────────────────────────────────────────────────

@shopify_bp.route('/')
@login_required
def dashboard():
    """Shopify integration dashboard."""
    tid = current_user.tenant_id
    access_token  = _get_setting(tid, 'shopify_access_token', '')
    is_connected  = bool(access_token)

    store_name    = None
    listed_count  = 0
    pending_count = 0
    order_count   = 0
    recent_logs   = []

    if is_connected:
        try:
            client = get_shopify_client(tid)
            if client:
                ok, name = client.test_connection()
                if ok:
                    store_name = name
                else:
                    flash(f"Shopify connection error: {name}", "warning")
        except Exception as e:
            logger.warning(f"Shopify dashboard connection test: {e}")

        listed_count  = ProductInstance.query.filter_by(tenant_id=tid, shopify_listed=True).count()
        pending_count = ShopifyOrder.query.filter_by(tenant_id=tid, status='draft').count()
        order_count   = ShopifyOrder.query.filter_by(tenant_id=tid).count()
        recent_logs   = (
            ShopifySyncLog.query
            .filter_by(tenant_id=tid)
            .order_by(ShopifySyncLog.created_at.desc())
            .limit(10).all()
        )

    settings = {
        'enable_shopify_sync':  _get_setting(tid, 'enable_shopify_sync', 'false'),
        'shopify_push_enabled': _get_setting(tid, 'shopify_push_enabled', 'true'),
        'shopify_pull_enabled': _get_setting(tid, 'shopify_pull_enabled', 'true'),
    }

    return render_template(
        'shopify/dashboard.html',
        is_connected=is_connected,
        store_name=store_name,
        settings=settings,
        listed_count=listed_count,
        pending_count=pending_count,
        order_count=order_count,
        recent_logs=recent_logs,
    )


@shopify_bp.route('/settings', methods=['POST'])
@login_required
def save_settings():
    """Save Shopify toggle settings."""
    _require_admin()
    tid = current_user.tenant_id
    for key in ('enable_shopify_sync', 'shopify_push_enabled', 'shopify_pull_enabled'):
        _set_setting(tid, key, 'true' if key in request.form else 'false')
    flash("Shopify settings saved.", "success")
    return redirect(url_for('shopify_bp.dashboard'))


@shopify_bp.route('/disconnect', methods=['POST'])
@login_required
def disconnect():
    """Remove stored access token to disconnect Shopify."""
    _require_admin()
    _set_setting(current_user.tenant_id, 'shopify_access_token', '')
    _set_setting(current_user.tenant_id, 'enable_shopify_sync', 'false')
    log_sync(current_user.tenant_id, 'oauth_disconnect', 'push', 'success', 'Disconnected')
    flash("Shopify disconnected.", "info")
    return redirect(url_for('shopify_bp.dashboard'))


@shopify_bp.route('/test_webhook_payload')
@login_required
def test_webhook_payload():
    """Show exactly what would be sent to Shopify for webhook registration."""
    store_url   = current_app.config.get('SHOPIFY_STORE_URL', '')
    public_base = (
        current_app.config.get('SHOPIFY_REDIRECT_URI', '').rsplit('/shopify/callback', 1)[0]
        or request.host_url.rstrip('/')
    )
    return jsonify({
        'url': f"https://{store_url}/admin/api/2024-01/webhooks.json",
        'public_base': public_base,
        'https_ok': public_base.startswith('https://'),
        'payloads': [
            {'webhook': {'topic': 'orders/create',
                         'address': f"{public_base}/shopify/webhook/orders_create",
                         'format': 'json'}},
            {'webhook': {'topic': 'orders/cancelled',
                         'address': f"{public_base}/shopify/webhook/orders_cancelled",
                         'format': 'json'}},
        ],
        'note': 'Shopify requires https:// — http:// addresses will be rejected with 422'
    })


@shopify_bp.route('/test')
@login_required
def test_connection():
    """AJAX endpoint: test Shopify API connectivity."""
    client = get_shopify_client(current_user.tenant_id)
    if not client:
        return jsonify(success=False, message="Not configured")
    ok, msg = client.test_connection()
    return jsonify(success=ok, message=msg)


# ─────────────────────────────────────────────────────
# PHASE 4 — PUSH UNITS TO SHOPIFY
# ─────────────────────────────────────────────────────

@shopify_bp.route('/publish/<int:instance_id>', methods=['POST'])
@login_required
def publish_instance(instance_id):
    """Publish a single unit to Shopify (create product or add inventory)."""
    tid = current_user.tenant_id
    instance = ProductInstance.query.filter_by(id=instance_id, tenant_id=tid).first_or_404()

    if not is_shopify_enabled(tid):
        return jsonify(success=False, message="Shopify sync is disabled"), 400

    push_enabled = _get_setting(tid, 'shopify_push_enabled', 'true')
    if push_enabled != 'true':
        return jsonify(success=False, message="Shopify push is disabled"), 400

    if not instance.asking_price:
        return jsonify(success=False, message="Unit has no asking price"), 400

    # Block publishing if unit has an active reservation
    reservation = CustomerOrderTracking.query.filter(
        CustomerOrderTracking.product_instance_id == instance_id,
        CustomerOrderTracking.status.in_(['reserved', 'delivered']),
    ).first()
    if reservation:
        return jsonify(success=False,
                       message='Cannot publish reserved unit to Shopify. Cancel reservation first.'), 400

    client = get_shopify_client(tid)
    if not client:
        return jsonify(success=False, message="Shopify not connected"), 400

    key = _product_key(instance)
    if not key:
        return jsonify(success=False,
                       message="Unit must have Make and Model set before publishing to Shopify"), 400

    p   = instance.product
    grade = getattr(p, 'grade', '') or 'N/A'

    try:
        existing = ShopifyProduct.query.filter_by(tenant_id=tid, product_key=key).first()

        if existing and existing.shopify_product_id:
            # Product group already on Shopify — find or add the right variant
            inv_item_id, variant_id, was_existing = _find_or_add_variant(client, existing, instance)
            if was_existing:
                # Variant existed — increment its inventory by 1
                _increment_shopify_inventory(client, int(inv_item_id))
            # Update SP record to point at the most recently used variant
            existing.shopify_variant_id        = variant_id
            existing.shopify_inventory_item_id = inv_item_id
            existing.last_synced_at = datetime.now(timezone.utc)
            existing.sync_status = 'synced'
            existing.sync_error = None
            # Re-activate if the product was previously drafted
            try:
                client.put(
                    f"products/{existing.shopify_product_id}.json",
                    {'product': {'id': int(existing.shopify_product_id), 'status': 'active'}},
                )
            except Exception as act_err:
                logger.warning(f"Could not set product to active: {act_err}")  # non-fatal
        else:
            # Brand-new Shopify product
            product_payload = {
                'product': {
                    'title': build_title(instance),
                    'body_html': build_description(instance),
                    'vendor': getattr(p, 'make', '') or 'PCMart',
                    'product_type': getattr(p, 'item_name', '') or 'Laptop',
                    'tags': build_tags(instance),
                    'status': 'active',
                    'options': [
                        {'name': 'Memory',    'values': [p.ram or 'N/A']},
                        {'name': 'Storage',   'values': [format_storage(p.disk1size)]},
                        {'name': 'Processor', 'values': [shorten_cpu(p.cpu)]},
                    ],
                    'variants': [{
                        'option1': p.ram or 'N/A',
                        'option2': format_storage(p.disk1size),
                        'option3': shorten_cpu(p.cpu),
                        'price': str(instance.asking_price or 0),
                        'sku': f"{p.model or 'UNIT'}-{grade}-{instance.serial or ''}".replace(' ', '-'),
                        'inventory_management': 'shopify',
                        'inventory_quantity': 1,
                        'requires_shipping': True,
                    }],
                }
            }
            result = client.post('products.json', product_payload)
            shopify_prod  = result.get('product', {})
            variant       = (shopify_prod.get('variants') or [{}])[0]

            if existing:
                existing.shopify_product_id        = str(shopify_prod.get('id', ''))
                existing.shopify_variant_id        = str(variant.get('id', ''))
                existing.shopify_inventory_item_id = str(variant.get('inventory_item_id', ''))
                existing.last_synced_at = datetime.now(timezone.utc)
                existing.sync_status = 'synced'
                existing.sync_error = None
            else:
                sp = ShopifyProduct(
                    tenant_id=tid,
                    product_key=key,
                    shopify_product_id=str(shopify_prod.get('id', '')),
                    shopify_variant_id=str(variant.get('id', '')),
                    shopify_inventory_item_id=str(variant.get('inventory_item_id', '')),
                    sync_status='synced',
                    last_synced_at=datetime.now(timezone.utc),
                )
                db.session.add(sp)

        instance.shopify_listed = True
        db.session.commit()
        log_sync(tid, 'publish', 'push', 'success',
                 f"instance {instance_id} key={key}", key)
        return jsonify(success=True, message="Published to Shopify")

    except Exception as e:
        db.session.rollback()
        err = str(e)
        logger.error(f"Shopify publish error instance {instance_id}: {err}")
        log_sync(tid, 'publish', 'push', 'error', err[:500])
        # Mark sync error if record exists
        existing = ShopifyProduct.query.filter_by(tenant_id=tid, product_key=key).first()
        if existing:
            existing.sync_status = 'error'
            existing.sync_error  = err[:500]
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return jsonify(success=False, message=f"Shopify error: {err}"), 500


@shopify_bp.route('/unpublish/<int:instance_id>', methods=['POST'])
@login_required
def unpublish_instance(instance_id):
    """Set inventory to 0 for a unit on Shopify and draft the product if all variants are empty."""
    tid = current_user.tenant_id
    instance = ProductInstance.query.filter_by(id=instance_id, tenant_id=tid).first_or_404()

    if not is_shopify_enabled(tid):
        return jsonify(success=False, message="Shopify sync disabled"), 400

    client = get_shopify_client(tid)
    if not client:
        return jsonify(success=False, message="Shopify not connected"), 400

    key = _product_key(instance)
    sp  = ShopifyProduct.query.filter_by(tenant_id=tid, product_key=key).first()
    if not sp:
        instance.shopify_listed = False
        db.session.commit()
        return jsonify(success=True, message="Unit was not listed")

    try:
        inv_id = sp.shopify_inventory_item_id
        if not inv_id:
            raise ValueError("No inventory_item_id on ShopifyProduct record")

        # Step 1 — get inventory levels to find location_id
        levels_data = client.get(
            f"inventory_levels.json?inventory_item_ids={inv_id}"
        )
        levels = levels_data.get('inventory_levels', [])
        if not levels:
            raise ValueError(f"No inventory levels found for item {inv_id}")

        location_id = str(levels[0]['location_id'])
        sp.shopify_location_id = location_id  # cache for future calls

        # Step 2 — hard-set inventory to 0
        client.post('inventory_levels/set.json', {
            'location_id': int(location_id),
            'inventory_item_id': int(inv_id),
            'available': 0,
        })

        # Step 3 — check if all variants are now at 0; if so, draft the product
        if sp.shopify_product_id:
            try:
                all_levels = client.get(
                    f"inventory_levels.json"
                    f"?location_ids={location_id}"
                )
                prod_data = client.get(f"products/{sp.shopify_product_id}.json")
                variant_inv_ids = {
                    str(v['inventory_item_id'])
                    for v in prod_data.get('product', {}).get('variants', [])
                }
                total_qty = sum(
                    lv.get('available', 0) or 0
                    for lv in all_levels.get('inventory_levels', [])
                    if str(lv.get('inventory_item_id')) in variant_inv_ids
                )
                if total_qty == 0:
                    client.put(
                        f"products/{sp.shopify_product_id}.json",
                        {'product': {'id': int(sp.shopify_product_id), 'status': 'draft'}},
                    )
                    logger.info(f"Product {sp.shopify_product_id} set to draft (all variants at 0)")
            except Exception as draft_err:
                logger.warning(f"Could not set product to draft: {draft_err}")  # non-fatal

        instance.shopify_listed = False
        db.session.commit()
        log_sync(tid, 'unpublish', 'push', 'success',
                 f"instance {instance_id} inventory set to 0, key={key}", key)
        return jsonify(success=True, message="Inventory set to 0 on Shopify")

    except Exception as e:
        db.session.rollback()
        err = str(e)
        logger.error(f"Shopify unpublish error instance {instance_id}: {err}")
        log_sync(tid, 'unpublish', 'push', 'error', err[:500])
        return jsonify(success=False, message=f"Shopify error: {err}"), 500


def _increment_shopify_inventory(client, inventory_item_id, delta=1):
    """Increment (or decrement) a Shopify inventory item by delta at the first location.

    Connects the item to the location first if not already connected, so this
    works correctly for variants that were just created.
    """
    try:
        # Step 1: Get locations
        loc_resp = client.get('locations.json')
        locations = loc_resp.get('locations', [])
        if not locations:
            raise Exception("No locations found in Shopify store")
        location_id = locations[0]['id']

        # Step 2: Connect inventory item to location (idempotent — ignore if already connected)
        try:
            client.post('inventory_levels/connect.json', {
                'location_id': location_id,
                'inventory_item_id': inventory_item_id,
            })
        except Exception:
            pass  # Already connected — safe to ignore

        # Step 3: Get current inventory level
        levels_resp = client.get(
            f'inventory_levels.json?inventory_item_ids={inventory_item_id}'
            f'&location_ids={location_id}'
        )
        levels = levels_resp.get('inventory_levels', [])
        current_qty = levels[0]['available'] if levels else 0
        if current_qty is None:
            current_qty = 0

        # Step 4: Set new quantity
        new_qty = max(0, current_qty + delta)
        client.post('inventory_levels/set.json', {
            'location_id': location_id,
            'inventory_item_id': inventory_item_id,
            'available': new_qty,
        })

        logger.debug(
            f"_increment_shopify_inventory: item={inventory_item_id} "
            f"loc={location_id} {current_qty} -> {new_qty}"
        )
        return new_qty

    except Exception as e:
        import traceback
        logger.error(
            f"_increment_shopify_inventory FAILED: item={inventory_item_id} "
            f"error={e}\n{traceback.format_exc()}"
        )
        raise


@shopify_bp.route('/delete_listing/<int:instance_id>', methods=['POST'])
@login_required
def delete_listing(instance_id):
    """Permanently delete a Shopify product listing and clean up all local records.

    Deletes the product from Shopify, removes the ShopifyProduct DB record, and
    marks all instances sharing the same product group (make/model/grade) as unlisted.
    Use this to remove badly-formatted listings before re-publishing.
    """
    _require_admin()
    if not is_shopify_enabled(current_user.tenant_id):
        flash("Shopify integration is not enabled.", "warning")
        return redirect(url_for('shopify_bp.shopify_dashboard'))
    tid = current_user.tenant_id
    instance = ProductInstance.query.filter_by(id=instance_id, tenant_id=tid).first_or_404()

    key = _product_key(instance)
    sp  = ShopifyProduct.query.filter_by(tenant_id=tid, product_key=key).first()

    client = get_shopify_client(tid)
    if sp and sp.shopify_product_id and client:
        try:
            client.delete(f"products/{sp.shopify_product_id}.json")
            log_sync(tid, 'delete_listing', 'push', 'success',
                     f"Deleted Shopify product {sp.shopify_product_id}",
                     sp.shopify_product_id)
        except Exception as e:
            # Log but continue cleanup — product may already be deleted on Shopify
            logger.warning(f"Shopify DELETE products/{sp.shopify_product_id} failed: {e}")
            log_sync(tid, 'delete_listing', 'push', 'error', str(e)[:500])

    if sp:
        db.session.delete(sp)

    # Clear shopify_listed on all instances that shared this product group
    p = instance.product
    grade_val = getattr(p, 'grade', None)
    q = ProductInstance.query.filter_by(
        tenant_id=tid, product_id=p.id, shopify_listed=True
    )
    if grade_val:
        q = q.filter_by(grade=grade_val)
    for inst in q.all():
        inst.shopify_listed = False

    db.session.commit()
    return jsonify(success=True,
                   message=f"Listing deleted. You can now re-publish with the correct format.")


@shopify_bp.route('/bulk_publish', methods=['POST'])
@login_required
def bulk_publish():
    """Publish multiple units to Shopify.

    Accepts JSON:
        {
            "instance_ids": [1, 2, 3],
            "spec_prices": {"16GB|512GB|i7-1355U": "999.00"}  # optional
        }
    Returns:
        {published, skipped, failed, errors}
    """
    tid = current_user.tenant_id
    if not is_shopify_enabled(tid):
        return jsonify(success=False, message="Shopify sync disabled"), 400

    data        = request.get_json(silent=True) or {}
    ids         = data.get('instance_ids', [])
    spec_prices = data.get('spec_prices', {})  # spec_key → price string

    if not ids:
        return jsonify(success=False, message="No instance IDs provided"), 400

    published = 0
    skipped   = 0
    failed    = 0
    errors    = []

    for iid in ids:
        try:
            instance = ProductInstance.query.filter_by(id=iid, tenant_id=tid).first()
            if not instance:
                errors.append(f"ID {iid}: not found")
                failed += 1
                continue

            # Skip reserved units
            reservation = CustomerOrderTracking.query.filter(
                CustomerOrderTracking.product_instance_id == iid,
                CustomerOrderTracking.status.in_(['reserved', 'delivered']),
            ).first()
            if reservation:
                errors.append(f"ID {iid}: reserved — skipped")
                skipped += 1
                continue

            # Skip already-listed units
            if instance.shopify_listed:
                skipped += 1
                continue

            # Resolve price override from spec_prices
            price_override = None
            if spec_prices:
                p = instance.product
                spec_key = f"{p.ram or 'N/A'}|{format_storage(p.disk1size)}|{shorten_cpu(p.cpu)}"
                if spec_key in spec_prices:
                    try:
                        price_override = float(spec_prices[spec_key])
                    except (ValueError, TypeError):
                        pass

            if price_override is None and not instance.asking_price:
                errors.append(f"ID {iid}: no asking price — skipped")
                skipped += 1
                continue

            # Save price to instance before publishing so it's persisted
            if price_override is not None:
                instance.asking_price = price_override
                db.session.commit()
                logger.info(f"bulk_publish: saved asking_price={price_override} to instance {iid}")

            logger.info(f"bulk_publish: publishing instance {iid}, price={price_override or instance.asking_price}")
            _publish_one(tid, instance, price_override=price_override)
            published += 1

        except Exception as e:
            logger.error(f"bulk_publish FAILED instance {iid}: {e}", exc_info=True)
            errors.append(f"ID {iid}: {e}")
            failed += 1

    return jsonify(published=published, skipped=skipped, failed=failed, errors=errors)


@shopify_bp.route('/api/instance_specs')
@login_required
def api_instance_specs():
    """Return spec groups (RAM/Storage/CPU) for given instance IDs.

    GET /shopify/api/instance_specs?ids=1,2,3

    Response:
        {
            "success": true,
            "groups": [
                {
                    "key": "16GB|512GB|i7-1355U",
                    "label": "16GB RAM • 512GB • i7-1355U",
                    "count": 3,
                    "suggested_price": 899.00,
                    "ids": [1, 2, 3]
                }
            ]
        }
    """
    from collections import defaultdict
    tid     = current_user.tenant_id
    raw_ids = request.args.get('ids', '')
    try:
        ids = [int(x) for x in raw_ids.split(',') if x.strip()]
    except ValueError:
        return jsonify(success=False, message="Invalid IDs"), 400

    if not ids:
        return jsonify(success=False, message="No IDs provided"), 400

    instances = ProductInstance.query.filter(
        ProductInstance.id.in_(ids),
        ProductInstance.tenant_id == tid,
    ).all()

    groups = defaultdict(list)
    for inst in instances:
        p       = inst.product
        ram     = p.ram or 'N/A'
        storage = format_storage(p.disk1size)
        cpu     = shorten_cpu(p.cpu)
        key     = f"{ram}|{storage}|{cpu}"
        groups[key].append(inst)

    result = []
    for key, grp in groups.items():
        ram, storage, cpu = key.split('|', 2)
        prices    = [i.asking_price for i in grp if i.asking_price]
        suggested = max(prices) if prices else None
        result.append({
            'key':             key,
            'label':           f"{ram} RAM \u2022 {storage} \u2022 {cpu}",
            'count':           len(grp),
            'suggested_price': float(suggested) if suggested else None,
            'ids':             [i.id for i in grp],
        })

    return jsonify(success=True, groups=result)


@shopify_bp.route('/api/group_instances', methods=['POST'])
@login_required
def api_group_instances():
    """Resolve model+cpu group strings (from instance_table checkboxes) to instance IDs.

    POST /shopify/api/group_instances
    Body: {"groups": ["Model|||CPU", ...]}

    Response: {"success": true, "instance_ids": [1, 2, 3]}
    """
    from inventory_flask_app.models import Product
    tid    = current_user.tenant_id
    data   = request.get_json(silent=True) or {}
    groups = data.get('groups', [])

    if not groups:
        return jsonify(success=False, message="No groups provided"), 400

    instance_ids = []
    for group_val in groups:
        parts = group_val.split('|||', 1)
        model = parts[0].strip() if parts else ''
        cpu   = parts[1].strip() if len(parts) > 1 else ''

        q = ProductInstance.query.join(Product).filter(
            ProductInstance.tenant_id == tid,
            ProductInstance.is_sold == False,
            Product.model == model,
        )
        if cpu:
            q = q.filter(Product.cpu == cpu)

        instance_ids.extend(inst.id for inst in q.all())

    return jsonify(success=True, instance_ids=list(set(instance_ids)))


def _publish_one(tid, instance, price_override=None):
    """Internal helper — publish a single instance (no HTTP response).

    price_override: if provided, use this price instead of instance.asking_price.
    """
    client = get_shopify_client(tid)
    if not client:
        raise ValueError("Shopify not connected")
    key = _product_key(instance)
    if not key:
        raise ValueError("Unit must have Make and Model set before publishing to Shopify")
    p     = instance.product
    grade = getattr(p, 'grade', '') or 'N/A'
    price = str(price_override if price_override is not None else (instance.asking_price or 0))
    existing = ShopifyProduct.query.filter_by(tenant_id=tid, product_key=key).first()

    if existing and existing.shopify_product_id:
        # Product group already on Shopify — find or add the right variant
        inv_item_id, variant_id, was_existing = _find_or_add_variant(
            client, existing, instance, price=float(price))
        if was_existing:
            _increment_shopify_inventory(client, int(inv_item_id))
        existing.shopify_variant_id        = variant_id
        existing.shopify_inventory_item_id = inv_item_id
        existing.last_synced_at = datetime.now(timezone.utc)
        existing.sync_status = 'synced'
        # Re-activate if the product was previously drafted
        try:
            client.put(
                f"products/{existing.shopify_product_id}.json",
                {'product': {'id': int(existing.shopify_product_id), 'status': 'active'}},
            )
        except Exception as act_err:
            logger.warning(f"Could not set product to active: {act_err}")  # non-fatal
    else:
        product_payload = {
            'product': {
                'title': build_title(instance),
                'body_html': build_description(instance),
                'vendor': getattr(p, 'make', '') or 'PCMart',
                'product_type': getattr(p, 'item_name', '') or 'Laptop',
                'tags': build_tags(instance),
                'status': 'active',
                'options': [
                    {'name': 'Memory',    'values': [p.ram or 'N/A']},
                    {'name': 'Storage',   'values': [format_storage(p.disk1size)]},
                    {'name': 'Processor', 'values': [shorten_cpu(p.cpu)]},
                ],
                'variants': [{
                    'option1': p.ram or 'N/A',
                    'option2': format_storage(p.disk1size),
                    'option3': shorten_cpu(p.cpu),
                    'price': price,
                    'sku': f"{p.model or 'UNIT'}-{grade}-{instance.serial or ''}".replace(' ', '-'),
                    'inventory_management': 'shopify',
                    'inventory_quantity': 1,
                    'requires_shipping': True,
                }],
            }
        }
        result = client.post('products.json', product_payload)
        shopify_prod = result.get('product', {})
        variant = (shopify_prod.get('variants') or [{}])[0]
        if existing:
            existing.shopify_product_id        = str(shopify_prod.get('id', ''))
            existing.shopify_variant_id        = str(variant.get('id', ''))
            existing.shopify_inventory_item_id = str(variant.get('inventory_item_id', ''))
            existing.sync_status = 'synced'
            existing.last_synced_at = datetime.now(timezone.utc)
        else:
            sp = ShopifyProduct(
                tenant_id=tid, product_key=key,
                shopify_product_id=str(shopify_prod.get('id', '')),
                shopify_variant_id=str(variant.get('id', '')),
                shopify_inventory_item_id=str(variant.get('inventory_item_id', '')),
                sync_status='synced', last_synced_at=datetime.now(timezone.utc),
            )
            db.session.add(sp)

    instance.shopify_listed = True
    db.session.commit()
    log_sync(tid, 'publish', 'push', 'success',
             f"instance {instance.id} key={key}", key)


# ─────────────────────────────────────────────────────
# PHASE 5 — WEBHOOKS (PULL ORDERS)
# ─────────────────────────────────────────────────────

@shopify_bp.route('/webhook/orders_create', methods=['POST'])
@csrf.exempt
def webhook_orders_create():
    """Receive Shopify orders/create webhook."""
    raw_data    = request.get_data()
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')

    if not verify_webhook(raw_data, hmac_header):
        logger.warning("Shopify webhook HMAC verification failed")
        abort(401)

    try:
        order_data = json.loads(raw_data)
        shop_domain = request.headers.get('X-Shopify-Shop-Domain', '')
        _handle_new_order(order_data, shop_domain=shop_domain)
    except Exception as e:
        logger.error(f"webhook_orders_create processing error: {e}")
        # Always return 200 — Shopify will retry on non-2xx
    return '', 200


@shopify_bp.route('/webhook/orders_cancelled', methods=['POST'])
@csrf.exempt
def webhook_orders_cancelled():
    """Receive Shopify orders/cancelled webhook."""
    raw_data    = request.get_data()
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')

    if not verify_webhook(raw_data, hmac_header):
        logger.warning("Shopify webhook HMAC verification failed (cancel)")
        abort(401)

    try:
        order_data = json.loads(raw_data)
        _handle_cancelled_order(order_data)
    except Exception as e:
        logger.error(f"webhook_orders_cancelled processing error: {e}")
    return '', 200


def _handle_new_order(order_data, shop_domain=''):
    """Process incoming Shopify order — find/create customer and ShopifyOrder."""
    # Resolve tenant from Shopify access token setting — avoids hardcoded first()
    enabled_setting = TenantSettings.query.filter_by(
        key='shopify_access_token'
    ).filter(TenantSettings.value != '').first()
    if not enabled_setting:
        logger.warning("_handle_new_order: no tenant with shopify_access_token found")
        return
    tid = enabled_setting.tenant_id

    shopify_order_id = str(order_data.get('id', ''))
    if ShopifyOrder.query.filter_by(shopify_order_id=shopify_order_id).first():
        return  # already processed (duplicate webhook)

    # Find or create customer
    customer_id = None
    sc = order_data.get('customer') or {}
    if sc:
        email = sc.get('email', '')
        name  = f"{sc.get('first_name', '')} {sc.get('last_name', '')}".strip()
        cust  = Customer.query.filter_by(tenant_id=tid, email=email).first() if email else None
        if not cust and name:
            cust = Customer.query.filter_by(tenant_id=tid, name=name).first()
        if not cust:
            cust = Customer(
                tenant_id=tid,
                name=name or email or 'Shopify Customer',
                email=email or None,
                phone=sc.get('phone', ''),
            )
            db.session.add(cust)
            db.session.flush()
        customer_id = cust.id

    so = ShopifyOrder(
        tenant_id=tid,
        shopify_order_id=shopify_order_id,
        shopify_order_number=str(order_data.get('order_number', '')),
        customer_id=customer_id,
        status='draft',
        total_price=order_data.get('total_price'),
        currency=order_data.get('currency', ''),
        payment_method=order_data.get('payment_gateway', ''),
        shopify_data=json.dumps(order_data),
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(so)

    # Notify all admin users in this tenant
    admins = User.query.filter_by(tenant_id=tid, role='admin').all()
    for admin in admins:
        n = Notification(
            tenant_id=tid,
            user_id=admin.id,
            type='shopify_order',
            title='New Shopify Order',
            message=f"Order #{order_data.get('order_number')} received — AED {order_data.get('total_price', 0)}",
            link='/shopify/orders',
        )
        db.session.add(n)

    db.session.commit()
    log_sync(tid, 'webhook_order_create', 'pull', 'success',
             f"Shopify order {shopify_order_id}", shopify_order_id)


def _handle_cancelled_order(order_data):
    """Handle Shopify cancellation webhook."""
    shopify_order_id = str(order_data.get('id', ''))
    so = ShopifyOrder.query.filter_by(shopify_order_id=shopify_order_id).first()
    if not so:
        return
    old_status = so.status
    so.status = 'cancelled'
    db.session.commit()
    log_sync(so.tenant_id, 'webhook_order_cancelled', 'pull', 'success',
             f"Shopify order {shopify_order_id} was {old_status}", shopify_order_id)


@shopify_bp.route('/register_webhooks', methods=['POST'])
@login_required
def register_webhooks():
    """Register orders/create and orders/cancelled webhooks with Shopify.

    Always uses REST API 2024-01 for webhook registration — the webhooks.json
    REST endpoint was removed in 2025-01+, so we pin to a stable version
    regardless of the global SHOPIFY_API_VERSION setting.
    """
    _require_admin()
    if not is_shopify_enabled(current_user.tenant_id):
        flash("Shopify integration is not enabled.", "warning")
        return redirect(url_for('shopify_bp.shopify_dashboard'))
    tid       = current_user.tenant_id
    client    = get_shopify_client(tid)
    if not client:
        flash("Shopify not connected", "danger")
        return redirect(url_for('shopify_bp.dashboard'))

    # Webhook REST endpoint requires a version that still supports it
    WEBHOOK_API_VERSION = '2024-01'
    store_url    = current_app.config.get('SHOPIFY_STORE_URL', '')
    webhook_base = f"https://{store_url}/admin/api/{WEBHOOK_API_VERSION}"

    # Use the public URL override if set, else fall back to request host
    public_base = (
        current_app.config.get('SHOPIFY_REDIRECT_URI', '').rsplit('/shopify/callback', 1)[0]
        or request.host_url.rstrip('/')
    )
    webhooks = [
        {'topic': 'orders/create',    'address': f"{public_base}/shopify/webhook/orders_create"},
        {'topic': 'orders/cancelled', 'address': f"{public_base}/shopify/webhook/orders_cancelled"},
    ]

    import requests as _req
    headers = {
        'X-Shopify-Access-Token': client.access_token,
        'Content-Type': 'application/json',
    }

    # Shopify requires HTTPS for webhook addresses
    if not public_base.startswith('https://'):
        flash(
            "Shopify requires HTTPS for webhook addresses. "
            f"Your current address is '{public_base}' (HTTP). "
            "Set up SSL on your server and update SHOPIFY_REDIRECT_URI in .env to use https://",
            "danger"
        )
        log_sync(tid, 'register_webhook', 'push', 'error',
                 f"HTTPS required — address is {public_base}")
        return redirect(url_for('shopify_bp.dashboard'))

    results = []
    for wh in webhooks:
        payload = {'webhook': {'topic': wh['topic'], 'address': wh['address'], 'format': 'json'}}
        try:
            resp = _req.post(
                f"{webhook_base}/webhooks.json",
                json=payload,
                headers=headers,
                timeout=15,
            )
            if not resp.ok:
                raise ValueError(f"HTTP {resp.status_code}: {resp.text}")
            wh_id = resp.json().get('webhook', {}).get('id', '')
            results.append(f"{wh['topic']}: ID {wh_id}")
            log_sync(tid, 'register_webhook', 'push', 'success', wh['topic'], str(wh_id))
        except Exception as e:
            logger.error(f"register_webhooks failed for {wh['topic']}: {e}")
            results.append(f"{wh['topic']}: FAILED — {e}")
            log_sync(tid, 'register_webhook', 'push', 'error', str(e)[:500])

    flash("Webhooks: " + " | ".join(results), "info")
    return redirect(url_for('shopify_bp.dashboard'))


# ─────────────────────────────────────────────────────
# LISTINGS — ALL UNITS CURRENTLY ON SHOPIFY
# ─────────────────────────────────────────────────────

@shopify_bp.route('/listings')
@login_required
def listings():
    """Show all ProductInstances currently listed on Shopify."""
    from inventory_flask_app.models import Product
    tid  = current_user.tenant_id
    page = request.args.get('page', 1, type=int)

    instances = (
        ProductInstance.query
        .join(Product)
        .filter(ProductInstance.tenant_id == tid, ProductInstance.shopify_listed == True)
        .order_by(Product.make, Product.model, ProductInstance.id)
        .paginate(page=page, per_page=50)
    )
    return render_template('shopify/listings.html', instances=instances)


# ─────────────────────────────────────────────────────
# SHOPIFY ORDERS — REVIEW & CONFIRM
# ─────────────────────────────────────────────────────

@shopify_bp.route('/orders')
@login_required
def orders_list():
    """List all Shopify orders with tab filtering."""
    tid    = current_user.tenant_id
    tab    = request.args.get('tab', 'draft')
    page   = request.args.get('page', 1, type=int)

    q = ShopifyOrder.query.filter_by(tenant_id=tid)
    if tab != 'all':
        q = q.filter_by(status=tab)
    orders = q.order_by(ShopifyOrder.created_at.desc()).paginate(page=page, per_page=20)

    counts = {
        'draft':     ShopifyOrder.query.filter_by(tenant_id=tid, status='draft').count(),
        'confirmed': ShopifyOrder.query.filter_by(tenant_id=tid, status='confirmed').count(),
        'rejected':  ShopifyOrder.query.filter_by(tenant_id=tid, status='rejected').count(),
        'all':       ShopifyOrder.query.filter_by(tenant_id=tid).count(),
    }
    return render_template('shopify/orders_list.html',
                           orders=orders, tab=tab, counts=counts)


@shopify_bp.route('/orders/<int:order_id>/review')
@login_required
def review_order(order_id):
    """Review a Shopify order and optionally match to PCMart units."""
    tid = current_user.tenant_id
    so  = ShopifyOrder.query.filter_by(id=order_id, tenant_id=tid).first_or_404()
    order_data = {}
    if so.shopify_data:
        try:
            order_data = json.loads(so.shopify_data)
        except Exception:
            pass
    return render_template('shopify/review_order.html', so=so, order_data=order_data)


@shopify_bp.route('/orders/<int:order_id>/confirm', methods=['POST'])
@login_required
def confirm_order(order_id):
    """Confirm a Shopify order — create PCMart Order + SaleTransaction."""
    tid = current_user.tenant_id
    if not is_shopify_enabled(tid):
        flash("Shopify integration is not enabled.", "warning")
        return redirect(url_for('shopify_bp.shopify_dashboard'))
    so  = ShopifyOrder.query.filter_by(id=order_id, tenant_id=tid).first_or_404()
    if so.status != 'draft':
        flash("Order is not in draft status.", "warning")
        return redirect(url_for('shopify_bp.review_order', order_id=order_id))

    if not so.customer_id:
        flash("No customer linked to this order.", "danger")
        return redirect(url_for('shopify_bp.review_order', order_id=order_id))

    try:
        import random
        order_num = f"SHO-{so.shopify_order_number or random.randint(10000,99999)}"
        existing_order = Order.query.filter_by(order_number=order_num, tenant_id=tid).first()
        if not existing_order:
            new_order = Order(
                order_number=order_num,
                customer_id=so.customer_id,
                user_id=current_user.id,
                tenant_id=tid,
            )
            db.session.add(new_order)
            db.session.flush()
            so.order_id = new_order.id

        so.status       = 'confirmed'
        so.processed_at = datetime.now(timezone.utc)
        so.processed_by = current_user.id
        db.session.commit()

        log_sync(tid, 'order_confirmed', 'pull', 'success',
                 f"ShopifyOrder {order_id}", so.shopify_order_id)
        flash(f"Order #{so.shopify_order_number} confirmed!", "success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"confirm_order error: {e}")
        flash(f"Error confirming order: {e}", "danger")

    return redirect(url_for('shopify_bp.orders_list'))


@shopify_bp.route('/orders/<int:order_id>/reject', methods=['POST'])
@login_required
def reject_order(order_id):
    """Reject a Shopify order."""
    tid = current_user.tenant_id
    if not is_shopify_enabled(tid):
        flash("Shopify integration is not enabled.", "warning")
        return redirect(url_for('shopify_bp.shopify_dashboard'))
    so  = ShopifyOrder.query.filter_by(id=order_id, tenant_id=tid).first_or_404()
    so.status       = 'rejected'
    so.processed_at = datetime.now(timezone.utc)
    so.processed_by = current_user.id
    db.session.commit()
    log_sync(tid, 'order_rejected', 'pull', 'success',
             f"ShopifyOrder {order_id}", so.shopify_order_id)
    flash(f"Order #{so.shopify_order_number} rejected.", "info")
    return redirect(url_for('shopify_bp.orders_list'))

from inventory_flask_app.models import ProductInstance
from inventory_flask_app.models import CustomerOrderTracking, Customer
from datetime import datetime
import pytz
from flask_login import current_user
from functools import wraps
from flask import abort


def admin_required(f):
    """Decorator: only admin role may access this route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


def admin_or_supervisor_required(f):
    """Decorator: admin or supervisor role required."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role not in ('admin', 'supervisor'):
            abort(403)
        return f(*args, **kwargs)
    return decorated


def sales_required(f):
    """Decorator: admin, supervisor, or sales role required."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role not in ('admin', 'supervisor', 'sales'):
            abort(403)
        return f(*args, **kwargs)
    return decorated


def warehouse_required(f):
    """Decorator: admin, supervisor, or warehouse role required."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role not in ('admin', 'supervisor', 'warehouse'):
            abort(403)
        return f(*args, **kwargs)
    return decorated


def module_required(module, level='view'):
    """Decorator to check module permission.
    level: 'view' (any access) or 'full' (edit/write access).
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if level == 'full' and not current_user.can_edit(module):
                abort(403)
            elif level == 'view' and not current_user.can_access(module):
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def is_module_enabled(module_key):
    """Return True if the given module is enabled for the current tenant.

    Defaults to True when no setting exists (opt-in pattern: modules are on
    unless an admin explicitly disables them).

    Args:
        module_key: e.g. 'enable_parts_module', 'enable_order_module', etc.
    """
    from flask import g
    # Use request-cached settings when available (avoids extra DB hit)
    cached = getattr(g, '_tenant_settings', None)
    if cached is not None:
        val = cached.get(module_key)
        return val is None or val == 'true'
    from inventory_flask_app.models import TenantSettings
    setting = TenantSettings.query.filter_by(
        tenant_id=current_user.tenant_id, key=module_key
    ).first()
    # No row = never configured = enabled by default
    return setting is None or setting.value == 'true'


def upsert_instance(serial, spec_data, tenant_id, location_id=None, vendor_id=None,
                    po_id=None, status='unprocessed', moved_by_id=None,
                    create_product_fn=None):
    """
    Upsert a ProductInstance by serial + tenant_id.

    spec_data keys (all optional):
        item_name, make, model, cpu, ram, display, gpu1, gpu2, grade, disk1size, asset

    create_product_fn: optional callable() → Product that is already db.session.add()'d
        and flushed. If None, a new Product is created directly from spec_data.

    Returns: (outcome, instance, changes)
        outcome : 'created' | 'updated' | 'skipped'
        instance: ProductInstance object
        changes : dict { field: {'old': old_val, 'new': new_val} }
                  (empty dict for 'created' and 'skipped')
    """
    from inventory_flask_app.models import db, Product, ProductProcessLog

    PRODUCT_SPEC_FIELDS = (
        'item_name', 'make', 'model', 'cpu', 'ram',
        'display', 'gpu1', 'gpu2', 'grade', 'disk1size',
    )

    def _clean(val):
        s = str(val or '').strip()
        return '' if s.lower() in ('nan', 'none') else s

    # Normalize all incoming spec fields
    cleaned = {f: _clean(spec_data.get(f)) for f in PRODUCT_SPEC_FIELDS}
    raw_asset = _clean(spec_data.get('asset'))
    asset = raw_asset or None
    cleaned['item_name'] = cleaned['item_name'] or cleaned.get('model') or 'Unknown'

    now = get_now_for_tenant()

    existing = ProductInstance.query.filter_by(serial=serial, tenant_id=tenant_id).first()

    if existing:
        product = existing.product

        # Compare — only flag a change when incoming value is non-empty AND differs
        changes = {}
        for field in PRODUCT_SPEC_FIELDS:
            new_val = cleaned[field]
            old_val = getattr(product, field, '') or ''
            if new_val and old_val != new_val:
                changes[field] = {'old': old_val, 'new': new_val}

        old_asset = existing.asset or ''
        if raw_asset and old_asset != raw_asset:
            changes['asset'] = {'old': old_asset, 'new': raw_asset}

        if not changes:
            return ('skipped', existing, {})

        # Apply product changes
        for field, diff in changes.items():
            if field in PRODUCT_SPEC_FIELDS:
                setattr(product, field, diff['new'])
        if vendor_id:
            product.vendor_id = vendor_id
        db.session.add(product)

        # Apply instance changes
        if 'asset' in changes:
            existing.asset = asset
        existing.updated_at = now
        db.session.add(existing)

        # Audit log (truncate note at 200 chars to fit column)
        note = '; '.join(
            f"{k}: {v['old']!r} -> {v['new']!r}" for k, v in changes.items()
        )
        log = ProductProcessLog(
            product_instance_id=existing.id,
            action='spec_update',
            note=f"Specs updated via import: {note}"[:200],
            moved_by=moved_by_id,
            moved_at=now,
        )
        db.session.add(log)
        return ('updated', existing, changes)

    # --- Not found: create new ---
    if create_product_fn is not None:
        product = create_product_fn()
    else:
        product = Product(
            item_name=cleaned['item_name'],
            make=cleaned['make'],
            model=cleaned['model'],
            display=cleaned['display'],
            cpu=cleaned['cpu'],
            ram=cleaned['ram'],
            gpu1=cleaned['gpu1'],
            gpu2=cleaned['gpu2'],
            grade=cleaned['grade'],
            disk1size=cleaned['disk1size'],
            vendor_id=vendor_id,
            tenant_id=tenant_id,
            location_id=int(location_id) if location_id else None,
            created_at=now,
        )
        db.session.add(product)
        db.session.flush()

    instance = ProductInstance(
        serial=serial,
        asset=asset,
        status=status,
        product_id=product.id,
        location_id=int(location_id) if location_id else (product.location_id or None),
        tenant_id=tenant_id,
        po_id=po_id,
    )
    db.session.add(instance)
    db.session.flush()
    return ('created', instance, {})

def generate_part_invoice_number(tenant_id):
    """Return next PRT-XXXX invoice number for the given tenant (zero-padded to 4 digits)."""
    from inventory_flask_app.models import PartSaleTransaction
    from sqlalchemy import func
    last = (
        PartSaleTransaction.query
        .filter_by(tenant_id=tenant_id)
        .filter(PartSaleTransaction.invoice_number.like('PRT-%'))
        .order_by(PartSaleTransaction.id.desc())
        .first()
    )
    if last:
        try:
            last_num = int(last.invoice_number.split('-')[1])
        except (IndexError, ValueError):
            last_num = 0
    else:
        last_num = 0
    return f'PRT-{last_num + 1:04d}'


def get_instance_id(serial):
    """Given a serial, return the ProductInstance ID (or None if not found), scoped to current tenant."""
    try:
        tenant_id = current_user.tenant_id
    except Exception:
        return None
    from inventory_flask_app.models import Product
    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.serial == serial,
        Product.tenant_id == tenant_id
    ).first()
    return instance.id if instance else None

def create_notification(user_id, notif_type, title, message, link=None, tenant_id=None):
    """Create an in-app notification for a specific user.

    Args:
        user_id: ID of the user to notify
        notif_type: 'reassigned' | 'sla_breach' | 'stage_move' | 'disputed'
        title: Short notification title (≤200 chars)
        message: Notification body text
        link: Optional URL to navigate to on click
        tenant_id: Tenant ID (defaults to current_user.tenant_id if None)
    """
    try:
        from inventory_flask_app.models import db, Notification
        if tenant_id is None:
            tenant_id = current_user.tenant_id
        notif = Notification(
            tenant_id=tenant_id,
            user_id=user_id,
            type=notif_type,
            title=title[:200],
            message=message,
            link=link,
            is_read=False,
        )
        db.session.add(notif)
        # No commit here — caller handles commit
    except Exception:
        pass  # Notifications are non-critical; never break the main flow


def get_now_for_tenant():
    """Return the current datetime localized to the tenant's timezone."""
    try:
        tz_name = current_user.tenant.timezone or 'UTC'
        return datetime.now(pytz.timezone(tz_name))
    except Exception:
        return datetime.utcnow()


def format_duration(minutes):
    """Convert integer minutes to a human-readable string like '2h 15m', '3d 4h'."""
    if minutes is None or minutes < 0:
        return None
    if minutes < 1:
        return '<1m'
    if minutes < 60:
        return f'{minutes}m'
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f'{hours}h {mins}m' if mins else f'{hours}h'
    days, hrs = divmod(hours, 24)
    return f'{days}d {hrs}h' if hrs else f'{days}d'


def calc_duration_minutes(since_dt):
    """Return minutes elapsed since `since_dt` (a datetime). Returns None if since_dt is None."""
    if since_dt is None:
        return None
    now = datetime.utcnow()
    # Make both naive for subtraction
    if hasattr(since_dt, 'utcoffset') and since_dt.utcoffset() is not None:
        since_naive = since_dt.replace(tzinfo=None) - since_dt.utcoffset()
    else:
        since_naive = since_dt
    delta = now - since_naive
    return max(0, int(delta.total_seconds() / 60))


def sync_reservation_stage(instance_id, new_stage, username):
    """Update CustomerOrderTracking stage fields when a unit's process_stage changes.

    Call this after setting instance.process_stage but before db.session.commit().
    new_stage should be None when a unit is checked out / reset to unprocessed.
    """
    import json
    from datetime import datetime, timezone
    from inventory_flask_app.models import CustomerOrderTracking, db
    try:
        reservation = (
            CustomerOrderTracking.query
            .filter_by(product_instance_id=instance_id)
            .filter(CustomerOrderTracking.status.in_(['reserved', 'delivered']))
            .first()
        )
        if not reservation:
            return
        now = datetime.now(timezone.utc)
        reservation.current_stage = new_stage
        reservation.stage_updated_at = now
        history = json.loads(reservation.stage_history or '[]')
        history.append({
            'stage': new_stage or 'Checkout',
            'updated_at': now.isoformat(),
            'updated_by': username,
        })
        reservation.stage_history = json.dumps(history)
    except Exception:
        pass  # Stage sync is non-critical; never break the main flow


# Inventory and order notifications for a tenant
from inventory_flask_app.models import Product, ProductInstance, User, CustomerOrderTracking
from sqlalchemy import func
from datetime import timedelta

def get_inventory_notifications(tenant_id):
    now = get_now_for_tenant()
    aged_threshold = now - timedelta(days=60)
    slow_threshold = now - timedelta(days=3)

    notifications = []

    # Idle inventory
    idle_count = ProductInstance.query.join(Product).filter(
        ProductInstance.status == 'idle',
        Product.tenant_id == tenant_id
    ).count()
    if idle_count:
        notifications.append({
            "type": "idle_inventory",
            "label": f"{idle_count} idle unit{'s' if idle_count > 1 else ''}",
            "url": "/idle_units"
        })

    # Aged inventory
    aged_count = ProductInstance.query.join(Product).filter(
        ProductInstance.created_at < aged_threshold,
        Product.tenant_id == tenant_id
    ).count()
    if aged_count:
        notifications.append({
            "type": "aged_inventory",
            "label": f"{aged_count} aged unit{'s' if aged_count > 1 else ''} (60+ days)",
            "url": "/inventory/aged"
        })

    # Orders under process (reserved but not delivered)
    order_count = CustomerOrderTracking.query \
        .join(Customer) \
        .filter(
            Customer.tenant_id == tenant_id,
            CustomerOrderTracking.status != 'delivered'
        ).count()
    if order_count:
        notifications.append({
            "type": "orders_processing",
            "label": f"{order_count} order{'s' if order_count > 1 else ''} under process",
            "url": "/orders/pending"
        })

    # Slow technicians
    slow_techs = (
        ProductInstance.query
        .filter(ProductInstance.updated_at < slow_threshold)
        .join(Product)
        .filter(Product.tenant_id == tenant_id)
        .with_entities(ProductInstance.team_assigned)
        .group_by(ProductInstance.team_assigned)
        .all()
    )
    for tech in slow_techs:
        label = f"Technician {tech.team_assigned} has delayed units" if tech.team_assigned else "A technician has delayed units"
        notifications.append({
            "type": "slow_technician",
            "label": label,
            "url": f"/report/tech_profile/{tech.team_assigned}?slow=true" if tech.team_assigned else "/report/tech_profile"
        })

    # Pending orders (reserved but not delivered)
    pending_reserves = CustomerOrderTracking.query \
        .join(Customer) \
        .filter(
            Customer.tenant_id == tenant_id,
            CustomerOrderTracking.status != 'delivered'
        ).count()
    if pending_reserves:
        notifications.append({
            "type": "pending_orders",
            "label": f"{pending_reserves} pending order{'s' if pending_reserves > 1 else ''}",
            "url": "/orders/pending"
        })

    # Delayed orders (pending for more than 3 days)
    order_delay_threshold = now - timedelta(days=3)
    delayed_orders = CustomerOrderTracking.query \
        .join(Customer) \
        .filter(
            CustomerOrderTracking.status != 'delivered',
            CustomerOrderTracking.reserved_date < order_delay_threshold,
            Customer.tenant_id == tenant_id
        ).count()

    if delayed_orders:
        notifications.append({
            "type": "delayed_orders",
            "label": f"{delayed_orders} order{'s' if delayed_orders > 1 else ''} delayed > 3 days",
            "url": "/orders/pending"
        })

    return notifications

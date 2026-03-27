"""Shopify API client and helper utilities for PCMart."""
import re
import logging
import hmac as hmac_lib
import hashlib
import base64

import requests as _requests

logger = logging.getLogger(__name__)


class ShopifyClient:
    def __init__(self, store_url, access_token, api_version='2026-01'):
        self.store_url = store_url
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = f"https://{store_url}/admin/api/{api_version}"
        self.headers = {
            'X-Shopify-Access-Token': access_token,
            'Content-Type': 'application/json',
        }

    def get(self, endpoint):
        resp = _requests.get(f"{self.base_url}/{endpoint}", headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def post(self, endpoint, data):
        resp = _requests.post(
            f"{self.base_url}/{endpoint}", json=data, headers=self.headers, timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    def put(self, endpoint, data):
        resp = _requests.put(
            f"{self.base_url}/{endpoint}", json=data, headers=self.headers, timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    def delete(self, endpoint):
        resp = _requests.delete(f"{self.base_url}/{endpoint}", headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.status_code

    def test_connection(self):
        try:
            result = self.get('shop.json')
            return True, result.get('shop', {}).get('name', 'Unknown')
        except Exception as e:
            return False, str(e)


def get_shopify_client(tenant_id):
    """Return a ShopifyClient for this tenant, or None if not configured."""
    try:
        from flask import current_app
        access_token = _get_setting(tenant_id, 'shopify_access_token', '')
        store_url = current_app.config.get('SHOPIFY_STORE_URL', '')
        api_version = current_app.config.get('SHOPIFY_API_VERSION', '2026-01')
        if not access_token or not store_url:
            return None
        return ShopifyClient(store_url, access_token, api_version)
    except Exception as e:
        logger.warning(f"get_shopify_client failed: {e}")
        return None


def is_shopify_enabled(tenant_id):
    """Return True if Shopify sync is enabled for this tenant."""
    try:
        return _get_setting(tenant_id, 'enable_shopify_sync', 'false') == 'true'
    except Exception:
        return False


def _get_setting(tenant_id, key, default=''):
    """Read a single TenantSettings value by key."""
    from inventory_flask_app.models import TenantSettings
    row = TenantSettings.query.filter_by(tenant_id=tenant_id, key=key).first()
    return row.value if row and row.value is not None else default


def _set_setting(tenant_id, key, value):
    """Upsert a TenantSettings key/value."""
    from inventory_flask_app.models import TenantSettings, db
    row = TenantSettings.query.filter_by(tenant_id=tenant_id, key=key).first()
    if row:
        row.value = value
    else:
        row = TenantSettings(tenant_id=tenant_id, key=key, value=value)
        db.session.add(row)
    db.session.commit()


def verify_webhook(data, hmac_header):
    """Verify Shopify HMAC signature on a webhook payload."""
    try:
        from flask import current_app
        secret = current_app.config.get('SHOPIFY_WEBHOOK_SECRET', '')

        logger.info("HMAC debug: secret length=%d, secret_start=%s, hmac_header=%s",
                    len(secret), secret[:6] + '...' if secret else 'EMPTY',
                    hmac_header[:20] + '...' if hmac_header else 'NONE')

        if not secret:
            logger.warning("SHOPIFY_WEBHOOK_SECRET is empty — cannot verify webhook")
            return False
        if not hmac_header:
            logger.warning("No HMAC header received from Shopify")
            return False

        digest = hmac_lib.new(secret.encode('utf-8'), data, hashlib.sha256).digest()
        computed = base64.b64encode(digest).decode('utf-8')

        match = hmac_lib.compare_digest(computed, hmac_header)
        if not match:
            logger.warning("HMAC mismatch: computed=%s received=%s",
                           computed[:20] + '...', hmac_header[:20] + '...')
        return match
    except Exception as e:
        logger.warning(f"verify_webhook error: {e}")
        return False


def format_storage(storage):
    """Normalize storage to compact uppercase string (e.g. '512 gb' → '512GB', '1024' → '1TB')."""
    if not storage:
        return 'N/A'
    s = str(storage).strip()
    # Parse any "NNN GB" / "NNN TB" / "NNN" form
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(GB|TB)?$', s, re.IGNORECASE)
    if match:
        val  = float(match.group(1))
        unit = (match.group(2) or '').upper()
        # No unit → treat as GB
        if unit == 'TB':
            return f"{int(val)}TB" if val == int(val) else f"{val:.1f}TB"
        # GB or bare number
        if val >= 1024:
            tb = val / 1024
            return f"{int(tb)}TB" if tb == int(tb) else f"{tb:.1f}TB"
        return f"{int(val)}GB"
    return s.upper().replace(' ', '')


def shorten_cpu(cpu):
    """Shorten a verbose CPU name to a compact identifier.

    Examples:
        "13th Gen Intel(R) Core(TM) i7-1355U @ 1.70GHz" → "i7-1355U"
        "AMD Ryzen 5 5600H with Radeon Graphics"         → "Ryzen 5 5600H"
    """
    if not cpu:
        return 'N/A'
    match = re.search(r'(i\d-\d+\w*|Ryzen \d \d+\w*|Core \w+)', cpu)
    if match:
        return match.group(1)
    return cpu[:20].strip()


def build_product_title(instance):
    """Build a Shopify product title: Make + Model + Device type + CPU.

    Examples:
        "Dell 15 DC15250 Laptop with i5-1334U (Refurbished)"
        "Alienware m18 R1 Laptop with Ryzen 9 7845HX (Refurbished)"
        "HP EliteBook 840 G8 Laptop (Refurbished)"  ← when no CPU
    """
    p     = instance.product
    make  = (getattr(p, 'make',      None) or '').strip()
    model = (getattr(p, 'model',     None) or '').strip()
    cpu   = shorten_cpu(getattr(p, 'cpu', None) or '')

    # Avoid "HP HP EliteBook …"
    if make and model.lower().startswith(make.lower()):
        base = model
    else:
        base = f"{make} {model}".strip()

    # Determine device type from item_name hint
    device_type = 'Laptop'
    item_name = (getattr(p, 'item_name', None) or '').strip().lower()
    if item_name:
        if 'desktop'       in item_name: device_type = 'Desktop'
        elif 'workstation' in item_name: device_type = 'Workstation'
        elif 'macbook'     in item_name.replace(' ', ''): device_type = 'MacBook'
        elif 'imac'        in item_name.replace(' ', ''): device_type = 'iMac'
        elif 'tablet'      in item_name: device_type = 'Tablet'

    if cpu and cpu != 'N/A':
        return f"{base} {device_type} with {cpu} (Refurbished)"
    return f"{base} {device_type} (Refurbished)"


# Backward-compatible alias (routes import build_title)
def build_title(instance):
    return build_product_title(instance)


def build_tags(instance):
    """Build a comma-separated tag string for a Shopify product."""
    tags = []
    grade = getattr(instance.product, 'grade', None)
    if grade:
        tags.append(f"Grade-{grade}")
    p = instance.product
    if getattr(p, 'make', None):
        tags.append(p.make)
    if getattr(p, 'ram', None):
        tags.append(p.ram)
    if getattr(p, 'disk1size', None):
        tags.append(format_storage(p.disk1size))
    tags.append('Refurbished')
    tags.append('PCMart')
    return ', '.join(tags)


def build_description(instance):
    """Build an HTML table description for a Shopify product."""
    p = instance.product
    rows = []
    if getattr(p, 'make', None):
        rows.append(f"<tr><td><strong>Brand</strong></td><td>{p.make}</td></tr>")
    if getattr(p, 'model', None):
        rows.append(f"<tr><td><strong>Model</strong></td><td>{p.model}</td></tr>")
    if getattr(p, 'cpu', None):
        rows.append(f"<tr><td><strong>Processor</strong></td><td>{p.cpu}</td></tr>")
    if getattr(p, 'ram', None):
        rows.append(f"<tr><td><strong>RAM</strong></td><td>{p.ram}</td></tr>")
    if getattr(p, 'disk1size', None):
        rows.append(f"<tr><td><strong>Storage</strong></td><td>{format_storage(p.disk1size)}</td></tr>")
    if getattr(p, 'display', None):
        rows.append(f"<tr><td><strong>Display</strong></td><td>{p.display}</td></tr>")
    if getattr(p, 'gpu1', None):
        rows.append(f"<tr><td><strong>Graphics</strong></td><td>{p.gpu1}</td></tr>")
    grade = getattr(instance.product, 'grade', None)
    if grade:
        rows.append(f"<tr><td><strong>Grade</strong></td><td>{grade}</td></tr>")
    rows.append("<tr><td><strong>Condition</strong></td><td>Refurbished</td></tr>")
    return (
        "<table style='width:100%;border-collapse:collapse;'>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


# Backward-compatible alias
def build_product_description(instance):
    return build_description(instance)


def log_sync(tenant_id, action, direction, status, details='', shopify_id=None):
    """Write a ShopifySyncLog row."""
    try:
        from inventory_flask_app.models import ShopifySyncLog, db
        from datetime import datetime, timezone
        row = ShopifySyncLog(
            tenant_id=tenant_id,
            action=action,
            direction=direction,
            status=status,
            details=str(details)[:2000],
            shopify_id=str(shopify_id) if shopify_id else None,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(row)
        db.session.commit()
    except Exception as e:
        logger.warning(f"log_sync failed: {e}")

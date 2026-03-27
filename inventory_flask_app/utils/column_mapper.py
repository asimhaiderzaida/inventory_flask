"""Production-grade column mapper for Excel/CSV imports.

Three-tier matching strategy:
  1. EXACT match against comprehensive alias dictionary
  2. NORMALIZED match (strip punctuation, underscores, etc.)
  3. KEYWORD match (smart token-based detection)

Also maintains an explicit IGNORE set for vendor metadata columns
that should never map to any inventory field.

Tested against:
  - Internal inventory sheets (serial, asset, item_name, make, model, ...)
  - Dell broker lists (Service Tag, Product, FAMILY_NAME, Processor, ...)
  - Generic vendor spreadsheets (Serial Number, Description, Brand, ...)
"""
import re
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# TIER 1: Exact alias dictionary
# Each internal field → list of exact lowercase aliases
# ═══════════════════════════════════════════════════════════════════

COLUMN_ALIASES = {
    'serial': [
        'serial', 'serial_number', 'serial_no', 'serialnumber', 'serialno',
        'sn', 's/n', 'serial#',
        'service_tag', 'service_tag_number', 'servicetag', 'svctag',
        'dell_service_tag', 'tag_number',
        'imei', 'device_serial', 'unit_serial', 'hardware_serial',
    ],
    'asset': [
        'asset', 'asset_tag', 'assettag', 'asset_number', 'asset_no', 'asset#',
        'inventory_tag', 'property_tag', 'fixed_asset', 'asset_id',
        'at', 'equipment_id', 'device_tag',
    ],
    'item_name': [
        'item_name', 'itemname', 'item_name_1',
        'product_name', 'productname', 'product_title',
        'product', 'item', 'name', 'description', 'desc',
        'product_description', 'full_description',
        'title', 'device_name', 'device', 'equipment', 'unit_name',
        'system_description', 'system_name', 'system',
    ],
    'make': [
        'make', 'brand', 'manufacturer', 'mfg', 'mfr', 'oem',
        'make/brand', 'vendor_brand', 'brand_name',
    ],
    'model': [
        'model', 'model_name', 'modelname', 'model_number', 'model_no', 'model#',
        'part_number', 'part_no', 'part#', 'product_model', 'device_model',
        'family_name', 'family', 'product_family', 'product_line',
        'series', 'product_series', 'model_series',
    ],
    'cpu': [
        'cpu', 'processor', 'proc', 'cpu_type', 'cpu_model',
        'processor_type', 'processor_name', 'chipset', 'chip',
        'cpu_name', 'processor_model', 'proc_type',
    ],
    'ram': [
        'ram', 'memory', 'mem', 'ram_size', 'memory_size',
        'installed_memory', 'ram_gb', 'total_memory', 'system_memory',
        'ram_type', 'memory_type', 'ram_description',
    ],
    'display': [
        'display', 'screen', 'screen_size', 'screensize',
        'display_size', 'monitor', 'lcd', 'panel', 'screen_type',
        'diagonal', 'display_type', 'screen_resolution',
    ],
    'gpu1': [
        'gpu1', 'gpu', 'graphics', 'graphics_card', 'video_card',
        'video', 'vga', 'gpu_1', 'dedicated_graphics', 'discrete_gpu',
        'graphics_1', 'video_adapter', 'display_adapter',
    ],
    'gpu2': [
        'gpu2', 'gpu_2', 'graphics_2', 'graphics2', 'secondary_gpu',
        'integrated_graphics', 'igpu', 'onboard_graphics',
    ],
    'grade': [
        'grade', 'condition', 'quality', 'cosmetic', 'cosmetic_grade',
        'rating', 'quality_grade', 'unit_condition', 'device_condition',
        'physical_condition', 'functional_grade',
    ],
    'disk1size': [
        'disk1size', 'disk', 'storage', 'hdd', 'ssd', 'hard_drive',
        'harddrive', 'disk_size', 'drive', 'drive_size', 'disk1',
        'storage_size', 'primary_storage', 'main_storage', 'capacity',
        'disk_capacity', 'storage_capacity', 'hard_disk',
    ],
    'cost': [
        'cost', 'price', 'unit_cost', 'purchase_cost', 'buy_price',
        'acquisition_cost', 'unit_price', 'amount', 'value',
        'broker_price', 'purchase_price', 'landed_cost',
        'sj_offer', 'sj_offer_', 'our_price', 'our_offer', 'offer_price',
        'buying_price', 'net_price',
    ],
    'location': [
        'location', 'loc', 'warehouse', 'site', 'building',
        'storage_location', 'stock_location',
    ],
}

# ═══════════════════════════════════════════════════════════════════
# IGNORE SET: columns that must NEVER map to any field
# These are vendor metadata, logistics, accessories, etc.
# ═══════════════════════════════════════════════════════════════════

IGNORE_COLUMNS = {
    # Vendor internal codes
    'sku', 'outlet_sku', 'internal_sku', 'product_sku', 'item_sku',
    'vendor_sku', 'supplier_sku', 'catalog_number', 'catalog_no',
    'reference', 'ref', 'ref_number', 'reference_number',
    'order_number', 'order_no', 'po_number', 'invoice_number',

    # Logistics
    'broker_pallet_number', 'pallet', 'pallet_number', 'pallet_no',
    'pallet_id', 'box', 'box_number', 'carton', 'shipment',
    'tracking', 'tracking_number',

    # Categories (not a field we store)
    'segment', 'category', 'subcategory', 'sub_category',
    'product_type', 'product_category', 'device_type', 'type',
    'lob', 'line_of_business', 'business_unit', 'division',

    # Accessories & peripherals
    'networking', 'network', 'wifi', 'wireless', 'wlan', 'bluetooth',
    'os', 'operating_system', 'windows', 'software',
    'battery', 'battery_type', 'battery_capacity', 'battery_life',
    'camera', 'webcam', 'webcam_type',
    'keyboard', 'keyboard_type', 'keyboard_layout', 'kb',
    'mouse', 'mouse___touchpad', 'mouse_/_touchpad', 'touchpad', 'trackpad',
    'color', 'colour', 'chassis_color', 'body_color',
    'media_bay', 'optical_drive', 'dvd', 'cd_rom',
    'power', 'power_supply', 'ac_adapter', 'charger', 'wattage',
    'chassis', 'form_factor', 'enclosure', 'body',

    # Features / extras
    'feature_1', 'feature_2', 'feature_3', 'feature_4', 'feature_5',
    'feature1', 'feature2', 'feature3', 'feature4', 'feature5',
    'hardware_upgrade', 'upgrades', 'accessories', 'included',
    'default_warranty', 'warranty', 'warranty_type', 'warranty_status',
    'warranty_end', 'warranty_expiry',

    # Internal names / codes
    'family_internal_name', 'internal_name', 'code_name',
    'platform', 'platform_name',

    # Quantity (we import one unit per row)
    'qty', 'quantity', 'prc._qty', 'prc_qty', 'count', 'units',

    # Numeric memory summary (prefer descriptive 'memory' column instead)
    'mem_total', 'total_ram',

    # Notes / comments that are vendor-specific
    'notes', 'comments', 'remarks', 'internal_notes',
}

# ═══════════════════════════════════════════════════════════════════
# PRIORITY: when two columns could map to the same field,
# higher number wins. Default = 5.
# ═══════════════════════════════════════════════════════════════════

ALIAS_PRIORITY = {}

# Descriptive memory column wins over numeric summary
for _a in ['memory', 'ram', 'installed_memory', 'ram_type', 'memory_type']:
    ALIAS_PRIORITY[_a] = 10
for _a in ['mem_total', 'total_ram']:
    ALIAS_PRIORITY[_a] = 1

# Full product name wins over family name for item_name
for _a in ['product', 'product_name', 'item_name', 'description']:
    ALIAS_PRIORITY[_a] = 10
for _a in ['family_name', 'family', 'product_family']:
    ALIAS_PRIORITY[_a] = 8

# Our offer price wins over broker/list price for cost
for _a in ['sj_offer', 'sj_offer_', 'our_price', 'our_offer', 'offer_price']:
    ALIAS_PRIORITY[_a] = 10
for _a in ['broker_price', 'purchase_price', 'unit_cost', 'cost', 'price']:
    ALIAS_PRIORITY[_a] = 5


# ═══════════════════════════════════════════════════════════════════
# Build reverse lookup: alias → field_name
# ═══════════════════════════════════════════════════════════════════

_ALIAS_MAP = {}
for _field, _aliases in COLUMN_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_MAP[_alias] = _field

# Pre-compute aggressive-normalized ignore set
_IGNORE_AGGRESSIVE = {re.sub(r'[^a-z0-9]', '', ig) for ig in IGNORE_COLUMNS}


def _normalize(col_name):
    """Normalize a column header for matching.

    1. Strip whitespace
    2. Lowercase
    3. Replace separators (space, dash, dot, slash) with underscore
    4. Strip leading/trailing underscores
    5. Remove parenthetical notes like "(GB)" or "(optional)"
    """
    if not col_name:
        return ''
    s = str(col_name).strip().lower()
    s = re.sub(r'[\s\-\.\/\\]+', '_', s)
    s = s.strip('_')
    s = re.sub(r'_?\(.*?\)', '', s)
    s = s.strip('_')
    return s


def _normalize_aggressive(col_name):
    """Remove ALL non-alphanumeric for stubborn matches."""
    return re.sub(r'[^a-z0-9]', '', _normalize(col_name))


def _keyword_match(normalized):
    """Tier 3: keyword-based matching.

    Only fires when there is HIGH CONFIDENCE the column contains
    the right data type. Returns None if uncertain.
    """
    low = normalized

    # Hard-stop: vendor metadata keywords → never map
    _ignore_kw = [
        'sku', 'pallet', 'warranty', 'battery', 'keyboard', 'camera',
        'networking', 'network', 'wifi', 'wireless', 'bluetooth',
        'chassis', 'feature', 'power', 'adapter', 'charger',
        'color', 'colour', 'mouse', 'touchpad', 'trackpad',
        'optical', 'dvd', 'media_bay', 'os', 'operating',
        'software', 'upgrade', 'accessory', 'tracking', 'shipment',
        'carton', 'lob', 'segment', 'internal_name', 'code_name',
        'platform', 'qty', 'quantity', 'count',
    ]
    if any(k in low for k in _ignore_kw):
        return None

    if 'serial' in low or low in ('sn', 's_n'):
        return 'serial'
    if 'service_tag' in low or 'servicetag' in low:
        return 'serial'

    if 'asset' in low and 'serial' not in low:
        return 'asset'

    if 'processor' in low or 'cpu' in low or 'chipset' in low:
        return 'cpu'

    # RAM: only when clearly descriptive, not a bare number column
    if ('memory' in low or 'ram' in low) and 'total' not in low and low not in ('ram_gb', 'memory_gb'):
        return 'ram'

    if any(k in low for k in ('disk', 'hdd', 'ssd', 'storage', 'hard_drive', 'drive')):
        if 'optical' not in low and 'dvd' not in low and 'media' not in low:
            return 'disk1size'

    if any(k in low for k in ('screen', 'display', 'monitor', 'lcd')):
        return 'display'

    if any(k in low for k in ('gpu', 'graphic', 'video_card', 'vga')):
        return 'gpu1'

    if any(k in low for k in ('grade', 'condition', 'cosmetic')):
        if 'battery' not in low and 'warranty' not in low:
            return 'grade'

    if 'model' in low or 'part_number' in low or 'part_no' in low:
        return 'model'
    if 'family_name' in low or low == 'family':
        return 'model'

    if any(k in low for k in ('brand', 'manufacturer', 'make', 'oem', 'mfg', 'mfr')):
        return 'make'

    if any(k in low for k in ('cost', 'price', 'offer')):
        if 'sale' not in low and 'retail' not in low and 'msrp' not in low and 'list' not in low:
            return 'cost'

    # item_name last — broadest match, lowest confidence
    if any(k in low for k in ('product', 'item', 'description', 'device', 'equipment', 'title', 'system')):
        if 'type' not in low and 'category' not in low and 'sku' not in low:
            return 'item_name'

    return None


def map_columns(df_columns):
    """Map DataFrame column names to internal field names.

    Three-tier strategy with conflict resolution.

    Returns:
        dict: {normalized_column_name: internal_field_name}
    """
    mapping = {}
    field_sources = {}  # field → (column, priority)

    for col in df_columns:
        normalized = _normalize(col)

        # Skip explicitly ignored columns (exact and aggressive)
        if normalized in IGNORE_COLUMNS:
            continue
        aggressive = _normalize_aggressive(col)
        if aggressive in _IGNORE_AGGRESSIVE:
            continue

        # ── Tier 1: Exact alias match ──
        matched_field = _ALIAS_MAP.get(normalized)
        match_priority = ALIAS_PRIORITY.get(normalized, 5)

        # ── Tier 2: Aggressive normalized match ──
        if not matched_field:
            for alias, field in _ALIAS_MAP.items():
                if re.sub(r'[^a-z0-9]', '', alias) == aggressive:
                    matched_field = field
                    match_priority = ALIAS_PRIORITY.get(alias, 4)
                    break

        # ── Tier 3: Keyword match ──
        if not matched_field:
            matched_field = _keyword_match(normalized)
            match_priority = 2

        if not matched_field:
            continue

        # ── Conflict resolution ──
        if matched_field in field_sources:
            _, existing_priority = field_sources[matched_field]
            if match_priority <= existing_priority:
                continue  # existing mapping wins
            # Higher-priority column displaces existing
            existing_col = next(k for k, v in mapping.items() if v == matched_field)
            del mapping[existing_col]

        mapping[col] = matched_field
        field_sources[matched_field] = (col, match_priority)

    return mapping


def auto_rename_columns(df):
    """Auto-rename DataFrame columns to internal field names.

    Normalizes headers, applies three-tier mapping, renames in place.

    Returns: (df, mapping_used, unmapped_columns)
    """
    df.columns = [_normalize(c) for c in df.columns]

    mapping = map_columns(df.columns)

    rename = {orig: internal for orig, internal in mapping.items() if orig != internal}
    if rename:
        df.rename(columns=rename, inplace=True)

    allowed = {
        'serial', 'asset', 'item_name', 'make', 'model', 'cpu', 'ram',
        'display', 'gpu1', 'gpu2', 'grade', 'disk1size', 'cost', 'location',
    }
    mapped_vals = set(mapping.values())
    unmapped = [c for c in df.columns if c not in allowed and c not in mapped_vals]

    logger.info("Column mapping: %s", mapping)
    if unmapped:
        logger.info("Unmapped/ignored columns: %s", unmapped)

    return df, mapping, unmapped

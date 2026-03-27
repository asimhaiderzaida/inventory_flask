"""Smart column mapper for Excel/CSV imports.

Maps vendor spreadsheet column headers to our internal field names
using exact matches, common aliases, and fuzzy keyword matching.
"""
import re
import logging

logger = logging.getLogger(__name__)

# Internal field name → list of known aliases (lowercase, stripped)
COLUMN_ALIASES = {
    'serial': [
        'serial', 'serial_number', 'serial number', 'serialnumber', 'sn',
        'serial_no', 'serial no', 'serial#', 's/n', 'service_tag', 'service tag',
        'imei', 'device_serial', 'unit_serial',
    ],
    'asset': [
        'asset', 'asset_tag', 'asset tag', 'assettag', 'asset_number',
        'asset number', 'asset_no', 'asset#', 'at', 'tag', 'inventory_tag',
        'inventory tag', 'fixed_asset', 'property_tag',
    ],
    'item_name': [
        'item_name', 'item name', 'itemname', 'product_name', 'product name',
        'productname', 'product', 'item', 'name', 'description', 'desc',
        'product_description', 'product description', 'title', 'device_name',
        'device name', 'device', 'equipment', 'unit_name',
    ],
    'make': [
        'make', 'brand', 'manufacturer', 'mfg', 'mfr', 'vendor_name',
        'oem', 'company', 'make/brand',
    ],
    'model': [
        'model', 'model_name', 'model name', 'modelname', 'model_number',
        'model number', 'model_no', 'model#', 'part_number', 'part number',
        'sku', 'product_model',
    ],
    'cpu': [
        'cpu', 'processor', 'proc', 'cpu_type', 'cpu type', 'chipset',
        'processor_type', 'processor type', 'cpu_model', 'chip',
    ],
    'ram': [
        'ram', 'memory', 'mem', 'ram_size', 'ram size', 'memory_size',
        'memory size', 'installed_memory', 'installed memory', 'ram_gb',
        'total_memory', 'system_memory',
    ],
    'display': [
        'display', 'screen', 'screen_size', 'screen size', 'screensize',
        'display_size', 'display size', 'monitor', 'lcd', 'panel',
        'screen_type', 'diagonal',
    ],
    'gpu1': [
        'gpu1', 'gpu', 'graphics', 'graphics_card', 'graphics card',
        'video', 'video_card', 'video card', 'vga', 'gpu_1',
        'dedicated_graphics', 'discrete_gpu', 'graphics1',
    ],
    'gpu2': [
        'gpu2', 'gpu_2', 'graphics_2', 'graphics2', 'secondary_gpu',
        'integrated_graphics', 'igpu',
    ],
    'grade': [
        'grade', 'condition', 'quality', 'cosmetic', 'cosmetic_grade',
        'cosmetic grade', 'rating', 'quality_grade',
    ],
    'disk1size': [
        'disk1size', 'disk', 'storage', 'hdd', 'ssd', 'hard_drive',
        'hard drive', 'harddrive', 'disk_size', 'disk size', 'drive',
        'drive_size', 'disk1', 'storage_size', 'storage size',
        'primary_storage', 'main_storage', 'capacity',
    ],
    'cost': [
        'cost', 'price', 'unit_cost', 'unit cost', 'purchase_cost',
        'purchase cost', 'buy_price', 'buy price', 'acquisition_cost',
        'unit_price', 'unit price', 'amount', 'value',
    ],
    'location': [
        'location', 'loc', 'warehouse', 'site', 'building',
        'storage_location', 'stock_location', 'bin', 'shelf',
    ],
}

# Build reverse lookup: alias → field_name
_ALIAS_MAP = {}
for field, aliases in COLUMN_ALIASES.items():
    for alias in aliases:
        _ALIAS_MAP[alias] = field


def _normalize(col_name):
    """Normalize a column header for matching."""
    if not col_name:
        return ''
    s = str(col_name).strip().lower()
    s = re.sub(r'[\s\-\.\/\\]+', '_', s)
    s = s.strip('_')
    s = re.sub(r'_?\(.*?\)$', '', s)  # remove trailing (anything)
    return s


def _fuzzy_match(col_name):
    """Keyword-based fuzzy matching for headers not in the alias map."""
    low = col_name.lower()

    if 'serial' in low or low in ('sn', 's/n') or 'service_tag' in low:
        return 'serial'
    if 'asset' in low or ('tag' in low and 'serial' not in low):
        return 'asset'
    if 'processor' in low or 'cpu' in low or 'chipset' in low:
        return 'cpu'
    if 'memory' in low or 'ram' in low:
        return 'ram'
    if any(k in low for k in ('disk', 'hdd', 'ssd', 'storage', 'drive', 'capacity')):
        return 'disk1size'
    if any(k in low for k in ('screen', 'display', 'monitor', 'lcd')):
        return 'display'
    if any(k in low for k in ('gpu', 'graphic', 'video', 'vga')):
        return 'gpu1'
    if any(k in low for k in ('grade', 'condition', 'cosmetic', 'quality')):
        return 'grade'
    if 'model' in low or 'sku' in low or 'part_number' in low or 'part_no' in low:
        return 'model'
    if any(k in low for k in ('brand', 'manufacturer', 'make', 'oem', 'mfg')):
        return 'make'
    if any(k in low for k in ('cost', 'price', 'amount', 'value')) and 'sale' not in low:
        return 'cost'
    if any(k in low for k in ('product', 'item', 'description', 'name', 'device', 'equipment', 'title')):
        return 'item_name'

    return None


def map_columns(df_columns):
    """Map a list of DataFrame column names to internal field names.

    Returns:
        dict: {original_column_name: internal_field_name}
        Only includes columns that were successfully mapped.
    """
    mapping = {}
    used_fields = set()

    for col in df_columns:
        normalized = _normalize(col)

        # 1. Exact alias match
        if normalized in _ALIAS_MAP and _ALIAS_MAP[normalized] not in used_fields:
            mapping[col] = _ALIAS_MAP[normalized]
            used_fields.add(_ALIAS_MAP[normalized])
            continue

        # 2. Match ignoring underscores
        no_underscore = normalized.replace('_', '')
        for alias, field in _ALIAS_MAP.items():
            if alias.replace('_', '') == no_underscore and field not in used_fields:
                mapping[col] = field
                used_fields.add(field)
                break
        else:
            # 3. Fuzzy keyword match
            fuzzy = _fuzzy_match(normalized)
            if fuzzy and fuzzy not in used_fields:
                mapping[col] = fuzzy
                used_fields.add(fuzzy)

    return mapping


def auto_rename_columns(df):
    """Auto-rename DataFrame columns to internal field names.

    Normalizes headers (strip/lower/spaces→underscores), then applies
    alias + fuzzy matching. Unmapped columns are left as-is.

    Returns:
        (df, mapping_used, unmapped_columns)
        mapping_used: {original_col: internal_field} for all mapped columns
        unmapped_columns: list of column names that couldn't be mapped
    """
    df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

    mapping = map_columns(df.columns)

    rename = {orig: internal for orig, internal in mapping.items() if orig != internal}
    if rename:
        df.rename(columns=rename, inplace=True)

    allowed = {
        'serial', 'asset', 'item_name', 'make', 'model', 'cpu', 'ram',
        'display', 'gpu1', 'gpu2', 'grade', 'disk1size', 'cost', 'location',
    }
    unmapped = [c for c in df.columns if c not in allowed]

    logger.info("Column mapping: %s | Unmapped: %s", mapping, unmapped)
    return df, mapping, unmapped

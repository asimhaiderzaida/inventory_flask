import csv
import os
from fuzzywuzzy import fuzz

def load_vendor_mappings(file_path='static/data/vendor_mapping.csv'):
    mappings = {}
    with open(file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            vendor = row['vendor'].strip().lower()
            source = row['source_column'].strip()
            target = row['target_field'].strip()

            if vendor not in mappings:
                mappings[vendor] = {}
            mappings[vendor][source] = target
    return mappings


# Load standard product field list from CSV (based on your Product model)
def get_standard_fields_from_csv():
    return [
        'name',
        'serial_number',
        'model_number',
        'processor',
        'ram',
        'storage',
        'screen_size',
        'resolution',
        'grade',
        'video_card',
        'stock',
        'vendor',
        'location'
    ]

# Add missing vendor mappings with fuzzy matching
def add_vendor_mapping(vendor, df_columns, file_path='static/data/vendor_mapping.csv'):
    vendor = vendor.strip().lower()

    # Load current standard fields
    standard_fields = get_standard_fields_from_csv()

    # Prepare new mapping rows
    new_rows = []

    for col in df_columns:
        col_clean = col.strip()
        best_match = None
        best_score = 0

        for standard in standard_fields:
            score = fuzz.ratio(col_clean.lower(), standard.lower())
            if score > best_score:
                best_score = score
                best_match = standard

        if best_score >= 80:
            mapped_field = best_match
        else:
            mapped_field = f'unmapped_column'

        new_rows.append((vendor, col_clean, mapped_field))

    # Write to vendor_mapping.csv
    file_exists = os.path.isfile(file_path)

    with open(file_path, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        if not file_exists:
            writer.writerow(['vendor', 'source_column', 'target_field'])  # write header if needed
        for row in new_rows:
            writer.writerow(row)


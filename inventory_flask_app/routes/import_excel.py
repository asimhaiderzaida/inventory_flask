from flask import Blueprint, request, render_template, redirect, url_for, flash
from flask_login import login_required
from ..models import db, Product, Vendor, Location, ProductInstance
from datetime import datetime
import pandas as pd

import_excel_bp = Blueprint('import_excel_bp', __name__)

# Moved here directly since you're not using mappings.py anymore
def get_location_id(location_name):
    if not location_name or str(location_name).lower() == 'nan':
        return None
    location = Location.query.filter_by(name=location_name).first()
    if location:
        return location.id
    else:
        new_location = Location(name=location_name)
        db.session.add(new_location)
        db.session.commit()
        return new_location.id

@import_excel_bp.route('/upload_excel', methods=['GET', 'POST'])
@login_required
def upload_excel():
    vendors = Vendor.query.all()
    if request.method == 'POST':
        file = request.files.get('file')
        vendor_id = request.form.get('vendor_id')

        # If this is a confirmation step (user clicked Confirm Import)
        if request.form.get('confirm') == 'yes':
            import io, base64
            excel_data = request.form.get('excel_data')
            if not excel_data or not vendor_id:
                flash('Missing data for import.', 'error')
                return render_template('upload_product.html', vendors=vendors)
            decoded = base64.b64decode(excel_data)
            df = pd.read_excel(io.BytesIO(decoded))
            new_instances = []
            for _, row in df.iterrows():
                if pd.isna(row['serial_number']) or ProductInstance.query.filter_by(serial_number=row['serial_number']).first():
                    continue
                product = Product.query.filter_by(model_number=row['model_number']).first()
                if not product:
                    product = Product(
                        name=row['name'],
                        barcode=row['serial_number'],
                        model_number=row['model_number'],
                        processor=row.get('processor'),
                        ram=row.get('ram'),
                        storage=row.get('storage'),
                        screen_size=row.get('screen_size'),
                        resolution=row.get('resolution'),
                        grade=row.get('grade'),
                        video_card=row.get('video_card'),
                        purchase_price=float(row.get('purchase_price')) if pd.notna(row.get('purchase_price')) else 0,
                        selling_price=float(row.get('selling_price')) if pd.notna(row.get('selling_price')) else 0,
                        vendor_id=int(vendor_id),
                        location_id=get_location_id(row.get('location')) if row.get('location') else None,
                        created_at=datetime.utcnow()
                    )
                    db.session.add(product)
                    db.session.flush()
                instance = ProductInstance(
                    serial_number=row['serial_number'],
                    status='unprocessed',
                    product_id=product.id,
                    location_id=product.location_id
                )
                db.session.add(instance)
                new_instances.append(instance)
            db.session.commit()
            if not new_instances:
                flash('No new products were imported (maybe all were duplicates).', 'warning')
                return redirect(url_for('import_excel_bp.upload_excel'))
            instance_ids = [i.id for i in new_instances]
            summary_instances = ProductInstance.query.filter(ProductInstance.id.in_(instance_ids)).all()
            flash(f"Successfully imported {len(new_instances)} new products.", "success")
            return render_template('upload_result.html', instances=summary_instances, vendor=Vendor.query.get(int(vendor_id)))

        # STEP 1: PREVIEW — do not import yet!
        if not file or not vendor_id:
            flash('Please upload a file and select a vendor.', 'error')
            return render_template('upload_product.html', vendors=vendors)
        try:
            df = pd.read_excel(file)
        except Exception as e:
            flash(f"Error reading Excel file: {e}", 'error')
            return render_template('upload_product.html', vendors=vendors)
        required_fields = [
            'serial_number', 'model_number', 'name',
            'processor', 'ram', 'storage',
            'screen_size', 'resolution', 'grade', 'video_card'
        ]
        missing = [field for field in required_fields if field not in df.columns]
        if missing:
            flash(f"Missing required fields in Excel: {', '.join(missing)}", 'error')
            return render_template('upload_product.html', vendors=vendors)
        preview_columns = list(df.columns)
        preview_data = df.to_dict(orient='records')
        # Detect duplicates in uploaded serials that are already in the database
        existing_serials = set()
        for r in preview_data:
            serial = r.get('serial_number')
            if serial and ProductInstance.query.filter_by(serial_number=serial).first():
                existing_serials.add(str(serial))
        if existing_serials:
            flash(f"Duplicate serial(s) already in inventory: {', '.join(existing_serials)}", 'error')
        import io, base64
        excel_io = io.BytesIO()
        df.to_excel(excel_io, index=False)
        excel_b64 = base64.b64encode(excel_io.getvalue()).decode('utf-8')
        return render_template(
            'upload_product.html',
            vendors=vendors,
            preview_columns=preview_columns,
            preview_data=preview_data,
            vendor_id=vendor_id,
            excel_data=excel_b64
        )

    # GET
    return render_template('upload_product.html', vendors=vendors)

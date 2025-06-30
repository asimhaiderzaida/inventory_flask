from flask import Blueprint, request, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from ..models import db, Product, Vendor, Location, ProductInstance
from datetime import datetime
import pandas as pd
from inventory_flask_app import csrf
from inventory_flask_app.utils import get_now_for_tenant

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

@csrf.exempt
@import_excel_bp.route('/upload_excel', methods=['GET', 'POST'])
@login_required
def upload_excel():
    vendors = Vendor.query.all()
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
    if request.method == 'POST':
        file = request.files.get('file')
        vendor_id = request.form.get('vendor_id')

        # If this is a confirmation step (user clicked Confirm Import)
        if request.form.get('confirm') == 'yes':
            import io, base64
            excel_data = request.form.get('excel_data')
            if not excel_data or not vendor_id:
                flash('Missing data for import.', 'error')
                return render_template('upload_product.html', vendors=vendors, locations=locations)
            decoded = base64.b64decode(excel_data)
            df = pd.read_excel(io.BytesIO(decoded))
            df.dropna(how='all', inplace=True)
            df.columns = [col.strip() for col in df.columns]
            df.rename(columns={
                'Product Name': 'item_name',
                'Item': 'item_name',
                'Item Name': 'item_name',
                'Product': 'item_name'
            }, inplace=True)
            print("CONFIRM IMPORT ROW COUNT:", len(df))
            new_instances = []
            updated_instances = []

            for _, row in df.iterrows():
                print("Processing row:", row.to_dict())
                serial = str(row.get('serial') or '').strip()
                asset = str(row.get('asset') or '').strip()
                if not serial or serial.lower() in ('', 'nan', 'none'):
                    print("SKIPPED: Serial missing or invalid", row.to_dict())
                    continue
                if not asset or asset.lower() in ('', 'nan', 'none'):
                    print("SKIPPED: Asset  missing or invalid", row.to_dict())
                    continue

                model = str(row.get('model') or '').strip()
                item_name = str(row.get('item_name') or '').strip() or model
                if not item_name or not model:
                    print("SKIPPED: item_name and model missing", row.to_dict())
                    continue

                cpu = row.get('cpu')
                ram = row.get('ram')
                if not cpu or not ram:
                    print("SKIPPED: CPU or RAM missing", row.to_dict())
                    continue

                # Check if serial already exists BEFORE creating new product
                existing_instance = ProductInstance.query.filter_by(serial=serial, tenant_id=current_user.tenant_id).first()
                if existing_instance:
                    product = existing_instance.product
                    product.item_name = item_name
                    product.make = row.get('make')
                    product.model = model
                    product.display = row.get('display')
                    product.cpu = cpu
                    product.ram = ram
                    product.gpu1 = row.get('gpu1')
                    product.gpu2 = row.get('gpu2')
                    product.grade = row.get('grade')
                    product.disk1size = row.get('disk1size')
                    product.vendor_id = int(vendor_id)
                    product.location_id = get_location_id(row.get('location')) if row.get('location') else product.location_id
                    product.updated_at = get_now_for_tenant()

                    existing_instance.asset = asset
                    existing_instance.status = 'unprocessed'
                    existing_instance.location_id = product.location_id
                    existing_instance.updated_at = get_now_for_tenant()

                    db.session.add(product)
                    db.session.add(existing_instance)
                    updated_instances.append(existing_instance)
                    continue

                # Always create a new product for each serial (no reuse)
                product = Product(
                    item_name=item_name,
                    make=row.get('make'),
                    model=model,
                    display=row.get('display'),
                    cpu=cpu,
                    ram=ram,
                    gpu1=row.get('gpu1'),
                    gpu2=row.get('gpu2'),
                    grade=row.get('grade'),
                    disk1size=row.get('disk1size'),
                    stock=0,
                    vendor_id=int(vendor_id),
                    location_id=get_location_id(row.get('location')) if row.get('location') else None,
                    created_at=get_now_for_tenant(),
                    tenant_id=current_user.tenant_id
                )
                try:
                    db.session.add(product)
                    db.session.flush()
                    if not product.id:
                        print("SKIPPED: Product flush failed, no ID generated", row.to_dict())
                        continue
                except Exception as e:
                    print(f"SKIPPED: Failed to create product - {e}", row.to_dict())
                    db.session.rollback()
                    continue

                instance = ProductInstance(
                    serial=serial,
                    asset=asset,
                    status='unprocessed',
                    product_id=product.id,
                    location_id=product.location_id,
                    tenant_id=current_user.tenant_id,
                )
                db.session.add(instance)
                new_instances.append(instance)
            db.session.commit()

            total_new = len(new_instances)
            total_updated = len(updated_instances)

            if total_new == 0 and total_updated == 0:
                flash('No products were imported or updated.', 'warning')
                return redirect(url_for('import_excel_bp.upload_excel'))

            summary_instances = new_instances + updated_instances
            instance_ids = [i.id for i in summary_instances]
            summary_instances = ProductInstance.query.filter(ProductInstance.id.in_(instance_ids)).all()

            flash(f"Imported {total_new} new and updated {total_updated} existing products.", "success")
            locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
            return render_template(
                'upload_result.html',
                instances=summary_instances,
                vendor=Vendor.query.filter_by(id=int(vendor_id), tenant_id=current_user.tenant_id).first(),
                locations=locations
            )

        # STEP 1: PREVIEW — do not import yet!
        if not file or not vendor_id:
            flash('Please upload a file and select a vendor.', 'error')
            return render_template('upload_product.html', vendors=vendors, locations=locations)
        try:
            df = pd.read_excel(file)
        except Exception as e:
            flash(f"Error reading Excel file: {e}", 'error')
            return render_template('upload_product.html', vendors=vendors, locations=locations)
        # Drop fully empty rows
        df.dropna(how='all', inplace=True)
        # Strip all column names
        df.columns = [col.strip() for col in df.columns]
        df.rename(columns={
            'Product Name': 'item_name',
            'Item': 'item_name',
            'Item Name': 'item_name',
            'Product': 'item_name'
        }, inplace=True)
        required_fields = [
            'asset', 'serial', 'item_name', 'make', 'model', 'cpu', 'ram'
        ]
        missing = [field for field in required_fields if field not in df.columns]
        if missing:
            flash(f"Missing required fields in Excel: {', '.join(missing)}", 'error')
            return render_template('upload_product.html', vendors=vendors, locations=locations)
        preview_columns = list(df.columns)
        preview_data = df.to_dict(orient='records')
        print("PREVIEW ROW COUNT:", len(preview_data))
        # Detect duplicates in uploaded serials that are already in the database
        existing_serials = set()
        for r in preview_data:
            serial = r.get('serial')
            if serial and ProductInstance.query.join(Product).filter(
                ProductInstance.serial == serial,
                Product.tenant_id == current_user.tenant_id
            ).first():
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
            locations=locations,
            preview_columns=preview_columns,
            preview_data=preview_data,
            vendor_id=vendor_id,
            excel_data=excel_b64
        )

    # GET
    return render_template('upload_product.html', vendors=vendors, locations=locations)

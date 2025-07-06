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
        # Handle batch status/location assignment form submission
        if 'assign_status_location' in request.form:
            updated_count = 0
            for instance_id in request.form.getlist('instance_ids'):
                instance = ProductInstance.query.get(int(instance_id))
                if not instance:
                    continue

                updated = False

                # Desired values
                desired_status = request.form.get('status')
                desired_location_id = request.form.get('location_id')

                # Compare before assigning
                if desired_status and instance.status != desired_status:
                    instance.status = desired_status
                    updated = True

                if desired_location_id and str(instance.location_id) != desired_location_id:
                    instance.location_id = int(desired_location_id)
                    updated = True

                if updated:
                    instance.updated_at = get_now_for_tenant()
                    db.session.add(instance)
                    updated_count += 1

            if updated_count == 0:
                flash("✅ All units already had the desired status and location. Nothing was updated.", "info")
            else:
                flash(f"✅ {updated_count} unit(s) updated successfully.", "success")
            return redirect(url_for('import_excel_bp.upload_excel'))

        file = request.files.get('file')
        vendor_id = request.form.get('vendor_id')

        # If this is a confirmation step (user clicked Confirm Import)
        if request.form.get('confirm') == 'yes':
            location_id = request.form.get('location_id')
            import io, base64
            excel_data = request.form.get('excel_data')
            if not excel_data or not vendor_id:
                flash('Missing data for import.', 'error')
                return render_template('upload_product.html', vendors=vendors, locations=locations)
            decoded = base64.b64decode(excel_data)
            df = pd.read_excel(io.BytesIO(decoded))
            # Only keep fields defined in Product or ProductInstance models
            allowed_columns = {
                'asset', 'serial', 'item_name', 'make', 'model', 'cpu', 'ram',
                'display', 'gpu1', 'gpu2', 'grade', 'disk1size', 'location'
            }
            df = df[[col for col in df.columns if col in allowed_columns]]
            df.dropna(how='all', inplace=True)
            df.columns = [col.strip() for col in df.columns]
            df.rename(columns={
                'Product Name': 'item_name',
                'Item': 'item_name',
                'Item Name': 'item_name',
                'Product': 'item_name'
            }, inplace=True)

            print("CONFIRM IMPORT ROW COUNT:", len(df))
            updated_instances = []
            skipped_count = 0
            skipped_log = []
            new_instance_product_pairs = []

            for _, row in df.iterrows():
                print("Processing row:", row.to_dict())
                serial = str(row.get('serial') or '').strip()
                asset = str(row.get('asset') or '').strip()
                if not serial or serial.lower() in ('', 'nan', 'none'):
                    skipped_count += 1
                    skipped_log.append("SKIPPED: Serial missing or invalid " + str(row.to_dict()))
                    print("SKIPPED: Serial missing or invalid", row.to_dict())
                    continue
                if not asset or asset.lower() in ('', 'nan', 'none'):
                    skipped_count += 1
                    skipped_log.append("SKIPPED: Asset  missing or invalid " + str(row.to_dict()))
                    print("SKIPPED: Asset  missing or invalid", row.to_dict())
                    continue

                model = str(row.get('model') or '').strip()
                item_name = str(row.get('item_name') or '').strip() or model
                if not item_name or not model:
                    skipped_count += 1
                    skipped_log.append("SKIPPED: item_name and model missing " + str(row.to_dict()))
                    print("SKIPPED: item_name and model missing", row.to_dict())
                    continue

                cpu = row.get('cpu')
                ram = row.get('ram')
                if not cpu or not ram:
                    skipped_count += 1
                    skipped_log.append("SKIPPED: CPU or RAM missing " + str(row.to_dict()))
                    print("SKIPPED: CPU or RAM missing", row.to_dict())
                    continue

                # Check if serial already exists BEFORE creating new product
                existing_instance = ProductInstance.query.filter_by(serial=serial, tenant_id=current_user.tenant_id).first()
                if existing_instance:
                    product = existing_instance.product
                    updated = False

                    # Clean new data
                    item_name_clean = str(item_name or '').strip()
                    make_clean = str(row.get('make') or '').strip()
                    model_clean = model
                    display_clean = str(row.get('display') or '').strip()
                    cpu_clean = str(cpu or '').strip()
                    ram_clean = str(ram or '').strip()
                    gpu1_clean = str(row.get('gpu1') or '').strip()
                    gpu2_clean = str(row.get('gpu2') or '').strip()
                    grade_clean = str(row.get('grade') or '').strip()
                    disk_clean = str(row.get('disk1size') or '').strip()
                    loc_clean = get_location_id(row.get('location')) if row.get('location') else product.location_id

                    # Compare and update if needed
                    if product.item_name != item_name_clean:
                        product.item_name = item_name_clean
                        updated = True
                    if product.make != make_clean:
                        product.make = make_clean
                        updated = True
                    if product.model != model_clean:
                        product.model = model_clean
                        updated = True
                    if product.display != display_clean:
                        product.display = display_clean
                        updated = True
                    if product.cpu != cpu_clean:
                        product.cpu = cpu_clean
                        updated = True
                    if product.ram != ram_clean:
                        product.ram = ram_clean
                        updated = True
                    if product.gpu1 != gpu1_clean:
                        product.gpu1 = gpu1_clean
                        updated = True
                    if product.gpu2 != gpu2_clean:
                        product.gpu2 = gpu2_clean
                        updated = True
                    if product.grade != grade_clean:
                        product.grade = grade_clean
                        updated = True
                    if product.disk1size != disk_clean:
                        product.disk1size = disk_clean
                        updated = True
                    if str(product.vendor_id) != str(vendor_id):
                        product.vendor_id = int(vendor_id)
                        updated = True
                    if product.location_id != loc_clean:
                        product.location_id = loc_clean
                        updated = True

                    # Always update instance status/location
                    existing_instance.asset = asset
                    existing_instance.status = 'unprocessed'
                    existing_instance.location_id = int(location_id) if location_id else product.location_id
                    existing_instance.updated_at = get_now_for_tenant()
                    product.updated_at = get_now_for_tenant()

                    if updated:
                        db.session.add(product)
                        updated_instances.append(existing_instance)

                    db.session.add(existing_instance)
                    continue

                # Always create a new product for each serial (no reuse)
                product = Product(
                    item_name=str(item_name or '').strip(),
                    make=str(row.get('make') or '').strip(),
                    model=model,
                    display=str(row.get('display') or '').strip(),
                    cpu=str(cpu or '').strip(),
                    ram=str(ram or '').strip(),
                    gpu1=str(row.get('gpu1') or '').strip(),
                    gpu2=str(row.get('gpu2') or '').strip(),
                    grade=str(row.get('grade') or '').strip(),
                    disk1size=str(row.get('disk1size') or '').strip(),
                    stock=0,
                    vendor_id=int(vendor_id),
                    location_id=int(location_id) if location_id else get_location_id(row.get('location')) if row.get('location') else None,
                    created_at=get_now_for_tenant(),
                    tenant_id=current_user.tenant_id
                )
                instance = ProductInstance(
                    serial=serial,
                    asset=asset,
                    status='unprocessed',
                    product_id=None,  # Will set after flush
                    location_id=product.location_id,
                    tenant_id=current_user.tenant_id,
                )
                new_instance_product_pairs.append((instance, product))

            if new_instance_product_pairs:
                new_products = [p for (_, p) in new_instance_product_pairs]
                db.session.add_all(new_products)
                db.session.flush()

                for instance, product in new_instance_product_pairs:
                    instance.product_id = product.id

                new_instances = [i for (i, _) in new_instance_product_pairs]
                db.session.add_all(new_instances)
                db.session.flush()

            db.session.commit()

            total_new = len(new_instance_product_pairs)
            total_updated = len(updated_instances)

            if total_new == 0 and total_updated == 0:
                flash('⚠️ No products were changed, but showing summary for manual assignment.', 'info')

            if 'new_instances' not in locals():
                new_instances = []

            summary_instances = new_instances + updated_instances
            instance_ids = [i.id for i in summary_instances if i and i.id]
            summary_instances = ProductInstance.query.filter(ProductInstance.id.in_(instance_ids)).all()

            flash(f"✅ Imported: {total_new} | ♻️ Updated: {total_updated} | ⚠️ Skipped: {skipped_count}", "success")
            locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
            return render_template(
                'upload_result.html',
                instances=summary_instances,
                vendor=Vendor.query.filter_by(id=int(vendor_id), tenant_id=current_user.tenant_id).first(),
                locations=locations,
                skipped_log=skipped_log
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
        # Only keep allowed columns (same as confirm section)
        allowed_columns = {
            'asset', 'serial', 'item_name', 'make', 'model', 'cpu', 'ram',
            'display', 'gpu1', 'gpu2', 'grade', 'disk1size', 'location'
        }
        df = df[[col for col in df.columns if col in allowed_columns]]
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
                ProductInstance.serial == str(serial),
                Product.tenant_id == current_user.tenant_id
            ).first():
                existing_serials.add(str(serial))
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

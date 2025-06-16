import qrcode
from io import BytesIO
import base64
from inventory_flask_app.utils.utils import get_instance_id
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, make_response
from flask_login import login_required
from inventory_flask_app.models import db, Product, ProductInstance, PurchaseOrder, Vendor, Location
from inventory_flask_app.models import CustomerOrderTracking
from sqlalchemy.orm import aliased
from datetime import datetime
import csv
from io import StringIO


stock_bp = Blueprint('stock_bp', __name__, url_prefix='/stock')

# Simple stock_intake page route
@stock_bp.route('/stock_intake')
@login_required
def stock_intake():
    return render_template('stock_intake.html')

@stock_bp.route('/purchase_order/create', methods=['GET', 'POST'])
@login_required
def create_purchase_order():
    if request.method == 'POST':
        po_number = request.form.get('po_number')
        vendor_id = request.form.get('vendor_id')
        file = request.files.get('file')
        if not po_number or not vendor_id or not file or file.filename == "":
            flash("PO Number, Vendor and Excel file are required.", "danger")
            return redirect(url_for('stock_bp.create_purchase_order'))

        existing_po = PurchaseOrder.query.filter_by(po_number=po_number).first()
        if existing_po:
            flash(f"PO Number '{po_number}' already exists. Please use a unique PO Number.", "danger")
            return redirect(url_for('stock_bp.create_purchase_order'))

        import pandas as pd
        try:
            df = pd.read_excel(file)
        except Exception as e:
            flash(f"❌ Could not read Excel file: {e}", "danger")
            return redirect(url_for('stock_bp.create_purchase_order'))

        required_columns = ['serial_number', 'model_number']
        if not all(col in df.columns for col in required_columns):
            flash("Excel must include 'serial_number' and 'model_number'", "danger")
            return redirect(url_for('stock_bp.create_purchase_order'))

        serials = [str(s).strip() for s in df['serial_number'].dropna()]
        if not serials:
            flash("No valid serial numbers found in Excel.", "warning")
            return redirect(url_for('stock_bp.create_purchase_order'))

        po = PurchaseOrder(po_number=po_number, vendor_id=int(vendor_id), expected_serials=",".join(serials))
        db.session.add(po)
        db.session.commit()
        session['po_id'] = po.id
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        session['po_spec_data'] = df.to_dict(orient='records')
        flash(f"✅ PO {po.po_number} (ID #{po.id}) created with {len(serials)} serials.", "success")
        return redirect(url_for('stock_bp.create_purchase_order'))
    vendors = Vendor.query.all()
    print("Vendors in PO:", [v.name for v in vendors])
    return render_template('create_purchase_order.html', vendors=vendors)

@stock_bp.route('/stock_receiving/select', methods=['GET', 'POST'])
@login_required
def stock_receiving_select():
    po_list = PurchaseOrder.query.filter(
        PurchaseOrder.po_number.isnot(None),
        PurchaseOrder.status == "pending"
    ).all()
    if request.method == 'POST':
        po_number = request.form.get('po_number')
        po = PurchaseOrder.query.filter_by(po_number=po_number).first()
        if not po:
            flash("Purchase Order not found.", "danger")
            return redirect(url_for('stock_bp.stock_receiving_select'))
        session['po_id'] = po.id
        session['scanned'] = []
        flash(f"PO #{po_number} loaded for receiving.", "success")
        return redirect(url_for('stock_bp.stock_receiving_scan'))
    return render_template('stock_receiving_select.html', po_list=po_list)

@stock_bp.route('/stock_receiving/scan', methods=['GET', 'POST'])
@login_required
def stock_receiving_scan():
    po_id = session.get('po_id')
    if not po_id:
        flash("PO not found in session.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))
    po = PurchaseOrder.query.get(po_id)
    expected_serials = [s.strip() for s in po.expected_serials.split(',') if s.strip()]
    scanned = session.get('scanned', [])
    if request.method == 'POST':
        serial = request.form.get('serial_input', '').strip()
        if serial:
            scanned.append(serial)
            session['scanned'] = scanned
    matched = list(set(expected_serials) & set(scanned))
    extra = list(set(scanned) - set(expected_serials))
    missing = list(set(expected_serials) - set(scanned))
    return render_template(
        'stock_receiving_scan.html',
        po=po,
        matched=matched,
        extra=extra,
        missing=missing,
        scanned=scanned,
        total_expected=len(expected_serials)
    )

@stock_bp.route('/stock_receiving/summary')
@login_required
def stock_receiving_summary():
    po_id = session.get('po_id')
    if not po_id:
        flash("PO session missing.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))
    po = PurchaseOrder.query.get(po_id)
    expected_serials = [s.strip() for s in po.expected_serials.split(',') if s.strip()]
    scanned = session.get('scanned', [])
    matched = list(set(expected_serials) & set(scanned))
    extra = list(set(scanned) - set(expected_serials))
    missing = list(set(expected_serials) - set(scanned))
    spec_data = session.get('po_spec_data', [])
    print("spec_data in session:", spec_data)
    full_table = []
    for row in spec_data:
        serial = str(row.get('serial_number')).strip()
        status = (
            "Matched" if serial in matched else
            "Extra" if serial in extra else
            "Missing" if serial in missing else "Unknown"
        )
        row['match_status'] = status
        instance_id = get_instance_id(serial)
        print(f"Serial: {serial}  -->  Instance ID: {instance_id}")
        row['instance_id'] = instance_id
        full_table.append(row)
    matched_count = len([s for s in full_table if s['match_status'] == 'Matched'])
    extra_count = len([s for s in full_table if s['match_status'] == 'Extra'])
    missing_count = len([s for s in full_table if s['match_status'] == 'Missing'])
    total_count = len(full_table)
    return render_template('stock_receiving_summary.html', po=po, serials=full_table,
                           matched_count=matched_count, extra_count=extra_count,
                           missing_count=missing_count, total_count=total_count,
                           get_instance_id=get_instance_id)

def export_csv(data, columns, filename):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in data:
        writer.writerow({col: row.get(col, '') for col in columns})
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv'
    return response

@stock_bp.route('/stock_receiving/export/<category>')
@login_required
def stock_receiving_export(category):
    spec_data = session.get('po_spec_data', [])
    if not spec_data:
        flash("No data available for export.", "warning")
        return redirect(url_for('stock_bp.stock_receiving_summary'))
    export_rows = []
    for row in spec_data:
        status = row.get('match_status')
        if status and status.lower() == category:
            export_rows.append(row)
    if not export_rows:
        flash(f"No rows found for category '{category}'", "info")
        return redirect(url_for('stock_bp.stock_receiving_summary'))
    columns = list(export_rows[0].keys())
    filename = f'{category}_serials_export.csv'
    return export_csv(export_rows, columns, filename)

@stock_bp.route('/stock_receiving/confirm', methods=['POST'])
@login_required
def stock_receiving_confirm():
    po_id = session.get('po_id')
    matched = session.get('scanned', [])
    spec_data = session.get('po_spec_data', [])
    status_choice = request.form.get('status_choice')
    if not po_id or not matched:
        flash("Session expired or invalid.", "error")
        return redirect(url_for('dashboard_bp.main_dashboard'))
    if not status_choice:
        flash("Please select a status before importing.", "danger")
        return redirect(url_for('stock_bp.stock_receiving_summary'))
    allowed_statuses = ['unprocessed', 'under_process', 'processed', 'sold']
    if status_choice not in allowed_statuses:
        flash("Invalid status selected.", "danger")
        return redirect(url_for('stock_bp.stock_receiving_summary'))
    po = PurchaseOrder.query.get(po_id)
    imported = 0
    for serial in matched:
        serial = serial.strip()
        if ProductInstance.query.filter_by(serial_number=serial).first():
            flash(f"⚠️ Serial {serial} already exists in inventory and was skipped.", "warning")
            continue
        row = next((item for item in spec_data if str(item.get('serial_number')).strip() == serial), None)
        if not row:
            continue
        product = Product.query.filter_by(
            model_number=row.get('model_number'),
            vendor_id=po.vendor_id,
            processor=row.get('processor'),
            ram=row.get('ram'),
            storage=row.get('storage'),
            screen_size=row.get('screen_size'),
            resolution=row.get('resolution'),
            grade=row.get('grade'),
            video_card=row.get('video_card')
        ).first()
        if not product:
            product = Product(
                name=row.get('product_name') or "Imported Product",
                model_number=row.get('model_number'),
                barcode=serial,
                vendor_id=po.vendor_id,
                processor=row.get('processor'),
                ram=row.get('ram'),
                storage=row.get('storage'),
                screen_size=row.get('screen_size'),
                resolution=row.get('resolution'),
                grade=row.get('grade'),
                video_card=row.get('video_card'),
                purchase_price=row.get('purchase_price') or 0,
                selling_price=row.get('selling_price') or 0,
                stock=0,
                location_id=None,
                is_damaged=False
            )
            db.session.add(product)
            db.session.flush()
        else:
            # Update product name if it's still the default and new import has a name
            if product.name == "Imported Product" and row.get('product_name'):
                product.name = row.get('product_name')
                db.session.add(product)
                db.session.flush()
        instance = ProductInstance(
            product_id=product.id,
            serial_number=serial,
            status=status_choice,
            location_id=product.location_id,
            po_id=po.id
        )
        db.session.add(instance)
        imported += 1
    from inventory_flask_app.models import POImportLog
    from flask_login import current_user
    log = POImportLog(
        po_id=po_id,
        user_id=current_user.id,
        status=status_choice,
        quantity=imported
    )
    db.session.add(log)
    # Set PO status to "received" before committing
    po.status = "received"
    db.session.commit()
    flash(f"✅ {imported} matched units imported as '{status_choice}'.", "success")
    session.pop('scanned', None)
    session.pop('po_id', None)
    session.pop('po_spec_data', None)
    return redirect(url_for('dashboard_bp.main_dashboard'))


# Batch label printing route
@stock_bp.route('/print_labels_batch', methods=['POST'])
@login_required
def print_labels_batch():
    from datetime import datetime
    ids = request.form.getlist('instance_ids')
    if not ids:
        flash("No items selected for label printing.", "warning")
        return redirect(request.referrer or url_for('stock_bp.under_process'))
    # Query instances
    instances = ProductInstance.query.filter(ProductInstance.id.in_(ids)).all()
    # Generate QR codes for each
    batch_labels = []
    for instance in instances:
        qr_data = {
            "serial": instance.serial_number,
            "model": instance.product.model_number if instance.product else "",
            "cpu": instance.product.processor if instance.product else "",
            "ram": instance.product.ram if instance.product else "",
            "storage": instance.product.storage if instance.product else "",
            "vendor": instance.product.vendor.name if instance.product and instance.product.vendor else "",
        }
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_b64 = base64.b64encode(buffered.getvalue()).decode()
        batch_labels.append({
            "instance": instance,
            "qr_b64": qr_b64,
            "printed_time": datetime.now(),
        })
    return render_template("batch_print_labels.html", batch_labels=batch_labels)

@stock_bp.route('/under_process', methods=['GET', 'POST'])
@login_required
def under_process():
    status_filter = request.args.get('status')
    model_filter = request.args.get('model')
    processor_filter = request.args.get('processor')
    serial_search = request.args.get('serial_search', '').strip()
    stage_filter = request.args.get('stage')
    team_filter = request.args.get('team')

    # Enhanced: Support "all" for status
    if not status_filter or status_filter == 'all':
        query = ProductInstance.query
    else:
        # Only show not sold for each inventory status view
        if status_filter == 'unprocessed':
            query = ProductInstance.query.filter_by(status='unprocessed', is_sold=False)
        elif status_filter == 'under_process':
            query = ProductInstance.query.filter_by(status='under_process', is_sold=False)
        elif status_filter == 'processed':
            query = ProductInstance.query.filter_by(status='processed', is_sold=False)
        else:
            query = ProductInstance.query.filter_by(status=status_filter)
    if model_filter:
        query = query.join(Product).filter(Product.model_number == model_filter)
    if processor_filter:
        query = query.join(Product).filter(Product.processor == processor_filter)
    if serial_search:
        query = query.filter(ProductInstance.serial_number.ilike(f"%{serial_search}%"))
    if stage_filter:
        query = query.filter_by(process_stage=stage_filter)
    if team_filter:
        query = query.filter(ProductInstance.team_assigned.ilike(f"%{team_filter}%"))

    # Always exclude sold items for inventory views
    if not status_filter or status_filter == 'all':
        query = query.filter(ProductInstance.is_sold == False)

    # Exclude all reserved units from inventory views
    reserved_order = aliased(CustomerOrderTracking)
    query = query.outerjoin(
        reserved_order,
        (reserved_order.product_instance_id == ProductInstance.id) &
        (reserved_order.status == 'reserved')
    ).filter(reserved_order.id == None)

    instances = query.all()
    all_models = list({i.product.model_number for i in instances if i.product and i.product.model_number})
    all_processors = list({i.product.processor for i in instances if i.product and i.product.processor})
    distinct_stages = db.session.query(ProductInstance.process_stage).distinct().all()
    distinct_teams = db.session.query(ProductInstance.team_assigned).distinct().all()

    print("INSTANCES:", instances)
    if instances:
        print("First instance:", instances[0], "ID:", instances[0].id)
    return render_template(
        'instance_table.html',
        instances=instances,
        models=sorted(all_models),
        processors=sorted(all_processors),
        stages=[s[0] for s in distinct_stages if s[0]],
        teams=[t[0] for t in distinct_teams if t[0]],
        selected_stage=stage_filter,
        selected_team=team_filter,
        title=(
            "Unprocessed Inventory" if status_filter == 'unprocessed'
            else "Processed Inventory" if status_filter == 'processed'
            else "Under Process Inventory"
        )
    )

@stock_bp.route('/process_stage/update', methods=['GET', 'POST'])
@login_required
def process_stage_update():
    results = []
    if request.method == 'POST':
        serials_raw = request.form.get('serials', '')
        process_stage = request.form.get('process_stage')
        team = request.form.get('team_assigned')
        # Split serials by newline, comma, or space
        serials = [s.strip() for s in serials_raw.replace(',', ' ').replace('\n', ' ').split() if s.strip()]
        updated, not_found, no_change = 0, 0, 0
        for serial in serials:
            instance = ProductInstance.query.filter_by(serial_number=serial).first()
            if instance:
                prev_stage = instance.process_stage or '-'
                if instance.process_stage == process_stage and instance.team_assigned == team:
                    # No change needed
                    results.append({
                        'serial': serial,
                        'model': instance.product.model_number if instance.product else '',
                        'prev_stage': prev_stage,
                        'status': 'no_change'
                    })
                    no_change += 1
                else:
                    instance.process_stage = process_stage
                    instance.team_assigned = team
                    # Also set status if needed
                    if instance.status != 'under_process':
                        instance.status = 'under_process'
                    instance.updated_at = datetime.utcnow()
                    db.session.commit()
                    results.append({
                        'serial': serial,
                        'model': instance.product.model_number if instance.product else '',
                        'prev_stage': prev_stage,
                        'status': 'updated'
                    })
                    updated += 1
            else:
                results.append({
                    'serial': serial,
                    'model': '',
                    'prev_stage': '-',
                    'status': 'not_found'
                })
                not_found += 1
        flash(f"{updated} updated, {no_change} already at stage, {not_found} not found.", "info")
        return render_template('process_stage_update.html', results=results)
    # GET: just show the empty form
    return render_template('process_stage_update.html', results=None)

@stock_bp.route('/instance/<int:instance_id>/view_edit', methods=['GET', 'POST'])
@login_required
def view_edit_instance(instance_id):
    instance = ProductInstance.query.get_or_404(instance_id)
    allowed_statuses = ['unprocessed', 'under_process', 'processed', 'sold']
    if request.method == 'POST':
        # Allow editing status, team, and process stage
        status = request.form.get('status', instance.status)
        if status not in allowed_statuses:
            flash("Invalid status selected.", "danger")
            return redirect(url_for('stock_bp.view_edit_instance', instance_id=instance.id))
        instance.status = status
        instance.process_stage = request.form.get('process_stage', instance.process_stage)
        instance.team_assigned = request.form.get('team_assigned', instance.team_assigned)
        db.session.commit()
        flash("Instance updated.", "success")
        return redirect(url_for('stock_bp.view_edit_instance', instance_id=instance.id))
    return render_template('view_edit_instance.html', instance=instance)

# Delete ProductInstance route
@stock_bp.route('/instance/<int:instance_id>/delete', methods=['POST'])
@login_required
def delete_instance(instance_id):
    instance = ProductInstance.query.get_or_404(instance_id)
    db.session.delete(instance)
    db.session.commit()
    flash(f"Serial {instance.serial_number} deleted successfully.", "success")
    return redirect(url_for('stock_bp.under_process'))

@stock_bp.route('/export_instances')
@login_required
def export_instances():
    status = request.args.get('status')
    model = request.args.get('model')
    processor = request.args.get('processor')
    serial_search = request.args.get('serial_search', '').strip()

    query = ProductInstance.query
    if status:
        query = query.filter_by(status=status)
    if model:
        query = query.join(Product).filter(Product.model_number == model)
    if processor:
        query = query.join(Product).filter(Product.processor == processor)
    if serial_search:
        query = query.filter(ProductInstance.serial_number.ilike(f"%{serial_search}%"))

    instances = query.all()
    data = []
    for i in instances:
        data.append({
            "Serial": i.serial_number,
            "Product": i.product.name if i.product else '',
            "Model": i.product.model_number if i.product else '',
            "Vendor": i.product.vendor.name if i.product and i.product.vendor else '',
            "Status": i.status,
            "Process Stage": i.process_stage or '',
            "Team": i.team_assigned or '',
            "Location": i.location.name if i.location else '',
            "Is Sold": "Yes" if i.is_sold else "No"
        })
    import pandas as pd
    from io import BytesIO
    output = BytesIO()
    df = pd.DataFrame(data)
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Instances')
    output.seek(0)
    from flask import send_file
    return send_file(output, as_attachment=True, download_name='instances_export.xlsx')

@stock_bp.route('/scan_move', methods=['GET', 'POST'])
@login_required
def scan_move():
    # Use session to keep batch list between requests
    if 'batch_serials' not in session:
        session['batch_serials'] = []

    batch_serials = session.get('batch_serials', [])
    instances = []
    serial_number = ""

    # Handle serial scan
    if request.method == 'POST':
        # Remove serial (if user clicked 'remove')
        remove_serial = request.form.get('remove_serial')
        if remove_serial:
            batch_serials = [s for s in batch_serials if s != remove_serial]
            session['batch_serials'] = batch_serials
            session.modified = True
        # Add serial (on scan/submit)
        elif 'serial_number' in request.form and request.form.get('serial_number').strip():
            serial_number = request.form.get('serial_number').strip()
            if serial_number not in batch_serials:
                batch_serials.append(serial_number)
                session['batch_serials'] = batch_serials
                session.modified = True
        # Handle "Move/Assign All"
        elif 'move_all' in request.form:
            status = request.form.get('status')
            process_stage = request.form.get('process_stage')
            team_assigned = request.form.get('team_assigned')
            location_id = request.form.get('location_id')
            shelf_bin = request.form.get('shelf_bin', '').strip()
            updated = 0
            for serial in batch_serials:
                if status not in ['unprocessed', 'under_process', 'processed', 'sold']:
                    flash("Invalid status selected.", "danger")
                    break
                instance = ProductInstance.query.filter_by(serial_number=serial).first()
                if instance:
                    instance.status = status
                    instance.process_stage = process_stage
                    instance.team_assigned = team_assigned
                    if location_id:
                        instance.location_id = int(location_id)
                    if shelf_bin:
                        instance.shelf_bin = shelf_bin
                    updated += 1
            db.session.commit()
            flash(f"{updated} serial(s) updated successfully.", "success")
            batch_serials = []
            session['batch_serials'] = batch_serials
            session.modified = True

    # Build instances list for display (show info for each scanned serial)
    for s in batch_serials:
        instance = ProductInstance.query.filter_by(serial_number=s).first()
        instances.append(instance)

    return render_template(
        'scan_move.html',
        instances=instances,
        serial_number=serial_number,
        locations=Location.query.all()
    )


# QR code label printing route
@stock_bp.route('/print_label/<int:instance_id>')
@login_required
def print_label(instance_id):
    from datetime import datetime
    instance = ProductInstance.query.get_or_404(instance_id)
    if not instance.product:
        flash("No product linked to this instance.", "danger")
        return redirect(request.referrer or url_for('dashboard_bp.main_dashboard'))

    # Encode key info as QR code
    qr_data = {
        "serial": instance.serial_number,
        "model": instance.product.model_number,
        "cpu": instance.product.processor,
        "ram": instance.product.ram,
        "storage": instance.product.storage,
        "vendor": instance.product.vendor.name if instance.product.vendor else "",
    }
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Save QR code image to base64 for embedding in HTML
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    qr_b64 = base64.b64encode(buffered.getvalue()).decode()

    return render_template(
        "print_label.html",
        instance=instance,
        qr_b64=qr_b64,
        printed_time=datetime.now()
    )

@stock_bp.route('/batch_update_status', methods=['POST'])
@login_required
def batch_update_status():
    ids = request.form.getlist('instance_ids')
    status = request.form.get('status')
    if not ids or not status:
        flash("Please select at least one item and a status.", "danger")
        return redirect(request.referrer or url_for('dashboard_bp.main_dashboard'))

    # Only allow certain statuses for safety
    allowed_statuses = ['unprocessed', 'under_process', 'processed', 'sold']
    if status not in allowed_statuses:
        flash("Invalid status selected.", "danger")
        return redirect(request.referrer or url_for('dashboard_bp.main_dashboard'))

    updated_count = 0
    for instance in ProductInstance.query.filter(ProductInstance.id.in_(ids)).all():
        instance.status = status
        updated_count += 1
    db.session.commit()

    flash(f"Updated {updated_count} item(s) to status: {status.replace('_', ' ').title()}.", "success")
    return redirect(request.referrer or url_for('dashboard_bp.main_dashboard'))

@stock_bp.route('/sold')
@login_required
def sold_items():
    from inventory_flask_app.models import SaleTransaction, Customer
    # Get filter params
    customer_id = request.args.get('customer')
    sale_date = request.args.get('sale_date')

    # Find all sold product instances
    sold_instances = ProductInstance.query.filter_by(is_sold=True).all()

    # For each, get related sale transaction (most recent, if more than one)
    sold_data = []
    for instance in sold_instances:
        sale = SaleTransaction.query.filter_by(product_instance_id=instance.id).order_by(SaleTransaction.id.desc()).first()
        # Apply filters
        if customer_id and (not sale or str(sale.customer_id) != customer_id):
            continue
        if sale_date and (not sale or not sale.date_sold or sale.date_sold.strftime('%Y-%m-%d') != sale_date):
            continue
        sold_data.append({
            "serial_number": instance.serial_number,
            "product_name": instance.product.name if instance.product else "",
            "model_number": instance.product.model_number if instance.product else "",
            "cpu": instance.product.processor if instance.product else "",
            "ram": instance.product.ram if instance.product else "",
            "storage": instance.product.storage if instance.product else "",
            "screen_size": instance.product.screen_size if instance.product else "",
            "resolution": instance.product.resolution if instance.product else "",
            "grade": instance.product.grade if instance.product else "",
            "video_card": instance.product.video_card if instance.product else "",
            "customer": sale.customer.name if sale and sale.customer else "",
            "customer_id": sale.customer_id if sale else "",
            "sale_date": sale.date_sold.strftime('%Y-%m-%d') if sale and sale.date_sold else "",
            "price": sale.price_at_sale if sale else "",
        })

    # Get all customers for filter dropdown
    customers = Customer.query.order_by(Customer.name).all()
    return render_template("sold_items.html", sold_data=sold_data, customers=customers, selected_customer=customer_id, selected_date=sale_date)



# Add product page route
@stock_bp.route('/products/add', methods=['GET', 'POST'])
@login_required
def add_product_page():
    if request.method == 'POST':
        from inventory_flask_app.models import add_product_and_instance
        data = request.form.to_dict()
        data = {
            "name": data.get("name"),
            "model_number": data.get("model_number"),
            "serial_number": data.get("serial_number"),
            "processor": data.get("processor"),
            "ram": data.get("ram"),
            "storage": data.get("storage"),
            "screen_size": data.get("screen_size"),
            "resolution": data.get("resolution"),
            "grade": data.get("grade"),
            "video_card": data.get("video_card"),
            "status": data.get("status", "unprocessed")
        }
        product, instance = add_product_and_instance(db, data)
        db.session.commit()
        flash("✅ Product and instance added successfully!", "success")
        # Redirect to label printing page for the new instance
        return redirect(url_for('stock_bp.print_label', instance_id=instance.id))
    return render_template('add_product.html')
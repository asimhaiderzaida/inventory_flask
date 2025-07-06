from datetime import timedelta
import qrcode
from io import BytesIO
import base64
from inventory_flask_app.utils.utils import get_instance_id
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, make_response
from flask_login import login_required, current_user
from inventory_flask_app.models import db, Product, ProductInstance, PurchaseOrder, Vendor, Location
from inventory_flask_app.models import CustomerOrderTracking
from flask import jsonify
from sqlalchemy.orm import aliased, joinedload
from datetime import datetime
from inventory_flask_app.utils import get_now_for_tenant
import csv
from io import StringIO
from inventory_flask_app import csrf

stock_bp = Blueprint('stock_bp', __name__, url_prefix='/stock')

# Simple stock_intake page route
@csrf.exempt
@stock_bp.route('/stock_intake')
@login_required
def stock_intake():
    return render_template('stock_intake.html')

@csrf.exempt
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

        existing_po = PurchaseOrder.query.filter_by(po_number=po_number, tenant_id=current_user.tenant_id).first()
        if existing_po:
            flash(f"PO Number '{po_number}' already exists. Please use a unique PO Number.", "danger")
            return redirect(url_for('stock_bp.create_purchase_order'))

        import pandas as pd
        try:
            df = pd.read_excel(file)
        except Exception as e:
            flash(f"❌ Could not read Excel file: {e}", "danger")
            return redirect(url_for('stock_bp.create_purchase_order'))

        # Use unified product structure columns
        required_columns = ['serial', 'asset', 'item_name', 'make', 'model', 'display', 'cpu', 'ram', 'gpu1', 'gpu2', 'grade']
        # Clean columns before checking
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        # Drop any unexpected/legacy fields (e.g., screen_size)
        df = df.drop(columns=['screen_size'], errors='ignore')
        # Keep only required columns (ignore extra columns)
        df = df[[col for col in df.columns if col in required_columns]]
        # Ensure all required columns are present
        if not all(col in df.columns for col in required_columns):
            flash("Excel must include columns: 'serial', 'asset', 'item_name', 'make', 'model', 'display', 'cpu', 'ram', 'gpu1', 'gpu2', 'grade'", "danger")
            return redirect(url_for('stock_bp.create_purchase_order'))

        serials = [str(s).strip() for s in df['serial'].dropna()]
        if not serials:
            flash("No valid serial found in Excel.", "warning")
            return redirect(url_for('stock_bp.create_purchase_order'))

        po = PurchaseOrder(po_number=po_number, vendor_id=int(vendor_id), expected_serials=",".join(serials))
        # --- Tenant scoping ---
        po.tenant_id = current_user.tenant_id
        # ----------------------
        db.session.add(po)
        db.session.commit()
        session['po_id'] = po.id
        session['po_spec_data'] = df.to_dict(orient='records')
        flash(f"✅ PO {po.po_number} (ID #{po.id}) created with {len(serials)} serials.", "success")
        return redirect(url_for('stock_bp.create_purchase_order'))
    vendors = Vendor.query.all()
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
    return render_template('create_purchase_order.html', vendors=vendors, locations=locations)

@csrf.exempt
@stock_bp.route('/stock_receiving/select', methods=['GET', 'POST'])
@login_required
def stock_receiving_select():
    po_list = PurchaseOrder.query.filter(
        PurchaseOrder.po_number.isnot(None),
        PurchaseOrder.status == "pending",
        PurchaseOrder.tenant_id == current_user.tenant_id
    ).all()
    if request.method == 'POST':
        po_number = request.form.get('po_number')
        po = PurchaseOrder.query.filter_by(po_number=po_number, tenant_id=current_user.tenant_id).first()
        if not po:
            flash("Purchase Order not found.", "danger")
            return redirect(url_for('stock_bp.stock_receiving_select'))
        session['po_id'] = po.id
        session['scanned'] = []
        flash(f"PO #{po_number} loaded for receiving.", "success")
        return redirect(url_for('stock_bp.stock_receiving_scan'))
    return render_template('stock_receiving_select.html', po_list=po_list)

@csrf.exempt
@stock_bp.route('/stock_receiving/scan', methods=['GET', 'POST'])
@login_required
def stock_receiving_scan():
    po_id = session.get('po_id')
    if not po_id:
        flash("PO not found in session.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))
    po = PurchaseOrder.query.filter_by(id=po_id, tenant_id=current_user.tenant_id).first_or_404()
    expected_serials = [s.strip() for s in po.expected_serials.split(',') if s.strip()]
    expected_serials_set = set(s.strip().lower() for s in expected_serials)
    scanned = list(set(session.get('scanned', [])))  # Ensure uniqueness

    if request.method == 'POST':
        # Support resetting scanned items
        if request.form.get("reset_scanned") == "1":
            session['scanned'] = []
            flash("Scanned list has been cleared.", "info")
            return redirect(url_for('stock_bp.stock_receiving_scan'))
        serial_input = request.form.get('serial_input', '').strip()
        if serial_input and serial_input not in scanned:
            scanned.append(serial_input)
            session['scanned'] = scanned

    # Matching logic: allow scanning serial or asset, and map asset to correct serial for PO logic
    po_spec_data = session.get('po_spec_data', [])
    # Build asset_to_serial and serial_to_row maps (cleaned)
    asset_to_serial = {
        str(row.get('asset')).strip().lower(): str(row.get('serial')).strip().lower()
        for row in po_spec_data
        if row.get('asset') and row.get('serial')
    }
    serial_to_row = {
        str(r.get('serial')).strip().lower(): r for r in po_spec_data
    }

    scanned_rows = []
    for s in scanned:
        s_clean = s.strip().lower()
        matched_serial = s_clean if s_clean in expected_serials_set else asset_to_serial.get(s_clean)
        if matched_serial and matched_serial in serial_to_row:
            row = serial_to_row[matched_serial]
            row['serial'] = row.get('serial', '')
            row['asset'] = row.get('asset', '')
            scanned_rows.append(row)
        else:
            scanned_rows.append({'serial': s, 'asset': '', 'status': 'extra'})

    # Compute matched, extra, missing using the original logic:
    matched = []
    for s in scanned:
        s_clean = s.strip().lower()
        if s_clean in expected_serials_set:
            matched.append(s.strip())
        elif s_clean in asset_to_serial:
            matched.append(po_spec_data[0]['serial'] if asset_to_serial[s_clean] in serial_to_row and po_spec_data[0]['serial'] else asset_to_serial[s_clean])
    matched = list(set(matched))
    extra = [s for s in scanned if s.strip().lower() not in expected_serials_set and s.strip().lower() not in asset_to_serial]
    missing = list(set(expected_serials) - set(matched))

    return render_template(
        'stock_receiving_scan.html',
        po=po,
        matched=matched,
        extra=extra,
        missing=missing,
        scanned=scanned_rows,
        total_expected=len(expected_serials)
    )

@csrf.exempt
@stock_bp.route('/stock_receiving/summary')
@login_required
def stock_receiving_summary():
    po_id = session.get('po_id')
    if not po_id:
        flash("PO session missing.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))
    po = PurchaseOrder.query.filter_by(id=po_id, tenant_id=current_user.tenant_id).first_or_404()
    expected_serials = [s.strip() for s in po.expected_serials.split(',') if s.strip()]
    scanned = session.get('scanned', [])
    spec_data = session.get('po_spec_data', [])
    asset_to_serial = {
        str(row.get('asset')).strip(): str(row.get('serial')).strip()
        for row in spec_data
    }
    scanned_serials = set()
    for s in scanned:
        if s in expected_serials:
            scanned_serials.add(s)
        elif s in asset_to_serial:
            scanned_serials.add(asset_to_serial[s])
    matched = list(scanned_serials & set(expected_serials))
    extra = [s for s in scanned if s not in expected_serials and s not in asset_to_serial]
    missing = list(set(expected_serials) - scanned_serials)
    full_table = []
    for row in spec_data:
        serial = str(row.get('serial')).strip()
        status = (
            "Matched" if serial in matched else
            "Extra" if serial in extra else
            "Missing" if serial in missing else "Unknown"
        )
        row['match_status'] = status
        instance_id = get_instance_id(serial)
        row['instance_id'] = instance_id
        full_table.append(row)
    matched_count = len([s for s in full_table if s['match_status'] == 'Matched'])
    extra_count = len([s for s in full_table if s['match_status'] == 'Extra'])
    missing_count = len([s for s in full_table if s['match_status'] == 'Missing'])
    total_count = len(full_table)
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
    return render_template(
        'stock_receiving_summary.html',
        po=po,
        serials=full_table,
        matched_count=matched_count,
        extra_count=extra_count,
        missing_count=missing_count,
        total_count=total_count,
        get_instance_id=get_instance_id,
        locations=locations
    )

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

@csrf.exempt
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
    columns = ['serial', 'asset', 'item_name', 'make', 'model', 'display', 'cpu', 'ram', 'gpu1', 'gpu2', 'grade', 'match_status']
    filename = f'{category}_serials_export.csv'
    return export_csv(export_rows, columns, filename)

@csrf.exempt
@stock_bp.route('/stock_receiving/confirm', methods=['POST'])
@login_required
def stock_receiving_confirm():
    po_id = session.get('po_id')
    scanned = session.get('scanned', [])
    spec_data = session.get('po_spec_data', [])
    status_choice = request.form.get('status_choice')
    location_id = request.form.get('location_choice')

    if not po_id or not scanned:
        flash("Session expired or invalid.", "error")
        return redirect(url_for('dashboard_bp.main_dashboard'))
    if not status_choice:
        flash("Please select a status before importing.", "danger")
        return redirect(url_for('stock_bp.stock_receiving_summary'))

    allowed_statuses = ['unprocessed', 'under_process', 'processed', 'sold']
    if status_choice not in allowed_statuses:
        flash("Invalid status selected.", "danger")
        return redirect(url_for('stock_bp.stock_receiving_summary'))

    po = PurchaseOrder.query.filter_by(id=po_id, tenant_id=current_user.tenant_id).first_or_404()
    if po.tenant_id != current_user.tenant_id:
        flash("Unauthorized PO access.", "danger")
        return redirect(url_for('dashboard_bp.main_dashboard'))

    matched_serials = set()
    asset_to_serial = {str(row.get('asset')).strip(): str(row.get('serial')).strip() for row in spec_data}
    expected_serials = [str(row.get('serial')).strip() for row in spec_data]

    for s in scanned:
        if s in expected_serials:
            matched_serials.add(s)
        elif s in asset_to_serial:
            matched_serials.add(asset_to_serial[s])

    imported = 0
    for serial in matched_serials:
        serial = serial.strip()
        if ProductInstance.query.filter_by(serial=serial).first():
            flash(f"⚠️ Serial {serial} already exists in inventory and was skipped.", "warning")
            continue
        row = next((item for item in spec_data if str(item.get('serial')).strip() == serial), None)
        if not row:
            continue
        product = Product.query.filter_by(
            model=row.get('model'),
            make=row.get('make'),
            cpu=row.get('cpu'),
            ram=row.get('ram'),
            disk1size=row.get('disk1size'),
            display=row.get('display'),
            gpu1=row.get('gpu1'),
            gpu2=row.get('gpu2'),
            grade=row.get('grade'),
            tenant_id=current_user.tenant_id,
            vendor_id=po.vendor_id
        ).first()
        if not product:
            product = Product(
                item_name=row.get('item_name') or "Imported Product",
                model=row.get('model'),
                make=row.get('make'),
                cpu=row.get('cpu'),
                ram=row.get('ram'),
                disk1size=row.get('disk1size'),
                display=row.get('display'),
                gpu1=row.get('gpu1'),
                gpu2=row.get('gpu2'),
                grade=row.get('grade'),
                vendor_id=po.vendor_id,
                tenant_id=current_user.tenant_id,
                stock=0,
                created_at=get_now_for_tenant()
            )
            db.session.add(product)
            db.session.flush()

        instance = ProductInstance(
            product_id=product.id,
            serial_number=serial,
            asset_tag=row.get('asset'),
            status=status_choice,
            location_id=int(location_id) if location_id else product.location_id,
            tenant_id=current_user.tenant_id,
            po_id=po.id
        )
        db.session.add(instance)
        imported += 1

    from inventory_flask_app.models import POImportLog
    log = POImportLog(
        po_id=po_id,
        user_id=current_user.id,
        status=status_choice,
        quantity=imported
    )
    db.session.add(log)
    po.status = "received"
    db.session.commit()
    flash(f"✅ {imported} matched units imported as '{status_choice}'.", "success")
    session.pop('scanned', None)
    session.pop('po_id', None)
    session.pop('po_spec_data', None)
    return redirect(url_for('dashboard_bp.main_dashboard'))


@csrf.exempt
@stock_bp.route('/api/model_suggestions')
@login_required
def model_suggestions():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify([])
    # Query distinct models that contain the substring, case-insensitive
    models = (
        db.session.query(Product.model)
        .filter(Product.model.ilike(f"%{q}%"))
        .distinct()
        .order_by(Product.model)
        .limit(15)
        .all()
    )
    # Return just the list of model names
    return jsonify([m[0] for m in models if m[0]])

# Batch label printing route
@csrf.exempt
@stock_bp.route('/print_labels_batch', methods=['POST'])
@login_required
def print_labels_batch():
    # from datetime import datetime
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
            "asset": instance.asset if instance else "",
            "serial": instance.serial if instance else "",
            "item_name": instance.product.item_name if instance.product else "",
            "make": instance.product.make if instance.product else "",
            "model": instance.product.model if instance.product else "",
            "display": instance.product.display if instance.product else "",
            "cpu": instance.product.cpu if instance.product else "",
            "ram": instance.product.ram if instance.product else "",
            "gpu1": instance.product.gpu1 if instance.product else "",
            "gpu2": instance.product.gpu2 if instance.product else "",
            "grade": instance.product.grade if instance.product else "",
            "disk1size": instance.product.disk1size if instance.product else "",
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
            "printed_time": get_now_for_tenant(),
        })
    return render_template("batch_print_labels.html", batch_labels=batch_labels)

@csrf.exempt
@stock_bp.route('/under_process', methods=['GET', 'POST'])
@login_required
def under_process():
    status_filter = request.args.get('status')
    model_filter = request.args.get('model')
    processor_filter = request.args.get('processor')
    serial_search = request.args.get('serial_search', '').strip()
    stage_filter = request.args.get('stage')
    team_filter = request.args.get('team')
    location_id = request.args.get('location_id')
    bin_search = request.args.get('bin_search', '').strip()
    # New RAM and Disk filters
    ram_filter = request.args.get('ram')
    disk_filter = request.args.get('disk1size')

    # Improved status filter logic: always use .filter(), never .filter_by() for status
    if not status_filter or status_filter == 'all':
        query = ProductInstance.query
    else:
        query = ProductInstance.query
        if status_filter == 'unprocessed':
            query = query.filter(ProductInstance.status == 'unprocessed', ProductInstance.is_sold == False)
        elif status_filter == 'under_process':
            query = query.filter(ProductInstance.status == 'under_process', ProductInstance.is_sold == False)
        elif status_filter == 'processed':
            query = query.filter(ProductInstance.status == 'processed', ProductInstance.is_sold == False)
        elif status_filter == 'disputed':
            query = query.filter(ProductInstance.status == 'disputed', ProductInstance.is_sold == False)
        else:
            query = query.filter(ProductInstance.status == status_filter)

    # Eager load related product and location data for performance
    query = query.options(
        joinedload(ProductInstance.product),
        joinedload(ProductInstance.location)
    )

    # Low stock filter (for /stock/under_process?low_stock=1)
    low_stock = request.args.get('low_stock')
    if low_stock:
        query = query.join(Product).filter(Product.stock != None, Product.stock <= 3)

    # Join Product only once if any filter is present (or always, to simplify filter logic)
    if model_filter or processor_filter or ram_filter or disk_filter or True:
        query = query.join(Product)
    if model_filter:
        query = query.filter(Product.model.ilike(f"%{model_filter}%"))
    if processor_filter:
        query = query.filter(Product.cpu == processor_filter)
    # RAM and Disk filter logic (re-added after model/processor filter)
    if ram_filter:
        query = query.filter(Product.ram == ram_filter)
    if disk_filter:
        query = query.filter(Product.disk1size == disk_filter)
    if serial_search:
        from sqlalchemy import or_
        query = query.filter(or_(
            ProductInstance.serial.ilike(f"%{serial_search}%"),
            ProductInstance.asset.ilike(f"%{serial_search}%")
        ))
    if stage_filter:
        query = query.filter(ProductInstance.process_stage == stage_filter)
    if team_filter:
        query = query.filter(ProductInstance.team_assigned.ilike(f"%{team_filter}%"))
    if location_id:
        query = query.filter(ProductInstance.location_id == int(location_id))
    if bin_search:
        query = query.filter(ProductInstance.shelf_bin.ilike(f"%{bin_search}%"))

    # Always exclude sold items for inventory views
    if not status_filter or status_filter == 'all':
        query = query.filter(ProductInstance.is_sold == False)

    # Exclude all reserved units from inventory views
    reserved_order = aliased(CustomerOrderTracking)
    query = query.outerjoin(
        reserved_order,
        (reserved_order.product_instance_id == ProductInstance.id) &
        (reserved_order.status.ilike('reserved'))
    ).filter(reserved_order.id == None)

    # --- Tenant scoping: only show ProductInstances for current tenant ---
    query = query.filter(Product.tenant_id == current_user.tenant_id)
    # --------------------------------------------------------------------

    instances = query.all()
    all_models = list({i.product.model for i in instances if i.product and i.product.model})
    all_processors = list({i.product.cpu for i in instances if i.product and i.product.cpu})
    # Rebuild all_rams and all_disks for dropdowns based on filtered instances
    all_rams = list({i.product.ram for i in instances if i.product and i.product.ram})
    all_disks = list({i.product.disk1size for i in instances if i.product and i.product.disk1size})
    distinct_stages = db.session.query(ProductInstance.process_stage).distinct().all()
    distinct_teams = db.session.query(ProductInstance.team_assigned).distinct().all()

    # --- Unified column structure logic ---
    from inventory_flask_app.models import TenantSettings
    # Load and correct column order
    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings_dict = {s.key: s.value for s in tenant_settings}
    column_order = settings_dict.get("column_order_instance_table")

    # Unified structure
    default_columns = [
        "asset", "serial", "Item Name", "make", "model", "display", "cpu", "ram",
        "gpu1", "gpu2", "Grade", "location", "status", "process_stage",
        "team_assigned", "shelf_bin", "is_sold", "label", "action"
    ]

    # Replace outdated column names
    if column_order:
        for old, new in {
            "model_number": "model",
            "product": "Item Name",
            "processor": "cpu",
            "video_card": "gpu1",
            "resolution": "display"
        }.items():
            column_order = column_order.replace(old, new)

        existing = column_order.split(",")
        for col in default_columns:
            if col not in existing:
                existing.append(col)
        column_order = ",".join(existing)
    else:
        column_order = ",".join(default_columns)

    settings_dict["column_order_instance_table"] = column_order
    # --- END Unified column structure logic ---

    return render_template(
        'instance_table.html',
        instances=instances,
        models=sorted(all_models),
        processors=sorted(all_processors),
        rams=sorted(all_rams),
        disk1sizes=sorted(all_disks),
        stages=[s[0] for s in distinct_stages if s[0]],
        teams=[t[0] for t in distinct_teams if t[0]],
        selected_stage=stage_filter,
        selected_team=team_filter,
        title=(
            "Total Inventory" if not status_filter or status_filter == 'all'
            else "Unprocessed Inventory" if status_filter == 'unprocessed'
            else "Processed Inventory" if status_filter == 'processed'
            else "Under Process Inventory" if status_filter == 'under_process'
            else "Disputed Inventory" if status_filter == 'disputed'
            else "Inventory"
        ),
        locations=Location.query.all(),
        settings=settings_dict
    )

@csrf.exempt
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
        from sqlalchemy import or_
        for serial in serials:
            # --- Tenant scoping: allow lookup by serial_number OR asset_tag for current tenant ---
            instance = ProductInstance.query.join(Product).filter(
                or_(
                    ProductInstance.serial == serial,
                    ProductInstance.asset == serial
                ),
                Product.tenant_id == current_user.tenant_id
            ).first()
            # -------------------------------------------------------------------------------
            def _unified_product_dict(instance, prev_stage, serial, status_val):
                return {
                    "asset": instance.asset or (instance.product.asset if instance.product else ""),
                    "serial": instance.serial or (instance.product.serial if instance.product else ""),
                    "Item Name": instance.product.item_name if instance.product else "",
                    "make": instance.product.make if instance.product else "",
                    "model": instance.product.model if instance.product else "",
                    "display": instance.product.display if instance.product else "",
                    "cpu": instance.product.cpu if instance.product else "",
                    "ram": instance.product.ram if instance.product else "",
                    "gpu1": instance.product.gpu1 if instance.product else "",
                    "gpu2": instance.product.gpu2 if instance.product else "",
                    "Grade": instance.product.grade if instance.product else "",
                    "disk1size": instance.product.disk1size if instance.product else "",
                    "prev_stage": prev_stage,
                    "instance_id": instance.id,
                    "status": status_val
                }
            if instance:
                prev_stage = instance.process_stage or '-'
                # Check if user is allowed to process this unit
                if instance.assigned_to_user_id is not None and instance.assigned_to_user_id != current_user.id:
                    results.append(_unified_product_dict(instance, prev_stage, serial, "not_yours"))
                    continue
                if instance.process_stage == process_stage and instance.team_assigned == team:
                    # No change needed
                    results.append(_unified_product_dict(instance, prev_stage, serial, "no_change"))
                    no_change += 1
                else:
                    instance.process_stage = process_stage
                    instance.team_assigned = team
                    if instance.status != 'under_process':
                        instance.status = 'under_process'
                    instance.updated_at = datetime.utcnow()
                    instance.assigned_to_user_id = None  # <-- ensure ready for check-in
                    db.session.commit()
                    results.append(_unified_product_dict(instance, prev_stage, serial, "updated"))
                    updated += 1
            else:
                # For not_found, no instance or product
                results.append({
                    "asset": "",
                    "serial": "",
                    "Item Name": "",
                    "make": "",
                    "model": "",
                    "display": "",
                    "cpu": "",
                    "ram": "",
                    "gpu1": "",
                    "gpu2": "",
                    "Grade": "",
                    "disk1size": "",
                    "prev_stage": "-",
                    "instance_id": "",
                    "status": "not_found"
                })
                not_found += 1
        flash(f"{updated} updated, {no_change} already at stage, {not_found} not found.", "info")
        # Add: Query my_units before rendering template (include all processing stages)
        my_units = ProductInstance.query.filter(
            ProductInstance.assigned_to_user_id == current_user.id,
            ProductInstance.status.in_(['under_process', 'specs', 'qc', 'deployment', 'paint', 'processed'])
        ).all()
        return render_template('process_stage_update.html', results=results, my_units=my_units)
    # GET: just show the empty form
    my_units = ProductInstance.query.filter(
        ProductInstance.assigned_to_user_id == current_user.id,
        ProductInstance.status.in_(['under_process', 'specs', 'qc', 'deployment', 'paint', 'processed'])
    ).all()
    return render_template('process_stage_update.html', results=None, my_units=my_units)

@csrf.exempt
@stock_bp.route('/instance/<int:instance_id>/view_edit', methods=['GET', 'POST'])
@login_required
def view_edit_instance(instance_id):
    # --- Tenant scoping: only allow view/edit of ProductInstances for current tenant ---
    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.id == instance_id,
        Product.tenant_id == current_user.tenant_id
    ).first_or_404()
    # --------------------------------------------------------------------
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

# --- Unit history route ---
@csrf.exempt
@stock_bp.route('/unit_history/<serial>')
@login_required
def unit_history(serial):
    from sqlalchemy import or_
    instance = ProductInstance.query.join(Product).filter(
        or_(
            ProductInstance.serial == serial,
            ProductInstance.asset == serial
        ),
        Product.tenant_id == current_user.tenant_id
    ).first_or_404()
    from inventory_flask_app.models import SaleTransaction, Customer
    sale = SaleTransaction.query.filter_by(product_instance_id=instance.id).join(Customer).first()
    logs = ProductProcessLog.query.filter_by(product_instance_id=instance.id).order_by(ProductProcessLog.moved_at).all()
    return render_template('unit_history.html', instance=instance, logs=logs, sale=sale)

# Delete ProductInstance route
@csrf.exempt
@stock_bp.route('/instance/<int:instance_id>/delete', methods=['POST'])
@login_required
def delete_instance(instance_id):
    # --- Tenant scoping: only allow delete of ProductInstances for current tenant ---
    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.id == instance_id,
        Product.tenant_id == current_user.tenant_id
    ).first_or_404()
    # --------------------------------------------------------------------
    db.session.delete(instance)
    db.session.commit()
    flash(f"✅ Unit with serial '{instance.serial}' deleted successfully.", "success")
    return redirect(url_for('stock_bp.under_process'))

# --- Check-in/Check-out route for processing table ---
from flask_login import current_user
from inventory_flask_app.models import ProductProcessLog


# --- Improved Check-in/Check-out route with assignment logic ---
@csrf.exempt
@stock_bp.route('/checkin_checkout', methods=['POST'])
@login_required
def checkin_checkout():
    # Accept multiple IDs for batch processing
    instance_ids = request.form.getlist('instance_ids')
    action = request.form.get('action')
    # Per-instance notes: expect notes[<id>] in form
    # Also support mark_idle_ids for moving to idle
    notes_dict = request.form.to_dict(flat=False)
    idle_ids = set(request.form.getlist('mark_idle_ids'))

    # Also allow mark_idle_ids without action
    if not instance_ids and not idle_ids:
        flash("Missing information for check-in/out.", "danger")
        return redirect(request.referrer or url_for('stock_bp.process_stage_update'))

    from inventory_flask_app.models import ProductProcessLog

    updated_count = 0
    skipped = 0
    # Combine all ids to process: those checked for instance selection or idle checkbox
    all_ids = set(instance_ids).union(idle_ids)
    for instance_id in all_ids:
        # --- Tenant scoping: only allow update of ProductInstances for current tenant ---
        instance = ProductInstance.query.join(Product).filter(
            ProductInstance.id == instance_id,
            Product.tenant_id == current_user.tenant_id
        ).first()
        # --------------------------------------------------------------------
        if not instance:
            continue
        # Get per-instance note if present
        note = request.form.get(f'notes[{instance_id}]', '')
        # Move to idle if flagged (this check must come before anything else)
        if str(instance_id) in idle_ids:
            instance.status = "idle"
            instance.assigned_to_user_id = None
            instance.updated_at = get_now_for_tenant()
            db.session.add(ProductProcessLog(
                product_instance_id=instance.id,
                from_stage=instance.process_stage,
                to_stage="idle",
                from_team=instance.team_assigned,
                to_team=instance.team_assigned,
                moved_by=current_user.id,
                moved_at=get_now_for_tenant(),
                action="moved_to_idle",
                note=note
            ))
            updated_count += 1
            flash(f"Unit '{instance.serial}' moved to idle.", "info")
            continue
        if action == "check-in":
            # Only allow check-in if not already checked in (assigned)
            if instance.assigned_to_user_id:
                # Already checked in, must be checked out first
                skipped += 1
                continue
            instance.status = "under_process"
            instance.assigned_to_user_id = current_user.id
            log = ProductProcessLog(
                product_instance_id=instance.id,
                from_stage=instance.process_stage,
                to_stage=instance.process_stage,
                from_team=instance.team_assigned,
                to_team=instance.team_assigned,
                moved_by=current_user.id,
                moved_at=get_now_for_tenant(),
                action=action,
                note=note
            )
            db.session.add(log)
            updated_count += 1
            flash(f"Unit '{instance.serial}' checked in.", "info")
        elif action == "check-out":
            # Only allow check-out for units assigned to the current user
            if instance.assigned_to_user_id == current_user.id:
                instance.status = "processed"
                instance.assigned_to_user_id = None
                log = ProductProcessLog(
                    product_instance_id=instance.id,
                    from_stage=instance.process_stage,
                    to_stage=instance.process_stage,
                    from_team=instance.team_assigned,
                    to_team=instance.team_assigned,
                    moved_by=current_user.id,
                    moved_at=get_now_for_tenant(),
                    action=action,
                    note=note
                )
                db.session.add(log)
                updated_count += 1
                flash(f"Unit '{instance.serial}' checked out.", "info")
            else:
                skipped += 1
    db.session.commit()
    msg = f"✅ {action.capitalize()} complete: {updated_count} unit(s) updated."
    if skipped:
        msg += f" {skipped} skipped (not permitted)."
    flash(msg, "success" if updated_count else "warning")
    # After check-in/out, reload my_units so the checked-in unit appears right away
    if action == "check-in":
        # Query my assigned units after check-in
        my_units = ProductInstance.query.filter_by(assigned_to_user_id=current_user.id, status='under_process').all()
        # Optionally, you can render the process_stage_update template directly:
        return render_template('process_stage_update.html', results=None, my_units=my_units)
    return redirect(request.referrer or url_for('stock_bp.process_stage_update'))

@csrf.exempt
@stock_bp.route('/export_instances')
@login_required
def export_instances():
    from openpyxl import Workbook
    from io import BytesIO
    from flask import send_file
    from sqlalchemy import or_

    status = request.args.get('status')
    model = request.args.get('model')
    processor = request.args.get('processor')
    serial_search = request.args.get('serial_search', '').strip()
    stage_filter = request.args.get('stage')
    team_filter = request.args.get('team')
    location_id = request.args.get('location_id')
    bin_search = request.args.get('bin_search', '').strip()

    if not status or status == 'all':
        query = ProductInstance.query
    else:
        if status == 'unprocessed':
            query = ProductInstance.query.filter_by(status='unprocessed', is_sold=False)
        elif status == 'under_process':
            query = ProductInstance.query.filter_by(status='under_process', is_sold=False)
        elif status == 'processed':
            query = ProductInstance.query.filter_by(status='processed', is_sold=False)
        else:
            query = ProductInstance.query.filter_by(status=status)

    query = query.join(Product).filter(Product.tenant_id == current_user.tenant_id)

    if model:
        query = query.filter(Product.model.ilike(f"%{model}%"))
    if processor:
        query = query.filter(Product.cpu.ilike(f"%{processor}%"))
    if serial_search:
        query = query.filter(or_(
            ProductInstance.serial.ilike(f"%{serial_search}%"),
            ProductInstance.asset.ilike(f"%{serial_search}%")
        ))
    if stage_filter:
        query = query.filter(ProductInstance.process_stage == stage_filter)
    if team_filter:
        query = query.filter(ProductInstance.team_assigned.ilike(f"%{team_filter}%"))
    if location_id:
        query = query.filter(ProductInstance.location_id == int(location_id))
    if bin_search:
        query = query.filter(ProductInstance.shelf_bin.ilike(f"%{bin_search}%"))

    instances = query.all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory Export"
    ws.append([
        "Serial", "Asset", "Item Name", "Make", "Model", "CPU", "RAM", "Disk", "Display",
        "GPU1", "GPU2", "Grade", "Location", "Status", "Process Stage", "Shelf Bin", "Team", "Sold"
    ])

    for i in instances:
        p = i.product
        ws.append([
            i.serial,
            i.asset,
            p.item_name if p else '',
            p.make if p else '',
            p.model if p else '',
            p.cpu if p else '',
            p.ram if p else '',
            p.disk1size if p else '',
            p.display if p else '',
            p.gpu1 if p else '',
            p.gpu2 if p else '',
            p.grade if p else '',
            i.location.name if i.location else '',
            i.status,
            i.process_stage or '',
            i.shelf_bin or '',
            i.team_assigned or '',
            'Yes' if i.is_sold else 'No'
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="inventory_export.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@csrf.exempt
@stock_bp.route('/scan_move', methods=['GET', 'POST'])
@login_required
def scan_move():
    from sqlalchemy import or_, func
    from datetime import datetime

    if 'batch_serials' not in session:
        session['batch_serials'] = []

    batch_serials = session.get('batch_serials', [])
    serial = None

    # Handle serial scan or update
    if request.method == 'POST':
        if request.form.get("reset_scanned") == "1":
            batch_serials = []
            session['batch_serials'] = batch_serials
            session.modified = True
            flash("Scanned list has been cleared.", "info")
            return redirect(url_for('stock_bp.scan_move'))
        # Remove serial
        remove_serial = request.form.get('remove_serial')
        if remove_serial:
            batch_serials = [s for s in batch_serials if s != remove_serial]
            session['batch_serials'] = batch_serials
            session.modified = True

        # Add serial
        elif 'serial' in request.form and request.form.get('serial').strip():
            serial = request.form.get('serial').strip()
            if serial not in batch_serials:
                batch_serials.append(serial)
                session['batch_serials'] = batch_serials
                session.modified = True

        # Apply bulk updates
        elif 'move_all' in request.form:
            status = request.form.get('status')
            process_stage = request.form.get('process_stage')
            team_assigned = request.form.get('team_assigned')
            location_id = request.form.get('location_id')
            shelf_bin = request.form.get('shelf_bin', '').strip()
            updated = 0
            for s in batch_serials:
                clean = s.strip()
                instance = ProductInstance.query.join(Product).filter(
                    or_(
                        ProductInstance.serial == clean,
                        ProductInstance.asset == clean
                    ),
                    Product.tenant_id == current_user.tenant_id
                ).first()
                if instance:
                    if status in ['unprocessed', 'under_process', 'processed', 'sold']:
                        instance.status = status
                    if process_stage:
                        instance.process_stage = process_stage
                    if team_assigned:
                        instance.team_assigned = team_assigned
                    if location_id:
                        instance.location_id = int(location_id)
                    if shelf_bin:
                        instance.shelf_bin = shelf_bin
                    instance.updated_at = datetime.utcnow()
                    updated += 1
            db.session.commit()
            flash(f"{updated} serial(s) updated successfully.", "success")
            batch_serials = []
            session['batch_serials'] = batch_serials
            session.modified = True

    # ✅ Optimized bulk query for displaying scanned instances
    serials_upper = [s.strip().upper() for s in batch_serials]
    instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id
    ).filter(
        or_(
            func.upper(ProductInstance.serial).in_(serials_upper),
            func.upper(ProductInstance.asset).in_(serials_upper)
        )
    ).all()

    # Build map for fast lookup
    instance_map = {}
    for i in instances:
        if i.serial:
            instance_map[i.serial.strip().upper()] = i
        if i.asset:
            instance_map[i.asset.strip().upper()] = i

    # Build unified display list in scan order
    unified_instances = []
    for s in batch_serials:
        key = s.strip().upper()
        instance = instance_map.get(key)
        unified_instances.append({
            "serial": instance.serial if instance else s,
            "asset": instance.asset if instance else "",
            "item_name": instance.product.item_name if instance and instance.product else "",
            "make": instance.product.make if instance and instance.product else "",
            "model": instance.product.model if instance and instance.product else "",
            "display": instance.product.display if instance and instance.product else "",
            "cpu": instance.product.cpu if instance and instance.product else "",
            "ram": instance.product.ram if instance and instance.product else "",
            "gpu1": instance.product.gpu1 if instance and instance.product else "",
            "gpu2": instance.product.gpu2 if instance and instance.product else "",
            "grade": instance.product.grade if instance and instance.product else "",
            "disk1size": instance.product.disk1size if instance and instance.product else "",
            "instance_id": instance.id if instance else "",
            "status": instance.status if instance else "",
            "location_id": instance.location_id if instance else "",
            "process_stage": instance.process_stage if instance else "",
            "team_assigned": instance.team_assigned if instance else "",
            "shelf_bin": instance.shelf_bin if instance else "",
        })

    return render_template(
        'scan_move.html',
        instances=unified_instances,
        serial=serial or "",
        locations=Location.query.all()
    )


# QR code label printing route
@csrf.exempt
@stock_bp.route('/print_label/<int:instance_id>')
@login_required
def print_label(instance_id):
    from datetime import datetime
    instance = ProductInstance.query.get_or_404(instance_id)
    if not instance.product:
        flash("No product linked to this instance.", "danger")
        return redirect(request.referrer or url_for('dashboard_bp.main_dashboard'))

    # Encode key info as QR code using unified product structure
    qr_data = {
        "serial": instance.serial if instance else "",
        "asset": instance.asset if instance else "",
        "item_name": instance.product.item_name if instance.product else "",
        "make": instance.product.make if instance.product else "",
        "model": instance.product.model if instance.product else "",
        "display": instance.product.display if instance.product else "",
        "cpu": instance.product.cpu if instance.product else "",
        "ram": instance.product.ram if instance.product else "",
        "gpu1": instance.product.gpu1 if instance.product else "",
        "gpu2": instance.product.gpu2 if instance.product else "",
        "grade": instance.product.grade if instance.product else ""
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

@csrf.exempt
@stock_bp.route('/batch_update_status', methods=['POST'])
@login_required
def batch_update_status():
    ids = request.form.getlist('instance_ids')
    status = request.form.get('status')
    location_id = request.form.get('location_id')
    if not ids or not status:
        flash("Please select at least one item and a status.", "danger")
        return redirect(request.referrer or url_for('dashboard_bp.main_dashboard'))

    # Only allow certain statuses for safety
    allowed_statuses = ['unprocessed', 'under_process', 'processed', 'sold']
    if status not in allowed_statuses:
        flash("Invalid status selected.", "danger")
        return redirect(request.referrer or url_for('dashboard_bp.main_dashboard'))

    # Enforce tenant scoping: only update ProductInstances for current tenant
    updated_count = 0
    # Join Product to ensure tenant filtering
    for instance in ProductInstance.query.join(Product).filter(
        ProductInstance.id.in_(ids),
        Product.tenant_id == current_user.tenant_id
    ).all():
        instance.status = status
        if location_id:
            instance.location_id = int(location_id)
        updated_count += 1
    db.session.commit()

    flash(f"✅ {updated_count} item(s) updated to '{status.replace('_', ' ').title()}' status.", "success")
    return redirect(request.referrer or url_for('dashboard_bp.main_dashboard'))

@csrf.exempt
@stock_bp.route('/sold')
@login_required
def sold_items():
    from inventory_flask_app.models import SaleTransaction, Customer
    from inventory_flask_app.models import TenantSettings
    # Get filter params
    customer_id = request.args.get('customer')
    sale_date = request.args.get('sale_date')

    # Find all sold product instances (tenant scoped)
    sold_instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.is_sold == True
    ).all()

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
            "serial": instance.serial,
            "asset": instance.asset,
            "item_name": instance.product.item_name if instance.product else "",
            "make": instance.product.make if instance.product else "",
            "model": instance.product.model if instance.product else "",
            "display": instance.product.display if instance.product else "",
            "cpu": instance.product.cpu if instance.product else "",
            "ram": instance.product.ram if instance.product else "",
            "gpu1": instance.product.gpu1 if instance.product else "",
            "gpu2": instance.product.gpu2 if instance.product else "",
            "grade": instance.product.grade if instance.product else "",
            "disk1size": instance.product.disk1size if instance.product else "",
            "customer": sale.customer.name if sale and sale.customer else "",
            "customer_id": sale.customer_id if sale else "",
            "sale_date": sale.date_sold.strftime('%Y-%m-%d') if sale and sale.date_sold else "",
            "price": sale.price_at_sale if sale else "",
        })

    # Get all customers for filter dropdown
    customers = Customer.query.order_by(Customer.name).all()
    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in tenant_settings}
    return render_template("sold_items.html", sold_data=sold_data, customers=customers, selected_customer=customer_id, selected_date=sale_date, settings=settings)



# Add product page route
@csrf.exempt
@stock_bp.route('/products/add', methods=['GET', 'POST'])
@login_required
def add_product_page():
    from inventory_flask_app.models import TenantSettings
    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in tenant_settings}

    if request.method == 'POST':
        from inventory_flask_app.models import add_product_and_instance
        data = request.form.to_dict()
        # Use unified field names consistent with the rest of the system
        data = {
            "item_name": data.get("item_name"),
            "model": data.get("model"),
            "serial": data.get("serial"),
            "cpu": data.get("cpu"),
            "ram": data.get("ram"),
            "disk1size": data.get("disk1size"),
            "display": data.get("display"),
            "gpu1": data.get("gpu1"),
            "gpu2": data.get("gpu2"),
            "grade": data.get("grade"),
            "status": data.get("status", "unprocessed")
        }
        product, instance = add_product_and_instance(db, data)
        db.session.commit()
        flash("✅ Product and instance added successfully!", "success")
        return redirect(url_for('stock_bp.print_label', instance_id=instance.id))

    return render_template('add_product.html', settings=settings)

@csrf.exempt
@stock_bp.route('/bin_lookup', methods=['GET', 'POST'])
@login_required
def bin_lookup():
    if request.method == 'POST':
        bin_code = request.form.get('bin_code', '').strip().upper()
        if bin_code:
            return redirect(url_for('stock_bp.bin_contents', bin_code=bin_code))
    return render_template('bin_lookup.html')

@csrf.exempt
@stock_bp.route('/bin_contents/<bin_code>')
@login_required
def bin_contents(bin_code):
    # Enforce tenant scoping: only show ProductInstances for current tenant
    products = ProductInstance.query.join(Product).filter(
        ProductInstance.shelf_bin == bin_code,
        Product.tenant_id == current_user.tenant_id
    ).all()
    return render_template('bin_contents.html', bin_code=bin_code, products=products)
# --- Add Location Route ---
# --- Add Location Route ---
@stock_bp.route('/location/add', methods=['GET', 'POST'])
@login_required
def add_location():
    from flask_wtf.csrf import validate_csrf
    from wtforms.validators import ValidationError

    if request.method == 'GET':
        locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
        return render_template("add_location.html", locations=locations)

    next_url = request.args.get('next') or request.form.get('next') or request.referrer or url_for('dashboard_bp.main_dashboard')

    try:
        validate_csrf(request.form.get('csrf_token'))
    except ValidationError:
        flash("Invalid or missing CSRF token.", "danger")
        return redirect(next_url)

    name = request.form.get('name', '').strip().upper()
    if not name:
        flash("Location name is required.", "warning")
        return redirect(next_url)

    existing = Location.query.filter_by(name=name, tenant_id=current_user.tenant_id).first()
    if existing:
        flash("A location with this name already exists.", "warning")
        return redirect(next_url)

    location = Location(name=name, tenant_id=current_user.tenant_id)
    db.session.add(location)
    db.session.commit()
    flash(f"✅ Location '{name}' added successfully.", "success")
    # Conditional redirect logic based on next_url content
    if "upload_excel" in next_url:
        return redirect(url_for('import_excel_bp.upload_excel'))
    elif "purchase_order" in next_url:
        return redirect(url_for('stock_bp.create_purchase_order'))
    else:
        return redirect(url_for('dashboard_bp.main_dashboard'))


# --- Aged Inventory Route ---
@csrf.exempt
@stock_bp.route('/inventory/aged')
@login_required
def aged_inventory_view():
    from inventory_flask_app.models import TenantSettings
    settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings_dict = {s.key: s.value for s in settings}
    aged_days = int(settings_dict.get("aged_threshold_days", 60))

    now = get_now_for_tenant()
    threshold_date = now - timedelta(days=aged_days)

    instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.created_at < threshold_date,
        ProductInstance.is_sold == False
    ).all()

    return render_template(
        "aged_inventory.html",
        instances=instances,
        threshold_days=aged_days
    )
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload
from inventory_flask_app import csrf
from inventory_flask_app.models import db, Product, ProductInstance, Location, ProductProcessLog, Bin, Part, PartStock, PartMovement
from inventory_flask_app.utils import get_now_for_tenant
from inventory_flask_app.utils.utils import calc_duration_minutes, module_required

logger = logging.getLogger(__name__)

scanner_bp = Blueprint('scanner_bp', __name__, url_prefix='/stock')


@scanner_bp.route('/scan')
@login_required
@module_required('stock', 'view')
def scan_unit():
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).order_by(Location.name).all()
    return render_template('scanner.html', locations=locations)


@scanner_bp.route('/api/lookup_unit')
@login_required
@module_required('stock', 'view')
def lookup_unit():
    """Unified serial/asset lookup used by scanner and sale form (JSON).

    Query param: ?q=<serial_or_asset>
    Legacy alias: ?serial=<serial_or_asset>  (scanner backward compat)
    """
    q = (request.args.get('q') or request.args.get('serial', '')).strip()
    if not q:
        return jsonify({'error': 'Missing serial'}), 400

    instance = ProductInstance.query.join(Product).filter(
        (ProductInstance.serial == q) | (ProductInstance.asset == q),
        Product.tenant_id == current_user.tenant_id
    ).first()

    if not instance:
        return jsonify({'found': False, 'error': 'Unit not found', 'serial': q}), 404

    prod = instance.product
    location_name = None
    if instance.location_id:
        loc = db.session.get(Location, instance.location_id)
        if loc:
            location_name = loc.name

    return jsonify({
        # Scanner fields
        'found': True,
        'instance_id': instance.id,
        'serial': instance.serial or '',
        'asset': instance.asset or '',
        'status': instance.status or '',
        'process_stage': instance.process_stage or '',
        'shelf_bin': instance.bin_name or '',
        'bin_id': instance.bin_id,
        'location_id': instance.location_id,
        'location_name': location_name or '—',
        'note': instance.note or '',
        'is_sold': instance.is_sold,
        # Product fields (sale form)
        'item_name': prod.item_name if prod else '',
        'name': prod.item_name if prod else '',
        'make': prod.make if prod else '',
        'model': prod.model if prod else '',
        'cpu': prod.cpu if prod else '',
        'ram': prod.ram if prod else '',
        'disk1size': prod.disk1size if prod else '',
        'display': prod.display if prod else '',
        'gpu1': prod.gpu1 if prod else '',
        'gpu2': prod.gpu2 if prod else '',
        'grade': prod.grade if prod else '',
        'product_instance_id': instance.id,
    })


@scanner_bp.route('/scan/move', methods=['POST'])
@login_required
@module_required('stock', 'full')
def scan_move_unit():
    """Move a unit to a new location via the scanner page."""
    instance_id = request.form.get('instance_id', type=int)
    location_id = request.form.get('location_id', type=int)
    shelf_bin = request.form.get('shelf_bin', '').strip().upper()

    if not instance_id:
        return jsonify({'success': False, 'message': 'Missing instance_id'}), 400

    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.id == instance_id,
        Product.tenant_id == current_user.tenant_id
    ).first()
    if not instance:
        return jsonify({'success': False, 'message': 'Unit not found'}), 404

    if location_id:
        loc = Location.query.filter_by(id=location_id, tenant_id=current_user.tenant_id).first()
        if not loc:
            return jsonify({'success': False, 'message': 'Location not found'}), 404
        instance.location_id = location_id
        location_name = loc.name
    else:
        location_name = None

    if shelf_bin is not None:
        instance.shelf_bin = shelf_bin or None
        # Resolve to structured Bin record
        resolved_loc = location_id or instance.location_id
        if shelf_bin and resolved_loc:
            managed = Bin.query.filter_by(
                name=shelf_bin, location_id=resolved_loc, tenant_id=current_user.tenant_id
            ).first()
            instance.bin_id = managed.id if managed else None
        elif not shelf_bin:
            instance.bin_id = None

    # fix 11: audit log for scanner location moves
    now_ts = get_now_for_tenant()
    instance.updated_at = now_ts
    db.session.add(ProductProcessLog(
        product_instance_id=instance.id,
        from_stage=instance.process_stage,
        to_stage=instance.process_stage,
        from_team=instance.team_assigned,
        to_team=instance.team_assigned,
        moved_by=current_user.id,
        moved_at=now_ts,
        action='location_move',
        note=f'Moved to {location_name or "unknown"} bin {instance.shelf_bin or ""}',
    ))
    db.session.commit()
    return jsonify({
        'success': True,
        'message': 'Location updated.',
        'location_name': location_name or '—',
        'shelf_bin': instance.shelf_bin or '',
    })


@scanner_bp.route('/scan/update_status', methods=['POST'])
@login_required
@module_required('stock', 'full')
def scan_update_status():
    """Update status/stage of a unit via the scanner page."""
    instance_id = request.form.get('instance_id', type=int)
    new_status = request.form.get('status', '').strip()

    if not instance_id or not new_status:
        return jsonify({'success': False, 'message': 'Missing fields'}), 400

    valid_statuses = {'unprocessed', 'under_process', 'processed', 'idle', 'disputed'}
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'message': 'Invalid status'}), 400

    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.id == instance_id,
        Product.tenant_id == current_user.tenant_id
    ).first()
    if not instance:
        return jsonify({'success': False, 'message': 'Unit not found'}), 404

    prev_stage = instance.process_stage
    prev_status = instance.status
    duration = calc_duration_minutes(instance.entered_stage_at)
    now_ts = get_now_for_tenant()

    instance.status = new_status
    instance.updated_at = now_ts
    # Keep fields consistent: clear assignment when leaving under_process
    if new_status != 'under_process':
        instance.assigned_to_user_id = None
        instance.entered_stage_at = None
    if new_status == 'unprocessed':
        instance.process_stage = None

    # fix 11: audit log for scanner status changes
    db.session.add(ProductProcessLog(
        product_instance_id=instance.id,
        from_stage=prev_stage,
        to_stage=instance.process_stage,
        from_team=instance.team_assigned,
        to_team=instance.team_assigned,
        moved_by=current_user.id,
        moved_at=now_ts,
        action='scanner_status_update',
        note=f'Status changed from {prev_status} to {new_status} via scanner',
        duration_minutes=duration,
    ))
    db.session.commit()
    return jsonify({'success': True, 'message': f'Status set to {new_status}.', 'status': new_status})


@scanner_bp.route('/api/lookup_bin')
@login_required
@module_required('stock', 'view')
def lookup_bin():
    """Look up a bin by name — used by scanner for bin-code scanning."""
    q = (request.args.get('q') or '').strip().upper()
    if not q:
        return jsonify({'found': False}), 400
    bin_obj = Bin.query.filter_by(name=q, tenant_id=current_user.tenant_id).first()
    if not bin_obj:
        return jsonify({'found': False}), 404
    loc = db.session.get(Location, bin_obj.location_id)
    count = ProductInstance.query.join(Product).filter(
        ProductInstance.bin_id == bin_obj.id,
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.is_sold == False,
    ).count()
    from inventory_flask_app.models import PartStock, Part
    part_count = PartStock.query.join(Part, PartStock.part_id == Part.id).filter(
        PartStock.bin_id == bin_obj.id,
        PartStock.quantity > 0,
        Part.tenant_id == current_user.tenant_id,
    ).count()
    return jsonify({
        'found': True,
        'is_bin': True,
        'bin_id': bin_obj.id,
        'bin_name': bin_obj.name,
        'location_name': loc.name if loc else '—',
        'unit_count': count,
        'part_count': part_count,
        'url': url_for('stock_bp.bin_detail', bin_id=bin_obj.id),
    })


@scanner_bp.route('/api/lookup_part')
@login_required
@module_required('stock', 'view')
def lookup_part():
    """Look up a Part by barcode, part_number, or name — universal scanner fallback."""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'found': False}), 400

    # Exact match first (barcode or part_number), then fuzzy name
    part = Part.query.filter(
        Part.tenant_id == current_user.tenant_id,
        or_(Part.barcode == q, Part.part_number == q)
    ).first()
    if not part:
        part = Part.query.filter(
            Part.tenant_id == current_user.tenant_id,
            Part.name.ilike(f'%{q}%')
        ).first()
    if not part:
        return jsonify({'found': False}), 404

    # Stock by location (include bin data so scanner modals can pre-populate)
    stocks = []
    for ps in PartStock.query.filter_by(part_id=part.id).all():
        loc = db.session.get(Location, ps.location_id) if ps.location_id else None
        bin_obj = db.session.get(Bin, ps.bin_id) if ps.bin_id else None
        if ps.quantity > 0 or loc:
            stocks.append({
                'location': loc.name if loc else '—',
                'location_id': ps.location_id,
                'bin_id': ps.bin_id,
                'bin_name': bin_obj.name if bin_obj else None,
                'qty': ps.quantity,
            })
    total_stock = sum(s['qty'] for s in stocks)

    # Recent movements (5)
    movements = []
    for m in PartMovement.query.filter_by(part_id=part.id).order_by(PartMovement.id.desc()).limit(5).all():
        movements.append({
            'type': m.movement_type or '',
            'qty': m.quantity,
            'note': m.note or '',
            'date': m.created_at.strftime('%b %d') if m.created_at else '',
        })

    return jsonify({
        'found': True,
        'type': 'part',
        'part': {
            'id': part.id,
            'name': part.name,
            'part_number': part.part_number or '',
            'part_type': part.part_type or '',
            'barcode': part.barcode or '',
            'min_stock': part.min_stock or 0,
            'price': float(part.price or 0),
            'total_stock': total_stock,
            'low_stock': total_stock <= (part.min_stock or 0),
            'stocks': stocks,
            'recent_movements': movements,
            'url_detail': url_for('parts_bp.part_detail', part_id=part.id),
            'url_stock_in': url_for('parts_bp.stock_in') + f'?part_id={part.id}',
            'url_stock_out': url_for('parts_bp.stock_out') + f'?part_id={part.id}',
            'url_sell': url_for('parts_bp.sell') + f'?part_id={part.id}',
            'url_use': url_for('parts_bp.use') + f'?part_id={part.id}',
        }
    })


@scanner_bp.route('/scan/checkin', methods=['POST'])
@login_required
@module_required('stock', 'full')
def scan_checkin():
    """Check a unit in for processing via scanner."""
    instance_id = request.form.get('instance_id', type=int)
    if not instance_id:
        return jsonify({'success': False, 'message': 'Missing instance_id'}), 400
    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.id == instance_id,
        Product.tenant_id == current_user.tenant_id,
    ).first()
    if not instance:
        return jsonify({'success': False, 'message': 'Unit not found'}), 404
    prev_status = instance.status
    now_ts = get_now_for_tenant()
    instance.status = 'under_process'
    instance.assigned_to_user_id = current_user.id
    instance.entered_stage_at = now_ts
    instance.updated_at = now_ts
    db.session.add(ProductProcessLog(
        product_instance_id=instance.id,
        from_stage=instance.process_stage,
        to_stage=instance.process_stage,
        from_team=instance.team_assigned,
        to_team=instance.team_assigned,
        moved_by=current_user.id,
        moved_at=now_ts,
        action='scanner_checkin',
        note=f'Checked in for processing via scanner (was {prev_status})',
    ))
    db.session.commit()
    return jsonify({'success': True, 'message': 'Checked in for processing.', 'status': 'under_process'})


@scanner_bp.route('/scan/checkout', methods=['POST'])
@login_required
@module_required('stock', 'full')
def scan_checkout():
    """Check a unit out (mark processed) via scanner."""
    instance_id = request.form.get('instance_id', type=int)
    if not instance_id:
        return jsonify({'success': False, 'message': 'Missing instance_id'}), 400
    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.id == instance_id,
        Product.tenant_id == current_user.tenant_id,
    ).first()
    if not instance:
        return jsonify({'success': False, 'message': 'Unit not found'}), 404
    prev_stage = instance.process_stage
    duration = calc_duration_minutes(instance.entered_stage_at)
    now_ts = get_now_for_tenant()
    instance.status = 'processed'
    instance.assigned_to_user_id = None
    instance.entered_stage_at = None
    instance.updated_at = now_ts
    db.session.add(ProductProcessLog(
        product_instance_id=instance.id,
        from_stage=prev_stage,
        to_stage=instance.process_stage,
        from_team=instance.team_assigned,
        to_team=instance.team_assigned,
        moved_by=current_user.id,
        moved_at=now_ts,
        action='scanner_checkout',
        note='Checked out — marked processed via scanner',
        duration_minutes=duration,
    ))
    db.session.commit()
    return jsonify({'success': True, 'message': 'Unit marked processed.', 'status': 'processed'})


@scanner_bp.route('/scan/mark_idle', methods=['POST'])
@login_required
@module_required('stock', 'full')
def scan_mark_idle():
    """Mark a unit idle with an optional reason via scanner."""
    instance_id = request.form.get('instance_id', type=int)
    reason = request.form.get('reason', '').strip()
    if not instance_id:
        return jsonify({'success': False, 'message': 'Missing instance_id'}), 400
    instance = ProductInstance.query.join(Product).filter(
        ProductInstance.id == instance_id,
        Product.tenant_id == current_user.tenant_id,
    ).first()
    if not instance:
        return jsonify({'success': False, 'message': 'Unit not found'}), 404
    prev_status = instance.status
    duration = calc_duration_minutes(instance.entered_stage_at)
    now_ts = get_now_for_tenant()
    instance.status = 'idle'
    instance.assigned_to_user_id = None
    instance.entered_stage_at = None
    if reason:
        instance.idle_reason = reason
    instance.updated_at = now_ts
    db.session.add(ProductProcessLog(
        product_instance_id=instance.id,
        from_stage=instance.process_stage,
        to_stage=instance.process_stage,
        from_team=instance.team_assigned,
        to_team=instance.team_assigned,
        moved_by=current_user.id,
        moved_at=now_ts,
        action='scanner_mark_idle',
        note=f'Marked idle via scanner (was {prev_status}). Reason: {reason or "none"}',
        duration_minutes=duration,
    ))
    db.session.commit()
    return jsonify({'success': True, 'message': 'Unit marked idle.', 'status': 'idle'})


@scanner_bp.route('/scan/batch_apply', methods=['POST'])
@login_required
@module_required('stock', 'full')
def scan_batch_apply():
    """Apply bulk status/location/bin updates to a list of serials (batch mode)."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    serials    = data.get('serials', [])
    new_status = data.get('status', '').strip()
    new_stage  = data.get('process_stage', '').strip()
    location_id = data.get('location_id') or None
    shelf_bin  = (data.get('shelf_bin') or '').strip().upper()

    if not serials:
        return jsonify({'success': False, 'message': 'No serials provided'}), 400

    valid_statuses = {'unprocessed', 'under_process', 'processed', 'idle', 'disputed', ''}
    if new_status and new_status not in valid_statuses:
        return jsonify({'success': False, 'message': 'Invalid status'}), 400

    if location_id:
        loc_obj = Location.query.filter_by(id=location_id, tenant_id=current_user.tenant_id).first()
        if not loc_obj:
            return jsonify({'success': False, 'message': 'Location not found'}), 404
        location_name = loc_obj.name
    else:
        location_name = None

    results = []
    updated = 0
    now_ts  = get_now_for_tenant()

    for serial in serials:
        instance = ProductInstance.query.join(Product).filter(
            (ProductInstance.serial == serial) | (ProductInstance.asset == serial),
            Product.tenant_id == current_user.tenant_id,
        ).first()
        if not instance:
            results.append({'serial': serial, 'outcome': 'not_found', 'message': 'Not found'})
            continue

        prev_stage  = instance.process_stage
        prev_status = instance.status
        prev_team   = instance.team_assigned
        duration    = calc_duration_minutes(instance.entered_stage_at)

        if new_status:
            instance.status = new_status
            if new_status != 'under_process':
                instance.assigned_to_user_id = None
                instance.entered_stage_at    = None
            if new_status == 'unprocessed':
                instance.process_stage = None

        if new_stage:
            instance.process_stage = new_stage

        if location_id:
            instance.location_id = location_id

        if shelf_bin is not None and shelf_bin != '':
            instance.shelf_bin = shelf_bin
            resolved_loc = location_id or instance.location_id
            if resolved_loc:
                managed = Bin.query.filter_by(
                    name=shelf_bin, location_id=resolved_loc, tenant_id=current_user.tenant_id
                ).first()
                instance.bin_id = managed.id if managed else None

        instance.updated_at = now_ts
        db.session.add(ProductProcessLog(
            product_instance_id=instance.id,
            from_stage=prev_stage,
            to_stage=instance.process_stage,
            from_team=prev_team,
            to_team=instance.team_assigned,
            moved_by=current_user.id,
            moved_at=now_ts,
            action='scanner_batch',
            note=f'Batch: status={new_status or "—"} stage={new_stage or "—"} loc={location_name or "—"} bin={shelf_bin or "—"}',
            duration_minutes=duration,
        ))
        results.append({'serial': serial, 'outcome': 'updated', 'message': 'Updated'})
        updated += 1

    db.session.commit()
    return jsonify({
        'success': True,
        'updated': updated,
        'total':   len(serials),
        'results': results,
    })


@scanner_bp.route('/scan_move', methods=['GET', 'POST'])
@login_required
@module_required('stock', 'full')
def scan_move():
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
            return redirect(url_for('scanner_bp.scan_move'))
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
            status = request.form.get('status', '').strip()
            process_stage = request.form.get('process_stage', '').strip()
            team_assigned = request.form.get('team_assigned', '').strip()
            location_id = request.form.get('location_id', '').strip()
            shelf_bin = request.form.get('shelf_bin', '').strip().upper()
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
                    prev_stage = instance.process_stage
                    prev_status = instance.status
                    prev_team = instance.team_assigned
                    duration = calc_duration_minutes(instance.entered_stage_at)
                    now_ts = get_now_for_tenant()
                    # Only update fields when a real value was selected/entered
                    if status in ['unprocessed', 'under_process', 'processed', 'idle', 'disputed']:
                        instance.status = status
                    if process_stage:
                        instance.process_stage = process_stage
                    if team_assigned:
                        instance.team_assigned = team_assigned
                    if location_id:
                        instance.location_id = int(location_id)
                    if shelf_bin:
                        instance.shelf_bin = shelf_bin
                        resolved_loc = int(location_id) if location_id else instance.location_id
                        if resolved_loc:
                            managed = Bin.query.filter_by(
                                name=shelf_bin, location_id=resolved_loc,
                                tenant_id=current_user.tenant_id
                            ).first()
                            instance.bin_id = managed.id if managed else None
                    instance.updated_at = now_ts
                    db.session.add(ProductProcessLog(
                        product_instance_id=instance.id,
                        from_stage=prev_stage,
                        to_stage=instance.process_stage,
                        from_team=prev_team,
                        to_team=instance.team_assigned,
                        moved_by=current_user.id,
                        moved_at=now_ts,
                        action='scan_move',
                        duration_minutes=duration,
                    ))
                    updated += 1
            db.session.commit()
            flash(f"{updated} serial(s) updated successfully.", "success")
            batch_serials = []
            session['batch_serials'] = batch_serials
            session.modified = True

    # Optimized bulk query for displaying scanned instances
    serials_upper = [s.strip().upper() for s in batch_serials]
    instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id
    ).filter(
        or_(
            func.upper(ProductInstance.serial).in_(serials_upper),
            func.upper(ProductInstance.asset).in_(serials_upper)
        )
    ).options(joinedload(ProductInstance.location)).all()

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
            "location_name": instance.location.name if instance and instance.location else "—",
            "process_stage": instance.process_stage if instance else "",
            "team_assigned": instance.team_assigned if instance else "",
            "shelf_bin": instance.shelf_bin if instance else "",
        })

    return render_template(
        'scan_move.html',
        instances=unified_instances,
        serial=serial or "",
        locations=Location.query.filter_by(tenant_id=current_user.tenant_id).all()
    )

import logging
import time
import random
from flask import jsonify
from flask_login import current_user
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.exc import IntegrityError
from flask import session
from inventory_flask_app import csrf
from ..models import db, Part, PartStock, PartMovement, PartUsage, PartSale, PartSaleTransaction, PartSaleItem, Location, Bin, Vendor, Product, ProductInstance, Customer, SaleTransaction, Invoice, TenantSettings
from ..utils.mail_utils import get_low_stock_parts, maybe_send_low_stock_email
from ..utils.utils import generate_part_invoice_number, get_now_for_tenant, is_module_enabled, module_required

logger = logging.getLogger(__name__)

parts_bp = Blueprint('parts_bp', __name__, url_prefix='/parts')


def _require_parts_module():
    """Return a redirect response if parts module is disabled, else None."""
    from flask import abort
    if not is_module_enabled('enable_parts_module'):
        abort(403)


# ── helpers ──────────────────────────────────────────────────────────────────

def _attach_stock(parts):
    """Attach ._current_stock to each Part and return set of low-stock ids."""
    low_stock_ids = set()
    for part in parts:
        part._current_stock = sum(s.quantity for s in part.stocks)
        if part._current_stock < (part.min_stock or 1):
            low_stock_ids.add(part.id)
    return low_stock_ids


def _vendor_display(part):
    """Return the best display name for a part's vendor."""
    if part.vendor_rel:
        return part.vendor_rel.name
    return part.vendor or '—'


# ── list ─────────────────────────────────────────────────────────────────────

@parts_bp.route('/')
@login_required
@module_required('parts', 'view')
def parts_list():
    _require_parts_module()
    search = request.args.get('search', '').strip()
    query = Part.query.filter_by(tenant_id=current_user.tenant_id)

    if search:
        query = query.filter(
            (Part.part_number.ilike(f'%{search}%')) |
            (Part.name.ilike(f'%{search}%')) |
            (Part.vendor.ilike(f'%{search}%'))
        )

    parts = query.order_by(Part.name).all()
    low_stock_ids = _attach_stock(parts)
    total_quantity = sum(p._current_stock for p in parts)
    total_value = sum(p._current_stock * (p.price or 0) for p in parts)
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).order_by(Location.name).all()

    return render_template(
        'parts/parts_list.html',
        parts=parts,
        total_parts=len(parts),
        total_quantity=total_quantity,
        total_value=total_value,
        low_stock_ids=low_stock_ids,
        search=search,
        locations=locations,
    )


# ── add ───────────────────────────────────────────────────────────────────────

@parts_bp.route('/add', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def add_part():
    _require_parts_module()
    vendors = Vendor.query.filter_by(
        tenant_id=current_user.tenant_id
    ).order_by(Vendor.name).all()

    if request.method == 'POST':
        part_number = request.form.get('part_number', '').strip()
        name = request.form.get('name', '').strip()

        if not part_number or not name:
            flash('Part number and name are required.', 'danger')
            return render_template('parts/add_part.html', vendors=vendors)

        if Part.query.filter_by(
            part_number=part_number, tenant_id=current_user.tenant_id
        ).first():
            flash('Part number already exists.', 'danger')
            return render_template('parts/add_part.html', vendors=vendors)

        # Barcode: use submitted value or auto-generate
        barcode = request.form.get('barcode', '').strip() or None
        if not barcode:
            barcode = f"PRT-{current_user.tenant_id}-{int(time.time())}"

        # Uniqueness check for barcode within tenant
        if Part.query.filter_by(barcode=barcode, tenant_id=current_user.tenant_id).first():
            flash('That barcode is already assigned to another part. Regenerate and try again.', 'danger')
            return render_template('parts/add_part.html', vendors=vendors)

        vendor_id = request.form.get('vendor_id') or None
        vendor_text = request.form.get('vendor', '').strip()

        # If a linked vendor is selected, sync the text field from it
        if vendor_id:
            v = Vendor.query.filter_by(id=int(vendor_id), tenant_id=current_user.tenant_id).first()
            vendor_text = v.name if v else vendor_text

        part = Part(
            part_number=part_number,
            name=name,
            part_type=request.form.get('part_type', '').strip(),
            vendor=vendor_text,
            vendor_id=int(vendor_id) if vendor_id else None,
            min_stock=int(request.form.get('min_stock', 1) or 1),
            price=float(request.form.get('price', 0) or 0),
            description=request.form.get('description', '').strip(),
            barcode=barcode,
            tenant_id=current_user.tenant_id,
        )
        db.session.add(part)
        try:
            db.session.commit()
            flash('Part added successfully.', 'success')
            return redirect(url_for('parts_bp.parts_list'))
        except IntegrityError:
            db.session.rollback()
            flash('Part number already exists.', 'danger')

    return render_template('parts/add_part.html', vendors=vendors)


# ── edit ──────────────────────────────────────────────────────────────────────

@parts_bp.route('/<int:part_id>/edit', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def edit_part(part_id):
    _require_parts_module()
    part = Part.query.filter_by(
        id=part_id, tenant_id=current_user.tenant_id
    ).first_or_404()
    vendors = Vendor.query.filter_by(
        tenant_id=current_user.tenant_id
    ).order_by(Vendor.name).all()

    if request.method == 'POST':
        part_number = request.form.get('part_number', '').strip()
        name = request.form.get('name', '').strip()

        if not part_number or not name:
            flash('Part number and name are required.', 'danger')
            return render_template('parts/edit_part.html', part=part, vendors=vendors)

        # Uniqueness check — exclude current part
        conflict = Part.query.filter(
            Part.part_number == part_number,
            Part.tenant_id == current_user.tenant_id,
            Part.id != part_id,
        ).first()
        if conflict:
            flash('That part number is already used by another part.', 'danger')
            return render_template('parts/edit_part.html', part=part, vendors=vendors)

        vendor_id = request.form.get('vendor_id') or None
        vendor_text = request.form.get('vendor', '').strip()

        if vendor_id:
            v = Vendor.query.filter_by(id=int(vendor_id), tenant_id=current_user.tenant_id).first()
            vendor_text = v.name if v else vendor_text

        # Barcode: allow clearing (set to None) or updating
        barcode_raw = request.form.get('barcode', '').strip()
        barcode = barcode_raw or None

        # Uniqueness check — exclude current part
        if barcode:
            barcode_conflict = Part.query.filter(
                Part.barcode == barcode,
                Part.tenant_id == current_user.tenant_id,
                Part.id != part_id,
            ).first()
            if barcode_conflict:
                flash('That barcode is already assigned to another part.', 'danger')
                return render_template('parts/edit_part.html', part=part, vendors=vendors)

        part.part_number = part_number
        part.name = name
        part.part_type = request.form.get('part_type', '').strip()
        part.vendor = vendor_text
        part.vendor_id = int(vendor_id) if vendor_id else None
        part.min_stock = int(request.form.get('min_stock', 1) or 1)
        part.price = float(request.form.get('price', 0) or 0)
        part.description = request.form.get('description', '').strip()
        part.barcode = barcode

        try:
            db.session.commit()
            flash('Part updated.', 'success')
            return redirect(url_for('parts_bp.part_detail', part_id=part_id))
        except IntegrityError:
            db.session.rollback()
            flash('Part number already exists.', 'danger')

    return render_template('parts/edit_part.html', part=part, vendors=vendors)


# ── delete ────────────────────────────────────────────────────────────────────

@parts_bp.route('/<int:part_id>/delete', methods=['POST'])
@login_required
@module_required('parts', 'full')
def delete_part(part_id):
    _require_parts_module()
    part = Part.query.filter_by(
        id=part_id, tenant_id=current_user.tenant_id
    ).first_or_404()

    total_stock = sum(s.quantity for s in part.stocks)
    if total_stock > 0:
        flash(
            f'Cannot delete "{part.name}" — {total_stock} unit(s) still in stock. '
            'Remove all stock first.',
            'danger',
        )
        return redirect(url_for('parts_bp.parts_list'))

    name = part.name
    db.session.delete(part)
    db.session.commit()
    flash(f'Part "{name}" deleted.', 'success')
    return redirect(url_for('parts_bp.parts_list'))


# ── stock in ──────────────────────────────────────────────────────────────────

@parts_bp.route('/stock_in', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def stock_in():
    preselect = request.args.get('part_id', type=int)
    search_query = request.args.get('search', '').strip()
    q = Part.query.filter_by(tenant_id=current_user.tenant_id)
    if search_query:
        q = q.filter(
            (Part.part_number.ilike(f'%{search_query}%')) |
            (Part.name.ilike(f'%{search_query}%'))
        )
    parts = q.order_by(Part.name).all()
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()

    preselected_part = None
    if preselect:
        preselected_part = Part.query.filter_by(
            id=preselect, tenant_id=current_user.tenant_id
        ).first()
        if preselected_part:
            _attach_stock([preselected_part])

    if request.method == 'POST':
        try:
            part_id = int(request.form['part_id'])
            location_id = int(request.form['location_id'])
            quantity = int(request.form['quantity'])
        except (KeyError, ValueError) as e:
            flash(f'Invalid form data: {e}', 'danger')
            return redirect(url_for('parts_bp.stock_in'))

        if quantity <= 0:
            flash('Quantity must be greater than zero.', 'danger')
            return redirect(url_for('parts_bp.stock_in'))

        note = request.form.get('note', '').strip()
        bin_id_raw = request.form.get('bin_id', '').strip()
        bin_id = int(bin_id_raw) if bin_id_raw else None

        # Guard: part must belong to this tenant
        part = Part.query.filter_by(
            id=part_id, tenant_id=current_user.tenant_id
        ).first_or_404()

        # Validate bin belongs to this location + tenant
        if bin_id:
            from ..models import Bin as BinModel
            b = BinModel.query.filter_by(
                id=bin_id, location_id=location_id, tenant_id=current_user.tenant_id
            ).first()
            if not b:
                flash('Invalid bin for that location.', 'danger')
                return redirect(url_for('parts_bp.stock_in', part_id=preselect))
            bin_id = b.id

        part_stock = PartStock.query.filter_by(
            part_id=part_id, location_id=location_id, bin_id=bin_id
        ).first()
        if not part_stock:
            part_stock = PartStock(
                part_id=part_id, location_id=location_id, bin_id=bin_id, quantity=0
            )
            db.session.add(part_stock)
        part_stock.quantity += quantity

        db.session.add(PartMovement(
            part_id=part_id,
            to_location_id=location_id,
            to_bin_id=bin_id,
            quantity=quantity,
            movement_type='stock_in',
            note=note,
            user_id=current_user.id,
        ))
        db.session.commit()
        flash(f'Added {quantity}× {part.name} to stock.', 'success')
        maybe_send_low_stock_email(current_user.tenant_id)
        return redirect(url_for('parts_bp.parts_list'))

    part_summaries = [
        {
            'id': p.id,
            'part_number': p.part_number,
            'name': p.name,
            'total_quantity': sum(s.quantity for s in p.stocks),
        }
        for p in parts
    ]
    prefill_bin_id      = request.args.get('bin_id', '').strip()
    prefill_location_id = request.args.get('location_id', '').strip()
    return render_template(
        'parts/stock_in.html',
        parts=parts,
        part_summaries=part_summaries,
        locations=locations,
        search_query=search_query,
        preselected_part=preselected_part,
        prefill_bin_id=prefill_bin_id,
        prefill_location_id=prefill_location_id,
    )


# ── ajax add (inline from stock_in modal) ─────────────────────────────────────

@parts_bp.route('/ajax_add', methods=['POST'])
@login_required
@module_required('parts', 'full')
def ajax_add_part():
    part_number = request.form.get('part_number', '').strip()
    name = request.form.get('name', '').strip()

    if not part_number or not name:
        return jsonify(success=False, message='Part number and name are required.')

    if Part.query.filter_by(
        part_number=part_number, tenant_id=current_user.tenant_id
    ).first():
        return jsonify(success=False, message='Part number already exists.')

    # Auto-generate a unique barcode so this part is scannable immediately
    barcode = f"PRT-{current_user.tenant_id}-{int(time.time())}"
    while Part.query.filter_by(barcode=barcode, tenant_id=current_user.tenant_id).first():
        barcode = f"PRT-{current_user.tenant_id}-{int(time.time())}-{random.randint(1000, 9999)}"

    part = Part(
        part_number=part_number,
        name=name,
        part_type=request.form.get('part_type', ''),
        vendor=request.form.get('vendor', ''),
        min_stock=int(request.form.get('min_stock', 1) or 1),
        price=float(request.form.get('price', 0) or 0),
        description=request.form.get('description', ''),
        barcode=barcode,
        tenant_id=current_user.tenant_id,
    )
    db.session.add(part)
    try:
        db.session.commit()
        return jsonify(success=True, part_id=part.id,
                       part_number=part.part_number, name=part.name, barcode=barcode)
    except IntegrityError:
        db.session.rollback()
        return jsonify(success=False, message='Database error: could not add part.')


# ── CHANGE 1: bins for a location (parts only) ────────────────────────────────

@parts_bp.route('/api/bins')
@login_required
@module_required('parts', 'view')
def api_bins():
    """Return parts bins for a location with stock quantity summary."""
    location_id = request.args.get('location_id', type=int)
    if not location_id:
        return jsonify([])
    bins = (
        Bin.query
        .filter_by(location_id=location_id, bin_type='parts', tenant_id=current_user.tenant_id)
        .order_by(Bin.name)
        .all()
    )
    result = []
    for b in bins:
        current_qty = sum(ps.quantity for ps in b.part_stocks)
        result.append({'id': b.id, 'name': b.name, 'current_qty': current_qty})
    return jsonify(result)


# ── CHANGE 3: move part stock to a bin (scanner / bin detail) ──────────────────

@parts_bp.route('/api/move_to_bin', methods=['POST'])
@login_required
@module_required('parts', 'full')
def api_move_to_bin():
    """Move part stock from one location/bin to another (assign or relocate)."""
    data = request.get_json(silent=True) or {}
    try:
        part_id          = int(data['part_id'])
        from_location_id = int(data['from_location_id'])
        to_location_id   = int(data['to_location_id'])
        quantity         = int(data['quantity'])
    except (KeyError, TypeError, ValueError) as e:
        return jsonify(success=False, message=f'Invalid data: {e}'), 400

    from_bin_id_raw = data.get('from_bin_id')
    to_bin_id_raw   = data.get('to_bin_id')
    from_bin_id = int(from_bin_id_raw) if from_bin_id_raw else None
    to_bin_id   = int(to_bin_id_raw)   if to_bin_id_raw   else None

    if quantity <= 0:
        return jsonify(success=False, message='Quantity must be greater than zero.'), 400

    if from_location_id == to_location_id and from_bin_id == to_bin_id:
        return jsonify(success=False, message='Source and destination are the same.'), 400

    part = Part.query.filter_by(id=part_id, tenant_id=current_user.tenant_id).first()
    if not part:
        return jsonify(success=False, message='Part not found.'), 404

    from_stock = PartStock.query.filter_by(
        part_id=part_id, location_id=from_location_id, bin_id=from_bin_id
    ).first()
    available = from_stock.quantity if from_stock else 0
    if available < quantity:
        return jsonify(success=False, message=f'Not enough stock at source. Available: {available}.'), 400

    from_stock.quantity -= quantity

    to_stock = PartStock.query.filter_by(
        part_id=part_id, location_id=to_location_id, bin_id=to_bin_id
    ).first()
    if not to_stock:
        to_stock = PartStock(
            part_id=part_id, location_id=to_location_id, bin_id=to_bin_id, quantity=0
        )
        db.session.add(to_stock)
    to_stock.quantity += quantity

    db.session.add(PartMovement(
        part_id=part_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        from_bin_id=from_bin_id,
        to_bin_id=to_bin_id,
        quantity=quantity,
        movement_type='transfer',
        note=data.get('note', ''),
        user_id=current_user.id,
    ))
    db.session.commit()
    return jsonify(success=True, message=f'Moved {quantity}× {part.name} to new bin.')


# ── shared helper for movement forms ─────────────────────────────────────────

def _get_parts_with_location_stock(tenant_id):
    """Return all parts for tenant with per-location/bin stock data attached."""
    parts = Part.query.filter_by(tenant_id=tenant_id).order_by(Part.name).all()
    _attach_stock(parts)
    summaries = []
    for p in parts:
        summaries.append({
            'id': p.id,
            'part_number': p.part_number,
            'name': p.name,
            'price': p.price,
            'total_quantity': p._current_stock,
            'location_stocks': [
                {
                    'location_id': s.location_id,
                    'location_name': s.location.name,
                    'bin_id': s.bin_id,
                    'bin_name': s.bin.name if s.bin else None,
                    'quantity': s.quantity,
                }
                for s in p.stocks if s.quantity > 0
            ],
        })
    return parts, summaries


# ── stock out ─────────────────────────────────────────────────────────────────

@parts_bp.route('/stock_out', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def stock_out():
    preselect = request.args.get('part_id', type=int)
    parts, part_summaries = _get_parts_with_location_stock(current_user.tenant_id)
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
    preselected_part = next((p for p in parts if p.id == preselect), None)

    if request.method == 'POST':
        try:
            part_id   = int(request.form['part_id'])
            location_id = int(request.form['location_id'])
            quantity  = int(request.form['quantity'])
        except (KeyError, ValueError) as e:
            flash(f'Invalid form data: {e}', 'danger')
            return redirect(url_for('parts_bp.stock_out'))

        if quantity <= 0:
            flash('Quantity must be greater than zero.', 'danger')
            return redirect(url_for('parts_bp.stock_out'))

        note = request.form.get('note', '').strip()
        bin_id_raw = request.form.get('bin_id', '').strip()
        bin_id = int(bin_id_raw) if bin_id_raw else None

        part = Part.query.filter_by(
            id=part_id, tenant_id=current_user.tenant_id
        ).first_or_404()

        part_stock = PartStock.query.filter_by(
            part_id=part_id, location_id=location_id, bin_id=bin_id
        ).first()
        available = part_stock.quantity if part_stock else 0
        if available < quantity:
            flash(f'Not enough stock at that location/bin. Available: {available}.', 'danger')
            return redirect(url_for('parts_bp.stock_out'))

        part_stock.quantity -= quantity
        db.session.add(PartMovement(
            part_id=part_id,
            from_location_id=location_id,
            from_bin_id=bin_id,
            quantity=quantity,
            movement_type='stock_out',
            note=note,
            user_id=current_user.id,
        ))
        db.session.commit()
        flash(f'Removed {quantity}× {part.name} from stock.', 'success')
        maybe_send_low_stock_email(current_user.tenant_id)
        return redirect(url_for('parts_bp.parts_list'))

    return render_template(
        'parts/stock_out.html',
        parts=parts,
        part_summaries=part_summaries,
        locations=locations,
        preselect=preselect,
        preselected_part=preselected_part,
    )


# ── consume (tech uses part in a repair) ──────────────────────────────────────

@parts_bp.route('/consume', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def consume():
    preselect = request.args.get('part_id', type=int)
    parts, part_summaries = _get_parts_with_location_stock(current_user.tenant_id)
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
    preselected_part = next((p for p in parts if p.id == preselect), None)

    if request.method == 'POST':
        try:
            part_id     = int(request.form['part_id'])
            location_id = int(request.form['location_id'])
            quantity    = int(request.form['quantity'])
        except (KeyError, ValueError) as e:
            flash(f'Invalid form data: {e}', 'danger')
            return redirect(url_for('parts_bp.consume'))

        if quantity <= 0:
            flash('Quantity must be greater than zero.', 'danger')
            return redirect(url_for('parts_bp.consume'))

        note   = request.form.get('note', '').strip()
        serial = request.form.get('unit_serial', '').strip()
        bin_id_raw = request.form.get('bin_id', '').strip()
        bin_id = int(bin_id_raw) if bin_id_raw else None

        part = Part.query.filter_by(
            id=part_id, tenant_id=current_user.tenant_id
        ).first_or_404()

        # Optional unit lookup by serial or asset tag
        instance = None
        if serial:
            instance = (
                ProductInstance.query
                .join(Product, Product.id == ProductInstance.product_id)
                .filter(
                    Product.tenant_id == current_user.tenant_id,
                    db.or_(
                        ProductInstance.serial == serial,
                        ProductInstance.asset  == serial,
                    ),
                )
                .first()
            )
            if not instance:
                flash(
                    f'Unit "{serial}" not found — part will be consumed without a unit link.',
                    'warning',
                )
            else:
                note = (f'[Unit: {instance.serial}] ' + note).strip()

        part_stock = PartStock.query.filter_by(
            part_id=part_id, location_id=location_id, bin_id=bin_id
        ).first()
        available = part_stock.quantity if part_stock else 0
        if available < quantity:
            flash(f'Not enough stock at that location/bin. Available: {available}.', 'danger')
            return redirect(url_for('parts_bp.consume'))

        part_stock.quantity -= quantity
        db.session.add(PartMovement(
            part_id=part_id,
            from_location_id=location_id,
            from_bin_id=bin_id,
            quantity=quantity,
            movement_type='consume',
            note=note,
            user_id=current_user.id,
            instance_id=instance.id if instance else None,
        ))
        # Also create a PartUsage record so standalone consumes appear in usage reports
        db.session.add(PartUsage(
            part_id=part_id,
            quantity=quantity,
            used_by=current_user.id,
            instance_id=instance.id if instance else None,
            note=note,
            tenant_id=current_user.tenant_id,
        ))
        db.session.commit()

        msg = f'Consumed {quantity}× {part.name}'
        if instance:
            msg += f' (unit: {instance.serial})'
        flash(msg + '.', 'success')
        maybe_send_low_stock_email(current_user.tenant_id)
        return redirect(url_for('parts_bp.parts_list'))

    return render_template(
        'parts/consume.html',
        parts=parts,
        part_summaries=part_summaries,
        locations=locations,
        preselect=preselect,
        preselected_part=preselected_part,
    )


# ── transfer ──────────────────────────────────────────────────────────────────

@parts_bp.route('/transfer', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def transfer():
    preselect = request.args.get('part_id', type=int)
    parts, part_summaries = _get_parts_with_location_stock(current_user.tenant_id)
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
    preselected_part = next((p for p in parts if p.id == preselect), None)

    if request.method == 'POST':
        try:
            part_id          = int(request.form['part_id'])
            from_location_id = int(request.form['from_location_id'])
            to_location_id   = int(request.form['to_location_id'])
            quantity         = int(request.form['quantity'])
        except (KeyError, ValueError) as e:
            flash(f'Invalid form data: {e}', 'danger')
            return redirect(url_for('parts_bp.transfer'))

        if quantity <= 0:
            flash('Quantity must be greater than zero.', 'danger')
            return redirect(url_for('parts_bp.transfer'))

        note = request.form.get('note', '').strip()
        from_bin_raw = request.form.get('from_bin_id', '').strip()
        to_bin_raw   = request.form.get('to_bin_id',   '').strip()
        from_bin_id  = int(from_bin_raw) if from_bin_raw else None
        to_bin_id    = int(to_bin_raw)   if to_bin_raw   else None

        if from_location_id == to_location_id and from_bin_id == to_bin_id:
            flash('Source and destination must be different.', 'danger')
            return redirect(url_for('parts_bp.transfer'))

        part = Part.query.filter_by(
            id=part_id, tenant_id=current_user.tenant_id
        ).first_or_404()

        from_stock = PartStock.query.filter_by(
            part_id=part_id, location_id=from_location_id, bin_id=from_bin_id
        ).first()
        available = from_stock.quantity if from_stock else 0
        if available < quantity:
            flash(f'Not enough stock in source location/bin. Available: {available}.', 'danger')
            return redirect(url_for('parts_bp.transfer'))

        # Decrement source
        from_stock.quantity -= quantity

        # Increment (or create) destination
        to_stock = PartStock.query.filter_by(
            part_id=part_id, location_id=to_location_id, bin_id=to_bin_id
        ).first()
        if not to_stock:
            to_stock = PartStock(
                part_id=part_id, location_id=to_location_id, bin_id=to_bin_id, quantity=0
            )
            db.session.add(to_stock)
        to_stock.quantity += quantity

        db.session.add(PartMovement(
            part_id=part_id,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            from_bin_id=from_bin_id,
            to_bin_id=to_bin_id,
            quantity=quantity,
            movement_type='transfer',
            note=note,
            user_id=current_user.id,
        ))
        db.session.commit()
        flash(f'Transferred {quantity}× {part.name}.', 'success')
        maybe_send_low_stock_email(current_user.tenant_id)
        return redirect(url_for('parts_bp.parts_list'))

    return render_template(
        'parts/transfer.html',
        parts=parts,
        part_summaries=part_summaries,
        locations=locations,
        preselect=preselect,
        preselected_part=preselected_part,
    )


# ── part detail page ──────────────────────────────────────────────────────────

@parts_bp.route('/<int:part_id>')
@login_required
@module_required('parts', 'view')
def part_detail(part_id):
    part = Part.query.filter_by(
        id=part_id, tenant_id=current_user.tenant_id
    ).first_or_404()

    _attach_stock([part])

    movements = (
        PartMovement.query
        .filter_by(part_id=part_id)
        .order_by(PartMovement.created_at.desc())
        .all()
    )

    usages = (
        PartUsage.query
        .filter_by(part_id=part_id, tenant_id=current_user.tenant_id)
        .order_by(PartUsage.used_at.desc())
        .all()
    )

    # Legacy PartSale rows (older sell flow)
    legacy_sales = (
        PartSale.query
        .filter_by(part_id=part_id, tenant_id=current_user.tenant_id)
        .order_by(PartSale.sold_at.desc())
        .all()
    )

    # New cart-based sale items (with invoice links)
    sale_items = (
        PartSaleItem.query
        .filter(
            PartSaleItem.part_id == part_id,
            PartSaleItem.tenant_id == current_user.tenant_id,
        )
        .order_by(PartSaleItem.id.desc())
        .all()
    )

    total_sold    = sum(i.quantity for i in sale_items) + sum(s.quantity for s in legacy_sales)
    total_revenue = sum(float(i.subtotal) for i in sale_items) + sum(
        (s.unit_price or 0) * s.quantity for s in legacy_sales
    )
    total_used    = sum(u.quantity for u in usages)
    total_stock   = part._current_stock
    total_value   = total_stock * (part.price or 0)
    low_stock     = total_stock < (part.min_stock or 1)

    # CSV export for movements
    if request.args.get('export') == 'movements_csv':
        import csv
        from io import StringIO
        from flask import make_response
        out = StringIO()
        w = csv.writer(out)
        w.writerow(['Date', 'Type', 'Qty', 'From Location', 'To Location', 'User', 'Unit Serial', 'Note'])
        for m in movements:
            w.writerow([
                m.created_at.strftime('%Y-%m-%d %H:%M') if m.created_at else '',
                m.movement_type,
                m.quantity,
                m.from_location.name if m.from_location else '',
                m.to_location.name if m.to_location else '',
                m.user.username if m.user else '',
                m.instance.serial if m.instance else '',
                m.note or '',
            ])
        resp = make_response(out.getvalue())
        resp.headers['Content-Type'] = 'text/csv'
        resp.headers['Content-Disposition'] = (
            f'attachment; filename=part_{part_id}_movements.csv'
        )
        return resp

    return render_template(
        'parts/detail.html',
        part=part,
        movements=movements,
        usages=usages,
        legacy_sales=legacy_sales,
        sale_items=sale_items,
        total_sold=total_sold,
        total_revenue=total_revenue,
        total_used=total_used,
        total_stock=total_stock,
        total_value=total_value,
        low_stock=low_stock,
    )


# ── movement history ──────────────────────────────────────────────────────────

@parts_bp.route('/<int:part_id>/history')
@login_required
@module_required('parts', 'view')
def part_history(part_id):
    part = Part.query.filter_by(
        id=part_id, tenant_id=current_user.tenant_id
    ).first_or_404()

    _attach_stock([part])

    movements = (
        PartMovement.query
        .filter_by(part_id=part_id)
        .order_by(PartMovement.created_at.desc())
        .all()
    )

    # Running balance (most-recent first list → reverse to compute forward)
    total_stock = part._current_stock
    balance = total_stock
    for m in reversed(movements):
        m._balance_after = balance
        if m.movement_type == 'stock_in':
            balance -= m.quantity
        elif m.movement_type in ('stock_out', 'consume'):
            balance += m.quantity
        elif m.movement_type == 'transfer':
            pass  # net zero — balance unchanged
    # Fix: balance is "before" after the reverse pass; flip so _balance_after is correct
    # Recompute forward pass
    balance = 0
    for m in reversed(movements):
        if m.movement_type == 'stock_in':
            balance += m.quantity
        elif m.movement_type in ('stock_out', 'consume', 'sale'):
            balance -= m.quantity
        m._balance_after = balance

    return render_template(
        'parts/history.html',
        part=part,
        movements=movements,
    )


# ── ajax: unit lookup for consume form ───────────────────────────────────────

@parts_bp.route('/ajax_lookup_unit')
@login_required
@module_required('parts', 'view')
def lookup_unit():
    serial = request.args.get('serial', '').strip()
    if not serial:
        return jsonify(found=False)

    instance = (
        ProductInstance.query
        .join(Product, Product.id == ProductInstance.product_id)
        .filter(
            Product.tenant_id == current_user.tenant_id,
            db.or_(
                ProductInstance.serial == serial,
                ProductInstance.asset  == serial,
            ),
        )
        .first()
    )
    if not instance:
        return jsonify(found=False)

    return jsonify(
        found=True,
        serial=instance.serial,
        item_name=instance.product.item_name,
        status=instance.status,
        instance_id=instance.id,
    )


# ── use (tech records part used on a unit) ────────────────────────────────────

@parts_bp.route('/use', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def use():
    """Record a tech using a part on a specific unit.

    This creates a PartUsage row (unit-linked audit), decrements PartStock,
    and logs a PartMovement(type='consume').
    """
    preselect_part     = request.args.get('part_id', type=int)
    preselect_instance = request.args.get('instance_id', type=int)

    parts, part_summaries = _get_parts_with_location_stock(current_user.tenant_id)
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
    preselected_part = next((p for p in parts if p.id == preselect_part), None)

    # Pre-fill instance info if coming from a unit page
    preselect_serial = ''
    if preselect_instance:
        inst = (
            ProductInstance.query
            .join(Product, Product.id == ProductInstance.product_id)
            .filter(
                Product.tenant_id == current_user.tenant_id,
                ProductInstance.id == preselect_instance,
            )
            .first()
        )
        if inst:
            preselect_serial = inst.serial or inst.asset or ''

    if request.method == 'POST':
        try:
            part_id     = int(request.form['part_id'])
            location_id = int(request.form['location_id'])
            quantity    = int(request.form['quantity'])
        except (KeyError, ValueError) as e:
            flash(f'Invalid form data: {e}', 'danger')
            return redirect(url_for('parts_bp.use'))

        if quantity <= 0:
            flash('Quantity must be greater than zero.', 'danger')
            return redirect(url_for('parts_bp.use'))

        note   = request.form.get('note', '').strip()
        serial = request.form.get('unit_serial', '').strip()
        bin_id_raw = request.form.get('bin_id', '').strip()
        bin_id = int(bin_id_raw) if bin_id_raw else None

        part = Part.query.filter_by(
            id=part_id, tenant_id=current_user.tenant_id
        ).first_or_404()

        # Resolve unit
        instance = None
        if serial:
            instance = (
                ProductInstance.query
                .join(Product, Product.id == ProductInstance.product_id)
                .filter(
                    Product.tenant_id == current_user.tenant_id,
                    db.or_(
                        ProductInstance.serial == serial,
                        ProductInstance.asset  == serial,
                    ),
                )
                .first()
            )
            if not instance:
                flash(
                    f'Unit "{serial}" not found — part will be logged without a unit link.',
                    'warning',
                )

        # Check stock
        part_stock = PartStock.query.filter_by(
            part_id=part_id, location_id=location_id, bin_id=bin_id
        ).first()
        available = part_stock.quantity if part_stock else 0
        if available < quantity:
            flash(f'Not enough stock at that location/bin. Available: {available}.', 'danger')
            return redirect(url_for('parts_bp.use'))

        # Decrement stock
        part_stock.quantity -= quantity

        # Log PartMovement
        movement_note = (f'[Unit: {instance.serial}] ' + note).strip() if instance else note
        db.session.add(PartMovement(
            part_id=part_id,
            from_location_id=location_id,
            from_bin_id=bin_id,
            quantity=quantity,
            movement_type='consume',
            note=movement_note,
            user_id=current_user.id,
            instance_id=instance.id if instance else None,
        ))

        # Create PartUsage record
        db.session.add(PartUsage(
            part_id=part_id,
            instance_id=instance.id if instance else None,
            quantity=quantity,
            used_by=current_user.id,
            note=note,
            tenant_id=current_user.tenant_id,
        ))

        db.session.commit()

        msg = f'Recorded {quantity}× {part.name} used'
        if instance:
            msg += f' on unit {instance.serial}'
        flash(msg + '.', 'success')
        maybe_send_low_stock_email(current_user.tenant_id)

        # Return to unit page if we came from one
        if instance:
            return redirect(url_for('stock_bp.unit_history', serial=instance.serial))
        return redirect(url_for('parts_bp.parts_list'))

    return render_template(
        'parts/use.html',
        parts=parts,
        part_summaries=part_summaries,
        locations=locations,
        preselect=preselect_part,
        preselect_serial=preselect_serial,
        preselected_part=preselected_part,
    )



# ─────────────────────────────────────────────────────────────────────────────
# PARTS SALE SYSTEM  (multi-step cart → customer → invoice-type → payment)
# ─────────────────────────────────────────────────────────────────────────────

_SALE_SESSION_CART     = 'psale_cart'
_SALE_SESSION_CUSTOMER = 'psale_customer'
_SALE_SESSION_INVOICE  = 'psale_invoice'


def _get_sale_parts_data(tenant_id):
    """Return (parts, summaries) for sale cart — lightweight version."""
    parts = Part.query.filter_by(tenant_id=tenant_id).order_by(Part.name).all()
    _attach_stock(parts)
    summaries = []
    for p in parts:
        summaries.append({
            'id': p.id,
            'part_number': p.part_number,
            'name': p.name,
            'price': float(p.price) if p.price else None,
            'total_stock': p._current_stock,
            'location_stocks': [
                {
                    'location_id': s.location_id,
                    'location_name': s.location.name,
                    'bin_id': s.bin_id,
                    'bin_name': s.bin.name if s.bin else None,
                    'quantity': s.quantity,
                }
                for s in p.stocks if s.quantity > 0
            ],
        })
    return parts, summaries


# ── Step 1: Cart ──────────────────────────────────────────────────────────────

@parts_bp.route('/sell', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def sell():
    _require_parts_module()
    parts, summaries = _get_sale_parts_data(current_user.tenant_id)
    preselect_part_id = request.args.get('part_id', type=int)
    customers = Customer.query.filter_by(tenant_id=current_user.tenant_id).order_by(Customer.name).all()
    settings = {s.key: s.value for s in TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()}

    def _render():
        return render_template('parts/sale_cart.html',
                               part_summaries_json=summaries,
                               preselect_part_id=preselect_part_id,
                               customers=customers,
                               settings=settings)

    if request.method == 'POST':
        # ── Customer ──
        cid_raw = request.form.get('customer_id', '').strip()
        customer_id = int(cid_raw) if cid_raw else None
        if not customer_id:
            flash('Please select a customer.', 'warning')
            return _render()
        customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first_or_404()

        # ── Parse cart rows ──
        part_ids    = request.form.getlist('part_id[]')
        location_ids = request.form.getlist('location_id[]')
        bin_ids     = request.form.getlist('bin_id[]')
        quantities  = request.form.getlist('quantity[]')
        unit_prices = request.form.getlist('unit_price[]')

        cart = []
        errors = []
        for i, pid in enumerate(part_ids):
            row_label = f'Row {i+1}'
            try:
                pid = int(pid)
            except (ValueError, TypeError):
                errors.append(f'{row_label}: please select a valid part.')
                continue
            try:
                lid = int(location_ids[i]) if i < len(location_ids) and location_ids[i] else None
            except (ValueError, IndexError):
                lid = None
            try:
                raw_bid = bin_ids[i] if i < len(bin_ids) else ''
                bid = int(raw_bid) if raw_bid else None
            except ValueError:
                bid = None
            try:
                qty = int(quantities[i])
            except (ValueError, IndexError):
                errors.append(f'{row_label}: quantity must be a whole number.')
                continue
            try:
                price = float(unit_prices[i]) if i < len(unit_prices) and unit_prices[i] else 0.0
            except (ValueError, IndexError):
                price = 0.0
            if not lid:
                errors.append(f'{row_label}: please select a location.')
                continue
            if qty <= 0:
                errors.append(f'{row_label}: quantity must be at least 1.')
                continue
            if price <= 0:
                errors.append(f'{row_label}: unit price must be greater than 0.')
                continue
            stock_row = PartStock.query.filter_by(part_id=pid, location_id=lid, bin_id=bid).first()
            available = stock_row.quantity if stock_row else 0
            if available < qty:
                part_obj = next((p for p in parts if p.id == pid), None)
                pname = part_obj.name if part_obj else f'Part #{pid}'
                errors.append(f'{pname}: only {available} in stock at that location.')
                continue
            part_obj = next((p for p in parts if p.id == pid), None)
            cart.append({
                'part_id': pid,
                'part_name': part_obj.name if part_obj else '',
                'part_number': part_obj.part_number if part_obj else '',
                'location_id': lid,
                'bin_id': bid,
                'quantity': qty,
                'unit_price': price,
                'subtotal': round(price * qty, 2),
            })

        if errors:
            for e in errors:
                flash(e, 'danger')
            return _render()
        if not cart:
            flash('Add at least one item to the cart.', 'danger')
            return _render()

        # ── Payment + VAT ──
        method = request.form.get('payment_method', 'cash')
        vat_applied = request.form.get('vat_applied', 'false') == 'true'
        vat_rate = float(settings.get('vat_rate') or '5')
        subtotal = sum(item['subtotal'] for item in cart)
        tax = round(subtotal * vat_rate / 100, 2) if vat_applied else 0
        total_amount = subtotal + tax

        # ── Create transaction ──
        status = 'pending' if method == 'credit' else 'paid'
        now = get_now_for_tenant()
        invoice_number = generate_part_invoice_number(current_user.tenant_id)

        txn = PartSaleTransaction(
            invoice_number=invoice_number,
            customer_id=customer_id,
            customer_name=None,
            sale_id=None,
            payment_method=method,
            payment_status=status,
            subtotal=subtotal,
            tax=tax,
            total_amount=total_amount,
            notes=None,
            sold_by=current_user.id,
            sold_at=now,
            tenant_id=current_user.tenant_id,
        )
        db.session.add(txn)
        db.session.flush()

        for item in cart:
            stock_row = PartStock.query.filter_by(
                part_id=item['part_id'],
                location_id=item['location_id'],
                bin_id=item['bin_id'],
            ).first()
            available = stock_row.quantity if stock_row else 0
            if available < item['quantity']:
                db.session.rollback()
                flash(f"{item['part_name']}: stock changed — only {available} available. Please retry.", 'danger')
                return _render()
            stock_row.quantity -= item['quantity']
            db.session.add(PartSaleItem(
                transaction_id=txn.id,
                part_id=item['part_id'],
                bin_id=item['bin_id'],
                location_id=item['location_id'],
                quantity=item['quantity'],
                unit_price=item['unit_price'],
                subtotal=item['subtotal'],
                tenant_id=current_user.tenant_id,
            ))
            db.session.add(PartMovement(
                part_id=item['part_id'],
                from_location_id=item['location_id'],
                from_bin_id=item['bin_id'],
                quantity=item['quantity'],
                movement_type='sale',
                note=f'Sale {invoice_number}',
                user_id=current_user.id,
            ))

        if method == 'credit':
            c_obj = db.session.get(Customer, customer_id)
            if c_obj:
                c_obj.parts_balance = float(c_obj.parts_balance or 0) + total_amount

        db.session.commit()
        maybe_send_low_stock_email(current_user.tenant_id)
        flash(f'Sale {invoice_number} completed.', 'success')
        return redirect(url_for('parts_bp.sale_detail', txn_id=txn.id))

    return _render()


# ── Step 2: Customer ──────────────────────────────────────────────────────────

@parts_bp.route('/sale/customer', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def sale_customer():
    if not session.get(_SALE_SESSION_CART):
        flash('Your cart is empty. Please add items first.', 'warning')
        return redirect(url_for('parts_bp.sell'))

    customers = Customer.query.filter_by(
        tenant_id=current_user.tenant_id
    ).order_by(Customer.name).all()

    if request.method == 'POST':
        ctype = request.form.get('customer_type', 'existing')
        if ctype == 'walkin':
            cname = request.form.get('customer_name', '').strip()
            session[_SALE_SESSION_CUSTOMER] = {'type': 'walkin', 'customer_name': cname or 'Walk-in Customer', 'customer_id': None}
        else:
            cid_raw = request.form.get('customer_id', '').strip()
            if not cid_raw:
                flash('Please select a customer or choose walk-in.', 'warning')
                return render_template('parts/sale_customer.html', customers=customers, cart=session[_SALE_SESSION_CART])
            cid = int(cid_raw)
            c = Customer.query.filter_by(id=cid, tenant_id=current_user.tenant_id).first_or_404()
            session[_SALE_SESSION_CUSTOMER] = {'type': 'existing', 'customer_id': c.id, 'customer_name': c.name}
        return redirect(url_for('parts_bp.sale_invoice_type'))

    return render_template('parts/sale_customer.html',
                           customers=customers,
                           cart=session.get(_SALE_SESSION_CART, []))


# ── Step 3: Invoice Type ──────────────────────────────────────────────────────

@parts_bp.route('/sale/invoice-type', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def sale_invoice_type():
    if not session.get(_SALE_SESSION_CART):
        return redirect(url_for('parts_bp.sell'))
    if not session.get(_SALE_SESSION_CUSTOMER):
        return redirect(url_for('parts_bp.sale_customer'))

    if request.method == 'POST':
        inv_type = request.form.get('invoice_type', 'standalone')
        linked_sale_id = None
        if inv_type == 'attached':
            sid_raw = request.form.get('linked_sale_id', '').strip()
            if sid_raw:
                linked_sale_id = int(sid_raw)
        session[_SALE_SESSION_INVOICE] = {'type': inv_type, 'sale_id': linked_sale_id}
        return redirect(url_for('parts_bp.sale_payment'))

    return render_template('parts/sale_invoice_type.html',
                           cart=session.get(_SALE_SESSION_CART, []),
                           customer=session.get(_SALE_SESSION_CUSTOMER, {}))


# ── AJAX: search unit sales for "attach to existing" ─────────────────────────

@parts_bp.route('/api/sale-search')
@login_required
@module_required('parts', 'view')
def api_sale_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    # Search invoices by number or customer name
    results = []
    invoices = (
        Invoice.query
        .join(Customer, Invoice.customer_id == Customer.id)
        .filter(
            Invoice.tenant_id == current_user.tenant_id,
            db.or_(
                Invoice.invoice_number.ilike(f'%{q}%'),
                Customer.name.ilike(f'%{q}%'),
            )
        )
        .order_by(Invoice.created_at.desc())
        .limit(10)
        .all()
    )
    for inv in invoices:
        # Get sale transactions linked to this invoice
        sales = SaleTransaction.query.filter_by(invoice_id=inv.id).all()
        results.append({
            'sale_id': sales[0].id if sales else None,
            'invoice_number': inv.invoice_number,
            'customer_name': inv.customer.name,
            'date': inv.created_at.strftime('%d %b %Y') if inv.created_at else '',
            'item_count': len(sales),
        })
    return jsonify(results)


# ── Step 4: Payment ───────────────────────────────────────────────────────────

@parts_bp.route('/sale/payment', methods=['GET', 'POST'])
@login_required
@module_required('parts', 'full')
def sale_payment():
    if not session.get(_SALE_SESSION_CART):
        return redirect(url_for('parts_bp.sell'))
    if not session.get(_SALE_SESSION_CUSTOMER):
        return redirect(url_for('parts_bp.sale_customer'))

    cart = session[_SALE_SESSION_CART]
    customer_data = session[_SALE_SESSION_CUSTOMER]
    invoice_data = session.get(_SALE_SESSION_INVOICE, {'type': 'standalone', 'sale_id': None})

    subtotal = sum(item['subtotal'] for item in cart)

    # Load VAT rate from tenant settings (same logic as single-step sell())
    _settings = {s.key: s.value for s in TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()}
    _vat_rate = float(_settings.get('vat_rate') or '5')

    if request.method == 'POST':
        method = request.form.get('payment_method', 'cash')
        notes = request.form.get('notes', '').strip()
        vat_applied = request.form.get('vat_applied', 'false') == 'true'
        tax = round(subtotal * _vat_rate / 100, 2) if vat_applied else 0
        total_amount = subtotal + tax

        # ── Process the sale ───────────────────────────────────────────────────
        status = 'pending' if method == 'credit' else 'paid'
        now = get_now_for_tenant()
        invoice_number = generate_part_invoice_number(current_user.tenant_id)

        txn = PartSaleTransaction(
            invoice_number=invoice_number,
            customer_id=customer_data.get('customer_id'),
            customer_name=customer_data.get('customer_name') if not customer_data.get('customer_id') else None,
            sale_id=invoice_data.get('sale_id'),
            payment_method=method,
            payment_status=status,
            subtotal=subtotal,
            tax=tax,
            total_amount=total_amount,
            notes=notes or None,
            sold_by=current_user.id,
            sold_at=now,
            tenant_id=current_user.tenant_id,
        )
        db.session.add(txn)
        db.session.flush()  # get txn.id

        affected_part_ids = []
        for item in cart:
            stock_row = PartStock.query.filter_by(
                part_id=item['part_id'],
                location_id=item['location_id'],
                bin_id=item['bin_id'],
            ).first()
            available = stock_row.quantity if stock_row else 0
            if available < item['quantity']:
                db.session.rollback()
                flash(f"{item['part_name']}: stock changed — only {available} available. Please review your cart.", 'danger')
                return redirect(url_for('parts_bp.sell', resume='1'))

            stock_row.quantity -= item['quantity']

            db.session.add(PartSaleItem(
                transaction_id=txn.id,
                part_id=item['part_id'],
                bin_id=item['bin_id'],
                location_id=item['location_id'],
                quantity=item['quantity'],
                unit_price=item['unit_price'],
                subtotal=item['subtotal'],
                tenant_id=current_user.tenant_id,
            ))
            db.session.add(PartMovement(
                part_id=item['part_id'],
                from_location_id=item['location_id'],
                from_bin_id=item['bin_id'],
                quantity=item['quantity'],
                movement_type='sale',
                note=f'Sale {invoice_number}',
                user_id=current_user.id,
            ))
            affected_part_ids.append(item['part_id'])

        # Credit balance
        if method == 'credit' and customer_data.get('customer_id'):
            c = db.session.get(Customer, customer_data['customer_id'])
            if c:
                c.parts_balance = float(c.parts_balance or 0) + total_amount

        db.session.commit()

        # Clear session
        session.pop(_SALE_SESSION_CART, None)
        session.pop(_SALE_SESSION_CUSTOMER, None)
        session.pop(_SALE_SESSION_INVOICE, None)

        maybe_send_low_stock_email(current_user.tenant_id)
        generate_inv = request.form.get('generate_invoice', 'yes')
        flash(f'Sale {invoice_number} completed.', 'success')
        if generate_inv == 'no':
            return redirect(url_for('parts_bp.parts_list'))
        return redirect(url_for('parts_bp.sale_detail', txn_id=txn.id))

    return render_template('parts/sale_payment.html',
                           cart=cart,
                           customer=customer_data,
                           invoice_data=invoice_data,
                           subtotal=subtotal,
                           vat_rate=_vat_rate)


# ── Sale detail / success ─────────────────────────────────────────────────────

@parts_bp.route('/sale/<int:txn_id>')
@login_required
@module_required('parts', 'view')
def sale_detail(txn_id):
    txn = PartSaleTransaction.query.filter_by(
        id=txn_id, tenant_id=current_user.tenant_id
    ).first_or_404()
    settings = {s.key: s.value for s in TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()}
    return render_template('parts/sale_detail.html', txn=txn, settings=settings)


# ── Record payment (credit → paid) ───────────────────────────────────────────

@parts_bp.route('/sale/<int:txn_id>/pay', methods=['POST'])
@login_required
@module_required('parts', 'full')
def sale_pay(txn_id):
    txn = PartSaleTransaction.query.filter_by(
        id=txn_id, tenant_id=current_user.tenant_id
    ).first_or_404()
    if txn.payment_status == 'paid':
        flash('Already marked as paid.', 'info')
        return redirect(url_for('parts_bp.sale_detail', txn_id=txn_id))

    txn.payment_status = 'paid'
    # Deduct from customer credit balance
    if txn.customer_id:
        c = db.session.get(Customer, txn.customer_id)
        if c:
            c.parts_balance = max(0, float(c.parts_balance or 0) - float(txn.total_amount))
    db.session.commit()
    flash('Payment recorded.', 'success')
    return redirect(url_for('parts_bp.sale_detail', txn_id=txn_id))


# ── PDF invoice ───────────────────────────────────────────────────────────────

@parts_bp.route('/sale/<int:txn_id>/invoice')
@login_required
@module_required('parts', 'view')
def sale_invoice_pdf(txn_id):
    from flask import make_response
    from weasyprint import HTML as WeasyHTML
    txn = PartSaleTransaction.query.filter_by(
        id=txn_id, tenant_id=current_user.tenant_id
    ).first_or_404()
    settings = {s.key: s.value for s in TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()}
    html = render_template('parts/sale_invoice_pdf.html', txn=txn, settings=settings,
                           printed_time=get_now_for_tenant().strftime('%d-%b-%Y %H:%M'))
    pdf_bytes = WeasyHTML(string=html, base_url=request.host_url).write_pdf()
    resp = make_response(pdf_bytes)
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = f'inline; filename={txn.invoice_number}.pdf'
    return resp


# ── Sales history list ────────────────────────────────────────────────────────

@parts_bp.route('/sales')
@login_required
@module_required('parts', 'view')
def sales_list():
    # Filters
    status_filter   = request.args.get('status', '')
    customer_filter = request.args.get('customer_id', type=int)
    date_from       = request.args.get('date_from', '')
    date_to         = request.args.get('date_to', '')
    search          = request.args.get('search', '').strip()

    q = PartSaleTransaction.query.filter_by(tenant_id=current_user.tenant_id)
    if status_filter:
        q = q.filter(PartSaleTransaction.payment_status == status_filter)
    if customer_filter:
        q = q.filter(PartSaleTransaction.customer_id == customer_filter)
    if search:
        q = q.filter(PartSaleTransaction.invoice_number.ilike(f'%{search}%'))
    if date_from:
        try:
            from datetime import datetime as dt
            q = q.filter(PartSaleTransaction.sold_at >= dt.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import datetime as dt
            q = q.filter(PartSaleTransaction.sold_at <= dt.strptime(date_to + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            pass

    transactions = q.order_by(PartSaleTransaction.sold_at.desc()).all()
    customers = Customer.query.filter_by(tenant_id=current_user.tenant_id).order_by(Customer.name).all()

    # CSV export
    if request.args.get('export') == 'csv':
        import csv
        from io import StringIO
        from flask import make_response
        out = StringIO()
        w = csv.writer(out)
        w.writerow(['Invoice No', 'Date', 'Customer', 'Items', 'Subtotal', 'Total', 'Payment Method', 'Status'])
        for t in transactions:
            cname = t.customer.name if t.customer else (t.customer_name or 'Walk-in')
            w.writerow([
                t.invoice_number,
                t.sold_at.strftime('%Y-%m-%d %H:%M') if t.sold_at else '',
                cname,
                len(t.line_items),
                float(t.subtotal),
                float(t.total_amount),
                t.payment_method,
                t.payment_status,
            ])
        resp = make_response(out.getvalue())
        resp.headers['Content-Type'] = 'text/csv'
        resp.headers['Content-Disposition'] = 'attachment; filename=parts_sales.csv'
        return resp

    return render_template('parts/sales_list.html',
                           transactions=transactions,
                           customers=customers,
                           status_filter=status_filter,
                           customer_filter=customer_filter,
                           date_from=date_from,
                           date_to=date_to,
                           search=search)


# ── Parts AJAX search (for parts_list live search + dropdowns) ────────────────

@parts_bp.route('/api/search')
@login_required
@module_required('parts', 'view')
def api_parts_search():
    _require_parts_module()
    q          = request.args.get('q', '').strip()
    type_filter   = request.args.get('type', '').strip()    # part_type string | ''
    status_filter = request.args.get('status', '').strip()  # 'in_stock' | 'low_stock' | 'out_of_stock' | ''
    # legacy 'filter' param kept for backward compat
    legacy = request.args.get('filter', '').strip()
    if legacy and not type_filter and not status_filter:
        if legacy in ('low_stock', 'out_of_stock', 'in_stock'):
            status_filter = legacy
        else:
            type_filter = legacy

    base_q = Part.query.filter_by(tenant_id=current_user.tenant_id)
    if q:
        base_q = (
            base_q
            .outerjoin(Vendor, Part.vendor_id == Vendor.id)
            .filter(db.or_(
                Part.part_number.ilike(f'%{q}%'),
                Part.name.ilike(f'%{q}%'),
                Part.barcode.ilike(f'%{q}%'),
                Part.description.ilike(f'%{q}%'),
                Part.vendor.ilike(f'%{q}%'),
                Vendor.name.ilike(f'%{q}%'),
            ))
        )
    if type_filter:
        base_q = base_q.filter(Part.part_type == type_filter)

    parts = base_q.order_by(Part.name).all()
    _attach_stock(parts)

    results = []
    for part in parts:
        total  = part._current_stock
        mn     = part.min_stock or 1
        if total == 0:
            status = 'out_of_stock'
        elif total < mn:
            status = 'low_stock'
        else:
            status = 'in_stock'

        if status_filter and status != status_filter:
            continue

        scan_q = part.barcode or part.part_number
        results.append(dict(
            id=part.id,
            name=part.name,
            part_number=part.part_number,
            part_type=part.part_type or '',
            vendor=_vendor_display(part),
            barcode=part.barcode or '',
            total_stock=total,
            min_stock=mn,
            price=part.price,
            value=round(total * (part.price or 0), 2),
            status=status,
            url_detail=url_for('parts_bp.part_detail', part_id=part.id),
            url_scan=url_for('parts_bp.parts_scan') + '?q=' + scan_q,
            url_stock_in=url_for('parts_bp.stock_in', part_id=part.id),
            url_stock_out=url_for('parts_bp.stock_out') + f'?part_id={part.id}',
            url_consume=url_for('parts_bp.consume') + f'?part_id={part.id}',
            url_sell=url_for('parts_bp.sell', part_id=part.id),
            url_history=url_for('parts_bp.part_history', part_id=part.id),
            url_label=url_for('parts_bp.part_label', part_id=part.id),
            url_edit=url_for('parts_bp.edit_part', part_id=part.id),
            url_delete=url_for('parts_bp.delete_part', part_id=part.id),
        ))

    return jsonify(
        parts=results,
        total=len(results),
        total_qty=sum(r['total_stock'] for r in results),
        total_value=round(sum(r['value'] for r in results), 2),
    )


# ── Single barcode label page ─────────────────────────────────────────────────

@parts_bp.route('/<int:part_id>/label')
@login_required
@module_required('parts', 'view')
def part_label(part_id):
    _require_parts_module()
    part = Part.query.filter_by(
        id=part_id, tenant_id=current_user.tenant_id
    ).first_or_404()
    if not part.barcode:
        flash('This part has no barcode assigned. Edit the part to add one.', 'warning')
        return redirect(url_for('parts_bp.part_detail', part_id=part_id))
    return render_template('parts/label.html', part=part)


# ── Bulk label print page ─────────────────────────────────────────────────────

@parts_bp.route('/labels')
@login_required
@module_required('parts', 'view')
def parts_labels_bulk():
    _require_parts_module()
    ids_str = request.args.get('ids', '')
    ids = [int(i) for i in ids_str.split(',') if i.strip().isdigit()]
    if not ids:
        flash('No parts selected for printing.', 'warning')
        return redirect(url_for('parts_bp.parts_list'))

    parts = (
        Part.query
        .filter(
            Part.id.in_(ids),
            Part.tenant_id == current_user.tenant_id,
            Part.barcode != None,
            Part.barcode != '',
        )
        .order_by(Part.name)
        .all()
    )
    if not parts:
        flash('None of the selected parts have barcodes assigned.', 'warning')
        return redirect(url_for('parts_bp.parts_list'))

    return render_template('parts/labels_bulk.html', parts=parts)


# ── Per-part stock JSON (powers inline assign-bin modals) ─────────────────────

@parts_bp.route('/<int:part_id>/stock_json')
@login_required
@module_required('parts', 'view')
def part_stock_json(part_id):
    part = Part.query.filter_by(
        id=part_id, tenant_id=current_user.tenant_id
    ).first_or_404()
    stocks = []
    for ps in PartStock.query.filter_by(part_id=part_id).all():
        if ps.quantity > 0:
            stocks.append({
                'location_id':   ps.location_id,
                'location_name': ps.location.name,
                'bin_id':        ps.bin_id,
                'bin_name':      ps.bin.name if ps.bin else None,
                'quantity':      ps.quantity,
            })
    return jsonify(stocks=stocks, part_name=part.name)


# ── Bin management overview ────────────────────────────────────────────────────

@parts_bp.route('/bin_management')
@login_required
@module_required('parts', 'view')
def bin_management():
    _require_parts_module()
    unassigned_only = request.args.get('unassigned') == '1'

    q = (
        PartStock.query
        .join(Part, PartStock.part_id == Part.id)
        .filter(
            Part.tenant_id == current_user.tenant_id,
            PartStock.quantity > 0,
        )
    )
    if unassigned_only:
        q = q.filter(PartStock.bin_id.is_(None))

    stocks = q.order_by(Part.name).all()
    locations = Location.query.filter_by(
        tenant_id=current_user.tenant_id
    ).order_by(Location.name).all()
    unassigned_count = (
        PartStock.query
        .join(Part, PartStock.part_id == Part.id)
        .filter(
            Part.tenant_id == current_user.tenant_id,
            PartStock.quantity > 0,
            PartStock.bin_id.is_(None),
        )
        .count()
    )

    return render_template(
        'parts/bin_management.html',
        stocks=stocks,
        locations=locations,
        unassigned_only=unassigned_only,
        total=len(stocks),
        unassigned_count=unassigned_count,
    )


# ── Parts scanner page ────────────────────────────────────────────────────────

@parts_bp.route('/scan')
@login_required
@module_required('parts', 'view')
def parts_scan():
    _require_parts_module()
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).order_by(Location.name).all()
    prefill = request.args.get('q', '').strip()
    return render_template('parts/scanner.html', locations=locations, prefill=prefill)


# ── Parts AJAX lookup (barcode / part_number / name) ─────────────────────────

@parts_bp.route('/api/lookup')
@login_required
@module_required('parts', 'view')
def api_part_lookup():
    _require_parts_module()
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify(found=False)

    # Search by barcode (exact), then part_number (exact), then name (ilike)
    part = (
        Part.query
        .filter_by(tenant_id=current_user.tenant_id, barcode=q)
        .first()
    )
    if not part:
        part = (
            Part.query
            .filter_by(tenant_id=current_user.tenant_id, part_number=q)
            .first()
        )
    if not part:
        part = (
            Part.query
            .filter_by(tenant_id=current_user.tenant_id)
            .filter(Part.name.ilike(f'%{q}%'))
            .first()
        )
    if not part:
        return jsonify(found=False)

    _attach_stock([part])
    total_stock = part._current_stock
    low_stock   = total_stock < (part.min_stock or 1)

    stocks = [
        {
            'location_id':   s.location_id,
            'location_name': s.location.name,
            'bin_id':        s.bin_id,
            'bin_name':      s.bin.name if s.bin else None,
            'quantity':      s.quantity,
        }
        for s in part.stocks
    ]

    recent = (
        PartMovement.query
        .filter_by(part_id=part.id)
        .order_by(PartMovement.created_at.desc())
        .limit(5)
        .all()
    )
    movements = []
    for m in recent:
        loc_parts = []
        if m.from_location:
            loc_parts.append(m.from_location.name)
        if m.to_location:
            loc_parts.append('→ ' + m.to_location.name)
        movements.append({
            'date':          m.created_at.strftime('%d %b %Y %H:%M') if m.created_at else '',
            'type':          m.movement_type,
            'qty':           m.quantity,
            'location_str':  ' '.join(loc_parts) or '—',
            'user':          m.user.username if m.user else '—',
            'note':          m.note or '',
        })

    return jsonify(
        found=True,
        part=dict(
            id=part.id,
            name=part.name,
            part_number=part.part_number,
            part_type=part.part_type or '',
            vendor=_vendor_display(part),
            barcode=part.barcode or '',
            min_stock=part.min_stock or 1,
            price=part.price,
            total_stock=total_stock,
            low_stock=low_stock,
            stocks=stocks,
            recent_movements=movements,
            url_detail=url_for('parts_bp.part_detail', part_id=part.id),
            url_stock_in=url_for('parts_bp.stock_in', part_id=part.id),
            url_stock_out=url_for('parts_bp.stock_out', part_id=part.id),
            url_sell=url_for('parts_bp.sell', part_id=part.id),
            url_use=url_for('parts_bp.use', part_id=part.id),
            url_transfer=url_for('parts_bp.transfer', part_id=part.id),
        ),
    )


# ── part history CSV export ───────────────────────────────────────────────────

@parts_bp.route('/<int:part_id>/history/export')
@login_required
@module_required('parts', 'view')
def part_history_export(part_id):
    import io, csv
    from flask import send_file
    part = Part.query.filter_by(
        id=part_id, tenant_id=current_user.tenant_id
    ).first_or_404()

    movements = (
        PartMovement.query
        .filter_by(part_id=part_id)
        .order_by(PartMovement.created_at.asc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Date', 'Type', 'Qty',
        'From Location', 'From Bin', 'To Location', 'To Bin',
        'User', 'Note', 'Linked Unit',
    ])
    for m in movements:
        writer.writerow([
            m.created_at.strftime('%Y-%m-%d %H:%M') if m.created_at else '',
            m.movement_type or '',
            m.quantity,
            m.from_location.name if m.from_location else '',
            m.from_bin.name if m.from_bin else '',
            m.to_location.name if m.to_location else '',
            m.to_bin.name if m.to_bin else '',
            m.user.username if m.user else '',
            m.note or '',
            m.instance.serial if m.instance else '',
        ])
    output.seek(0)
    filename = f'part_{part.part_number}_history.csv'.replace('/', '-')
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename,
    )

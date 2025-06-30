from flask import jsonify
from flask_login import current_user
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.exc import IntegrityError
from ..models import db, Part, PartStock, PartMovement, Location

parts_bp = Blueprint('parts_bp', __name__, url_prefix='/parts')

@parts_bp.route('/')
@login_required
def parts_list():
    search = request.args.get('search', '').strip()
    query = Part.query.filter_by(tenant_id=current_user.tenant_id)

    if search:
        query = query.filter(
            (Part.part_number.ilike(f"%{search}%")) |
            (Part.name.ilike(f"%{search}%")) |
            (Part.vendor.ilike(f"%{search}%"))
        )

    parts = query.all()
    total_parts = len(parts)
    total_quantity = sum(sum(stock.quantity for stock in p.stocks) for p in parts)

    return render_template(
        'parts/parts_list.html',
        parts=parts,
        total_parts=total_parts,
        total_quantity=total_quantity,
        search=search
    )

@parts_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_part():
    if request.method == 'POST':
        part_number = request.form['part_number']
        name = request.form['name']
        part_type = request.form['part_type']
        vendor = request.form.get('vendor')
        min_stock = request.form.get('min_stock', 1)
        price = request.form.get('price', 0.0)
        description = request.form.get('description', '')

        # Prevent duplicate part number
        if Part.query.filter_by(part_number=part_number, tenant_id=current_user.tenant_id).first():
            flash('Part number already exists. Please use a unique part number.', 'danger')
            return redirect(url_for('parts_bp.add_part'))

        part = Part(
            part_number=part_number,
            name=name,
            part_type=part_type,
            vendor=vendor,
            min_stock=int(min_stock),
            price=float(price),
            description=description,
            tenant_id=current_user.tenant_id,
        )
        db.session.add(part)
        try:
            db.session.commit()
            flash('Part added successfully!', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Database error: Part number already exists.', 'danger')
        return redirect(url_for('parts_bp.parts_list'))
    vendors = db.session.query(Part.vendor).filter(
        Part.vendor.isnot(None),
        Part.vendor != '',
        Part.tenant_id == current_user.tenant_id
    ).distinct().all()
    return render_template('parts/add_part.html', vendors=[v[0] for v in vendors])

@parts_bp.route('/stock_in', methods=['GET', 'POST'])
@login_required
def stock_in():
    search_query = request.args.get('q', '').strip()
    if search_query:
        # Simple search: by part number or name
        parts = Part.query.filter(
            (Part.tenant_id == current_user.tenant_id) &
            ((Part.part_number.ilike(f"%{search_query}%")) | (Part.name.ilike(f"%{search_query}%")))
        ).all()
    else:
        parts = Part.query.filter_by(tenant_id=current_user.tenant_id).all()
    locations = Location.query.filter_by(tenant_id=current_user.tenant_id).all()
    if request.method == 'POST':
        part_id = request.form['part_id']
        location_id = request.form['location_id']
        quantity = int(request.form['quantity'])
        note = request.form.get('note', '')

        # Find or create PartStock entry
        part_stock = PartStock.query.join(Part).filter(
            PartStock.part_id == part_id,
            Part.tenant_id == current_user.tenant_id,
            PartStock.location_id == location_id
        ).first()
        if not part_stock:
            part_stock = PartStock(part_id=part_id, location_id=location_id, quantity=0)
            db.session.add(part_stock)
        part_stock.quantity += quantity

        # Log the movement
        movement = PartMovement(
            part_id=part_id,
            to_location_id=location_id,
            quantity=quantity,
            movement_type='stock_in',
            note=note,
            user_id=current_user.id
        )
        db.session.add(movement)
        db.session.commit()
        flash('Stock updated successfully!', 'success')
        return redirect(url_for('parts_bp.parts_list'))
    part_summaries = []
    for part in parts:
        total_qty = sum(s.quantity for s in part.stocks)
        part_summaries.append({
            'id': part.id,
            'part_number': part.part_number,
            'name': part.name,
            'total_quantity': total_qty
        })
    return render_template('parts/stock_in.html', parts=parts, part_summaries=part_summaries, locations=locations, search_query=search_query)

@parts_bp.route('/ajax_add', methods=['POST'])
@login_required
def ajax_add_part():
    part_number = request.form['part_number']
    name = request.form['name']
    part_type = request.form.get('part_type', '')
    vendor = request.form.get('vendor', '')
    min_stock = request.form.get('min_stock', 1)
    price = request.form.get('price', 0.0)
    description = request.form.get('description', '')

    # Check for duplicate
    if Part.query.filter_by(part_number=part_number, tenant_id=current_user.tenant_id).first():
        return jsonify(success=False, message='Part number already exists.')

    part = Part(
        part_number=part_number,
        name=name,
        part_type=part_type,
        vendor=vendor,
        min_stock=int(min_stock),
        price=float(price),
        description=description,
        tenant_id=current_user.tenant_id,
    )
    db.session.add(part)
    try:
        db.session.commit()
        return jsonify(success=True, part_id=part.id, part_number=part.part_number, name=part.name)
    except IntegrityError:
        db.session.rollback()
        return jsonify(success=False, message='Database error: could not add part.')
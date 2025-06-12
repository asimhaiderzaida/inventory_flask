from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required
from ..models import db, Customer, ProductInstance, CustomerOrderTracking
from datetime import datetime

order_bp = Blueprint('order_bp', __name__)

@order_bp.route('/customer_orders')
@login_required
def customer_orders():
    customer_id = request.args.get('customer_id')
    query = CustomerOrderTracking.query
    if customer_id:
        query = query.filter_by(customer_id=customer_id)

    orders = query.all()
    customers = Customer.query.all()

    return render_template('customer_orders.html',
                           orders=orders,
                           customers=customers,
                           selected_customer_id=customer_id)

@order_bp.route('/customer_orders/reserve', methods=['GET', 'POST'])
@login_required
def reserve_product():
    if 'pending_reserve_serials' not in session:
        session['pending_reserve_serials'] = []
    if 'pending_reserve_customer_id' not in session:
        session['pending_reserve_customer_id'] = ""
    customers = Customer.query.all()
    available_instances = ProductInstance.query.filter_by(is_sold=False).all()
    all_serials = {inst.serial_number: inst for inst in available_instances}

    if request.method == 'POST':
        # Only update customer_id from form if present
        session['pending_reserve_customer_id'] = request.form.get('customer_id') or session.get('pending_reserve_customer_id', '')
        session.modified = True

        action = request.form.get('action')
        if action == 'reset_batch':
            # Reset batch: clear customer and serials only
            session['pending_reserve_serials'] = []
            session['pending_reserve_customer_id'] = ""
            session.modified = True
            return redirect(url_for('order_bp.reserve_product'))

        if action == 'add':
            # Strictly require customer before adding a serial
            if not session['pending_reserve_customer_id']:
                flash("Please select customer before adding a serial.", "danger")
            else:
                serial = request.form.get('serial_input', '').strip()
                if not serial:
                    flash("Please enter or scan a serial.", "warning")
                elif serial not in all_serials:
                    flash(f"Serial {serial} not found in available stock.", "danger")
                elif serial in session['pending_reserve_serials']:
                    flash(f"Serial {serial} already added for reservation.", "warning")
                else:
                    session['pending_reserve_serials'].append(serial)
                    session.modified = True
        elif action == 'remove':
            serial = request.form.get('remove_serial')
            if serial in session['pending_reserve_serials']:
                session['pending_reserve_serials'].remove(serial)
                session.modified = True
        elif action == 'confirm':
            customer_id = session.get('pending_reserve_customer_id', '')
            if not customer_id or not session['pending_reserve_serials']:
                flash("Please select a customer and add at least one serial.", "danger")
            else:
                for serial in session['pending_reserve_serials']:
                    instance = all_serials.get(serial)
                    if instance:
                        order = CustomerOrderTracking(
                            customer_id=customer_id,
                            product_instance_id=instance.id,
                            status='reserved',
                            process_stage=None,
                            team_assigned=None
                        )
                        db.session.add(order)
                db.session.commit()
                flash(f"✅ Reserved {len(session['pending_reserve_serials'])} unit(s) for customer.", "success")
                session['pending_reserve_serials'] = []
                session['pending_reserve_customer_id'] = ""
                session.modified = True
                return redirect(url_for('order_bp.reserve_product'))

    # Build preview list
    preview_instances = [all_serials[s] for s in session['pending_reserve_serials'] if s in all_serials]

    return render_template('reserve_product.html',
        customers=customers,
        instances=available_instances,
        preview_instances=preview_instances,
        pending_serials=session['pending_reserve_serials'],
        selected_customer_id=session.get('pending_reserve_customer_id', ''))

@order_bp.route('/customer_orders/mark_delivered/<int:order_id>', methods=['POST'])
@login_required
def mark_delivered(order_id):
    order = CustomerOrderTracking.query.get(order_id)
    if order:
        order.status = 'delivered'
        order.delivered_date = datetime.utcnow()
        db.session.commit()
        flash(f"✅ Serial {order.product_instance.serial_number} marked as delivered.", "success")
    else:
        flash("❌ Order not found.", "error")

    return redirect(url_for('order_bp.customer_orders'))


# --- Batch Move Route with Process Logging ---
from flask_login import current_user
from inventory_flask_app.models import ProductProcessLog

@order_bp.route('/customer_orders/batch_move', methods=['POST'])
@login_required
def batch_move():
    serials = request.form.getlist('serials')  # List of serial numbers to move
    to_stage = request.form.get('to_stage')
    to_team = request.form.get('to_team')

    moved_count = 0
    for serial in serials:
        order = CustomerOrderTracking.query.join(ProductInstance).filter(ProductInstance.serial_number == serial).first()
        if order:
            from_stage = order.process_stage
            from_team = order.team_assigned

            # Update order with new stage/team
            order.process_stage = to_stage
            order.team_assigned = to_team

            # Log the move
            log_entry = ProductProcessLog(
                product_instance_id=order.product_instance_id,
                from_stage=from_stage,
                to_stage=to_stage,
                from_team=from_team,
                to_team=to_team,
                moved_by=current_user.id,
                moved_at=datetime.utcnow()
            )
            db.session.add(log_entry)
            moved_count += 1
    db.session.commit()

    flash(f"✅ {moved_count} unit(s) moved to stage '{to_stage}' and team '{to_team}'.", "success")
    return redirect(url_for('order_bp.customer_orders'))


# --- Batch Delivered Route ---
@order_bp.route('/customer_orders/batch_delivered', methods=['POST'])
@login_required
def batch_delivered():
    serials = request.form.getlist('serials')
    if not serials:
        flash("No units selected.", "warning")
        return redirect(url_for('order_bp.customer_orders'))

    updated = 0
    for serial in serials:
        order = CustomerOrderTracking.query.join(ProductInstance).filter(ProductInstance.serial_number == serial).first()
        if order and order.status != 'delivered':
            order.status = 'delivered'
            order.process_stage = 'delivered'
            order.delivered_date = datetime.utcnow()
            db.session.commit()
            updated += 1

    flash(f"✅ {updated} unit(s) marked as delivered.", "success")
    return redirect(url_for('order_bp.customer_orders'))

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required
from ..models import db, Customer, ProductInstance, CustomerOrderTracking, Product
from datetime import datetime
from inventory_flask_app.utils import get_now_for_tenant
from flask_login import current_user
from inventory_flask_app.models import TenantSettings
from sqlalchemy import or_
from inventory_flask_app import csrf

order_bp = Blueprint('order_bp', __name__)

@csrf.exempt
@order_bp.route('/customer_orders')
@login_required
def customer_orders():
    customer_id = request.args.get('customer_id')
    show_completed = request.args.get('show_completed')
    query = CustomerOrderTracking.query.join(Customer).filter(Customer.tenant_id == current_user.tenant_id)
    if not show_completed:
        query = query.join(ProductInstance).filter(ProductInstance.is_sold == False)
    if customer_id:
        query = query.filter(CustomerOrderTracking.customer_id == customer_id)

    orders = query.all()
    customers = Customer.query.filter_by(tenant_id=current_user.tenant_id).all()

    return render_template(
        'customer_orders.html',
        orders=orders,
        customers=customers,
        selected_customer_id=customer_id)

# --- Pending Orders Route ---
@csrf.exempt
@order_bp.route('/orders/pending')
@login_required
def pending_orders():
    query = CustomerOrderTracking.query \
        .join(Customer) \
        .join(ProductInstance) \
        .join(Product) \
        .filter(
            Customer.tenant_id == current_user.tenant_id,
            CustomerOrderTracking.status != 'delivered'
        )

    orders = query.order_by(CustomerOrderTracking.created_at.desc()).all()
    customers = Customer.query.filter_by(tenant_id=current_user.tenant_id).all()

    return render_template(
        'customer_orders.html',
        orders=orders,
        customers=customers,
        selected_customer_id=None,
        pending_only=True
    )

@csrf.exempt
@order_bp.route('/customer_orders/reserve', methods=['GET', 'POST'])
@login_required
def reserve_product():
    if 'pending_reserve_serials' not in session:
        session['pending_reserve_serials'] = []
    if 'pending_reserve_customer_id' not in session:
        session['pending_reserve_customer_id'] = ""
    customers = Customer.query.filter_by(tenant_id=current_user.tenant_id).all()
    available_instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.is_sold == False
    ).all()

    serial_map = {}
    for inst in available_instances:
        if inst.serial:
            serial_map[inst.serial] = inst
        if inst.asset:
            serial_map[inst.asset] = inst

    if request.method == 'POST':
        session['pending_reserve_customer_id'] = request.form.get('customer_id') or session.get('pending_reserve_customer_id', '')
        session.modified = True

        action = request.form.get('action')
        if action == 'reset_batch':
            session['pending_reserve_serials'] = []
            session['pending_reserve_customer_id'] = ""
            session.modified = True
            return redirect(url_for('order_bp.reserve_product'))

        if action == 'add':
            if not session['pending_reserve_customer_id']:
                flash("Please select customer before adding a serial.", "danger")
            else:
                serial = request.form.get('serial_input', '').strip()
                asset = request.form.get('asset')
                if not serial:
                    flash("Please enter or scan a serial.", "warning")
                elif serial not in serial_map:
                    flash(f"Serial {serial} not found in available stock.", "danger")
                elif serial in session['pending_reserve_serials']:
                    flash(f"Serial {serial} already added for reservation.", "warning")
                elif (
                    CustomerOrderTracking.query.join(ProductInstance).filter(
                        or_(
                            ProductInstance.serial == serial,
                            ProductInstance.asset == asset
                        ),
                        CustomerOrderTracking.status == 'reserved'
                    ).first()
                ):
                    flash(f"Serial {serial} is already reserved by another customer.", "danger")
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
                    instance = serial_map.get(serial)
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

    preview_instances = [serial_map[s] for s in session['pending_reserve_serials'] if s in serial_map]

    return render_template(
        'reserve_product.html',
        customers=customers,
        instances=available_instances,
        preview_instances=preview_instances,
        pending_serials=session['pending_reserve_serials'],
        selected_customer_id=session.get('pending_reserve_customer_id', '')
    )

@csrf.exempt
@order_bp.route('/customer_orders/mark_delivered/<int:order_id>', methods=['POST'])
@login_required
def mark_delivered(order_id):
    order = CustomerOrderTracking.query.join(ProductInstance).join(Product).filter(
        CustomerOrderTracking.id == order_id,
        Product.tenant_id == current_user.tenant_id
    ).first()
    if order:
        from_stage = order.process_stage
        from_team = order.team_assigned

        order.status = 'delivered'
        order.delivered_date = get_now_for_tenant()
        order.process_stage = 'delivered'

        # Log the delivery move
        log_entry = ProductProcessLog(
            product_instance_id=order.product_instance_id,
            from_stage=from_stage,
            to_stage='delivered',
            from_team=from_team,
            to_team=None,
            moved_by=current_user.id,
            moved_at=get_now_for_tenant(),
            action='mark_delivered'
        )
        db.session.add(log_entry)

        db.session.commit()
        flash(f"✅ Serial {order.product_instance.serial} marked as delivered.", "success")
    else:
        flash("❌ Order not found.", "error")

    return redirect(url_for('order_bp.customer_orders'))


# --- Batch Move Route with Process Logging ---
from flask_login import current_user
from inventory_flask_app.models import ProductProcessLog

@csrf.exempt
@order_bp.route('/customer_orders/batch_move', methods=['POST'])
@login_required
def batch_move():
    serials = request.form.getlist('serials')  # List of serial numbers to move
    to_stage = request.form.get('to_stage')
    to_team = request.form.get('to_team')

    moved_count = 0
    for serial in serials:
        order = CustomerOrderTracking.query.join(ProductInstance).join(Product).filter(
            or_(
                ProductInstance.serial == serial,
                ProductInstance.asset == serial
            ),
            Product.tenant_id == current_user.tenant_id
        ).first()
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
                moved_at=get_now_for_tenant(),
                action='batch_move'
            )
            db.session.add(log_entry)
            moved_count += 1
    db.session.commit()

    flash(f"✅ {moved_count} unit(s) moved to stage '{to_stage}' and team '{to_team}'.", "success")
    return redirect(url_for('order_bp.customer_orders'))


# --- Batch Delivered Route ---
@csrf.exempt
@order_bp.route('/customer_orders/batch_delivered', methods=['POST'])
@login_required
def batch_delivered():
    serials = request.form.getlist('serials')
    if not serials:
        flash("No units selected.", "warning")
        return redirect(url_for('order_bp.customer_orders'))

    updated = 0
    for serial in serials:
        serial_clean = serial.strip()
        order = CustomerOrderTracking.query.join(ProductInstance).join(Product).filter(
            or_(
                ProductInstance.serial == serial_clean,
                ProductInstance.asset == serial_clean
            ),
            Product.tenant_id == current_user.tenant_id,
            CustomerOrderTracking.status != 'delivered'
        ).first()
        if order:
            from_stage = order.process_stage
            from_team = order.team_assigned

            order.status = 'delivered'
            order.process_stage = 'delivered'
            order.delivered_date = get_now_for_tenant()

            log_entry = ProductProcessLog(
                product_instance_id=order.product_instance_id,
                from_stage=from_stage,
                to_stage='delivered',
                from_team=from_team,
                to_team=None,
                moved_by=current_user.id,
                moved_at=get_now_for_tenant(),
                action='batch_delivered'
            )
            db.session.add(log_entry)
            db.session.commit()
            updated += 1

    flash(f"✅ {updated} unit(s) marked as delivered.", "success")
    return redirect(url_for('order_bp.customer_orders'))


# --- Batch Cancel Reservation Route ---
@csrf.exempt
@order_bp.route('/customer_orders/batch_cancel_reservation', methods=['POST'])
@login_required
def batch_cancel_reservation():
    serials = request.form.getlist('serials')
    if not serials:
        flash("No units selected.", "warning")
        return redirect(url_for('order_bp.customer_orders'))
    canceled = 0
    for serial in serials:
        order = CustomerOrderTracking.query.join(ProductInstance).join(Product).filter(
            or_(
                ProductInstance.serial == serial,
                ProductInstance.asset == serial
            ),
            CustomerOrderTracking.status == 'reserved',
            Product.tenant_id == current_user.tenant_id
        ).first()
        if order:
            from_stage = order.process_stage
            from_team = order.team_assigned

            # Log cancellation
            log_entry = ProductProcessLog(
                product_instance_id=order.product_instance_id,
                from_stage=from_stage,
                to_stage=None,
                from_team=from_team,
                to_team=None,
                moved_by=current_user.id,
                moved_at=get_now_for_tenant(),
                action='cancel_reservation'
            )
            db.session.add(log_entry)

            db.session.delete(order)
            canceled += 1
    db.session.commit()
    flash(f"✅ {canceled} reservation(s) canceled and unit(s) returned to inventory.", "success")
    return redirect(url_for('order_bp.customer_orders'))

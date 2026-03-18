from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from ..models import db, Customer, ProductInstance, CustomerOrderTracking, Product
from inventory_flask_app.models import TenantSettings, ProductProcessLog
from datetime import datetime
from inventory_flask_app.utils import get_now_for_tenant
from inventory_flask_app.utils.mail_utils import send_reservation_confirmation, send_reservation_ready
from inventory_flask_app.utils.utils import is_module_enabled
from sqlalchemy import or_, func
from inventory_flask_app import csrf

order_bp = Blueprint('order_bp', __name__)


def _require_order_module():
    from flask import abort
    if not is_module_enabled('enable_order_module'):
        abort(403)


def _instance_to_unit_dict(instance):
    """Convert a ProductInstance to a unit dict for email formatting."""
    prod = instance.product
    return {
        'serial':    instance.serial,
        'model':     prod.model if prod else '',
        'cpu':       prod.cpu if prod else '',
        'ram':       prod.ram if prod else '',
        'disk1size': prod.disk1size if prod else '',
    }

@order_bp.route('/orders')
@login_required
def orders_index():
    _require_order_module()
    return render_template('orders_index.html')

@order_bp.route('/customer_orders')
@login_required
def customer_orders():
    _require_order_module()
    customer_id = request.args.get('customer_id')
    show_completed = request.args.get('show_completed')
    status_filter = request.args.get('status')  # All | reserved | delivered | cancelled

    query = CustomerOrderTracking.query.join(Customer).filter(
        Customer.tenant_id == current_user.tenant_id
    )

    if status_filter and status_filter != 'all':
        query = query.filter(CustomerOrderTracking.status == status_filter)
    elif not show_completed:
        # Default: only active reservations (hide delivered + cancelled)
        query = query.filter(CustomerOrderTracking.status == 'reserved')

    if customer_id:
        query = query.filter(CustomerOrderTracking.customer_id == customer_id)

    orders = query.order_by(CustomerOrderTracking.reserved_date.desc()).all()
    customers = Customer.query.filter_by(tenant_id=current_user.tenant_id).all()

    # Count per status for tab badges
    base = CustomerOrderTracking.query.join(Customer).filter(
        Customer.tenant_id == current_user.tenant_id
    )
    if customer_id:
        base = base.filter(CustomerOrderTracking.customer_id == customer_id)
    status_counts = {
        'all':       base.count(),
        'reserved':  base.filter(CustomerOrderTracking.status == 'reserved').count(),
        'delivered': base.filter(CustomerOrderTracking.status == 'delivered').count(),
        'cancelled': base.filter(CustomerOrderTracking.status == 'cancelled').count(),
    }

    return render_template(
        'customer_orders.html',
        orders=orders,
        customers=customers,
        selected_customer_id=customer_id,
        active_status=status_filter or ('all' if show_completed else 'reserved'),
        status_counts=status_counts,
    )

# --- Pending Orders Route — redirect to customer_orders with reserved filter ---
@order_bp.route('/orders/pending')
@login_required
def pending_orders():
    return redirect(url_for('order_bp.customer_orders', status='reserved'))

@order_bp.route('/customer_orders/reserve', methods=['GET', 'POST'])
@login_required
def reserve_product():
    _require_order_module()
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
                            team_assigned=None,
                            reserved_by_user_id=current_user.id,
                        )
                        db.session.add(order)
                reserved_instances = [serial_map[s] for s in session['pending_reserve_serials'] if s in serial_map]
                db.session.commit()

                # Send confirmation email (wrapped — never breaks the flow)
                reserved_customer = db.session.get(Customer, customer_id)
                unit_dicts = [_instance_to_unit_dict(i) for i in reserved_instances]
                email_sent = send_reservation_confirmation(
                    reserved_customer, unit_dicts, current_user.tenant_id
                )
                email_note = (
                    f" Confirmation email sent to {reserved_customer.email}."
                    if email_sent else ""
                )
                flash(
                    f"✅ Reserved {len(reserved_instances)} unit(s) for {reserved_customer.name}.{email_note}",
                    "success"
                )
                session['pending_reserve_serials'] = []
                session['pending_reserve_customer_id'] = ""
                session.modified = True
                return redirect(url_for('order_bp.reserve_product'))

    preview_instances = [serial_map[s] for s in session['pending_reserve_serials'] if s in serial_map]
    scanned_count = len(session['pending_reserve_serials'])

    return render_template(
        'reserve_product.html',
        customers=customers,
        instances=available_instances,
        preview_instances=preview_instances,
        pending_serials=session['pending_reserve_serials'],
        selected_customer_id=session.get('pending_reserve_customer_id', ''),
        scanned_count=scanned_count
    )

@order_bp.route('/customer_orders/mark_delivered/<int:order_id>', methods=['POST'])
@login_required
def mark_delivered(order_id):
    order = CustomerOrderTracking.query.join(ProductInstance).join(Product).filter(
        CustomerOrderTracking.id == order_id,
        Product.tenant_id == current_user.tenant_id
    ).first()
    if order:
        if order.status == 'delivered':
            flash("Unit already delivered.", "info")
            return redirect(url_for('order_bp.customer_orders'))
        from_stage = order.process_stage
        from_team = order.team_assigned

        order.status = 'delivered'
        order.delivered_date = get_now_for_tenant()
        order.process_stage = 'delivered'
        order.delivered_by_user_id = current_user.id

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

        # Send "ready for pickup" email (wrapped — never breaks the flow)
        unit_dicts = [_instance_to_unit_dict(order.product_instance)]
        email_sent = send_reservation_ready(order.customer, unit_dicts, current_user.tenant_id)
        email_note = f" Ready email sent to {order.customer.email}." if email_sent else ""
        flash(f"✅ {order.product_instance.serial} marked as ready for pickup.{email_note}", "success")

    elif order and order.status == 'delivered':
        flash("Unit is already marked as ready.", "info")
    else:
        flash("❌ Order not found.", "error")

    return redirect(url_for('order_bp.customer_orders'))


# --- Batch Move Route with Process Logging ---
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
@order_bp.route('/customer_orders/batch_delivered', methods=['POST'])
@login_required
def batch_delivered():
    serials = request.form.getlist('serials')
    if not serials:
        flash("No units selected.", "warning")
        return redirect(url_for('order_bp.customer_orders'))

    now = get_now_for_tenant()
    updated = 0
    # Group updated instances by customer for batched emails
    customer_units = {}  # customer_id -> {'customer': obj, 'units': [dicts]}

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
            from_stage = order.process_stage  # capture before overwrite
            from_team = order.team_assigned    # capture before overwrite

            order.status = 'delivered'
            order.process_stage = 'delivered'
            order.delivered_date = now
            order.delivered_by_user_id = current_user.id

            log_entry = ProductProcessLog(
                product_instance_id=order.product_instance_id,
                from_stage=from_stage,
                to_stage='delivered',
                from_team=from_team,
                to_team=None,
                moved_by=current_user.id,
                moved_at=now,
                action='batch_delivered'
            )
            db.session.add(log_entry)
            updated += 1

            # Collect for email grouping
            cid = order.customer_id
            if cid not in customer_units:
                customer_units[cid] = {'customer': order.customer, 'units': []}
            customer_units[cid]['units'].append(_instance_to_unit_dict(order.product_instance))

    db.session.commit()

    # Send one "ready for pickup" email per customer (wrapped — never breaks flow)
    emails_sent = 0
    for entry in customer_units.values():
        if send_reservation_ready(entry['customer'], entry['units'], current_user.tenant_id):
            emails_sent += 1

    email_note = f" Ready emails sent to {emails_sent} customer(s)." if emails_sent else ""
    flash(f"✅ {updated} unit(s) marked as ready for pickup.{email_note}", "success")
    return redirect(url_for('order_bp.customer_orders'))


# --- Batch Cancel Reservation Route — soft delete ---
@order_bp.route('/customer_orders/batch_cancel_reservation', methods=['POST'])
@login_required
def batch_cancel_reservation():
    serials = request.form.getlist('serials')
    if not serials:
        flash("No units selected.", "warning")
        return redirect(url_for('order_bp.customer_orders'))
    now = get_now_for_tenant()
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
            # Soft delete: mark as cancelled, keep the record
            order.status = 'cancelled'
            order.cancelled_at = now
            order.cancelled_by_user_id = current_user.id

            log_entry = ProductProcessLog(
                product_instance_id=order.product_instance_id,
                from_stage=order.process_stage,
                to_stage=None,
                from_team=order.team_assigned,
                to_team=None,
                moved_by=current_user.id,
                moved_at=now,
                action='cancel_reservation'
            )
            db.session.add(log_entry)
            canceled += 1
    db.session.commit()
    flash(f"✅ {canceled} reservation(s) cancelled.", "success")
    return redirect(url_for('order_bp.customer_orders'))

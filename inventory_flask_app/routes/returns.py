from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from inventory_flask_app.models import db, Return, ProductInstance
from datetime import datetime

returns_bp = Blueprint('returns_bp', __name__, url_prefix='/returns')


@returns_bp.route('/', methods=['GET'])
@login_required
def view_returns():
    returns = Return.query.filter_by(tenant_id=current_user.tenant_id).order_by(Return.return_date.desc()).all()
    return render_template('returns/view_returns.html', returns=returns)


@returns_bp.route('/new/<int:instance_id>', methods=['GET', 'POST'])
@login_required
def create_return(instance_id):
    instance = ProductInstance.query.get_or_404(instance_id)

    if request.method == 'POST':
        reason = request.form.get('reason')
        condition = request.form.get('condition')
        action = request.form.get('action')
        notes = request.form.get('notes')

        new_return = Return(
            instance_id=instance.id,
            return_date=datetime.utcnow(),
            reason=reason,
            condition=condition,
            action=action,
            notes=notes,
            tenant_id=current_user.tenant_id
        )
        db.session.add(new_return)
        db.session.commit()

        flash("✅ Return recorded successfully.", "success")
        return redirect(url_for('returns_bp.view_returns'))

    return render_template('returns/create_return.html', instance=instance)


@returns_bp.route('/lookup', methods=['GET', 'POST'])
@login_required
def lookup_return():
    if request.method == 'POST':
        serial = request.form.get('serial', '').strip().upper()

        from inventory_flask_app.models import SaleItem, SaleTransaction
        from sqlalchemy import or_

        matched_instance = None
        sale_info = None

        # Try to find SaleItem by serial or asset
        sale_item = SaleItem.query.join(ProductInstance).filter(
            or_(
                db.func.upper(ProductInstance.serial) == serial,
                db.func.upper(ProductInstance.asset) == serial
            ),
            ProductInstance.tenant_id == current_user.tenant_id
        ).first()

        if sale_item and sale_item.product_instance:
            matched_instance = sale_item.product_instance
            sale_info = sale_item

        # Fallback: try to find SaleTransaction using ProductInstance
        if not matched_instance:
            sale_txn = SaleTransaction.query.join(ProductInstance).filter(
                or_(
                    db.func.upper(ProductInstance.serial) == serial,
                    db.func.upper(ProductInstance.asset) == serial
                ),
                ProductInstance.tenant_id == current_user.tenant_id
            ).first()

            if sale_txn and sale_txn.product_instance_id:
                matched_instance = ProductInstance.query.get(sale_txn.product_instance_id)
                sale_info = sale_txn

        # Final fallback: match ProductInstance directly
        if not matched_instance:
            matched_instance = ProductInstance.query.filter(
                or_(
                    db.func.upper(ProductInstance.serial) == serial,
                    db.func.upper(ProductInstance.asset) == serial
                ),
                ProductInstance.tenant_id == current_user.tenant_id
            ).first()

        if matched_instance:
            return render_template('returns/preview_return.html', instance=matched_instance, sale=sale_info)

        # Log unmatched serial attempt
        flash(f"❌ No matching product found for serial: {serial}", "danger")

    return render_template('returns/lookup.html')
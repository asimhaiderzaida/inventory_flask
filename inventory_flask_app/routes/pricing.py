import logging
from decimal import Decimal

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from inventory_flask_app.models import (
    db, PurchaseOrder, ProductInstance, Product,
    UnitCost, POCostSettings, Location,
)
from inventory_flask_app.utils.utils import module_required

logger = logging.getLogger(__name__)

pricing_bp = Blueprint('pricing_bp', __name__, url_prefix='/pricing')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_po_or_404(po_id):
    return PurchaseOrder.query.filter_by(
        id=po_id, tenant_id=current_user.tenant_id
    ).first_or_404()


def _get_instance_or_404(instance_id):
    return (
        ProductInstance.query
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(
            ProductInstance.id == instance_id,
            Product.tenant_id == current_user.tenant_id,
        )
        .first_or_404()
    )


def _ensure_unit_cost(instance):
    """Get or create UnitCost for an instance."""
    uc = instance.unit_cost
    if not uc:
        uc = UnitCost(
            instance_id=instance.id,
            tenant_id=current_user.tenant_id,
        )
        db.session.add(uc)
        db.session.flush()
    return uc


# ---------------------------------------------------------------------------
# Pricing Dashboard
# ---------------------------------------------------------------------------

@pricing_bp.route('/')
@login_required
@module_required('accounting', 'view')
def pricing_dashboard():
    tid = current_user.tenant_id

    # Totals
    all_costs = (
        UnitCost.query
        .filter_by(tenant_id=tid)
        .join(ProductInstance, UnitCost.instance_id == ProductInstance.id)
        .filter(ProductInstance.is_sold == False)
        .all()
    )

    total_units_priced  = len(all_costs)
    total_cost_value    = sum(float(uc.total_cost or 0) for uc in all_costs)
    total_suggested     = sum(float(uc.suggested_price or 0) for uc in all_costs)

    # At-risk: asking_price < suggested_price (or no asking price set)
    at_risk = []
    units_below_cost = []
    units_no_purchase_cost = 0
    total_at_asking = 0.0
    units_with_asking = 0
    margin_values = []

    for uc in all_costs:
        inst = uc.instance
        asking = float(inst.asking_price or 0)
        suggested = float(uc.suggested_price or 0)
        total = float(uc.total_cost or 0)
        purchase = float(uc.purchase_cost or 0)

        if purchase == 0:
            units_no_purchase_cost += 1

        if asking > 0:
            total_at_asking += asking
            units_with_asking += 1
            if total > 0 and asking < total:
                units_below_cost.append({
                    'instance': inst,
                    'unit_cost': uc,
                    'asking': asking,
                    'total_cost': total,
                    'loss': total - asking,
                })

        if suggested > 0 and (asking == 0 or asking < suggested):
            at_risk.append({
                'instance': inst,
                'unit_cost': uc,
                'asking': asking,
                'suggested': suggested,
                'gap': suggested - asking,
            })

        if uc.margin_percent:
            margin_values.append(float(uc.margin_percent))

    at_risk.sort(key=lambda x: x['gap'], reverse=True)
    units_below_cost.sort(key=lambda x: x['loss'], reverse=True)
    avg_margin = round(sum(margin_values) / len(margin_values), 1) if margin_values else 0

    # Unsold units with NO UnitCost at all
    from sqlalchemy import func as _func
    units_total_unsold = (
        ProductInstance.query
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Product.tenant_id == tid, ProductInstance.is_sold == False)
        .count()
    )
    units_missing_cost_record = units_total_unsold - total_units_priced

    # Recent POs with cost settings
    pos_with_settings = (
        PurchaseOrder.query
        .filter_by(tenant_id=tid)
        .join(POCostSettings, PurchaseOrder.id == POCostSettings.po_id)
        .order_by(PurchaseOrder.created_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        'pricing/pricing_dashboard.html',
        total_units_priced=total_units_priced,
        total_cost_value=total_cost_value,
        total_suggested=total_suggested,
        at_risk=at_risk[:20],
        units_below_cost=units_below_cost[:20],
        units_no_purchase_cost=units_no_purchase_cost,
        units_missing_cost_record=units_missing_cost_record,
        units_total_unsold=units_total_unsold,
        total_at_asking=total_at_asking,
        units_with_asking=units_with_asking,
        avg_margin=avg_margin,
        pos_with_settings=pos_with_settings,
    )


# ---------------------------------------------------------------------------
# PO Cost Settings
# ---------------------------------------------------------------------------

@pricing_bp.route('/po/<int:po_id>', methods=['GET', 'POST'])
@login_required
@module_required('accounting', 'full')
def po_pricing(po_id):
    po = _get_po_or_404(po_id)
    settings = po.cost_settings or POCostSettings(
        po_id=po.id, tenant_id=current_user.tenant_id
    )

    if request.method == 'POST':
        settings.shipping_mode    = request.form.get('shipping_mode', 'shared')
        settings.total_shipping   = Decimal(request.form.get('total_shipping') or 0)
        settings.shipping_per_unit = Decimal(request.form.get('shipping_per_unit') or 0)
        settings.duty_type        = request.form.get('duty_type', 'percent')
        settings.duty_value       = Decimal(request.form.get('duty_value') or 0)
        settings.default_margin   = Decimal(request.form.get('default_margin') or 25)

        if not settings.id:
            db.session.add(settings)

        action = request.form.get('action', 'save')
        if action == 'apply':
            db.session.flush()
            _apply_po_costs_to_units(po, settings)
            flash('PO cost settings saved and applied to all units.', 'success')
        else:
            flash('PO cost settings saved.', 'success')

        db.session.commit()
        return redirect(url_for('pricing_bp.po_pricing', po_id=po.id))

    # Count units in PO
    unit_count = ProductInstance.query.filter_by(po_id=po.id).count()

    return render_template(
        'pricing/po_pricing.html',
        po=po,
        settings=settings,
        unit_count=unit_count,
    )


def _apply_po_costs_to_units(po, settings):
    """Apply PO-level shipping/duty/margin to every unit in the PO."""
    instances = ProductInstance.query.filter_by(po_id=po.id).all()
    unit_count = len(instances)
    if not unit_count:
        return

    # Shipping per unit
    if settings.shipping_mode == 'shared' and unit_count > 0:
        shipping_each = float(settings.total_shipping or 0) / unit_count
    else:
        shipping_each = float(settings.shipping_per_unit or 0)

    for inst in instances:
        uc = _ensure_unit_cost(inst)
        uc.shipping_cost = round(shipping_each, 2)

        # Duty on top of purchase cost
        if settings.duty_type == 'percent':
            uc.duty_amount = round(
                float(uc.purchase_cost or 0) * float(settings.duty_value or 0) / 100, 2
            )
        else:
            uc.duty_amount = float(settings.duty_value or 0) / unit_count

        uc.margin_percent = settings.default_margin
        uc.calculate()


# ---------------------------------------------------------------------------
# Unit Cost Editor
# ---------------------------------------------------------------------------

@pricing_bp.route('/unit/<int:instance_id>', methods=['GET', 'POST'])
@login_required
@module_required('accounting', 'full')
def unit_pricing(instance_id):
    inst = _get_instance_or_404(instance_id)
    uc = _ensure_unit_cost(inst)

    if request.method == 'POST':
        uc.purchase_cost    = Decimal(request.form.get('purchase_cost') or 0)
        uc.shipping_cost    = Decimal(request.form.get('shipping_cost') or 0)
        uc.duty_amount      = Decimal(request.form.get('duty_amount') or 0)
        uc.repair_cost      = Decimal(request.form.get('repair_cost') or 0)
        uc.ram_upgrade_cost = Decimal(request.form.get('ram_upgrade_cost') or 0)
        uc.ssd_upgrade_cost = Decimal(request.form.get('ssd_upgrade_cost') or 0)
        uc.other_cost       = Decimal(request.form.get('other_cost') or 0)
        uc.other_cost_note  = request.form.get('other_cost_note', '').strip() or None
        uc.margin_percent   = Decimal(request.form.get('margin_percent') or 25)
        uc.calculate()

        if request.form.get('apply_to_asking'):
            inst.asking_price = uc.suggested_price

        db.session.commit()
        flash('Unit cost saved.', 'success')
        return redirect(url_for('pricing_bp.unit_pricing', instance_id=inst.id))

    return render_template(
        'pricing/unit_pricing.html',
        inst=inst,
        uc=uc,
    )


@pricing_bp.route('/unit/<int:instance_id>/preview', methods=['POST'])
@login_required
@module_required('accounting', 'view')
def unit_pricing_preview(instance_id):
    """AJAX: return total_cost and suggested_price without saving."""
    data = request.get_json(silent=True) or {}
    fields = ['purchase_cost', 'shipping_cost', 'duty_amount', 'repair_cost',
              'ram_upgrade_cost', 'ssd_upgrade_cost', 'other_cost']
    total = sum(float(data.get(f) or 0) for f in fields)
    margin = float(data.get('margin_percent') or 25) / 100
    suggested = round(total * (1 + margin), 2)
    return jsonify(total_cost=round(total, 2), suggested_price=suggested)


# ---------------------------------------------------------------------------
# Bulk Pricing Editor
# ---------------------------------------------------------------------------

@pricing_bp.route('/bulk')
@login_required
@module_required('accounting', 'full')
def bulk_pricing():
    tid = current_user.tenant_id

    # Filters
    po_id       = request.args.get('po_id', type=int)
    status      = request.args.get('status', '')
    make        = request.args.get('make', '').strip()
    model       = request.args.get('model', '').strip()
    location    = request.args.get('location', '').strip()
    priced      = request.args.get('priced', '')  # 'yes' | 'no' | ''

    q = (
        ProductInstance.query
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(Product.tenant_id == tid, ProductInstance.is_sold == False)
    )
    if po_id:
        q = q.filter(ProductInstance.po_id == po_id)
    if status:
        q = q.filter(ProductInstance.status == status)
    if make:
        q = q.filter(Product.make.ilike(f'%{make}%'))
    if model:
        q = q.filter(Product.model.ilike(f'%{model}%'))
    if location:
        q = q.join(Location, ProductInstance.location_id == Location.id).filter(
            Location.name == location
        )
    if priced == 'yes':
        q = q.filter(ProductInstance.asking_price != None)
    elif priced == 'no':
        q = q.filter(ProductInstance.asking_price == None)

    instances = q.order_by(Product.make, Product.model).limit(200).all()

    # Sidebar data for filter dropdowns
    pos = PurchaseOrder.query.filter_by(tenant_id=tid).order_by(
        PurchaseOrder.created_at.desc()
    ).limit(50).all()
    locations = Location.query.filter_by(tenant_id=tid).order_by(Location.name).all()

    return render_template(
        'pricing/bulk_pricing.html',
        instances=instances,
        pos=pos,
        locations=locations,
        filters={
            'po_id': po_id, 'status': status, 'make': make,
            'model': model, 'location': location, 'priced': priced,
        },
    )


@pricing_bp.route('/bulk/update', methods=['POST'])
@login_required
@module_required('accounting', 'full')
def bulk_update():
    """JSON: update asking_price for multiple instances."""
    tid = current_user.tenant_id
    data = request.get_json(silent=True) or {}
    updates = data.get('updates', [])  # [{instance_id, asking_price}, ...]

    if not updates:
        return jsonify(ok=False, error='No updates provided'), 400

    ids = [u['instance_id'] for u in updates if 'instance_id' in u]
    instances = {
        inst.id: inst
        for inst in (
            ProductInstance.query
            .join(Product, ProductInstance.product_id == Product.id)
            .filter(ProductInstance.id.in_(ids), Product.tenant_id == tid)
            .all()
        )
    }

    updated = 0
    for u in updates:
        inst = instances.get(u.get('instance_id'))
        if inst and u.get('asking_price') is not None:
            inst.asking_price = Decimal(str(u['asking_price']))
            updated += 1

    db.session.commit()
    return jsonify(ok=True, updated=updated)


@pricing_bp.route('/bulk/apply_suggested', methods=['POST'])
@login_required
@module_required('accounting', 'full')
def bulk_apply_suggested():
    """Apply suggested_price → asking_price for selected instances."""
    tid = current_user.tenant_id
    data = request.get_json(silent=True) or {}
    ids = data.get('instance_ids', [])

    if not ids:
        return jsonify(ok=False, error='No instances selected'), 400

    unit_costs = (
        UnitCost.query
        .filter(UnitCost.tenant_id == tid, UnitCost.instance_id.in_(ids))
        .all()
    )

    updated = 0
    for uc in unit_costs:
        if uc.suggested_price and float(uc.suggested_price) > 0:
            uc.instance.asking_price = uc.suggested_price
            updated += 1

    db.session.commit()
    return jsonify(ok=True, updated=updated)

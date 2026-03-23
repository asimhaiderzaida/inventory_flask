from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import or_
from inventory_flask_app.models import (
    db, Return, CreditNote, ProductInstance, SaleTransaction, SaleItem,
    Invoice, ProductProcessLog, Part, PartStock, PartMovement,
    PartSaleTransaction, PartSaleItem, Location, AccountReceivable, ARPayment,
)
from inventory_flask_app.utils.utils import get_now_for_tenant

returns_bp = Blueprint('returns_bp', __name__, url_prefix='/returns')


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _generate_credit_note_number(tid, now):
    """Return next CN-{year}-{seq:04d} for this tenant."""
    year = now.year
    count = CreditNote.query.filter_by(tenant_id=tid).filter(
        db.func.extract('year', CreditNote.issued_at) == year
    ).count()
    return f"CN-{year}-{count + 1:04d}"


def _restore_part_stock(part_id, location_id, bin_id, quantity, note, now):
    """Add quantity back to PartStock and log a PartMovement(return)."""
    stock = PartStock.query.filter_by(
        part_id=part_id, location_id=location_id, bin_id=bin_id
    ).first()
    if not stock:
        stock = PartStock(part_id=part_id, location_id=location_id,
                          bin_id=bin_id, quantity=0)
        db.session.add(stock)
    stock.quantity += quantity
    db.session.add(PartMovement(
        part_id=part_id,
        to_location_id=location_id,
        to_bin_id=bin_id,
        quantity=quantity,
        movement_type='return',
        note=note or 'Customer return',
        user_id=current_user.id,
        created_at=now,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# UNIT RETURNS
# ─────────────────────────────────────────────────────────────────────────────

@returns_bp.route('/', methods=['GET'])
@login_required
def view_returns():
    from sqlalchemy.orm import joinedload
    tid = current_user.tenant_id
    tab          = request.args.get('tab', 'all')          # all / unit / part
    q_search     = request.args.get('q', '').strip()
    date_from    = request.args.get('date_from', '').strip()
    date_to      = request.args.get('date_to', '').strip()
    f_condition  = request.args.get('condition', '').strip()
    f_refund_status = request.args.get('refund_status', '').strip()

    query = (
        Return.query
        .filter_by(tenant_id=tid)
        .options(
            joinedload(Return.instance),
            joinedload(Return.part),
            joinedload(Return.invoice).joinedload(Invoice.customer),
            joinedload(Return.part_sale).joinedload(PartSaleTransaction.customer),
        )
    )

    if tab == 'unit':
        query = query.filter(Return.return_type == 'unit')
    elif tab == 'part':
        query = query.filter(Return.return_type == 'part')
    if f_condition:
        query = query.filter(Return.condition == f_condition)
    if f_refund_status:
        query = query.filter(Return.refund_status == f_refund_status)
    if date_from:
        try:
            from datetime import datetime as _dt
            query = query.filter(Return.return_date >= _dt.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import datetime as _dt
            query = query.filter(Return.return_date <= _dt.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59))
        except ValueError:
            pass

    returns = query.order_by(Return.return_date.desc()).all()

    # Search filter (in-Python — operates on already-loaded relationships)
    if q_search:
        ql = q_search.lower()
        filtered = []
        for r in returns:
            match = (
                (r.instance and r.instance.serial and ql in r.instance.serial.lower())
                or (r.instance and r.instance.asset and ql in r.instance.asset.lower())
                or (r.part and ql in r.part.name.lower())
                or (r.part and ql in r.part.part_number.lower())
                or (r.reason and ql in r.reason.lower())
                or (r.credit_note_number and ql in r.credit_note_number.lower())
            )
            if match:
                filtered.append(r)
        returns = filtered

    # Summary stats
    total_refund_amount = sum(float(r.refund_amount or 0) for r in returns)
    pending_refunds = sum(1 for r in returns if r.refund_status == 'pending')

    return render_template(
        'returns/view_returns.html',
        returns=returns,
        tab=tab,
        q_search=q_search,
        date_from=date_from,
        date_to=date_to,
        f_condition=f_condition,
        f_refund_status=f_refund_status,
        total_refund_amount=total_refund_amount,
        pending_refunds=pending_refunds,
    )


@returns_bp.route('/export', methods=['GET'])
@login_required
def export_returns():
    import csv
    import io
    from flask import make_response
    from sqlalchemy.orm import joinedload

    tid = current_user.tenant_id
    tab = request.args.get('tab', 'all')
    query = Return.query.filter_by(tenant_id=tid).options(
        joinedload(Return.instance),
        joinedload(Return.part),
        joinedload(Return.invoice).joinedload(Invoice.customer),
        joinedload(Return.part_sale).joinedload(PartSaleTransaction.customer),
    )
    if tab == 'unit':
        query = query.filter(Return.return_type == 'unit')
    elif tab == 'part':
        query = query.filter(Return.return_type == 'part')
    returns = query.order_by(Return.return_date.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        'Date', 'Type', 'Serial / Part #', 'Name / Model',
        'Customer', 'Reason', 'Condition', 'Action',
        'Refund Method', 'Refund Amount', 'Refund Status',
        'Credit Note #', 'Notes',
    ])
    for r in returns:
        if r.return_type == 'unit':
            identifier = (r.instance.serial if r.instance else '')
            name = (r.instance.product.model if r.instance and r.instance.product else '')
            customer = (
                r.invoice.customer.name if r.invoice and r.invoice.customer
                else ''
            )
        else:
            identifier = (r.part.part_number if r.part else '')
            name = (r.part.name if r.part else '')
            customer = (
                r.part_sale.customer.name if r.part_sale and r.part_sale.customer
                else (r.part_sale.customer_name if r.part_sale else '')
            )
        writer.writerow([
            r.return_date.strftime('%Y-%m-%d') if r.return_date else '',
            r.return_type,
            identifier,
            name,
            customer,
            r.reason or '',
            r.condition or '',
            r.action or '',
            r.refund_method or '',
            r.refund_amount or '',
            r.refund_status or '',
            r.credit_note_number or '',
            r.notes or '',
        ])

    response = make_response(buf.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=returns_export.csv'
    return response


@returns_bp.route('/new/<int:instance_id>', methods=['GET', 'POST'])
@login_required
def create_return(instance_id):
    instance = ProductInstance.query.filter_by(
        id=instance_id, tenant_id=current_user.tenant_id
    ).first_or_404()
    tid = current_user.tenant_id
    now = get_now_for_tenant()

    # Resolve sale/invoice context from optional query param
    sale_id = request.args.get('sale_id', type=int)
    sale = db.session.get(SaleTransaction, sale_id) if sale_id else None
    if sale and sale.tenant_id != current_user.tenant_id:
        sale = None
    if not sale:
        sale = (
            SaleTransaction.query
            .filter_by(product_instance_id=instance.id)
            .order_by(SaleTransaction.id.desc())
            .first()
        )
    invoice = db.session.get(Invoice, sale.invoice_id) if (sale and sale.invoice_id) else None

    if request.method == 'POST':
        reason = request.form.get('reason', '').strip()
        condition = request.form.get('condition')
        action = request.form.get('action')
        action_taken = request.form.get('action_taken', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        refund_method = request.form.get('refund_method') or 'none'
        refund_status = 'pending'
        refund_amount = None
        try:
            raw = request.form.get('refund_amount', '').strip()
            if raw:
                refund_amount = float(raw)
        except ValueError:
            pass

        credit_note_number = None
        credit_note_issued_at = None
        if refund_method == 'credit_note':
            credit_note_number = _generate_credit_note_number(tid, now)
            credit_note_issued_at = now
            refund_status = 'issued'
        elif refund_method == 'none':
            refund_status = 'denied'

        ret = Return(
            return_type='unit',
            instance_id=instance.id,
            invoice_id=invoice.id if invoice else None,
            return_date=now,
            reason=reason,
            condition=condition,
            action=action,
            action_taken=action_taken,
            notes=notes,
            refund_amount=refund_amount,
            refund_method=refund_method,
            refund_status=refund_status,
            credit_note_number=credit_note_number,
            credit_note_issued_at=credit_note_issued_at,
            tenant_id=tid,
        )
        db.session.add(ret)
        db.session.flush()

        if refund_method == 'credit_note' and credit_note_number:
            customer_id = (
                invoice.customer_id if invoice
                else (sale.customer_id if sale else None)
            )
            db.session.add(CreditNote(
                tenant_id=tid,
                return_id=ret.id,
                credit_note_number=credit_note_number,
                customer_id=customer_id,
                amount=refund_amount or 0,
                issued_at=now,
                issued_by=current_user.id,
                notes=notes,
            ))

        prev_status = instance.status or 'unprocessed'
        instance.is_sold = False
        instance.status = 'unprocessed'
        instance.assigned_to_user_id = None

        if sale:
            reversal_note = f"RETURNED {now.strftime('%Y-%m-%d')}: {reason or 'no reason given'}"
            sale.notes = (sale.notes + '\n' + reversal_note) if sale.notes else reversal_note

        db.session.add(ProductProcessLog(
            product_instance_id=instance.id,
            from_stage=prev_status,
            to_stage='unprocessed',
            moved_by=current_user.id,
            moved_at=now,
            action='return',
            note=reason or (notes or 'Return processed'),
        ))

        db.session.commit()

        if credit_note_number:
            flash(f'Return recorded. Credit note {credit_note_number} issued.', 'success')
        else:
            flash('Return recorded. Unit returned to unprocessed inventory.', 'success')
        return redirect(url_for('returns_bp.view_returns'))

    return render_template('returns/create_return.html',
                           instance=instance, sale=sale, invoice=invoice)


@returns_bp.route('/lookup', methods=['GET', 'POST'])
@login_required
def lookup_return():
    if request.method == 'POST':
        query_str = request.form.get('serial', '').strip().upper()

        matched_instance = None
        sale_info = None
        sale_id = None

        # Try invoice number first
        if not query_str.isdigit():
            inv = Invoice.query.filter(
                db.func.upper(Invoice.invoice_number) == query_str,
                Invoice.tenant_id == current_user.tenant_id
            ).first()
            if inv:
                txn = (
                    SaleTransaction.query
                    .filter_by(invoice_id=inv.id)
                    .order_by(SaleTransaction.id.desc())
                    .first()
                )
                if txn:
                    matched_instance = ProductInstance.query.filter_by(
                        id=txn.product_instance_id,
                        tenant_id=current_user.tenant_id
                    ).first()
                    sale_info = txn
                    sale_id = txn.id

        # Try SaleItem by serial/asset
        if not matched_instance:
            sale_item = (
                SaleItem.query
                .join(ProductInstance, SaleItem.product_instance_id == ProductInstance.id)
                .filter(
                    or_(
                        db.func.upper(ProductInstance.serial) == query_str,
                        db.func.upper(ProductInstance.asset) == query_str,
                    ),
                    ProductInstance.tenant_id == current_user.tenant_id
                ).first()
            )
            if sale_item and sale_item.product_instance:
                matched_instance = sale_item.product_instance
                sale_info = sale_item
                sale_id = sale_item.sale_transaction.id if sale_item.sale_transaction else None

        # Fallback: SaleTransaction direct join
        if not matched_instance:
            sale_txn = (
                SaleTransaction.query
                .join(ProductInstance, SaleTransaction.product_instance_id == ProductInstance.id)
                .filter(
                    or_(
                        db.func.upper(ProductInstance.serial) == query_str,
                        db.func.upper(ProductInstance.asset) == query_str,
                    ),
                    ProductInstance.tenant_id == current_user.tenant_id
                ).first()
            )
            if sale_txn:
                matched_instance = ProductInstance.query.filter_by(
                    id=sale_txn.product_instance_id,
                    tenant_id=current_user.tenant_id
                ).first()
                if matched_instance:
                    sale_info = sale_txn
                    sale_id = sale_txn.id

        # Final fallback: ProductInstance directly
        if not matched_instance:
            matched_instance = ProductInstance.query.filter(
                or_(
                    db.func.upper(ProductInstance.serial) == query_str,
                    db.func.upper(ProductInstance.asset) == query_str,
                ),
                ProductInstance.tenant_id == current_user.tenant_id
            ).first()

        if matched_instance:
            return render_template('returns/preview_return.html',
                                   instance=matched_instance,
                                   sale=sale_info,
                                   sale_id=sale_id)

        flash(f'No matching product found for: {query_str}', 'danger')

    return render_template('returns/lookup.html')


# ─────────────────────────────────────────────────────────────────────────────
# PART RETURNS
# ─────────────────────────────────────────────────────────────────────────────

@returns_bp.route('/part/lookup', methods=['GET', 'POST'])
@login_required
def part_lookup():
    if request.method == 'POST':
        query_str = request.form.get('query', '').strip()
        tid = current_user.tenant_id

        # Search by barcode exact match, then part_number, then name (ilike)
        part = (
            Part.query.filter_by(tenant_id=tid)
            .filter(
                or_(
                    db.func.upper(Part.barcode) == query_str.upper(),
                    db.func.upper(Part.part_number) == query_str.upper(),
                    Part.name.ilike(f'%{query_str}%'),
                )
            ).first()
        )

        if not part:
            flash(f'No part found for: {query_str}', 'danger')
            return render_template('returns/part_lookup.html')

        # Try to find the most recent sale item for this part
        sale_item = (
            PartSaleItem.query
            .filter_by(part_id=part.id, tenant_id=tid)
            .order_by(PartSaleItem.id.desc())
            .first()
        )

        return render_template('returns/part_preview.html',
                               part=part,
                               sale_item=sale_item)

    return render_template('returns/part_lookup.html')


@returns_bp.route('/part/create', methods=['GET', 'POST'])
@login_required
def create_part_return():
    tid = current_user.tenant_id
    part_id = request.args.get('part_id', type=int) or request.form.get('part_id', type=int)
    sale_item_id = request.args.get('sale_item_id', type=int) or request.form.get('sale_item_id', type=int)

    part = Part.query.filter_by(id=part_id, tenant_id=tid).first_or_404()
    sale_item = db.session.get(PartSaleItem, sale_item_id) if sale_item_id else None
    locations = Location.query.filter_by(tenant_id=tid).order_by(Location.name).all()

    if request.method == 'POST':
        now = get_now_for_tenant()
        reason = request.form.get('reason', '').strip()
        condition = request.form.get('condition')
        action = request.form.get('action')
        action_taken = request.form.get('action_taken', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        refund_method = request.form.get('refund_method') or 'none'
        location_id = request.form.get('location_id', type=int)
        refund_status = 'pending'
        refund_amount = None
        try:
            raw = request.form.get('refund_amount', '').strip()
            if raw:
                refund_amount = float(raw)
        except ValueError:
            pass

        quantity = request.form.get('quantity', 1, type=int)
        if quantity < 1:
            quantity = 1

        credit_note_number = None
        credit_note_issued_at = None
        if refund_method == 'credit_note':
            credit_note_number = _generate_credit_note_number(tid, now)
            credit_note_issued_at = now
            refund_status = 'issued'
        elif refund_method == 'none':
            refund_status = 'denied'

        # Resolve restore location/bin: prefer sale item's origin
        restore_location_id = location_id or (sale_item.location_id if sale_item else None)
        restore_bin_id = sale_item.bin_id if sale_item else None

        if not restore_location_id:
            # Fall back to the first PartStock location for this part
            first_stock = PartStock.query.filter_by(part_id=part.id).first()
            restore_location_id = first_stock.location_id if first_stock else None

        ret = Return(
            return_type='part',
            part_id=part.id,
            part_quantity=quantity,
            part_sale_id=sale_item.transaction_id if sale_item else None,
            return_date=now,
            reason=reason,
            condition=condition,
            action=action,
            action_taken=action_taken,
            notes=notes,
            refund_amount=refund_amount,
            refund_method=refund_method,
            refund_status=refund_status,
            credit_note_number=credit_note_number,
            credit_note_issued_at=credit_note_issued_at,
            tenant_id=tid,
        )
        db.session.add(ret)
        db.session.flush()

        if refund_method == 'credit_note' and credit_note_number:
            customer_id = (
                sale_item.transaction.customer_id
                if sale_item and sale_item.transaction
                else None
            )
            db.session.add(CreditNote(
                tenant_id=tid,
                return_id=ret.id,
                credit_note_number=credit_note_number,
                customer_id=customer_id,
                amount=refund_amount or 0,
                issued_at=now,
                issued_by=current_user.id,
                notes=notes,
            ))

        # Restore stock
        if restore_location_id:
            _restore_part_stock(
                part_id=part.id,
                location_id=restore_location_id,
                bin_id=restore_bin_id,
                quantity=quantity,
                note=reason or 'Customer return',
                now=now,
            )

        db.session.commit()

        if credit_note_number:
            flash(f'Part return recorded. Credit note {credit_note_number} issued. {quantity}× {part.name} returned to stock.', 'success')
        else:
            flash(f'Part return recorded. {quantity}× {part.name} returned to stock.', 'success')
        return redirect(url_for('returns_bp.view_returns'))

    return render_template('returns/part_create.html',
                           part=part,
                           sale_item=sale_item,
                           locations=locations)


# ─────────────────────────────────────────────────────────────────────────────
# CREDIT NOTE MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

@returns_bp.route('/credit-notes', methods=['GET'])
@login_required
def credit_notes():
    from sqlalchemy.orm import joinedload
    tid = current_user.tenant_id

    f_status   = request.args.get('status', '').strip()
    f_customer = request.args.get('customer_id', type=int)
    q_search   = request.args.get('q', '').strip()

    query = (
        CreditNote.query
        .filter_by(tenant_id=tid)
        .options(
            joinedload(CreditNote.customer),
            joinedload(CreditNote.issuer),
            joinedload(CreditNote.return_record),
            joinedload(CreditNote.applied_ar),
        )
    )
    if f_status:
        query = query.filter(CreditNote.status == f_status)
    if f_customer:
        query = query.filter(CreditNote.customer_id == f_customer)

    credit_notes_list = query.order_by(CreditNote.issued_at.desc()).all()

    if q_search:
        ql = q_search.lower()
        credit_notes_list = [
            cn for cn in credit_notes_list
            if ql in cn.credit_note_number.lower()
            or (cn.customer and ql in cn.customer.name.lower())
            or (cn.notes and ql in cn.notes.lower())
        ]

    total_unapplied = sum(
        float(cn.amount or 0)
        for cn in credit_notes_list
        if cn.status == 'unapplied'
    )

    # Customer list for filter dropdown
    from inventory_flask_app.models import Customer
    customers = Customer.query.filter_by(tenant_id=tid).order_by(Customer.name).all()

    return render_template(
        'returns/credit_notes.html',
        credit_notes=credit_notes_list,
        f_status=f_status,
        f_customer=f_customer,
        q_search=q_search,
        total_unapplied=total_unapplied,
        customers=customers,
    )


@returns_bp.route('/credit-notes/<int:cn_id>/apply', methods=['GET', 'POST'])
@login_required
def apply_credit_note(cn_id):
    from sqlalchemy.orm import joinedload
    tid = current_user.tenant_id
    cn = CreditNote.query.filter_by(id=cn_id, tenant_id=tid).first_or_404()

    if cn.status == 'applied':
        flash('This credit note has already been fully applied.', 'warning')
        return redirect(url_for('returns_bp.credit_notes'))

    # Load open AR records for this customer
    open_ar_list = []
    if cn.customer_id:
        open_ar_list = (
            AccountReceivable.query
            .filter(
                AccountReceivable.customer_id == cn.customer_id,
                AccountReceivable.tenant_id == tid,
                AccountReceivable.status.in_(('open', 'partial', 'overdue')),
            )
            .options(joinedload(AccountReceivable.invoice))
            .order_by(AccountReceivable.due_date.asc().nullslast())
            .all()
        )

    if request.method == 'POST':
        ar_id = request.form.get('ar_id', type=int)
        if not ar_id:
            flash('Please select an invoice to apply the credit to.', 'danger')
            return render_template('returns/credit_note_apply.html',
                                   cn=cn, open_ar_list=open_ar_list)

        ar = AccountReceivable.query.filter_by(id=ar_id, tenant_id=tid).first()
        if not ar:
            flash('Invoice not found.', 'danger')
            return redirect(url_for('returns_bp.credit_notes'))

        now = get_now_for_tenant()
        cn_remaining = float(cn.amount or 0) - float(cn.applied_amount or 0)
        ar_balance = ar.balance
        apply_amount = min(cn_remaining, ar_balance)

        if apply_amount <= 0:
            flash('No balance remaining to apply.', 'warning')
            return redirect(url_for('returns_bp.credit_notes'))

        # Record as an AR payment
        db.session.add(ARPayment(
            tenant_id=tid,
            ar_id=ar.id,
            amount=apply_amount,
            payment_method='credit_note',
            payment_date=now.date(),
            reference=cn.credit_note_number,
            recorded_by=current_user.id,
            notes=f'Credit note {cn.credit_note_number} applied',
        ))

        # Update AR
        ar.amount_paid = float(ar.amount_paid or 0) + apply_amount
        new_balance = float(ar.amount_due or 0) - float(ar.amount_paid)
        if new_balance <= 0.005:
            ar.status = 'paid'
        else:
            ar.status = 'partial'

        # Update credit note
        cn.applied_amount = apply_amount
        cn.applied_to_ar_id = ar.id
        cn.applied_at = now
        cn.applied_by = current_user.id
        cn.status = 'applied' if (cn_remaining - apply_amount) <= 0.005 else 'partially_applied'

        db.session.commit()

        flash(f'Credit note {cn.credit_note_number} — ${apply_amount:.2f} applied to invoice.', 'success')
        return redirect(url_for('returns_bp.credit_notes'))

    return render_template('returns/credit_note_apply.html',
                           cn=cn, open_ar_list=open_ar_list)

import logging
from flask import redirect, url_for, flash, jsonify
from flask import Blueprint, request, render_template, send_file
from flask_login import login_required, current_user
from ..models import db, Invoice, SaleItem, ProductInstance
from datetime import datetime, timezone
from io import BytesIO
from weasyprint import HTML as WeasyHTML
from inventory_flask_app.models import TenantSettings
from inventory_flask_app import csrf
from inventory_flask_app.utils import get_now_for_tenant
from inventory_flask_app.utils.utils import module_required

logger = logging.getLogger(__name__)
invoices_bp = Blueprint('invoices_bp', __name__)


# ─────────────────────────────────────────────────────────────
# Shared helper — build invoice items_data + totals
# Used by download, view, and send routes
# ─────────────────────────────────────────────────────────────
def _build_invoice_data(invoice):
    """Return (items_data, subtotal, total_vat, grand_total, settings_dict)."""
    _ts = TenantSettings.query.filter_by(tenant_id=invoice.tenant_id).all()
    settings_dict = {s.key: s.value for s in _ts}

    # Use stored SaleItem vat_rate if available (reflects what was charged at sale time,
    # e.g. 0 if VAT was explicitly disabled). Fall back to tenant setting.
    tenant_vat_rate = float(settings_dict.get('vat_rate') or 5)
    first_sale_item = SaleItem.query.filter_by(invoice_id=invoice.id).first()
    if first_sale_item is not None and first_sale_item.vat_rate is not None:
        default_vat_rate = float(first_sale_item.vat_rate)
    else:
        default_vat_rate = tenant_vat_rate

    subtotal = total_vat = grand_total = 0
    items_data = []

    for item in invoice.items:
        pi = item.product_instance
        prod = pi.product

        unit_price = item.price_at_sale or 0
        # Per-item vat_rate via linked SaleItem; fall back to invoice-level default
        sale_item = SaleItem.query.filter_by(sale_id=item.id).first()
        vat_rate = float(sale_item.vat_rate) if (sale_item and sale_item.vat_rate is not None) else default_vat_rate
        vat_amount = unit_price * vat_rate / 100
        total_line = unit_price + vat_amount

        items_data.append({
            'serial':         pi.serial,
            'asset':          getattr(pi, 'asset', ''),
            'item_name':      prod.item_name,
            'model':          prod.model,
            'cpu':            prod.cpu,
            'ram':            prod.ram,
            'disk1size':      prod.disk1size,
            'display':        prod.display,
            'gpu1':           prod.gpu1,
            'gpu2':           prod.gpu2,
            'grade':          prod.grade,
            'unit_price':     unit_price,
            'line_total':     unit_price,
            'vat_rate':       vat_rate,
            'vat_amount':     vat_amount,
            'total_with_vat': total_line,
        })
        subtotal    += unit_price
        total_vat   += vat_amount
        grand_total += total_line

    return items_data, subtotal, total_vat, grand_total, settings_dict


def _render_pdf(invoice):
    """Render the PDF BytesIO for an invoice."""
    items_data, subtotal, total_vat, grand_total, settings_dict = _build_invoice_data(invoice)
    html = render_template(
        'invoice_pdf_template.html',
        invoice=invoice,
        customer=invoice.customer,
        items=items_data,
        subtotal=subtotal,
        total_vat=total_vat,
        grand_total=grand_total,
        printed_time=get_now_for_tenant().strftime('%d-%b-%Y %H:%M'),
        settings=settings_dict,
    )
    pdf_bytes = WeasyHTML(string=html, base_url=request.host_url).write_pdf()
    return BytesIO(pdf_bytes)


# ─────────────────────────────────────────────────────────────
# Invoice view page
# ─────────────────────────────────────────────────────────────
@invoices_bp.route('/invoices/view/<int:invoice_id>')
@login_required
@module_required('sales', 'view')
def view_invoice(invoice_id):
    invoice = Invoice.query.filter(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).first_or_404()

    items_data, subtotal, total_vat, grand_total, settings_dict = _build_invoice_data(invoice)

    from inventory_flask_app.models import Return
    from sqlalchemy.orm import joinedload as _jl
    invoice_returns = (
        Return.query
        .filter_by(invoice_id=invoice.id, tenant_id=current_user.tenant_id)
        .options(_jl(Return.instance))
        .order_by(Return.return_date.desc())
        .all()
    )

    return render_template(
        'invoice_view.html',
        invoice=invoice,
        customer=invoice.customer,
        items=items_data,
        subtotal=subtotal,
        total_vat=total_vat,
        grand_total=grand_total,
        settings=settings_dict,
        printed_time=get_now_for_tenant().strftime('%d-%b-%Y %H:%M'),
        invoice_returns=invoice_returns,
    )


# ─────────────────────────────────────────────────────────────
# Download PDF
# ─────────────────────────────────────────────────────────────
@invoices_bp.route('/download_invoice/<int:invoice_id>')
@login_required
@module_required('sales', 'view')
def download_invoice(invoice_id):
    invoice = Invoice.query.filter(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).first_or_404()

    buf = _render_pdf(invoice)
    fname = f'invoice_{invoice.invoice_number or invoice.id}.pdf'
    return send_file(buf, download_name=fname, as_attachment=True)


# ─────────────────────────────────────────────────────────────
# Send invoice by email  (AJAX POST → JSON)
# ─────────────────────────────────────────────────────────────
@invoices_bp.route('/invoices/send/<int:invoice_id>', methods=['POST'])
@login_required
@module_required('sales', 'full')
def send_invoice_email(invoice_id):
    from inventory_flask_app import mail
    from flask_mail import Message

    invoice = Invoice.query.filter(
        Invoice.id == invoice_id,
        Invoice.tenant_id == current_user.tenant_id
    ).first_or_404()

    customer = invoice.customer
    if not customer.email:
        return jsonify(success=False,
                       message=f'Customer "{customer.name}" has no email address on file.'), 422

    try:
        buf = _render_pdf(invoice)
        inv_label = invoice.invoice_number or f"INV-{invoice.id:05d}"

        # Resolve sender name and custom template from settings
        _ts = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
        settings_dict = {s.key: s.value for s in _ts}
        company = (settings_dict.get('company_name') or
                   settings_dict.get('invoice_title') or
                   settings_dict.get('dashboard_name') or 'Us')

        from inventory_flask_app.utils.mail_utils import _render_email_template
        placeholders = {
            'customer_name': customer.name,
            'company_name': company,
            'invoice_number': inv_label,
            'amount': '',
            'due_date': '',
        }
        body = _render_email_template(current_user.tenant_id, 'email_tpl_invoice', placeholders)
        if body is None:
            body = (
                f"Dear {customer.name},\n\n"
                f"Please find attached your invoice {inv_label}.\n\n"
                f"Thank you for your business.\n\n"
                f"Best regards,\n{company}"
            )

        msg = Message(
            subject=f"Invoice {inv_label} from {company}",
            recipients=[customer.email],
            body=body,
        )
        msg.attach(
            filename=f"{inv_label}.pdf",
            content_type='application/pdf',
            data=buf.read(),
        )
        mail.send(msg)

        # Log the send date
        invoice.email_sent_at = datetime.now(timezone.utc)
        db.session.commit()

        # Log communication record
        try:
            from inventory_flask_app.models import CustomerCommunication
            comm = CustomerCommunication(
                tenant_id=current_user.tenant_id,
                customer_id=customer.id,
                type='invoice_email',
                subject=f"Invoice {inv_label} from {company}",
                sent_by=current_user.id,
                sent_at=invoice.email_sent_at,
            )
            db.session.add(comm)
            db.session.commit()
        except Exception as _ce:
            logger.warning("Failed to log invoice email communication: %s", _ce)

        logger.info("Invoice %s emailed to %s by user %s",
                    inv_label, customer.email, current_user.username)

        return jsonify(
            success=True,
            message=f"Invoice {inv_label} sent to {customer.email}.",
            sent_at=invoice.email_sent_at.strftime('%d %b %Y %H:%M'),
        )

    except Exception as e:
        logger.error("Failed to send invoice %s: %s", invoice_id, e)
        return jsonify(success=False, message=f"Failed to send email: {e}"), 500


@invoices_bp.route('/invoices/regenerate/<order_number>')
@login_required
@module_required('sales', 'full')
def generate_invoice_for_order(order_number):
    from inventory_flask_app.models import Order, SaleTransaction, SaleItem

    order = Order.query.filter_by(
        order_number=order_number, tenant_id=current_user.tenant_id
    ).first()
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for('customers_bp.customer_center'))

    transactions = SaleTransaction.query.filter_by(order_id=order.id).all()
    if not transactions:
        flash("No transactions found for this order.", "warning")
        return redirect(url_for('customers_bp.customer_center'))

    invoice = (
        Invoice.query.filter_by(id=transactions[0].invoice_id).first()
        if transactions[0].invoice_id else None
    )
    if not invoice:
        invoice = Invoice(
            customer_id=order.customer_id,
            user_id=current_user.id,
            tenant_id=order.tenant_id,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(invoice)
        db.session.commit()

    for tx in transactions:
        tx.invoice_id = invoice.id
    db.session.commit()

    if not invoice.invoice_number:
        invoice.invoice_number = f"INV-{invoice.id:05d}"
        db.session.commit()

    sale_items = SaleItem.query.filter_by(invoice_id=invoice.id).all()
    if not sale_items:
        for tx in transactions:
            db.session.add(SaleItem(
                sale_id=tx.id,
                product_instance_id=tx.product_instance_id,
                price_at_sale=tx.price_at_sale,
                vat_rate=5,
                invoice_id=invoice.id,
            ))
        db.session.commit()

    flash("Invoice regenerated.", "success")
    return redirect(url_for('invoices_bp.view_invoice', invoice_id=invoice.id))

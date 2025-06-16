from flask import Blueprint, request, jsonify, render_template, send_file
from flask_login import login_required
from ..models import db, Invoice, SaleItem, ProductInstance
from datetime import datetime
from xhtml2pdf import pisa
from io import BytesIO

invoices_bp = Blueprint('invoices_bp', __name__)

@invoices_bp.route('/create_invoice', methods=['POST'])
@login_required
def create_invoice():
    # This route is now disabled.
    return jsonify({"error": "Direct invoice creation is disabled. Please use the sale confirmation workflow."}), 400


@invoices_bp.route('/download_invoice/<int:invoice_id>')
@login_required
def download_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    customer = invoice.customer
    sale_items = invoice.items

    subtotal, total_vat, grand_total = 0, 0, 0
    items_data = []

    for item in sale_items:
        pi = item.product_instance
        prod = pi.product

        # Try from instance first, then fallback to product
        processor = getattr(pi, 'processor', '') or getattr(prod, 'processor', '') or ''
        ram = getattr(pi, 'ram', '') or getattr(prod, 'ram', '') or ''
        storage = getattr(pi, 'storage', '') or getattr(prod, 'storage', '') or ''
        vga = getattr(pi, 'vga', '') or getattr(prod, 'vga', '') or ''
        model = getattr(pi, 'model_number', '') or getattr(prod, 'model_number', '') or ''

        specs_parts = [model]
        if processor: specs_parts.append(processor)
        if ram: specs_parts.append(ram)
        if storage: specs_parts.append(storage)
        if vga: specs_parts.append(vga)
        specs_str = ", ".join(specs_parts)

        unit_price = item.price_at_sale or 0
        vat_rate = getattr(item, 'vat_rate', 5)
        line_total = unit_price
        vat_amount = (line_total * vat_rate) / 100
        total_with_vat = line_total + vat_amount

        subtotal += line_total
        total_vat += vat_amount
        grand_total += total_with_vat

        items_data.append({
            'serial_number': pi.serial_number,
            'product_name': prod.name,
            'model_number': model,
            'specs': specs_str,
            'unit_price': unit_price,
            'line_total': line_total,
            'vat_rate': vat_rate,
            'vat_amount': vat_amount,
            'total_with_vat': total_with_vat
        })

    html = render_template('invoice_pdf_template.html', invoice=invoice, customer=customer, items=items_data, subtotal=subtotal, total_vat=total_vat, grand_total=grand_total)
    result = BytesIO()
    pisa.CreatePDF(html, dest=result)
    result.seek(0)

    return send_file(result, download_name=f'invoice_{invoice.id}.pdf', as_attachment=True)

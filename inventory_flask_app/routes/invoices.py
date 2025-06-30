from flask import Blueprint, request, jsonify, render_template, send_file
from flask_login import login_required, current_user
from ..models import db, Invoice, SaleItem, ProductInstance
from datetime import datetime
from xhtml2pdf import pisa
from io import BytesIO
from inventory_flask_app.models import TenantSettings
from inventory_flask_app import csrf
from inventory_flask_app.utils import get_now_for_tenant

invoices_bp = Blueprint('invoices_bp', __name__)

@csrf.exempt
@invoices_bp.route('/create_invoice', methods=['POST'])
@login_required
def create_invoice():
    # This route is now disabled.
    return jsonify({"error": "Direct invoice creation is disabled. Please use the sale confirmation workflow."}), 400

@csrf.exempt
@invoices_bp.route('/download_invoice/<int:invoice_id>')
@login_required
def download_invoice(invoice_id):
    invoice = Invoice.query.filter(
        Invoice.id == invoice_id,
        (Invoice.tenant_id == current_user.tenant_id) | (Invoice.tenant_id == None)
    ).first_or_404()
    customer = invoice.customer
    sale_items = invoice.items

    subtotal, total_vat, grand_total = 0, 0, 0
    items_data = []

    for item in sale_items:
        pi = item.product_instance
        prod = pi.product

        # Use unified structure attribute names from product
        processor = getattr(prod, 'cpu', '')
        ram = getattr(prod, 'ram', '')
        storage = getattr(prod, 'disk1size', '')
        vga = getattr(prod, 'gpu1', '')
        model = getattr(prod, 'model', '')

        specs_parts = []
        if model: specs_parts.append(model)
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

        items_data.append({
            'serial': pi.serial,
            'item_name': prod.item_name,
            'model': prod.model,
            'cpu': prod.cpu,
            'ram': prod.ram,
            'disk1size': prod.disk1size,
            'display': prod.display,
            'gpu1': prod.gpu1,
            'gpu2': prod.gpu2,
            'grade': prod.grade,
            'unit_price': unit_price,
            'line_total': line_total,
            'vat_rate': vat_rate,
            'vat_amount': vat_amount,
            'total_with_vat': total_with_vat,
            'asset': getattr(pi, 'asset', ''),
        })

        subtotal += line_total
        total_vat += vat_amount
        grand_total += total_with_vat

    html = render_template(
        'invoice_pdf_template.html',
        invoice=invoice,
        customer=customer,
        items=items_data,
        subtotal=subtotal,
        total_vat=total_vat,
        grand_total=grand_total,
        printed_time=get_now_for_tenant().strftime('%d-%b-%Y %H:%M')
    )
    result = BytesIO()
    pisa.CreatePDF(html, dest=result)
    result.seek(0)

    return send_file(result, download_name=f'invoice_{invoice.id}.pdf', as_attachment=True)

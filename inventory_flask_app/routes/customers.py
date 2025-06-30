from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from ..models import db, Customer

customers_bp = Blueprint('customers_bp', __name__)

@customers_bp.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    from inventory_flask_app.models import TenantSettings
    settings = {}
    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in tenant_settings}

    next_page = request.args.get('next', '')
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()

        if Customer.query.filter_by(name=name, phone=phone, email=email, tenant_id=current_user.tenant_id).first():
            flash('A customer with this phone or email already exists.', 'danger')
            return render_template('add_customer.html', settings=settings)

        new_customer = Customer(name=name, phone=phone, email=email, tenant_id=current_user.tenant_id)
        db.session.add(new_customer)
        db.session.commit()

        flash('✅ Customer added successfully!', 'success')
        return redirect(url_for(
            'customers_bp.customer_center' if next_page == 'customer_center' else 'sales_bp.create_sale_form'
        ))

    return render_template('add_customer.html', settings=settings)


# Customer center route with search functionality
@customers_bp.route('/customers/center')
@login_required
def customer_center():
    from inventory_flask_app.models import TenantSettings
    search = request.args.get('search', '').strip()

    query = Customer.query.filter_by(tenant_id=current_user.tenant_id)
    if search:
        query = query.filter(
            (Customer.name.ilike(f"%{search}%")) |
            (Customer.phone.ilike(f"%{search}%")) |
            (Customer.email.ilike(f"%{search}%"))
        )
    customers = query.order_by(Customer.name).all()

    # Annotate each customer with their latest invoice ID
    from inventory_flask_app.models import Invoice, SaleTransaction
    for customer in customers:
        latest_invoice = Invoice.query \
            .filter_by(customer_id=customer.id) \
            .join(SaleTransaction) \
            .order_by(Invoice.created_at.desc()) \
            .first()
        customer.last_invoice_id = latest_invoice.id if latest_invoice else None

    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in tenant_settings}

    return render_template('customer_center.html', customers=customers, search=search, settings=settings)

@customers_bp.route('/customers/<int:customer_id>/profile')
@login_required
def customer_profile(customer_id):
    customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first_or_404()
    from inventory_flask_app.models import SaleTransaction, ProductInstance, Product, Invoice
    view = request.args.get('view', 'units')
    order_details_map = {}
    orders_list = []
    sales_data = []
    if view == 'units':
        # Find all sale transactions for this customer, with instance and product info
        sales = SaleTransaction.query.join(ProductInstance).join(Product).filter(
            SaleTransaction.customer_id == customer.id,
            Product.tenant_id == current_user.tenant_id
        ).order_by(SaleTransaction.date_sold.desc()).all()
        for sale in sales:
            instance = ProductInstance.query.get(sale.product_instance_id)
            product = Product.query.get(instance.product_id) if instance else None
            sales_data.append({
                "serial": instance.serial if instance else "",
                "asset": instance.asset if instance else "",
                "model": product.model if product else "",
                "item_name": product.item_name if product else "",
                "grade": product.grade if product else "",
                "ram": product.ram if product else "",
                "cpu": product.cpu if product else "",
                "disk1size": product.disk1size if product else "",
                "display": product.display if product else "",
                "gpu1": product.gpu1 if product else "",
                "gpu2": product.gpu2 if product else "",
                "status": instance.status if instance else "",
                "price_at_sale": sale.price_at_sale,
                "date_sold": sale.date_sold,
                "notes": sale.notes
            })
    elif view == 'orders':
        orders_list = []
        order_details_map = {}
        invoices = Invoice.query.filter_by(customer_id=customer.id).join(SaleTransaction).join(ProductInstance).join(Product).filter(
            Product.tenant_id == current_user.tenant_id
        ).order_by(Invoice.created_at.desc()).all()
        for invoice in invoices:
            units_list = []
            for sale in invoice.items:
                instance = ProductInstance.query.get(sale.product_instance_id)
                product = Product.query.get(instance.product_id) if instance else None
                units_list.append({
                    "serial": instance.serial if instance else "",
                    "asset": instance.asset if instance else "",
                    "model": product.model if product else "",
                    "item_name": product.item_name if product else "",
                    "grade": product.grade if product else "",
                    "ram": product.ram if product else "",
                    "cpu": product.cpu if product else "",
                    "disk1size": product.disk1size if product else "",
                    "display": product.display if product else "",
                    "gpu1": product.gpu1 if product else "",
                    "gpu2": product.gpu2 if product else "",
                    "status": instance.status if instance else "",
                    "price_at_sale": sale.price_at_sale,
                    "date_sold": sale.date_sold,
                    "notes": sale.notes
                })
            orders_list.append({
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "date": invoice.created_at,
                "total_units": len(units_list),
                "total_amount": sum([u["price_at_sale"] or 0 for u in units_list])
            })
            order_details_map[invoice.id] = units_list
    return render_template(
        "customer_profile.html",
        customer=customer,
        sales_data=sales_data,
        orders_list=orders_list,
        order_details_map=order_details_map,
        view=view
    )

@customers_bp.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
    customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first_or_404()
    if request.method == 'POST':
        customer.name = request.form.get('name')
        customer.phone = request.form.get('phone')
        customer.email = request.form.get('email')
        db.session.commit()
        flash('Customer updated successfully!', 'success')
        return redirect(url_for('customers_bp.customer_center'))
    return render_template('edit_customer.html', customer=customer)

from openpyxl import Workbook
from flask import send_file
from io import BytesIO
from inventory_flask_app.utils import get_now_for_tenant

@customers_bp.route('/customers/<int:customer_id>/export_sales')
@login_required
def export_customer_sales(customer_id):
    customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first_or_404()
    from inventory_flask_app.models import SaleTransaction, TenantSettings
    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in tenant_settings}

    sales = SaleTransaction.query.filter_by(customer_id=customer.id).order_by(SaleTransaction.date_sold.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Sales History"
    ws.append([
        'Date Sold',
        settings.get("label_serial", "Serial"),
        settings.get("label_asset", "Asset"),
        settings.get("label_item_name", "Item Name"),
        settings.get("label_model", "Model"),
        settings.get("label_cpu", "CPU"),
        settings.get("label_ram", "RAM"),
        settings.get("label_disk1size", "Disk"),
        settings.get("label_display", "Display"),
        settings.get("label_gpu1", "GPU1"),
        settings.get("label_gpu2", "GPU2"),
        settings.get("label_grade", "Grade"),
        settings.get("label_status", "Status"),
        settings.get("label_price", "Price"),
        settings.get("label_notes", "Notes")
    ])
    for sale in sales:
        instance = sale.product_instance
        product = instance.product if instance else None
        ws.append([
            sale.date_sold.strftime('%Y-%m-%d') if sale.date_sold else get_now_for_tenant().strftime('%Y-%m-%d'),
            instance.serial if instance else '',
            instance.asset if instance else '',
            product.item_name if product else '',
            product.model if product else '',
            product.cpu if product else '',
            product.ram if product else '',
            product.disk1size if product else '',
            product.display if product else '',
            product.gpu1 if product else '',
            product.gpu2 if product else '',
            product.grade if product else '',
            instance.status if instance else '',
            sale.price_at_sale,
            sale.notes or ''
        ])
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"customer_{customer.id}_sales.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
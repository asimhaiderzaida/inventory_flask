from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from ..models import db, Customer

customers_bp = Blueprint('customers_bp', __name__)

@customers_bp.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    next_page = request.args.get('next', '')
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        email = request.form.get('email')

        existing = Customer.query.filter(
            (Customer.name == name) | (Customer.phone == phone) | (Customer.email == email)
        ).first()
        if existing:
            flash('A customer with this phone or email already exists.', 'danger')
            return render_template('add_customer.html')

        new_customer = Customer(name=name, phone=phone, email=email)
        db.session.add(new_customer)
        db.session.commit()

        flash('Customer added successfully!', 'success')
        if next_page == 'customer_center':
            return redirect(url_for('customers_bp.customer_center'))
        return redirect(url_for('sales_bp.create_sale_form'))
    return render_template('add_customer.html')


# Customer center route with search functionality
@customers_bp.route('/customers/center')
@login_required
def customer_center():
    search = request.args.get('search', '').strip()
    query = Customer.query
    if search:
        query = query.filter(
            (Customer.name.ilike(f"%{search}%")) |
            (Customer.phone.ilike(f"%{search}%")) |
            (Customer.email.ilike(f"%{search}%"))
        )
    customers = query.order_by(Customer.name).all()
    return render_template('customer_center.html', customers=customers, search=search)

@customers_bp.route('/customers/<int:customer_id>/profile')
@login_required
def customer_profile(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    from inventory_flask_app.models import SaleTransaction, ProductInstance, Product
    # Find all sale transactions for this customer, with instance and product info
    sales = SaleTransaction.query.filter_by(customer_id=customer.id).order_by(SaleTransaction.date_sold.desc()).all()
    sales_data = []
    for sale in sales:
        instance = ProductInstance.query.get(sale.product_instance_id)
        product = Product.query.get(instance.product_id) if instance else None
        sales_data.append({
            "serial_number": instance.serial_number if instance else "",
            "model_number": product.model_number if product else "",
            "name": product.name if product else "",
            "status": instance.status if instance else "",
            "price_at_sale": sale.price_at_sale,
            "date_sold": sale.date_sold,
            "notes": sale.notes
        })
    return render_template("customer_profile.html", customer=customer, sales_data=sales_data)

@customers_bp.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
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

@customers_bp.route('/customers/<int:customer_id>/export_sales')
@login_required
def export_customer_sales(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    from inventory_flask_app.models import SaleTransaction, ProductInstance, Product
    sales = SaleTransaction.query.filter_by(customer_id=customer.id).order_by(SaleTransaction.date_sold.desc()).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales History"
    ws.append(['Date Sold', 'Serial Number', 'Product Name', 'Model Number', 'Status', 'Price', 'Notes'])
    for sale in sales:
        instance = ProductInstance.query.get(sale.product_instance_id)
        product = Product.query.get(instance.product_id) if instance else None
        ws.append([
            sale.date_sold.strftime('%Y-%m-%d') if sale.date_sold else '',
            instance.serial_number if instance else '',
            product.name if product else '',
            product.model_number if product else '',
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
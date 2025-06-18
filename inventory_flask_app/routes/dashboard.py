from flask import redirect, url_for
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from ..models import Product, ProductInstance
from sqlalchemy import func
from datetime import datetime, timedelta
from collections import defaultdict

dashboard_bp = Blueprint('dashboard_bp', __name__)

@dashboard_bp.route('/main_dashboard')
@login_required
def main_dashboard():
    from inventory_flask_app.models import ProductInstance

    model_filter = request.args.get('model')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Base query
    query = Product.query.filter_by(is_deleted=False)

    if model_filter:
        query = query.filter(Product.model_number == model_filter)

    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            query = query.filter(Product.created_at.between(start, end))
        except ValueError:
            start = None
            end = None
    else:
        start = None
        end = None

    products = query.all()

    # Stats
    total_products = len(products)
    total_stock = sum([p.stock or 0 for p in products])

    all_instances = ProductInstance.query.join(Product).filter(Product.is_deleted == False)
    if model_filter:
        all_instances = all_instances.filter(Product.model_number == model_filter)
    if start and end:
        all_instances = all_instances.filter(ProductInstance.created_at.between(start, end))

    instances = all_instances.all()

    # Total inventory available (all not-sold ProductInstance records)
    total_inventory = ProductInstance.query.filter_by(is_sold=False).count()

    total_instances = len(instances)
    sold_instances = sum(1 for i in instances if i.is_sold)
    unsold_instances = total_instances - sold_instances

    # Status-based breakdown (optional: add .status check if defined)
    unprocessed = sum(1 for i in instances if i.status == 'unprocessed')
    under_process = sum(1 for i in instances if i.status == 'under_process')
    processed = sum(1 for i in instances if i.status == 'processed')
    disputed = sum(1 for i in instances if i.status == 'disputed')

    analytic_overview = {
        "Unprocessed": unprocessed,
        "Under Process": under_process,
        "Processed": processed,
        "Disputed": disputed
    }

    # Top model aggregation
    model_counts = defaultdict(int)
    for i in instances:
        if i.product:
            model_counts[i.product.name] += 1
    top_models = sorted(
        [{'product_name': name, 'instance_count': count} for name, count in model_counts.items()],
        key=lambda x: x['instance_count'],
        reverse=True
    )[:5]

    # Unique model list for dropdown (only models present in current inventory instances)
    available_models = list(set(
        i.product.model_number
        for i in ProductInstance.query.join(Product).filter(Product.is_deleted == False).all()
        if i.product and i.product.model_number
    ))

    total_sales = ProductInstance.query.filter_by(is_sold=True).count()

    # Generate real sales data for the past 7 days for the "Sales" analytics chart
    today = datetime.utcnow().date()
    last_seven_days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    sales_by_day = []
    from inventory_flask_app.models import SaleTransaction
    for day in last_seven_days:
        count = SaleTransaction.query.filter(
            SaleTransaction.date_sold >= datetime.combine(day, datetime.min.time()),
            SaleTransaction.date_sold < datetime.combine(day + timedelta(days=1), datetime.min.time())
        ).count()
        sales_by_day.append(count)
    sales_chart_labels = [day.strftime("%a") for day in last_seven_days]
    sales_chart = {
        'labels': sales_chart_labels,
        'data': sales_by_day
    }

    return render_template('main_dashboard.html',
        total_products=total_products,
        total_sales=total_sales,
        total_stock=total_stock,
        total_instances=total_instances,
        sold_instances=sold_instances,
        unsold_instances=unsold_instances,
        unprocessed=unprocessed,
        under_process=under_process,
        processed=processed,
        disputed=disputed,
        top_models=top_models,
        available_models=available_models,
        total_inventory=total_inventory,
        analytic_overview=analytic_overview,
        sales_chart=sales_chart,
    )

@dashboard_bp.route('/')
def home_redirect():
    return redirect(url_for('dashboard_bp.main_dashboard'))


# API route to provide latest dashboard stats as JSON for AJAX updates
@dashboard_bp.route('/api/dashboard_stats')
@login_required
def dashboard_stats():
    unprocessed = ProductInstance.query.filter_by(status='unprocessed', is_sold=False).count()
    under_process = ProductInstance.query.filter_by(status='under_process', is_sold=False).count()
    processed = ProductInstance.query.filter_by(status='processed', is_sold=False).count()
    disputed = ProductInstance.query.filter_by(status='disputed', is_sold=False).count()
    sold_instances = ProductInstance.query.filter_by(is_sold=True).count()
    total_products = Product.query.filter_by(is_deleted=False).count()
    # You can adjust/add any other stats you want to update live

    return jsonify({
        "unprocessed": unprocessed,
        "under_process": under_process,
        "processed": processed,
        "disputed": disputed,
        "sold_instances": sold_instances,
        "total_products": total_products,
    })

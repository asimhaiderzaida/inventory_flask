from inventory_flask_app.models import ProductInstance
from inventory_flask_app.models import CustomerOrderTracking, Customer
from datetime import datetime
import pytz
from flask_login import current_user

def get_instance_id(serial):
    """Given a serial, return the ProductInstance ID (or None if not found)."""
    instance = ProductInstance.query.filter_by(serial=serial).first()
    return instance.id if instance else None

def get_now_for_tenant():
    """Return the current datetime localized to the tenant's timezone."""
    try:
        tz_name = current_user.tenant.timezone or 'UTC'
        return datetime.now(pytz.timezone(tz_name))
    except Exception:
        return datetime.utcnow()


# Inventory and order notifications for a tenant
from inventory_flask_app.models import Product, ProductInstance, SaleTransaction, User
from sqlalchemy import func
from datetime import timedelta

def get_inventory_notifications(tenant_id):
    now = get_now_for_tenant()
    aged_threshold = now - timedelta(days=60)
    slow_threshold = now - timedelta(days=3)

    notifications = []

    # Idle inventory
    idle_count = ProductInstance.query.join(Product).filter(
        ProductInstance.status == 'idle',
        Product.tenant_id == tenant_id
    ).count()
    if idle_count:
        notifications.append({
            "type": "idle_inventory",
            "label": f"{idle_count} idle unit{'s' if idle_count > 1 else ''}",
            "url": "/inventory/idle"
        })

    # Aged inventory
    aged_count = ProductInstance.query.join(Product).filter(
        ProductInstance.created_at < aged_threshold,
        Product.tenant_id == tenant_id
    ).count()
    if aged_count:
        notifications.append({
            "type": "aged_inventory",
            "label": f"{aged_count} aged unit{'s' if aged_count > 1 else ''} (60+ days)",
            "url": "/inventory/aged"
        })

    # Orders under process
    order_count = SaleTransaction.query.filter(
        SaleTransaction.customer_id.isnot(None),
        SaleTransaction.status != 'delivered',
        SaleTransaction.tenant_id == tenant_id
    ).count()
    if order_count:
        notifications.append({
            "type": "orders_processing",
            "label": f"{order_count} order{'s' if order_count > 1 else ''} under process",
            "url": "/orders/under-process"
        })

    # Slow technicians
    slow_techs = (
        ProductInstance.query
        .filter(ProductInstance.updated_at < slow_threshold)
        .join(Product)
        .filter(Product.tenant_id == tenant_id)
        .with_entities(ProductInstance.team_assigned)
        .group_by(ProductInstance.team_assigned)
        .all()
    )
    for tech in slow_techs:
        label = f"Technician {tech.team_assigned} has delayed units" if tech.team_assigned else "A technician has delayed units"
        notifications.append({
            "type": "slow_technician",
            "label": label,
            "url": f"/report/tech_profile/{tech.team_assigned}?slow=true" if tech.team_assigned else "/report/tech_profile"
        })

    # Pending orders (reserved but not delivered)
    pending_reserves = SaleTransaction.query.filter(
        SaleTransaction.status != 'delivered',
        SaleTransaction.tenant_id == tenant_id,
        SaleTransaction.customer_id.isnot(None)
    ).count()
    if pending_reserves:
        notifications.append({
            "type": "pending_orders",
            "label": f"{pending_reserves} pending order{'s' if pending_reserves > 1 else ''}",
            "url": "/orders/pending"
        })

    # Delayed orders (pending for more than 3 days)
    order_delay_threshold = now - timedelta(days=3)
    delayed_orders = CustomerOrderTracking.query \
        .join(Customer) \
        .filter(
            CustomerOrderTracking.status != 'delivered',
            CustomerOrderTracking.created_at < order_delay_threshold,
            Customer.tenant_id == tenant_id
        ).count()

    if delayed_orders:
        notifications.append({
            "type": "delayed_orders",
            "label": f"{delayed_orders} order{'s' if delayed_orders > 1 else ''} delayed > 3 days",
            "url": "/orders/pending"
        })

    return notifications
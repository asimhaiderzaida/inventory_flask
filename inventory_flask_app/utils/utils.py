

from inventory_flask_app.models import ProductInstance

def get_instance_id(serial_number):
    """Given a serial number, return the ProductInstance ID (or None if not found)."""
    instance = ProductInstance.query.filter_by(serial_number=serial_number).first()
    return instance.id if instance else None
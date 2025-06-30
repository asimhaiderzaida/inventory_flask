from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(db.Model, UserMixin):
    __table_args__ = (
        db.UniqueConstraint('username', 'tenant_id', name='uq_username_per_tenant'),
    )
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='staff')
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', name='fk_user_tenant_id'),
        nullable=True
    )
    tenant = db.relationship('Tenant', backref='users')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Tenant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    logo = db.Column(db.String(255))
    plan = db.Column(db.String(50), default='basic')
    timezone = db.Column(db.String(64), default='UTC')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Tenant {self.name}>"

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id'), nullable=True)
    tenant = db.relationship('Tenant', backref='customers')

class Vendor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    contact = db.Column(db.String(100))
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id'), nullable=True)
    tenant = db.relationship('Tenant', backref='vendors')

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id'), nullable=True)
    tenant = db.relationship('Tenant', backref='locations')

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset = db.Column(db.String(100), unique=True, nullable=True, index=True)
    serial = db.Column(db.String(100), unique=True, nullable=True, index=True)
    item_name = db.Column(db.String(100), nullable=False, index=True)
    make = db.Column(db.String(100))
    model = db.Column(db.String(100))
    display = db.Column(db.String(100))
    cpu = db.Column(db.String(100))
    ram = db.Column(db.String(100))
    gpu1 = db.Column(db.String(100))
    gpu2 = db.Column(db.String(100))
    disk1size = db.Column(db.String(100))
    grade = db.Column(db.String(20))
    stock = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'), nullable=True)
    vendor = db.relationship('Vendor', backref='products')
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=True)
    location = db.relationship('Location', backref='products')
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id'), nullable=True)
    tenant = db.relationship('Tenant', backref='products')

class ProductInstance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    serial = db.Column(db.String(100), unique=True, nullable=False, index=True)
    asset = db.Column(db.String(100), unique=True, index=True)

    status = db.Column(db.String(50), default='unprocessed')
    process_stage = db.Column(db.String(50))
    team_assigned = db.Column(db.String(100))
    idle_reason = db.Column(db.String(255))
    note = db.Column(db.Text)

    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    assigned_user = db.relationship('User', backref='assigned_instances')

    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    location_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    location = db.relationship('Location', backref='product_instances')

    shelf_bin = db.Column(db.String(64))
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'))
    po = db.relationship('PurchaseOrder', backref='instances')
    is_sold = db.Column(db.Boolean, default=False)

    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', name='fk_product_instance_tenant_id'),
        nullable=True
    )
    tenant = db.relationship('Tenant', backref='product_instances')

    product = db.relationship('Product', backref='product_instances')

class SaleTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    price_at_sale = db.Column(db.Float, nullable=False)
    date_sold = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=True)

    product_instance = db.relationship('ProductInstance', backref='sales')
    customer = db.relationship('Customer', backref='sales')
    user = db.relationship('User', backref='sales')

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False)
    total_amount = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('SaleItem', backref='sale', lazy=True)

class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=False)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id'), nullable=False)
    price_at_sale = db.Column(db.Float, nullable=False)
    vat_rate = db.Column(db.Float, default=5.0)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))

    invoice = db.relationship('Invoice', backref='sale_items')
    product_instance = db.relationship('ProductInstance', backref='sale_items')

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(20), unique=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='invoices')
    customer = db.relationship('Customer', backref='invoices')
    items = db.relationship('SaleTransaction', backref='invoice', lazy=True)

class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    po_number = db.Column(db.String(50), unique=True, nullable=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id'), nullable=True)
    expected_serials = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    vendor = db.relationship('Vendor')
    tenant = db.relationship('Tenant', backref='purchase_orders')

class CustomerOrderTracking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id'), nullable=False)

    status = db.Column(db.String(50), default='reserved')
    process_stage = db.Column(db.String(50))
    team_assigned = db.Column(db.String(100))
    reserved_date = db.Column(db.DateTime, default=datetime.utcnow)
    delivered_date = db.Column(db.DateTime)

    customer = db.relationship('Customer')
    product_instance = db.relationship('ProductInstance')

class ProductProcessLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id'), nullable=False)
    from_stage = db.Column(db.String(50))
    to_stage = db.Column(db.String(50))
    from_team = db.Column(db.String(100))
    to_team = db.Column(db.String(100))
    moved_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    moved_at = db.Column(db.DateTime, default=datetime.utcnow)
    action = db.Column(db.String(20))
    note = db.Column(db.String(200))

    product_instance = db.relationship('ProductInstance', backref='process_logs')
    user = db.relationship('User')

class POImportLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<POImportLog PO#{self.po_id} imported {self.quantity} as {self.status}>'

class Part(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    part_number = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    part_type = db.Column(db.String(64))
    vendor = db.Column(db.String(128))
    min_stock = db.Column(db.Integer, default=1)
    price = db.Column(db.Float)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id'), nullable=True)

    tenant = db.relationship('Tenant', backref='parts')
    stocks = db.relationship('PartStock', backref='part', lazy=True)

class PartStock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('part.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    quantity = db.Column(db.Integer, default=0)

    location = db.relationship('Location', backref='part_stocks')

    __table_args__ = (db.UniqueConstraint('part_id', 'location_id', name='uix_part_location'),)

class PartMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('part.id'))
    from_location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=True)
    to_location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=True)
    quantity = db.Column(db.Integer)
    movement_type = db.Column(db.String(32))
    note = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    part = db.relationship('Part', backref='movements')
    from_location = db.relationship('Location', foreign_keys=[from_location_id], backref='parts_moved_from')
    to_location = db.relationship('Location', foreign_keys=[to_location_id], backref='parts_moved_to')
    user = db.relationship('User', backref='part_movements')

class TenantSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id'), nullable=False)
    tenant = db.relationship('Tenant', backref='settings')
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.String(500), nullable=True)

    def __repr__(self):
        return f"<TenantSettings {self.key}={self.value} for Tenant {self.tenant_id}>"
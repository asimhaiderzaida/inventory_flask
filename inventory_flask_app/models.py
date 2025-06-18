from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='staff')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Vendor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    contact = db.Column(db.String(100))

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    barcode = db.Column(db.String(100), unique=True, nullable=False, index=True)
    model_number = db.Column(db.String(100), nullable=False)
    low_stock_threshold = db.Column(db.Integer, default=5)
    stock = db.Column(db.Integer, default=0)
    purchase_price = db.Column(db.Float, default=0.0)
    selling_price = db.Column(db.Float, default=0.0)
    warranty_date = db.Column(db.Date)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    ram = db.Column(db.String(50))
    processor = db.Column(db.String(50))
    storage = db.Column(db.String(50))
    screen_size = db.Column(db.String(50))
    resolution = db.Column(db.String(50))
    grade = db.Column(db.String(20))
    video_card = db.Column(db.String(50))
    image_url = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_damaged = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)

    vendor = db.relationship('Vendor', backref='products')
    location = db.relationship('Location', backref='products')

    # ❌ REMOVE THIS to fix the crash:
    # instances = db.relationship('ProductInstance', backref='product', lazy=True)

class ProductInstance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    serial_number = db.Column(db.String(100), unique=True, nullable=False, index=True)

    status = db.Column(db.String(50), default='unprocessed')
    process_stage = db.Column(db.String(50))
    team_assigned = db.Column(db.String(100))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    location_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    shelf_bin = db.Column(db.String(64))
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'))
    po = db.relationship('PurchaseOrder', backref='instances')
    is_sold = db.Column(db.Boolean, default=False)

    # ✅ Correct relationships with safe backref
    product = db.relationship('Product', backref='product_instances')
    location = db.relationship('Location', backref='product_instances')


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
    invoice_number = db.Column(db.String(20), unique=True)  # nullable removed
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('SaleTransaction', backref='invoice', lazy=True)
    customer = db.relationship('Customer', backref='invoices')

class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    po_number = db.Column(db.String(50), unique=True, nullable=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'), nullable=False)
    expected_serials = db.Column(db.Text)  # Comma-separated serials
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')

    vendor = db.relationship('Vendor')


class CustomerOrderTracking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id'), nullable=False)

    status = db.Column(db.String(50), default='reserved')  # reserved, under_process, ready, delivered
    process_stage = db.Column(db.String(50))               # specs, qc, etc.
    team_assigned = db.Column(db.String(100))
    reserved_date = db.Column(db.DateTime, default=datetime.utcnow)
    delivered_date = db.Column(db.DateTime)

    customer = db.relationship('Customer')
    product_instance = db.relationship('ProductInstance')

# --- Product process log model ---
class ProductProcessLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id'), nullable=False)
    from_stage = db.Column(db.String(50))
    to_stage = db.Column(db.String(50))
    from_team = db.Column(db.String(100))
    to_team = db.Column(db.String(100))
    moved_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    moved_at = db.Column(db.DateTime, default=datetime.utcnow)

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


# --- Product import helper ---
def add_product_and_instance(db, data):
    """
    Adds or reuses a Product and adds a ProductInstance.
    Expects `data` dict to include:
      name, model_number, serial_number, processor, ram, storage,
      screen_size, resolution, grade, video_card
    """
    # Check if Product exists by model_number, else create
    product = Product.query.filter_by(model_number=data.get('model_number')).first()
    if not product:
        product = Product(
            name=data.get('name'),
            model_number=data.get('model_number'),
            processor=data.get('processor'),
            ram=data.get('ram'),
            storage=data.get('storage'),
            screen_size=data.get('screen_size'),
            resolution=data.get('resolution'),
            grade=data.get('grade'),
            video_card=data.get('video_card'),
            barcode=data.get('model_number'),  # or any unique logic you prefer
        )
        db.session.add(product)
        db.session.flush()  # get product.id

    # Prevent duplicate instance
    instance = ProductInstance.query.filter_by(serial_number=data.get('serial_number')).first()
    if not instance:
        instance = ProductInstance(
            product_id=product.id,
            serial_number=data.get('serial_number'),
            status=data.get('status', 'unprocessed')
        )
        db.session.add(instance)
        db.session.flush()  # get instance.id

    return product, instance
print(">>> LOADED add_product_and_instance!")


# --- PARTS INVENTORY MODELS ---
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

    stocks = db.relationship('PartStock', backref='part', lazy=True)


class PartStock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('part.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    # Relationships
    location = db.relationship('Location', backref='part_stocks')
    __table_args__ = (db.UniqueConstraint('part_id', 'location_id', name='uix_part_location'),)


class PartMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('part.id'))
    from_location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=True)
    to_location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=True)
    quantity = db.Column(db.Integer)
    movement_type = db.Column(db.String(32))  # "stock_in", "consume", "sell", "transfer"
    note = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))  # Who did it (optional)
    part = db.relationship('Part', backref='movements')
    from_location = db.relationship('Location', foreign_keys=[from_location_id], backref='parts_moved_from')
    to_location = db.relationship('Location', foreign_keys=[to_location_id], backref='parts_moved_to')
    user = db.relationship('User', backref='part_movements')
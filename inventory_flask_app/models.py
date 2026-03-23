# Use the ONE shared SQLAlchemy instance for the whole app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from sqlalchemy.ext.hybrid import hybrid_property
from . import db
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='staff')
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE', name='fk_user_tenant_id'),
        nullable=False
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
    company = db.Column(db.String(120), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    portal_token = db.Column(db.String(48), unique=True, nullable=True, index=True)
    parts_balance = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False
    )
    tenant = db.relationship('Tenant', backref='customers')


class CustomerNote(db.Model):
    __tablename__ = 'customer_note'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=False)
    note = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='customer_notes')
    customer = db.relationship('Customer', backref='note_log')
    author = db.relationship('User', foreign_keys=[created_by])
    __table_args__ = (db.Index('ix_customer_note_customer', 'customer_id'),)


class CustomerCommunication(db.Model):
    __tablename__ = 'customer_communication'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=False)
    # invoice_email | portal_link | reservation_confirmation | ready_pickup
    type = db.Column(db.String(50), nullable=False)
    subject = db.Column(db.String(200), nullable=True)
    sent_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='customer_comms')
    customer = db.relationship('Customer', backref='communications')
    sender = db.relationship('User', foreign_keys=[sent_by])
    __table_args__ = (db.Index('ix_customer_comm_customer', 'customer_id'),)

class Vendor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)  # removed global unique
    contact = db.Column(db.String(100))
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    payment_terms = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False
    )
    tenant = db.relationship('Tenant', backref='vendors')


class VendorNote(db.Model):
    __tablename__ = 'vendor_note'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id', ondelete='CASCADE'), nullable=False)
    note = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='vendor_notes')
    vendor = db.relationship('Vendor', backref='note_log')
    author = db.relationship('User', foreign_keys=[created_by])
    __table_args__ = (db.Index('ix_vendor_note_vendor', 'vendor_id'),)

class Location(db.Model):
    __table_args__ = (
        db.UniqueConstraint('name', 'tenant_id', name='uq_location_name_per_tenant'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False
    )
    tenant = db.relationship('Tenant', backref='locations')


class Bin(db.Model):
    __tablename__ = 'bin'
    __table_args__ = (
        db.UniqueConstraint('name', 'location_id', 'tenant_id', name='uq_bin_name_location_tenant'),
    )
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(64), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='CASCADE'), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    bin_type    = db.Column(db.String(10), nullable=False, server_default='units', default='units')

    location = db.relationship('Location', backref='bins')
    tenant   = db.relationship('Tenant',   backref='bins')

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset = db.Column(db.String(100), unique=True, nullable=True, index=True)
    serial = db.Column(db.String(100), unique=True, nullable=True, index=True)
    item_name = db.Column(db.String(100), nullable=False, index=True)
    make = db.Column(db.String(100))
    model = db.Column(db.String(100))
    display = db.Column(db.String(100))
    cpu = db.Column(db.String(100))

    @hybrid_property
    def processor(self):
        return self.cpu

    @processor.expression
    def processor(cls):
        return cls.cpu

    ram = db.Column(db.String(100))
    gpu1 = db.Column(db.String(100))
    gpu2 = db.Column(db.String(100))
    disk1size = db.Column(db.String(100))
    grade = db.Column(db.String(20))
    # stock = db.Column(db.Integer, default=0)   ← REMOVED - use ProductInstance count instead
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id', ondelete='SET NULL'), nullable=True)
    vendor = db.relationship('Vendor', backref='products')
    location_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='SET NULL'), nullable=True)
    location = db.relationship('Location', backref='products')
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False
    )
    tenant = db.relationship('Tenant', backref='products')

class ProductInstance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id', ondelete='CASCADE'), nullable=False)
    serial = db.Column(db.String(100), unique=True, nullable=False, index=True)
    asset = db.Column(db.String(100), unique=True, index=True)
    status = db.Column(db.String(50), default='unprocessed')
    process_stage = db.Column(db.String(50))
    team_assigned = db.Column(db.String(100))
    idle_reason = db.Column(db.String(255))
    note = db.Column(db.Text)
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    assigned_user = db.relationship('User', backref='assigned_instances')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='SET NULL'))
    location = db.relationship('Location', backref='product_instances')
    shelf_bin = db.Column(db.String(64))   # kept in sync with bin.name for backward compat
    bin_id = db.Column(db.Integer, db.ForeignKey('bin.id', ondelete='SET NULL'), nullable=True)
    bin = db.relationship('Bin', backref='product_instances')
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id', ondelete='SET NULL'))
    po = db.relationship('PurchaseOrder', backref='instances')
    is_sold = db.Column(db.Boolean, default=False)
    shopify_listed = db.Column(db.Boolean, default=False, nullable=False)
    asking_price = db.Column(db.Float, nullable=True)
    entered_stage_at = db.Column(db.DateTime, nullable=True)  # timestamp when current stage began
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE', name='fk_product_instance_tenant_id'),
        nullable=False
    )
    tenant = db.relationship('Tenant', backref='product_instances')
    product = db.relationship('Product', backref='product_instances')
    sale_items = db.relationship(
        'SaleItem',
        back_populates='product_instance',
        foreign_keys='SaleItem.product_instance_id',
        cascade='all, delete-orphan'
    )

    __table_args__ = (
        db.Index('ix_pi_tenant_sold_status', 'tenant_id', 'is_sold', 'status'),
    )

    @hybrid_property
    def bin_name(self):
        """Display name: structured bin.name if linked, else free-text shelf_bin."""
        return self.bin.name if self.bin else (self.shelf_bin or None)

    def __init__(self, **kwargs):
        """Backward-compat shim: accept legacy kwargs used by older code paths."""
        if 'serial_number' in kwargs and 'serial' not in kwargs:
            kwargs['serial'] = kwargs.pop('serial_number')
        if 'asset_tag' in kwargs and 'asset' not in kwargs:
            kwargs['asset'] = kwargs.pop('asset_tag')
        super().__init__(**kwargs)

# ────────────────────────────────────────────────
# The rest of your models remain almost unchanged
# ────────────────────────────────────────────────

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    customer = db.relationship('Customer', backref='orders')
    user = db.relationship('User')
    tenant = db.relationship('Tenant')
    sale_transactions = db.relationship('SaleTransaction', backref='order')

class SaleTransaction(db.Model):
    __table_args__ = (
        db.Index('ix_sale_transaction_customer_id', 'customer_id'),
    )
    id = db.Column(db.Integer, primary_key=True)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id', ondelete='CASCADE'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    price_at_sale = db.Column(db.Float, nullable=False)
    date_sold = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    payment_method = db.Column(db.String(16), nullable=True)   # cash/card/transfer/credit
    payment_status = db.Column(db.String(16), nullable=True, default='paid')
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id', ondelete='SET NULL'), nullable=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id', ondelete='SET NULL'), nullable=True)
    product_instance = db.relationship('ProductInstance', backref='sales')
    customer = db.relationship('Customer', backref='sales')
    user = db.relationship('User', backref='sales')
    items = db.relationship(
        'SaleItem',
        back_populates='sale_transaction',
        foreign_keys='SaleItem.sale_id',
        cascade='all, delete-orphan'
    )

class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale_transaction.id', ondelete='CASCADE'), nullable=False)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id', ondelete='CASCADE'), nullable=False)
    price_at_sale = db.Column(db.Float, nullable=False)
    vat_rate = db.Column(db.Float, default=5.0)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id', ondelete='SET NULL'))
    invoice = db.relationship('Invoice', backref='sale_items')
    product_instance = db.relationship(
        'ProductInstance',
        back_populates='sale_items',
        foreign_keys=[product_instance_id]
    )
    sale_transaction = db.relationship(
        'SaleTransaction',
        back_populates='items',
        foreign_keys=[sale_id]
    )

class Invoice(db.Model):
    __table_args__ = (
        db.UniqueConstraint('invoice_number', 'tenant_id', name='uix_invoice_number_tenant'),
    )
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(20))
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    email_sent_at = db.Column(db.DateTime, nullable=True)
    payment_method = db.Column(db.String(16), nullable=True)   # cash/card/transfer/credit
    payment_status = db.Column(db.String(16), nullable=True, default='paid')
    tenant = db.relationship('Tenant', backref='invoices')
    customer = db.relationship('Customer', backref='invoices')
    user = db.relationship('User', backref='invoices')
    items = db.relationship('SaleTransaction', backref='invoice', lazy=True)

class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    po_number = db.Column(db.String(50), unique=True, nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id', ondelete='SET NULL'), nullable=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False
    )
    location_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='SET NULL'), nullable=True)
    # expected_serials kept for backward compatibility with old POs; new POs use PurchaseOrderItem rows
    expected_serials = db.Column(db.Text)
    # status: pending | partial | received | cancelled
    status = db.Column(db.String(20), default='pending')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    vendor = db.relationship('Vendor')
    location = db.relationship('Location', foreign_keys=[location_id])
    tenant = db.relationship('Tenant', backref='purchase_orders')
    items = db.relationship('PurchaseOrderItem', backref='po', cascade='all, delete-orphan', lazy='dynamic')


class PurchaseOrderItem(db.Model):
    """One row per expected unit on a PurchaseOrder."""
    __tablename__ = 'purchase_order_item'
    id          = db.Column(db.Integer, primary_key=True)
    po_id       = db.Column(db.Integer, db.ForeignKey('purchase_order.id', ondelete='CASCADE'), nullable=False, index=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    # Identifiers
    serial      = db.Column(db.String(100), nullable=False, index=True)
    asset_tag   = db.Column(db.String(100), nullable=True, index=True)
    # Spec fields (all optional except serial)
    item_name   = db.Column(db.String(100))
    make        = db.Column(db.String(100))
    model       = db.Column(db.String(100))
    display     = db.Column(db.String(100))
    cpu         = db.Column(db.String(100))
    ram         = db.Column(db.String(100))
    gpu1        = db.Column(db.String(100))
    gpu2        = db.Column(db.String(100))
    grade       = db.Column(db.String(20))
    disk1size   = db.Column(db.String(100))
    location_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='SET NULL'), nullable=True)
    # Receiving status: expected | received | missing | extra
    status      = db.Column(db.String(20), nullable=False, default='expected')
    received_at = db.Column(db.DateTime, nullable=True)
    notes       = db.Column(db.Text, nullable=True)
    location    = db.relationship('Location', foreign_keys=[location_id])
    tenant      = db.relationship('Tenant')

class CustomerOrderTracking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=False)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id', ondelete='CASCADE'), nullable=False)
    status = db.Column(db.String(50), default='reserved')
    process_stage = db.Column(db.String(50))
    team_assigned = db.Column(db.String(100))
    reserved_date = db.Column(db.DateTime, default=datetime.utcnow)
    delivered_date = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    reserved_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    delivered_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    was_shopify_listed = db.Column(db.Boolean, default=False, nullable=False)
    current_stage = db.Column(db.String(100), nullable=True)
    stage_updated_at = db.Column(db.DateTime, nullable=True)
    stage_history = db.Column(db.Text, nullable=True)  # JSON array of stage changes
    customer = db.relationship('Customer')
    product_instance = db.relationship('ProductInstance')
    cancelled_by = db.relationship('User', foreign_keys=[cancelled_by_user_id])
    reserved_by = db.relationship('User', foreign_keys=[reserved_by_user_id])
    delivered_by = db.relationship('User', foreign_keys=[delivered_by_user_id])

class ProductProcessLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id', ondelete='CASCADE'), nullable=False)
    from_stage = db.Column(db.String(50))
    to_stage = db.Column(db.String(50))
    from_team = db.Column(db.String(100))
    to_team = db.Column(db.String(100))
    moved_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    moved_at = db.Column(db.DateTime, default=datetime.utcnow)
    action = db.Column(db.String(50))
    note = db.Column(db.String(200))
    duration_minutes = db.Column(db.Integer, nullable=True)  # time spent in previous stage
    product_instance = db.relationship('ProductInstance', backref='process_logs')
    user = db.relationship('User')

class ProcessStage(db.Model):
    """Tenant-configurable ordered list of processing stages."""
    __tablename__ = 'process_stage'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(80), nullable=False)
    order      = db.Column(db.Integer, default=0)
    color      = db.Column(db.String(20), default='#6b7280')
    sla_hours  = db.Column(db.Integer, default=24)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    tenant     = db.relationship('Tenant', backref='process_stages')
    __table_args__ = (
        db.Index('ix_process_stage_tenant', 'tenant_id'),
    )

    def __repr__(self):
        return f"<ProcessStage {self.name}>"


class POImportLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<POImportLog PO#{self.po_id} imported {self.quantity} as {self.status}>'

class Part(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    part_number = db.Column(db.String(64), nullable=False, index=True)  # unique per tenant via __table_args__
    name = db.Column(db.String(128), nullable=False)
    part_type = db.Column(db.String(64))
    vendor = db.Column(db.String(128))          # free-text fallback; use vendor_rel for FK link
    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey('vendor.id', ondelete='SET NULL'),
        nullable=True
    )
    min_stock = db.Column(db.Integer, default=1)
    price = db.Column(db.Float)
    description = db.Column(db.Text)
    barcode = db.Column(db.String(100), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False
    )
    tenant = db.relationship('Tenant', backref='parts')
    vendor_rel = db.relationship('Vendor', foreign_keys=[vendor_id], backref='parts')
    stocks = db.relationship('PartStock', backref='part', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('part_number', 'tenant_id', name='uix_part_number_tenant'),
        db.Index('uix_part_barcode_tenant', 'barcode', 'tenant_id',
                 unique=True, postgresql_where=db.text('barcode IS NOT NULL')),
    )

class PartStock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('part.id', ondelete='CASCADE'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='CASCADE'), nullable=False)
    bin_id = db.Column(db.Integer, db.ForeignKey('bin.id', ondelete='SET NULL'), nullable=True)
    quantity = db.Column(db.Integer, default=0)
    location = db.relationship('Location', backref='part_stocks')
    bin = db.relationship('Bin', backref='part_stocks')

    __table_args__ = (
        # Two partial unique indexes handle NULL bin_id correctly in PostgreSQL:
        # one for unlabelled stock (bin_id IS NULL), one for bin-specific stock.
        db.Index('uix_part_stock_no_bin', 'part_id', 'location_id',
                 unique=True, postgresql_where=db.text('bin_id IS NULL')),
        db.Index('uix_part_stock_with_bin', 'part_id', 'location_id', 'bin_id',
                 unique=True, postgresql_where=db.text('bin_id IS NOT NULL')),
    )

class PartMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('part.id', ondelete='CASCADE'))
    from_location_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='SET NULL'), nullable=True)
    to_location_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='SET NULL'), nullable=True)
    from_bin_id = db.Column(db.Integer, db.ForeignKey('bin.id', ondelete='SET NULL'), nullable=True)
    to_bin_id = db.Column(db.Integer, db.ForeignKey('bin.id', ondelete='SET NULL'), nullable=True)
    quantity = db.Column(db.Integer)
    movement_type = db.Column(db.String(32))
    note = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    instance_id = db.Column(
        db.Integer,
        db.ForeignKey('product_instance.id', ondelete='SET NULL'),
        nullable=True
    )
    part = db.relationship('Part', backref='movements')
    from_location = db.relationship('Location', foreign_keys=[from_location_id], backref='parts_moved_from')
    to_location = db.relationship('Location', foreign_keys=[to_location_id], backref='parts_moved_to')
    from_bin = db.relationship('Bin', foreign_keys=[from_bin_id], backref='parts_moved_from_bin')
    to_bin = db.relationship('Bin', foreign_keys=[to_bin_id], backref='parts_moved_to_bin')
    user = db.relationship('User', backref='part_movements')
    instance = db.relationship('ProductInstance', backref='part_movements')

class PartUsage(db.Model):
    """Records a part consumed on a specific unit by a technician."""
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('part.id', ondelete='CASCADE'), nullable=False, index=True)
    instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id', ondelete='SET NULL'), nullable=True, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    used_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    used_at = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.String(256))
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    part = db.relationship('Part', backref='usages')
    instance = db.relationship('ProductInstance', backref='part_usages')
    user = db.relationship('User', foreign_keys=[used_by], backref='part_usages')
    tenant = db.relationship('Tenant', backref='part_usages')


class PartSale(db.Model):
    """Legacy model — superseded by PartSaleTransaction. Do not write to this table.
    Kept to avoid breaking existing migrations and any historical data."""
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('part.id', ondelete='CASCADE'), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='SET NULL'), nullable=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='SET NULL'), nullable=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=True)   # price at time of sale
    note = db.Column(db.String(256))
    sold_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    sold_at = db.Column(db.DateTime, default=datetime.utcnow)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    part = db.relationship('Part', backref='sales')
    location = db.relationship('Location', backref='part_sales')
    customer = db.relationship('Customer', backref='part_sales')
    user = db.relationship('User', foreign_keys=[sold_by], backref='part_sales')
    tenant = db.relationship('Tenant', backref='part_sales')


class PartSaleTransaction(db.Model):
    """Full parts sale transaction — supports invoice, multi-item cart, credit."""
    __tablename__ = 'part_sale_transaction'
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(20), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='SET NULL'), nullable=True)
    customer_name = db.Column(db.String(128), nullable=True)  # walk-in fallback
    sale_id = db.Column(db.Integer, db.ForeignKey('sale_transaction.id', ondelete='SET NULL'), nullable=True)
    payment_method = db.Column(db.String(16), nullable=False, default='cash')   # cash/card/credit
    payment_status = db.Column(db.String(16), nullable=False, default='paid')   # paid/pending
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    tax = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    sold_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    sold_at = db.Column(db.DateTime, default=datetime.utcnow)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    customer = db.relationship('Customer', backref='part_sale_transactions')
    seller = db.relationship('User', foreign_keys=[sold_by], backref='part_sale_transactions')
    tenant = db.relationship('Tenant', backref='part_sale_transactions')
    linked_sale = db.relationship('SaleTransaction', foreign_keys=[sale_id], backref='part_sale_txns')
    line_items = db.relationship('PartSaleItem', backref='transaction', cascade='all, delete-orphan')
    __table_args__ = (
        db.UniqueConstraint('invoice_number', 'tenant_id', name='uix_part_invoice_tenant'),
        db.Index('ix_pst_tenant_date', 'tenant_id', 'sold_at'),
    )


class PartSaleItem(db.Model):
    """One line item within a PartSaleTransaction."""
    __tablename__ = 'part_sale_item'
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('part_sale_transaction.id', ondelete='CASCADE'), nullable=False)
    part_id = db.Column(db.Integer, db.ForeignKey('part.id', ondelete='CASCADE'), nullable=False)
    bin_id = db.Column(db.Integer, db.ForeignKey('bin.id', ondelete='SET NULL'), nullable=True)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id', ondelete='SET NULL'), nullable=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    part = db.relationship('Part', backref='sale_items')
    bin = db.relationship('Bin', backref='part_sale_items')
    location = db.relationship('Location', backref='part_sale_items')
    tenant = db.relationship('Tenant', backref='part_sale_items')
    __table_args__ = (
        db.Index('ix_psi_transaction_id', 'transaction_id'),
        db.Index('ix_psi_part_id', 'part_id'),
    )


class Return(db.Model):
    __tablename__ = 'returns'
    id = db.Column(db.Integer, primary_key=True)
    # return_type: 'unit' or 'part'
    return_type = db.Column(db.String(10), nullable=False, default='unit')
    # Unit return fields
    instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id', ondelete='SET NULL'), nullable=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id', ondelete='SET NULL'), nullable=True)
    order_id = db.Column(db.Integer, db.ForeignKey('customer_order_tracking.id', ondelete='SET NULL'), nullable=True)
    # Parts return fields
    part_id = db.Column(db.Integer, db.ForeignKey('part.id', ondelete='SET NULL'), nullable=True)
    part_quantity = db.Column(db.Integer, nullable=True)
    part_sale_id = db.Column(db.Integer, db.ForeignKey('part_sale_transaction.id', ondelete='SET NULL'), nullable=True)
    # Common fields
    return_date = db.Column(db.DateTime, default=datetime.utcnow)
    reason = db.Column(db.String(255))
    condition = db.Column(db.String(50))
    action = db.Column(db.String(50))
    action_taken = db.Column(db.String(255))  # free-text resolution note
    notes = db.Column(db.Text)
    # Refund / credit
    refund_amount = db.Column(db.Numeric(10, 2), nullable=True)
    refund_method = db.Column(db.String(32), nullable=True)   # cash/card/credit_note/none
    refund_status = db.Column(db.String(16), nullable=False, default='pending')  # pending/issued/denied
    credit_note_number = db.Column(db.String(32), nullable=True)
    credit_note_issued_at = db.Column(db.DateTime, nullable=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    instance = db.relationship('ProductInstance', backref='returns')
    part = db.relationship('Part', backref='returns')
    invoice = db.relationship('Invoice', backref='returns')
    part_sale = db.relationship('PartSaleTransaction', foreign_keys=[part_sale_id], backref='returns')
    credit_notes = db.relationship('CreditNote', backref='return_record', cascade='all, delete-orphan')
    tenant = db.relationship('Tenant', backref='returns')


class CreditNote(db.Model):
    """Formal credit note issued to a customer upon a return."""
    __tablename__ = 'credit_note'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False, index=True)
    return_id = db.Column(db.Integer, db.ForeignKey('returns.id', ondelete='CASCADE'), nullable=False)
    credit_note_number = db.Column(db.String(32), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='SET NULL'), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='USD')
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    issued_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    # Application tracking: unapplied / applied / void
    status = db.Column(db.String(20), nullable=False, default='unapplied')
    applied_to_ar_id = db.Column(db.Integer, db.ForeignKey('account_receivable.id', ondelete='SET NULL'), nullable=True)
    applied_amount = db.Column(db.Numeric(10, 2), nullable=True)
    applied_at = db.Column(db.DateTime, nullable=True)
    applied_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    customer = db.relationship('Customer', backref='credit_notes')
    issuer = db.relationship('User', foreign_keys=[issued_by], backref='credit_notes')
    applier = db.relationship('User', foreign_keys=[applied_by], backref='credit_notes_applied')
    applied_ar = db.relationship('AccountReceivable', foreign_keys=[applied_to_ar_id], backref='credit_note_applications')
    tenant = db.relationship('Tenant', backref='credit_notes')
    __table_args__ = (
        db.UniqueConstraint('credit_note_number', 'tenant_id', name='uix_credit_note_tenant'),
        db.Index('ix_credit_note_tenant', 'tenant_id'),
    )

class TenantSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenant.id', ondelete='CASCADE'),
        nullable=False
    )
    tenant = db.relationship('Tenant', backref='settings')
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.String(500), nullable=True)

    def __repr__(self):
        return f"<TenantSettings {self.key}={self.value} for Tenant {self.tenant_id}>"


# ─────────────────────────────────────────────────────────────
# ACCOUNTING MODELS
# ─────────────────────────────────────────────────────────────

class ExpenseCategory(db.Model):
    """Per-tenant expense categories (pre-seeded + custom)."""
    __tablename__ = 'expense_category'
    __table_args__ = (
        db.UniqueConstraint('slug', 'tenant_id', name='uq_expense_category_slug_tenant'),
        db.Index('ix_expense_category_tenant', 'tenant_id'),
    )
    id        = db.Column(db.Integer, primary_key=True)
    name      = db.Column(db.String(80), nullable=False)
    slug      = db.Column(db.String(80), nullable=False)
    icon      = db.Column(db.String(50), default='bi-receipt')
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    tenant    = db.relationship('Tenant', backref='expense_categories')
    expenses  = db.relationship('Expense', backref='category', lazy='dynamic')

    def __repr__(self):
        return f"<ExpenseCategory {self.name}>"


# Default categories seeded per tenant on first access
EXPENSE_CATEGORY_DEFAULTS = [
    ('Salaries',              'salaries',           'bi-person-badge'),
    ('Rent & Utilities',      'rent-utilities',     'bi-building'),
    ('Shipping & Logistics',  'shipping-logistics', 'bi-truck'),
    ('Repair Consumables',    'repair-consumables', 'bi-tools'),
    ('Equipment & Tools',     'equipment-tools',    'bi-wrench'),
    ('Marketing & Advertising','marketing-advertising','bi-megaphone'),
    ('Stock Purchases',       'stock-purchases',    'bi-box-arrow-in-down'),
    ('Other',                 'other',              'bi-three-dots'),
]


class Expense(db.Model):
    """Manual expense record entered by staff."""
    __tablename__ = 'expense'
    id             = db.Column(db.Integer, primary_key=True)
    tenant_id      = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    category_id    = db.Column(db.Integer, db.ForeignKey('expense_category.id', ondelete='SET NULL'), nullable=True)
    amount         = db.Column(db.Numeric(10, 2), nullable=False)
    currency       = db.Column(db.String(10), default='AED')
    description    = db.Column(db.String(255), nullable=False)
    reference      = db.Column(db.String(100), nullable=True)   # invoice/receipt ref
    expense_date   = db.Column(db.Date, nullable=False)
    payment_method = db.Column(db.String(20), default='cash')   # cash/card/bank_transfer
    paid_by        = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    vendor_id      = db.Column(db.Integer, db.ForeignKey('vendor.id', ondelete='SET NULL'), nullable=True)
    po_id          = db.Column(db.Integer, db.ForeignKey('purchase_order.id', ondelete='SET NULL'), nullable=True)
    receipt_url    = db.Column(db.String(255), nullable=True)
    notes          = db.Column(db.Text, nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    created_by     = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    deleted_at     = db.Column(db.DateTime, nullable=True)      # soft delete

    tenant  = db.relationship('Tenant', backref='expenses')
    payer   = db.relationship('User', foreign_keys=[paid_by],   backref='expenses_paid')
    creator = db.relationship('User', foreign_keys=[created_by], backref='expenses_created')
    vendor  = db.relationship('Vendor', backref='expenses')
    po      = db.relationship('PurchaseOrder', backref='expenses')
    __table_args__ = (
        db.Index('ix_expense_tenant_date', 'tenant_id', 'expense_date'),
    )

    def __repr__(self):
        return f"<Expense {self.description} {self.amount}>"


class AccountReceivable(db.Model):
    """Outstanding balance owed by a customer against an invoice/order."""
    __tablename__ = 'account_receivable'
    id           = db.Column(db.Integer, primary_key=True)
    tenant_id    = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    customer_id  = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=False)
    invoice_id   = db.Column(db.Integer, db.ForeignKey('invoice.id', ondelete='SET NULL'), nullable=True)
    sale_id      = db.Column(db.Integer, db.ForeignKey('order.id', ondelete='SET NULL'), nullable=True)
    amount_due   = db.Column(db.Numeric(10, 2), nullable=False)
    amount_paid  = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    currency     = db.Column(db.String(10), default='AED')
    due_date     = db.Column(db.Date, nullable=True)
    # open / partial / paid / overdue / written_off
    status       = db.Column(db.String(20), default='open', nullable=False)
    notes        = db.Column(db.Text, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant   = db.relationship('Tenant', backref='receivables')
    customer = db.relationship('Customer', backref='receivables')
    invoice  = db.relationship('Invoice', backref='receivable', uselist=False)
    order    = db.relationship('Order', backref='receivable', foreign_keys=[sale_id], uselist=False)
    payments = db.relationship('ARPayment', backref='ar', cascade='all, delete-orphan',
                               order_by='ARPayment.payment_date')
    __table_args__ = (
        db.Index('ix_ar_customer', 'customer_id'),
        db.Index('ix_ar_tenant_status', 'tenant_id', 'status'),
    )

    @property
    def balance(self):
        return float(self.amount_due or 0) - float(self.amount_paid or 0)

    @property
    def is_overdue(self):
        from datetime import date as _date
        return (self.due_date and self.due_date < _date.today()
                and self.status not in ('paid', 'written_off'))

    @property
    def days_overdue(self):
        from datetime import date as _date
        if not self.is_overdue:
            return 0
        return (_date.today() - self.due_date).days

    def __repr__(self):
        return f"<AR customer={self.customer_id} due={self.amount_due} status={self.status}>"


class ARPayment(db.Model):
    """A payment recorded against an AccountReceivable."""
    __tablename__ = 'ar_payment'
    id             = db.Column(db.Integer, primary_key=True)
    tenant_id      = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    ar_id          = db.Column(db.Integer, db.ForeignKey('account_receivable.id', ondelete='CASCADE'), nullable=False)
    amount         = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(20), default='cash')   # cash/card/bank_transfer
    payment_date   = db.Column(db.Date, nullable=False)
    reference      = db.Column(db.String(100), nullable=True)
    recorded_by    = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    notes          = db.Column(db.Text, nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    tenant   = db.relationship('Tenant', backref='ar_payments')
    recorder = db.relationship('User', backref='ar_payments_recorded')
    __table_args__ = (
        db.Index('ix_ar_payment_ar', 'ar_id'),
    )

    def __repr__(self):
        return f"<ARPayment ar={self.ar_id} amount={self.amount}>"


class OtherIncome(db.Model):
    """Miscellaneous income not from unit or parts sales."""
    __tablename__ = 'other_income'
    id           = db.Column(db.Integer, primary_key=True)
    tenant_id    = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    amount       = db.Column(db.Numeric(10, 2), nullable=False)
    currency     = db.Column(db.String(10), default='AED')
    description  = db.Column(db.String(255), nullable=False)
    income_date  = db.Column(db.Date, nullable=False)
    reference    = db.Column(db.String(100), nullable=True)
    notes        = db.Column(db.Text, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    created_by   = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    deleted_at   = db.Column(db.DateTime, nullable=True)        # soft delete

    tenant   = db.relationship('Tenant', backref='other_incomes')
    creator  = db.relationship('User', backref='other_incomes_created')
    __table_args__ = (
        db.Index('ix_other_income_tenant_date', 'tenant_id', 'income_date'),
    )

    def __repr__(self):
        return f"<OtherIncome {self.description} {self.amount}>"


class CustomField(db.Model):
    """Admin-defined extra fields for ProductInstance, scoped per tenant."""
    __tablename__ = 'custom_field'
    id              = db.Column(db.Integer, primary_key=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    field_key       = db.Column(db.String(50), nullable=False)
    field_label     = db.Column(db.String(100), nullable=False)
    field_type      = db.Column(db.String(20), nullable=False, default='text')  # text/number/select/date
    field_options   = db.Column(db.Text, nullable=True)   # JSON array of strings for select type
    is_required     = db.Column(db.Boolean, default=False, nullable=False)
    show_in_list    = db.Column(db.Boolean, default=False, nullable=False)
    show_in_invoice = db.Column(db.Boolean, default=False, nullable=False)
    sort_order      = db.Column(db.Integer, default=0, nullable=False)

    tenant = db.relationship('Tenant', backref='custom_fields')
    values = db.relationship('CustomFieldValue', backref='field', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'field_key', name='uq_custom_field_tenant_key'),
        db.Index('ix_custom_field_tenant', 'tenant_id'),
    )

    def __repr__(self):
        return f"<CustomField {self.field_key}>"


class CustomFieldValue(db.Model):
    """Stores the value of a CustomField for a specific ProductInstance."""
    __tablename__ = 'custom_field_value'
    id          = db.Column(db.Integer, primary_key=True)
    tenant_id   = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id', ondelete='CASCADE'), nullable=False)
    field_id    = db.Column(db.Integer, db.ForeignKey('custom_field.id', ondelete='CASCADE'), nullable=False)
    value       = db.Column(db.Text, nullable=True)

    tenant = db.relationship('Tenant', backref='custom_field_values')

    __table_args__ = (
        db.UniqueConstraint('instance_id', 'field_id', name='uq_cfv_instance_field'),
        db.Index('ix_cfv_instance', 'instance_id'),
    )

    def __repr__(self):
        return f"<CustomFieldValue field={self.field_id} instance={self.instance_id}>"


class Notification(db.Model):
    """Per-user in-app notifications (reassigned, sla_breach, stage_move, disputed)."""
    __tablename__ = 'notification'
    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    type       = db.Column(db.String(50), nullable=False)   # reassigned | sla_breach | stage_move | disputed
    title      = db.Column(db.String(200), nullable=False)
    message    = db.Column(db.Text, nullable=False)
    link       = db.Column(db.String(255), nullable=True)
    is_read    = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    tenant = db.relationship('Tenant', backref='notifications')
    user   = db.relationship('User',   backref='notifications')

    __table_args__ = (
        db.Index('ix_notification_user_read', 'user_id', 'is_read'),
        db.Index('ix_notification_tenant',    'tenant_id'),
    )

    def __repr__(self):
        return f"<Notification {self.type} user={self.user_id} read={self.is_read}>"


# ─────────────────────────────────────────────────────────────
# SHOPIFY INTEGRATION MODELS
# ─────────────────────────────────────────────────────────────

class ShopifyProduct(db.Model):
    """Maps a PCMart product key (make_model_grade) to Shopify IDs."""
    __tablename__ = 'shopify_product'
    id                       = db.Column(db.Integer, primary_key=True)
    tenant_id                = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    product_key              = db.Column(db.String(200))        # e.g. Dell_Latitude_5520_A
    shopify_product_id       = db.Column(db.String(50))
    shopify_variant_id       = db.Column(db.String(50))
    shopify_inventory_item_id= db.Column(db.String(50))
    shopify_location_id      = db.Column(db.String(50))         # Shopify fulfilment location
    sync_status              = db.Column(db.String(20), default='synced')
    sync_error               = db.Column(db.Text, nullable=True)
    last_synced_at           = db.Column(db.DateTime, nullable=True)
    created_at               = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    tenant = db.relationship('Tenant', backref='shopify_products')

    __table_args__ = (
        db.Index('ix_shopify_product_tenant_key', 'tenant_id', 'product_key'),
    )

    def __repr__(self):
        return f"<ShopifyProduct {self.product_key} pid={self.shopify_product_id}>"


class ShopifySyncLog(db.Model):
    """Audit log for every Shopify push/pull action."""
    __tablename__ = 'shopify_sync_log'
    id         = db.Column(db.Integer, primary_key=True)
    tenant_id  = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    action     = db.Column(db.String(50))       # publish | unpublish | webhook_order | etc.
    direction  = db.Column(db.String(10))       # push | pull
    status     = db.Column(db.String(20))       # success | error
    details    = db.Column(db.Text)
    shopify_id = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    tenant = db.relationship('Tenant', backref='shopify_sync_logs')

    __table_args__ = (
        db.Index('ix_shopify_sync_log_tenant', 'tenant_id', 'created_at'),
    )

    def __repr__(self):
        return f"<ShopifySyncLog {self.action} {self.status}>"


class ShopifyOrder(db.Model):
    """A Shopify order received via webhook, pending review by staff."""
    __tablename__ = 'shopify_order'
    id                   = db.Column(db.Integer, primary_key=True)
    tenant_id            = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False)
    shopify_order_id     = db.Column(db.String(50), unique=True, nullable=False)
    shopify_order_number = db.Column(db.String(50))
    customer_id          = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='SET NULL'), nullable=True)
    # draft | confirmed | rejected | cancelled
    status               = db.Column(db.String(20), default='draft')
    total_price          = db.Column(db.Numeric(10, 2))
    currency             = db.Column(db.String(10))
    payment_method       = db.Column(db.String(50))
    shopify_data         = db.Column(db.Text)   # full JSON from Shopify
    order_id             = db.Column(db.Integer, db.ForeignKey('order.id', ondelete='SET NULL'), nullable=True)
    created_at           = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    processed_at         = db.Column(db.DateTime, nullable=True)
    processed_by         = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    tenant     = db.relationship('Tenant',   backref='shopify_orders')
    customer   = db.relationship('Customer', backref='shopify_orders')
    order      = db.relationship('Order',    backref='shopify_order', uselist=False)
    processor  = db.relationship('User',     foreign_keys=[processed_by], backref='shopify_orders_processed')

    __table_args__ = (
        db.Index('ix_shopify_order_tenant_status', 'tenant_id', 'status'),
    )

    def __repr__(self):
        return f"<ShopifyOrder #{self.shopify_order_number} status={self.status}>"


class CustomerOrder(db.Model):
    """Customer purchase order — tracks what a customer wants to buy."""
    __tablename__ = 'customer_order'

    id              = db.Column(db.Integer, primary_key=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('tenant.id', ondelete='CASCADE'),
                                nullable=False, index=True)
    customer_id     = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='SET NULL'),
                                nullable=True)
    customer_name   = db.Column(db.String(120), nullable=False)
    model_description = db.Column(db.String(255), nullable=False)
    quantity        = db.Column(db.Integer, default=1, nullable=False)
    expected_price  = db.Column(db.Numeric(10, 2), nullable=True)
    total_budget    = db.Column(db.Numeric(10, 2), nullable=True)
    delivery_date   = db.Column(db.Date, nullable=True)
    deposit_amount  = db.Column(db.Numeric(10, 2), nullable=True)
    deposit_paid    = db.Column(db.Boolean, default=False, nullable=False)
    payment_status  = db.Column(db.String(20), default='none', nullable=False)
    status          = db.Column(db.String(20), default='open', nullable=False, index=True)
    notes           = db.Column(db.Text, nullable=True)
    created_by      = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'),
                                nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed_at       = db.Column(db.DateTime, nullable=True)

    customer = db.relationship('Customer', backref='purchase_orders', lazy='select')
    creator  = db.relationship('User',     backref='created_purchase_orders', lazy='select')

    __table_args__ = (
        db.Index('ix_customer_order_tenant_status', 'tenant_id', 'status'),
    )

    def __repr__(self):
        return f"<CustomerOrder {self.id} {self.customer_name!r} status={self.status}>"
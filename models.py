from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

# ==================== Users ====================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50))
    phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)

# ==================== Categories ====================
class Category(db.Model):
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

# ==================== Products ====================
class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    description = db.Column(db.Text)
    
    cost_price = db.Column(db.Float, default=0)
    selling_price = db.Column(db.Float, default=0)
    
    current_stock = db.Column(db.Float, default=0)
    min_stock_level = db.Column(db.Float, default=0)
    max_stock_level = db.Column(db.Float, default=0)
    
    unit = db.Column(db.String(20))
    barcode = db.Column(db.String(100))
    
    expiry_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)

# ==================== Customers ====================
class Customer(db.Model):
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    
    customer_type = db.Column(db.String(50))  # cash / credit
    credit_limit = db.Column(db.Float, default=0)
    
    current_balance = db.Column(db.Float, default=0)
    total_purchases = db.Column(db.Float, default=0)
    invoice_count = db.Column(db.Integer, default=0)
    last_purchase_date = db.Column(db.DateTime)
    current_balance = db.Column(db.Float, default=0)
    wallet_balance = db.Column(db.Float, default=0)

    # علاقات
    invoices = db.relationship('SaleInvoice', backref='customer', lazy=True)

# ==================== Suppliers ====================
class Supplier(db.Model):
    __tablename__ = 'suppliers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    address = db.Column(db.Text)

    purchases = db.relationship('PurchaseInvoice', backref='supplier', lazy=True)

# ==================== Sale Invoices ====================
class SaleInvoice(db.Model):
    __tablename__ = 'sale_invoices'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(100), unique=True)
    
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'))
    
    subtotal = db.Column(db.Float, default=0)
    discount = db.Column(db.Float, default=0)
    tax = db.Column(db.Float, default=0)
    total_amount = db.Column(db.Float, default=0)
    
    paid_amount = db.Column(db.Float, default=0)
    payment_status = db.Column(db.String(50))  # paid / partial / credit
    payment_method = db.Column(db.String(50))
    
    cashier_id = db.Column(db.Integer)
    notes = db.Column(db.Text)
    
    sale_date = db.Column(db.DateTime, default=datetime.utcnow)
    is_cancelled = db.Column(db.Boolean, default=False)

    # 🔥 العلاقة المهمة (تحل مشكلتك)
    items = db.relationship('SaleItem', backref='invoice', lazy=True, cascade="all, delete-orphan")

# ==================== Sale Items ====================
class SaleItem(db.Model):
    __tablename__ = 'sale_items'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('sale_invoices.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    
    quantity = db.Column(db.Float)
    unit_price = db.Column(db.Float)
    total = db.Column(db.Float)

    product = db.relationship('Product')

# ==================== Purchase Invoices ====================
class PurchaseInvoice(db.Model):
    __tablename__ = 'purchase_invoices'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(100), unique=True)
    
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'))
    
    total_amount = db.Column(db.Float, default=0)
    paid_amount = db.Column(db.Float, default=0)
    payment_status = db.Column(db.String(50))  # paid / partial / unpaid
    payment_method = db.Column(db.String(50))
    
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer)
    
    receipt_date = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('PurchaseItem', backref='invoice', lazy=True, cascade="all, delete-orphan")

# ==================== Purchase Items ====================
class PurchaseItem(db.Model):
    __tablename__ = 'purchase_items'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('purchase_invoices.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    
    quantity = db.Column(db.Float)
    cost_price = db.Column(db.Float)
    total = db.Column(db.Float)

    product = db.relationship('Product')

# ==================== Debts ====================
class Debt(db.Model):
    __tablename__ = 'debts'
    
    id = db.Column(db.Integer, primary_key=True)
    
    debt_type = db.Column(db.String(50))  # customer / supplier
    entity_id = db.Column(db.Integer)
    
    original_amount = db.Column(db.Float)
    remaining_amount = db.Column(db.Float)
    
    due_date = db.Column(db.Date)
    status = db.Column(db.String(50))  # due / paid / partially_paid
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==================== Payments ====================
class Payment(db.Model):
    __tablename__ = 'payments'
    
    id = db.Column(db.Integer, primary_key=True)
    
    debt_id = db.Column(db.Integer, db.ForeignKey('debts.id'), nullable=True)
    amount = db.Column(db.Float)
    
    payment_method = db.Column(db.String(50))
    notes = db.Column(db.Text)
    
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    recorded_by = db.Column(db.Integer)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)

# ==================== Inventory Movement ====================
class InventoryMovement(db.Model):
    __tablename__ = 'inventory_movements'
    
    id = db.Column(db.Integer, primary_key=True)
    
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    movement_type = db.Column(db.String(20))  # in / out
    
    quantity = db.Column(db.Float)
    
    reference_type = db.Column(db.String(50))  # sale / purchase
    reference_id = db.Column(db.Integer)
    
    user_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Product, Category, Customer, Supplier, SaleInvoice, SaleItem, PurchaseInvoice, PurchaseItem, Debt, Payment, InventoryMovement
from datetime import datetime, timedelta
import bcrypt
from sqlalchemy import func, extract
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///supermarket.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Helper functions
def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def role_required(allowed_roles):
    def decorator(f):
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in allowed_roles:
                flash('غير مصرح لك بالوصول إلى هذه الصفحة', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator

def generate_invoice_number(prefix):
    date_str = datetime.now().strftime('%Y%m%d')
    last_invoice = SaleInvoice.query.filter(SaleInvoice.invoice_number.like(f'{prefix}{date_str}%')).order_by(SaleInvoice.id.desc()).first()
    if last_invoice:
        last_num = int(last_invoice.invoice_number[-4:])
        new_num = last_num + 1
    else:
        new_num = 1
    return f"{prefix}{date_str}{new_num:04d}"

def generate_purchase_number():
    date_str = datetime.now().strftime('%Y%m%d')
    last_purchase = PurchaseInvoice.query.filter(PurchaseInvoice.invoice_number.like(f'PO{date_str}%')).order_by(PurchaseInvoice.id.desc()).first()
    if last_purchase:
        last_num = int(last_purchase.invoice_number[-4:])
        new_num = last_num + 1
    else:
        new_num = 1
    return f"PO{date_str}{new_num:04d}"

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password(password, user.password_hash):
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user)
            flash(f'مرحباً {user.username}', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('تم تسجيل الخروج بنجاح', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    today_sales = SaleInvoice.query.filter(
        SaleInvoice.sale_date >= today_start,
        SaleInvoice.sale_date <= today_end,
        SaleInvoice.is_cancelled == False
    ).all()
    today_total = sum(s.total_amount for s in today_sales)
    today_invoices = len(today_sales)
    
    month_start = datetime(today.year, today.month, 1)
    month_sales = SaleInvoice.query.filter(
        SaleInvoice.sale_date >= month_start,
        SaleInvoice.is_cancelled == False
    ).all()
    month_total = sum(s.total_amount for s in month_sales)
    month_profit = 0
    for sale in month_sales:
        for item in sale.items:
            product = Product.query.get(item.product_id)
            if product:
                month_profit += (item.unit_price - product.cost_price) * item.quantity
    
    expiring_soon = Product.query.filter(
        Product.expiry_date <= datetime.now().date() + timedelta(days=30),
        Product.expiry_date >= datetime.now().date(),
        Product.is_active == True
    ).all()
    low_stock = Product.query.filter(
        Product.current_stock <= Product.min_stock_level,
        Product.is_active == True
    ).all()
    
    overdue_debts = Customer.query.filter(Customer.current_balance > 0).all()
    recent_invoices = SaleInvoice.query.filter_by(is_cancelled=False).order_by(SaleInvoice.sale_date.desc()).limit(10).all()
    
    top_products = db.session.query(
        Product.name,
        func.sum(SaleItem.quantity).label('total_sold')
    ).join(SaleItem).join(SaleInvoice).filter(SaleInvoice.is_cancelled == False)\
     .group_by(Product.id).order_by(func.sum(SaleItem.quantity).desc()).limit(5).all()
    
    return render_template('dashboard.html',
                         today_total=today_total,
                         today_invoices=today_invoices,
                         month_total=month_total,
                         month_profit=month_profit,
                         expiring_soon=expiring_soon,
                         low_stock=low_stock,
                         overdue_debts=overdue_debts,
                         recent_invoices=recent_invoices,
                         top_products=top_products)

# ==================== Products Management ====================
@app.route('/products')
@login_required
@role_required(['admin', 'inventory_manager'])
def products():
    products = Product.query.filter_by(is_active=True).all()
    categories = Category.query.all()
    return render_template('products.html', products=products, categories=categories)

@app.route('/product/add', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'inventory_manager'])
def add_product():
    if request.method == 'POST':
        product = Product(
            name=request.form.get('name'),
            category_id=request.form.get('category_id') or None,
            description=request.form.get('description'),
            cost_price=float(request.form.get('cost_price', 0)),
            selling_price=float(request.form.get('selling_price', 0)),
            # ✅ المخزون الأولي دائماً صفر — يتحدث عبر فواتير الشراء فقط
            current_stock=0,
            min_stock_level=float(request.form.get('min_stock_level', 0)),
            max_stock_level=float(request.form.get('max_stock_level', 0)),
            unit=request.form.get('unit'),
            barcode=request.form.get('barcode')
        )
        expiry_date = request.form.get('expiry_date')
        if expiry_date:
            product.expiry_date = datetime.strptime(expiry_date, '%Y-%m-%d')
        
        db.session.add(product)
        db.session.commit()
        flash('تم إضافة المنتج بنجاح. أضف فاتورة شراء لتحديث المخزون.', 'success')
        return redirect(url_for('products'))
    
    categories = Category.query.all()
    return render_template('product_form.html', categories=categories, product=None)

@app.route('/product/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'inventory_manager'])
def edit_product(id):
    product = Product.query.get_or_404(id)
    if request.method == 'POST':
        product.name = request.form.get('name')
        product.category_id = request.form.get('category_id') or None
        product.description = request.form.get('description')
        product.cost_price = float(request.form.get('cost_price', 0))
        product.selling_price = float(request.form.get('selling_price', 0))
        product.min_stock_level = float(request.form.get('min_stock_level', 0))
        product.max_stock_level = float(request.form.get('max_stock_level', 0))
        product.unit = request.form.get('unit')
        product.barcode = request.form.get('barcode')
        expiry_date = request.form.get('expiry_date')
        if expiry_date:
            product.expiry_date = datetime.strptime(expiry_date, '%Y-%m-%d')
        # ✅ لا نلمس current_stock هنا إطلاقاً
        db.session.commit()
        flash('تم تحديث المنتج بنجاح', 'success')
        return redirect(url_for('products'))
    
    categories = Category.query.all()
    return render_template('product_form.html', categories=categories, product=product)

@app.route('/product/delete/<int:id>')
@login_required
@role_required(['admin'])
def delete_product(id):
    product = Product.query.get_or_404(id)
    product.is_active = False
    db.session.commit()
    flash('تم حذف المنتج بنجاح', 'success')
    return redirect(url_for('products'))

# ==================== POS ====================
@app.route('/pos')
@login_required
@role_required(['admin', 'cashier'])
def pos():
    products = Product.query.filter_by(is_active=True).all()
    customers = Customer.query.all()
    return render_template('pos.html', products=products, customers=customers)

@app.route('/api/search_products')
@login_required
def api_search_products():
    query = request.args.get('q', '')
    products = Product.query.filter(
        Product.is_active == True,
        Product.name.contains(query)
    ).limit(20).all()
    
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'selling_price': p.selling_price,
        'current_stock': p.current_stock,
        'unit': p.unit
    } for p in products])

@app.route('/api/create_sale', methods=['POST'])
@login_required
@role_required(['admin', 'cashier'])

def api_create_sale():
    data = request.json
    cart = data.get('cart', [])
    customer_id = data.get('customer_id')
    paid_amount = float(data.get('paid_amount', 0))
    payment_method = data.get('payment_method', 'cash')
 
    if not cart:
        return jsonify({'error': 'السلة فارغة'}), 400
 
    subtotal = sum(item['total'] for item in cart)
    discount = float(data.get('discount', 0))
    tax = float(data.get('tax', 0))
    total = subtotal - discount + tax
 
    # ── 1. جلب العميل مرة وحدة ──
    customer = Customer.query.get(customer_id) if customer_id else None
 
    # ── 2. اخصم من المحفظة أولاً (قبل ما تحسب الدين) ──
    wallet_used = 0
    if customer and (customer.wallet_balance or 0) > 0:
        remaining_after_cash = max(total - paid_amount, 0)
        wallet_used = min(customer.wallet_balance, remaining_after_cash)
        if wallet_used > 0:
            customer.wallet_balance -= wallet_used
            paid_amount += wallet_used
 
    # ── 3. الزيادة في الدفع: تخصم الدين أولاً ثم المحفظة ──
    extra_paid = 0
    debt_reduced = 0
    extra_to_wallet = 0
 
    if paid_amount > total:
        extra_paid = paid_amount - total
        paid_amount = total  # الفاتورة تتسجل بقيمتها الصحيحة
 
        if customer:
            # أولاً: خصم الدين الموجود
            if (customer.current_balance or 0) > 0:
                debt_reduced = min(extra_paid, customer.current_balance)
                customer.current_balance -= debt_reduced
                extra_paid -= debt_reduced
 
                # تحديث سجلات الديون التفصيلية
                debts = Debt.query.filter_by(
                    debt_type='customer', entity_id=customer_id
                ).filter(Debt.remaining_amount > 0).order_by(Debt.created_at).all()
 
                rem = debt_reduced
                for debt in debts:
                    if rem <= 0:
                        break
                    if debt.remaining_amount <= rem:
                        rem -= debt.remaining_amount
                        debt.remaining_amount = 0
                        debt.status = 'paid'
                    else:
                        debt.remaining_amount -= rem
                        debt.status = 'partially_paid'
                        rem = 0
 
            # ثانياً: اللي تبقى يروح للمحفظة
            if extra_paid > 0:
                extra_to_wallet = extra_paid
                customer.wallet_balance = (customer.wallet_balance or 0) + extra_to_wallet
 
    # ── 4. تحديد حالة الدفع ──
    if paid_amount >= total:
        payment_status = 'paid'
        remaining = 0
    elif paid_amount > 0:
        payment_status = 'partial'
        remaining = total - paid_amount
    else:
        payment_status = 'credit'
        remaining = total
 
    if payment_status in ['credit', 'partial'] and not customer_id:
        return jsonify({'error': 'يجب اختيار عميل للشراء بالدين أو الدفع الجزئي'}), 400
 
    # ── 5. إنشاء الفاتورة ──
    invoice_number = generate_invoice_number('INV')
    invoice = SaleInvoice(
        invoice_number=invoice_number,
        customer_id=customer_id if customer_id else None,
        subtotal=subtotal,
        discount=discount,
        tax=tax,
        total_amount=total,
        paid_amount=paid_amount,
        payment_status=payment_status,
        payment_method=payment_method,
        cashier_id=current_user.id,
        notes=data.get('notes', '')
    )
    db.session.add(invoice)
    db.session.flush()
 
    # ── 6. إضافة الأصناف وتحديث المخزون ──
    for item in cart:
        sale_item = SaleItem(
            invoice_id=invoice.id,
            product_id=item['id'],
            quantity=item['quantity'],
            unit_price=item['price'],
            total=item['total']
        )
        db.session.add(sale_item)
 
        product = Product.query.get(item['id'])
        if product:
            product.current_stock -= item['quantity']
 
        movement = InventoryMovement(
            product_id=item['id'],
            movement_type='out',
            quantity=item['quantity'],
            reference_type='sale',
            reference_id=invoice.id,
            user_id=current_user.id
        )
        db.session.add(movement)
 
    # ── 7. تحديث بيانات العميل والديون ──
    if customer:
        customer.total_purchases += total
        customer.invoice_count += 1
        customer.last_purchase_date = datetime.utcnow()
 
        if remaining > 0:
            customer.current_balance = (customer.current_balance or 0) + remaining
            debt = Debt(
                debt_type='customer',
                entity_id=customer_id,
                original_amount=remaining,
                remaining_amount=remaining,
                due_date=datetime.now().date() + timedelta(days=30),
                status='due'
            )
            db.session.add(debt)
 
    db.session.commit()
 
    # ── 8. بناء رسالة النتيجة ──
    msg_parts = []
    if wallet_used > 0:
        msg_parts.append(f'استُخدم {wallet_used:.2f} ₪ من المحفظة')
    if debt_reduced > 0:
        msg_parts.append(f'خُصم {debt_reduced:.2f} ₪ من الدين')
    if extra_to_wallet > 0:
        msg_parts.append(f'أُضيف {extra_to_wallet:.2f} ₪ للمحفظة')
 
    return jsonify({
        'success': True,
        'invoice_id': invoice.id,
        'invoice_number': invoice_number,
        'total': total,
        'paid_amount': paid_amount,
        'wallet_used': wallet_used,
        'debt_reduced': debt_reduced,
        'extra_to_wallet': extra_to_wallet,
        'change': 0,
        'remaining_balance': remaining,
        'message': ' | '.join(msg_parts) if msg_parts else None
    })


@app.route('/api/add_customer_quick', methods=['POST'])
@login_required
def api_add_customer_quick():
    data = request.json
    name = data.get('name')
    phone = data.get('phone')
    
    if not name or not phone:
        return jsonify({'error': 'الاسم ورقم الهاتف مطلوبان'}), 400
    
    existing = Customer.query.filter_by(phone=phone).first()
    if existing:
        return jsonify({'error': 'رقم الهاتف موجود مسبقاً', 'customer': {'id': existing.id, 'name': existing.name}}), 409
    
    customer = Customer(
        name=name,
        phone=phone,
        customer_type='credit',
        current_balance=0
    )
    db.session.add(customer)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'customer': {'id': customer.id, 'name': customer.name, 'balance': customer.current_balance}
    })

# ==================== Customers ====================
@app.route('/customers')
@login_required
def customers():
    customers = Customer.query.all()
    return render_template('customers.html', customers=customers)

@app.route('/customer/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        initial_balance = float(request.form.get('initial_balance', 0) or 0)
        
        customer = Customer(
            name=request.form.get('name'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
            customer_type=request.form.get('customer_type'),
            credit_limit=float(request.form.get('credit_limit', 0)),
            current_balance=initial_balance,
            total_purchases=initial_balance
        )
        db.session.add(customer)
        db.session.flush()
        
        if initial_balance > 0:
            debt = Debt(
                debt_type='customer',
                entity_id=customer.id,
                original_amount=initial_balance,
                remaining_amount=initial_balance,
                due_date=datetime.now().date() + timedelta(days=30),
                status='due'
            )
            db.session.add(debt)
        
        db.session.commit()
        
        if initial_balance > 0:
            flash(f'تم إضافة العميل {customer.name} بنجاح - الدين الأولي: {initial_balance:.2f} ₪', 'success')
        else:
            flash('تم إضافة العميل بنجاح', 'success')
        
        return redirect(url_for('customers'))
    
    return render_template('customer_form.html', customer=None)

@app.route('/customer/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_customer(id):
    customer = Customer.query.get_or_404(id)
    if request.method == 'POST':
        customer.name = request.form.get('name')
        customer.phone = request.form.get('phone')
        customer.email = request.form.get('email')
        customer.address = request.form.get('address')
        customer.customer_type = request.form.get('customer_type')
        customer.credit_limit = float(request.form.get('credit_limit', 0))
        db.session.commit()
        flash('تم تحديث بيانات العميل', 'success')
        return redirect(url_for('customers'))
    
    return render_template('customer_form.html', customer=customer)

# ==================== Incoming Goods (Purchase) ====================
@app.route('/incoming')
@login_required
@role_required(['admin', 'inventory_manager'])
def incoming():
    purchases = PurchaseInvoice.query.order_by(PurchaseInvoice.receipt_date.desc()).all()
    suppliers = Supplier.query.all()
    return render_template('incoming.html', purchases=purchases, suppliers=suppliers)

@app.route('/incoming/add', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'inventory_manager'])
def add_incoming():
    if request.method == 'POST':
        invoice_number = generate_purchase_number()
        supplier_id = request.form.get('supplier_id')
        
        total_amount = float(request.form.get('total_amount', 0))
        paid_amount = float(request.form.get('paid_amount', 0))
        payment_status = request.form.get('payment_status', 'unpaid')
        
        purchase = PurchaseInvoice(
            invoice_number=invoice_number,
            supplier_id=supplier_id if supplier_id else None,
            total_amount=total_amount,
            paid_amount=paid_amount,
            payment_status=payment_status,
            payment_method=request.form.get('payment_method'),
            notes=request.form.get('notes'),
            created_by=current_user.id
        )
        db.session.add(purchase)
        db.session.flush()
        
        product_ids = request.form.getlist('product_ids[]')
        quantities = request.form.getlist('quantities[]')
        cost_prices = request.form.getlist('cost_prices[]')
        
        for i in range(len(product_ids)):
            if not product_ids[i] or not quantities[i] or not cost_prices[i]:
                continue

            qty = float(quantities[i])
            cost = float(cost_prices[i])

            if qty <= 0:
                continue

            item = PurchaseItem(
                invoice_id=purchase.id,
                product_id=int(product_ids[i]),
                quantity=qty,
                cost_price=cost,
                total=qty * cost
            )
            db.session.add(item)

            product = Product.query.get(int(product_ids[i]))
            if product:
                old_stock = product.current_stock  # المخزون القديم قبل الإضافة
                new_stock = old_stock + qty          # المخزون الجديد

                # ✅ حساب متوسط سعر الشراء بشكل صحيح
                if new_stock > 0:
                    product.cost_price = ((product.cost_price * old_stock) + (cost * qty)) / new_stock

                # ✅ تحديث المخزون مرة واحدة فقط
                product.current_stock = new_stock

                movement = InventoryMovement(
                    product_id=int(product_ids[i]),
                    movement_type='in',
                    quantity=qty,
                    reference_type='purchase',
                    reference_id=purchase.id,
                    user_id=current_user.id
                )
                db.session.add(movement)
        
        db.session.commit()
        flash('تم إضافة فاتورة الشراء بنجاح وتحديث المخزون', 'success')
        return redirect(url_for('incoming'))
    
    products = Product.query.filter_by(is_active=True).all()
    suppliers = Supplier.query.all()
    return render_template('incoming_form.html', products=products, suppliers=suppliers, purchase=None)

@app.route('/api/purchase_details/<int:purchase_id>')
@login_required
def api_purchase_details(purchase_id):
    purchase = PurchaseInvoice.query.get_or_404(purchase_id)
    items = PurchaseItem.query.filter_by(invoice_id=purchase_id).all()
    
    return jsonify({
        'invoice': {
            'invoice_number': purchase.invoice_number,
            'receipt_date': purchase.receipt_date.strftime('%Y-%m-%d %H:%M'),
            'supplier_name': purchase.supplier.name if purchase.supplier else None,
            'payment_method': purchase.payment_method,
            'payment_status': purchase.payment_status,
            'total_amount': purchase.total_amount,
            'paid_amount': purchase.paid_amount,
            'notes': purchase.notes
        },
        'items': [{
            'product_name': item.product.name,
            'quantity': item.quantity,
            'cost_price': item.cost_price,
            'total': item.total
        } for item in items]
    })

@app.route('/record_supplier_payment', methods=['POST'])
@login_required
@role_required(['admin', 'inventory_manager', 'accountant'])
def record_supplier_payment():
    purchase_id = request.form.get('purchase_id')
    amount = float(request.form.get('amount'))
    payment_method = request.form.get('payment_method')
    notes = request.form.get('notes', '')
    
    purchase = PurchaseInvoice.query.get_or_404(purchase_id)
    remaining = purchase.total_amount - purchase.paid_amount
    
    if amount <= 0:
        flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
        return redirect(url_for('incoming'))
    
    if amount > remaining:
        flash('المبلغ المسدد أكبر من المتبقي', 'danger')
        return redirect(url_for('incoming'))
    
    purchase.paid_amount += amount
    if purchase.paid_amount >= purchase.total_amount:
        purchase.payment_status = 'paid'
    else:
        purchase.payment_status = 'partial'
    
    db.session.commit()
    flash(f'تم تسديد {amount} ₪ للمورد {purchase.supplier.name if purchase.supplier else ""}', 'success')
    return redirect(url_for('incoming'))

# ==================== Debts ====================
@app.route('/debts')
@login_required
def debts():
    # ✅ اعرض كل من عنده دين أو رصيد محفظة
    debt_customers = Customer.query.filter(
        db.or_(
            Customer.current_balance > 0,
            Customer.wallet_balance > 0
        )
    ).all()
    return render_template('debts.html', customers=debt_customers)


@app.route('/record_customer_payment', methods=['POST'])
@login_required
def record_customer_payment():
    customer_id = request.form.get('customer_id')
    amount = float(request.form.get('amount'))
    payment_method = request.form.get('payment_method')
    notes = request.form.get('notes', '')
 
    if amount <= 0:
        flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
        return redirect(url_for('debts'))
 
    customer = Customer.query.get_or_404(customer_id)
 
    # ✅ المبلغ يُطبَّق أولاً على الدين
    debt_payment = min(amount, customer.current_balance)
    extra = amount - debt_payment  # الزيادة فوق الدين
 
    # تخفيض الدين
    customer.current_balance -= debt_payment
 
    # أي زيادة تضاف كرصيد في المحفظة
    if extra > 0:
        customer.wallet_balance = (customer.wallet_balance or 0) + extra
 
    # تحديث سجلات الديون التفصيلية
    if debt_payment > 0:
        debts = Debt.query.filter_by(
            debt_type='customer', entity_id=customer_id
        ).filter(Debt.remaining_amount > 0).all()
        remaining_to_apply = debt_payment
        for debt in debts:
            if remaining_to_apply <= 0:
                break
            if debt.remaining_amount <= remaining_to_apply:
                remaining_to_apply -= debt.remaining_amount
                debt.remaining_amount = 0
                debt.status = 'paid'
            else:
                debt.remaining_amount -= remaining_to_apply
                debt.status = 'partially_paid'
                remaining_to_apply = 0
 
    # تسجيل الدفعة
    payment = Payment(
        debt_id=None,
        customer_id=customer.id,
        payment_date=datetime.utcnow(),
        amount=amount,
        payment_method=payment_method,
        notes=f'سداد من عميل {customer.name}: {notes}',
        recorded_by=current_user.id
    )
    db.session.add(payment)
    db.session.commit()
 
    # رسالة مناسبة
    if extra > 0:
        flash(
            f'تم استلام {amount:.2f} ₪ من {customer.name}. '
            f'تم تصفية الدين، والرصيد الزائد {extra:.2f} ₪ أُضيف لمحفظته.',
            'success'
        )
    else:
        flash(
            f'تم استلام {amount:.2f} ₪ من {customer.name}. '
            f'الدين المتبقي: {customer.current_balance:.2f} ₪',
            'success'
        )
    return redirect(url_for('debts'))



# ==================== سجل المدفوعات ====================
@app.route('/debt_payments')
@login_required
def debt_payments():
    # استعلام يجلب جميع المدفوعات مع بيانات العميل
    payments = db.session.query(
        Payment, Customer.name.label('customer_name'), Customer.id.label('customer_id')
    ).outerjoin(Customer, Payment.customer_id == Customer.id)\
     .order_by(Payment.payment_date.desc()).all()
    
    payment_list = []
    for payment, customer_name, customer_id in payments:
        payment_list.append({
            'id': payment.id,
            'date': payment.payment_date,
            'customer_name': customer_name if customer_name else 'عميل غير محدد',
            'customer_id': customer_id,
            'amount': payment.amount,
            'method': payment.payment_method,
            'notes': payment.notes,
            'recorded_by': payment.recorded_by
        })
    
    customers = Customer.query.order_by(Customer.name).all()
    return render_template('debt_payments.html', payments=payment_list, customers=customers)

@app.route('/api/debt_payments')
@login_required
def api_debt_payments():
    customer_id = request.args.get('customer_id', type=int)
    query = db.session.query(Payment, Customer).outerjoin(Customer, Payment.customer_id == Customer.id)
    if customer_id:
        query = query.filter(Customer.id == customer_id)
    results = query.order_by(Payment.payment_date.desc()).all()
    
    data = []
    for payment, customer in results:
        data.append({
            'id': payment.id,
            'date': payment.payment_date.strftime('%Y-%m-%d %H:%M'),
            'customer_name': customer.name if customer else 'غير معروف',
            'amount': payment.amount,
            'method': payment.payment_method,
            'notes': payment.notes
        })
    return jsonify(data)

@app.route('/api/customer_invoices/<int:customer_id>')
@login_required
# ==================== API: تفاصيل فواتير العميل + الأصناف ====================
def api_customer_invoices(customer_id):
    invoices = SaleInvoice.query.filter_by(customer_id=customer_id, is_cancelled=False)\
        .order_by(SaleInvoice.sale_date.desc()).all()
    
    result = []
    for inv in invoices:
        # جلب أصناف الفاتورة
        items = SaleItem.query.filter_by(invoice_id=inv.id).all()
        result.append({
            'invoice_number': inv.invoice_number,
            'sale_date': inv.sale_date.strftime('%Y-%m-%d %H:%M'),
            'total_amount': inv.total_amount,
            'paid_amount': inv.paid_amount,
            'payment_status': inv.payment_status,
            'items': [{
                'product_name': item.product.name,
                'quantity': item.quantity,
                'unit_price': item.unit_price,
                'total': item.total
            } for item in items]
        })
    
    return jsonify({'invoices': result})

# ==================== Reports ====================
@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')

@app.route('/api/sales_report')
@login_required
def api_sales_report():
    report_type = request.args.get('type', 'daily')
    today = datetime.now().date()
    
    if report_type == 'daily':
        start_date = datetime.combine(today, datetime.min.time())
        end_date = datetime.combine(today, datetime.max.time())
    elif report_type == 'weekly':
        start_date = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
        end_date = datetime.combine(today, datetime.max.time())
    elif report_type == 'monthly':
        start_date = datetime(today.year, today.month, 1)
        end_date = datetime.combine(today, datetime.max.time())
    else:
        start_date = datetime.combine(today - timedelta(days=30), datetime.min.time())
        end_date = datetime.combine(today, datetime.max.time())
    
    # جلب فواتير البيع مع أصنافها
    sales = SaleInvoice.query.filter(
        SaleInvoice.sale_date >= start_date,
        SaleInvoice.sale_date <= end_date,
        SaleInvoice.is_cancelled == False
    ).all()
    
    total_sales = sum(s.total_amount for s in sales)
    total_invoices = len(sales)
    avg_invoice = total_sales / total_invoices if total_invoices > 0 else 0
    paid_amount = sum(s.paid_amount for s in sales)
    
    # حساب التكلفة الإجمالية والأرباح
    total_cost = 0
    total_profit = 0
    for sale in sales:
        for item in sale.items:
            product = Product.query.get(item.product_id)
            if product:
                cost_item = product.cost_price * item.quantity
                total_cost += cost_item
                total_profit += (item.unit_price - product.cost_price) * item.quantity
    
    # أفضل المنتجات مبيعاً (حسب الإيرادات)
    top_products = db.session.query(
        Product.name,
        func.sum(SaleItem.quantity).label('quantity'),
        func.sum(SaleItem.total).label('revenue')
    ).join(SaleItem).join(SaleInvoice).filter(
        SaleInvoice.sale_date >= start_date,
        SaleInvoice.sale_date <= end_date,
        SaleInvoice.is_cancelled == False
    ).group_by(Product.id).order_by(func.sum(SaleItem.total).desc()).limit(5).all()
    
    # المبيعات اليومية مع الربح اليومي
    daily_data = db.session.query(
        func.date(SaleInvoice.sale_date).label('date'),
        func.sum(SaleInvoice.total_amount).label('total'),
        func.sum(SaleItem.total).label('revenue')  # هذا ليس الربح، سنحسب الربح يدوياً
    ).join(SaleItem).filter(
        SaleInvoice.sale_date >= start_date,
        SaleInvoice.sale_date <= end_date,
        SaleInvoice.is_cancelled == False
    ).group_by(func.date(SaleInvoice.sale_date)).all()
    
    # حساب الربح لكل يوم
    daily_sales = []
    daily_profit = []
    for day in daily_data:
        # نحتاج لحساب الربح الفعلي لذلك اليوم
        day_sales = SaleInvoice.query.filter(
            func.date(SaleInvoice.sale_date) == day.date,
            SaleInvoice.is_cancelled == False
        ).all()
        day_profit = 0
        for sale in day_sales:
            for item in sale.items:
                product = Product.query.get(item.product_id)
                if product:
                    day_profit += (item.unit_price - product.cost_price) * item.quantity
        daily_sales.append({'date': str(day.date), 'total': day.total})
        daily_profit.append({'date': str(day.date), 'profit': day_profit})
    
    # توزيع المدفوعات
    paid_sum = sum(s.total_amount for s in sales if s.payment_status == 'paid')
    partial_sum = sum(s.total_amount for s in sales if s.payment_status == 'partial')
    unpaid_sum = sum(s.total_amount for s in sales if s.payment_status in ['unpaid', 'credit'])
    
    # آخر الفواتير (خمسة)
    recent = SaleInvoice.query.filter(
        SaleInvoice.sale_date >= start_date,
        SaleInvoice.sale_date <= end_date,
        SaleInvoice.is_cancelled == False
    ).order_by(SaleInvoice.sale_date.desc()).limit(5).all()
    
    recent_invoices = []
    for inv in recent:
        recent_invoices.append({
            'number': inv.invoice_number,
            'customer': inv.customer.name if inv.customer else 'عميل نقدي',
            'total': inv.total_amount,
            'status': inv.payment_status,
            'time': inv.sale_date.strftime('%H:%M')
        })
    
    return jsonify({
        'total_sales': total_sales,
        'total_invoices': total_invoices,
        'avg_invoice': avg_invoice,
        'paid_amount': paid_amount,
        'total_cost': total_cost,
        'total_profit': total_profit,
        'payment_breakdown': {
            'paid': paid_sum,
            'partial': partial_sum,
            'unpaid': unpaid_sum
        },
        'top_products': [{'name': p.name, 'revenue': p.revenue, 'quantity': p.quantity} for p in top_products],
        'daily_sales': daily_sales,
        'daily_profit': daily_profit,
        'recent_invoices': recent_invoices
    })

# ==================== Users ====================
@app.route('/users')
@login_required
@role_required(['admin'])
def users():
    users = User.query.all()
    return render_template('users.html', users=users)

@app.route('/user/add', methods=['POST'])
@login_required
@role_required(['admin'])
def add_user():
    user = User(
        username=request.form.get('username'),
        email=request.form.get('email'),
        password_hash=hash_password(request.form.get('password')),
        role=request.form.get('role'),
        phone=request.form.get('phone')
    )
    db.session.add(user)
    db.session.commit()
    flash('تم إضافة المستخدم بنجاح', 'success')
    return redirect(url_for('users'))

@app.route('/user/toggle/<int:id>')
@login_required
@role_required(['admin'])
def toggle_user(id):
    user = User.query.get_or_404(id)
    user.is_active = not user.is_active
    db.session.commit()
    flash('تم تحديث حالة المستخدم', 'success')
    return redirect(url_for('users'))

# ==================== Context Processor ====================
@app.context_processor
def utility_processor():
    from datetime import date, timedelta
    return dict(now=datetime.now, timedelta=timedelta, date=date)

# ==================== Initialize DB ====================
with app.app_context():
    db.create_all()
    
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            email='admin@supermarket.com',
            password_hash=hash_password('admin123'),
            role='admin',
            phone='123456789',
            is_active=True
        )
        db.session.add(admin)
        
        categories = ['ألبان', 'خضروات', 'فواكه', 'مشروبات', 'لحوم', 'مخبوزات', 'حلويات']
        for cat_name in categories:
            if not Category.query.filter_by(name=cat_name).first():
                cat = Category(name=cat_name)
                db.session.add(cat)
        
        if not Customer.query.first():
            
            credit_customer = Customer(
                name='محمد أحمد',
                phone='0501234567',
                customer_type='credit',
                current_balance=150,
                total_purchases=150,
                invoice_count=1
            )
            db.session.add(credit_customer)
        
        if not Supplier.query.first():
            supplier = Supplier(name='شركة المواد الغذائية', phone='0512345678', address='الرياض')
            db.session.add(supplier)
        
        db.session.commit()
        print("✅ تم إنشاء المستخدم الافتراضي: admin / admin123")
        print("✅ تم إضافة بيانات تجريبية (فئات، عملاء، موردين)")
        
        
# ==================== سجل حركات العميل الشامل ====================
@app.route('/customer/<int:customer_id>/activity')
@login_required
def customer_activity(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    activities = []
 
    # ── فواتير البيع ──
    invoices = SaleInvoice.query.filter_by(
        customer_id=customer_id, is_cancelled=False
    ).all()
    for inv in invoices:
        items = SaleItem.query.filter_by(invoice_id=inv.id).all()
        activities.append({
            'type': 'sale',
            'date': inv.sale_date,
            'ref': inv.invoice_number,
            'amount': inv.total_amount,
            'paid': inv.paid_amount,
            'remaining': inv.total_amount - inv.paid_amount,
            'status': inv.payment_status,
            'items': [{
                'name': i.product.name if i.product else '—',
                'qty': i.quantity,
                'unit_price': i.unit_price,
                'total': i.total
            } for i in items],
            'notes': inv.notes or ''
        })
 
    # ── مدفوعات الديون ──
    payments = Payment.query.filter_by(customer_id=customer_id).all()
    for p in payments:
        activities.append({
            'type': 'payment',
            'date': p.payment_date,
            'ref': f'PMT-{p.id:04d}',
            'amount': p.amount,
            'paid': p.amount,
            'remaining': 0,
            'status': 'paid',
            'items': [],
            'notes': p.notes or '',
            'method': p.payment_method
        })
 
    # ترتيب زمني تنازلي
    activities.sort(key=lambda x: x['date'], reverse=True)
 
    # ── ملخص ──
    total_purchased = sum(a['amount'] for a in activities if a['type'] == 'sale')
    total_paid_sales = sum(a['paid'] for a in activities if a['type'] == 'sale')
    total_payments = sum(a['amount'] for a in activities if a['type'] == 'payment')
 
    summary = {
        'total_purchased': total_purchased,
        'total_paid': total_paid_sales + total_payments,
        'current_debt': customer.current_balance or 0,
        'wallet': customer.wallet_balance or 0,
        'invoice_count': len(invoices),
        'payment_count': len(payments),
    }
 
    return render_template('customer_activity.html',
                           customer=customer,
                           activities=activities,
                           summary=summary)
 
 
@app.route('/api/customer/<int:customer_id>/activity')
@login_required
def api_customer_activity(customer_id):
    """API للفلترة الديناميكية"""
    filter_type = request.args.get('type', 'all')  # all / sale / payment
    
    activities = []
    customer = Customer.query.get_or_404(customer_id)
 
    if filter_type in ('all', 'sale'):
        invoices = SaleInvoice.query.filter_by(
            customer_id=customer_id, is_cancelled=False
        ).order_by(SaleInvoice.sale_date.desc()).all()
        for inv in invoices:
            items = SaleItem.query.filter_by(invoice_id=inv.id).all()
            activities.append({
                'type': 'sale',
                'date': inv.sale_date.strftime('%Y-%m-%d %H:%M'),
                'ref': inv.invoice_number,
                'amount': inv.total_amount,
                'paid': inv.paid_amount,
                'remaining': round(inv.total_amount - inv.paid_amount, 2),
                'status': inv.payment_status,
                'items': [{
                    'name': i.product.name if i.product else '—',
                    'qty': i.quantity,
                    'unit_price': i.unit_price,
                    'total': i.total
                } for i in items],
                'notes': inv.notes or ''
            })
 
    if filter_type in ('all', 'payment'):
        payments = Payment.query.filter_by(
            customer_id=customer_id
        ).order_by(Payment.payment_date.desc()).all()
        for p in payments:
            activities.append({
                'type': 'payment',
                'date': p.payment_date.strftime('%Y-%m-%d %H:%M'),
                'ref': f'PMT-{p.id:04d}',
                'amount': p.amount,
                'paid': p.amount,
                'remaining': 0,
                'status': 'paid',
                'items': [],
                'notes': p.notes or '',
                'method': p.payment_method or 'cash'
            })
 
    # ترتيب تنازلي
    activities.sort(key=lambda x: x['date'], reverse=True)
 
    return jsonify({
        'customer': {
            'name': customer.name,
            'phone': customer.phone,
            'balance': customer.current_balance or 0,
            'wallet': customer.wallet_balance or 0,
        },
        'activities': activities
    })
         

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
import os
from datetime import datetime, date, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, get_jwt
)
from database import SessionLocal, init_db
from models import (
    User, Product, ProductVariant, Plan, QuotationTemplate,
    TaxRule, DiscountRule, Subscription, SubscriptionLine,
    Invoice, InvoiceLine, Payment
)
from auth_utils import validate_password, hash_password, verify_password, generate_reset_token
from billing_engine import run_billing_day_batch, process_subscription_billing, generate_invoice_number

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'brightloop-odoo-super-secret-key-2026')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=7)

CORS(app, resources={r"/api/*": {"origins": "*"}})
jwt = JWTManager(app)

# Helper to get current user and role
def get_current_user_obj(db):
    try:
        user_id = get_jwt_identity()
        if not user_id:
            return None
        return db.query(User).get(int(user_id))
    except Exception:
        return None

# ----------------- AUTH ROUTES ----------------- #

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    name = data.get('name', '').strip()
    company_name = data.get('company_name', '').strip()
    role = data.get('role', 'customer')

    if not email or not password or not name:
        return jsonify({"error": "Email, password, and name are required."}), 400

    # PDF requirement: "the password must be more than eight characters, with an uppercase letter, a lowercase letter and a special character."
    valid, msg = validate_password(password)
    if not valid:
        return jsonify({"error": msg}), 400

    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            return jsonify({"error": "An account with this email already exists."}), 400

        # Normal registrations default to customer; admin can create staff
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=name,
            company_name=company_name,
            role=role if role in ['customer', 'admin'] else 'customer'
        )
        db.add(user)
        db.commit()

        token = create_access_token(identity=str(user.id), additional_claims={"role": user.role, "email": user.email})
        return jsonify({
            "message": "Registration successful",
            "token": token,
            "user": user.to_dict()
        }), 201
    finally:
        db.close()

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.password_hash):
            return jsonify({"error": "Invalid email or password."}), 401

        token = create_access_token(identity=str(user.id), additional_claims={"role": user.role, "email": user.email})
        return jsonify({
            "message": "Login successful",
            "token": token,
            "user": user.to_dict()
        }), 200
    finally:
        db.close()

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_me():
    db = SessionLocal()
    try:
        user = get_current_user_obj(db)
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"user": user.to_dict()}), 200
    finally:
        db.close()

@app.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            # Avoid leaking user existence, but inform user
            return jsonify({"message": "If this email is registered, a password reset link has been dispatched."}), 200
        
        token = generate_reset_token()
        user.reset_token = token
        db.commit()
        reset_link = f"http://localhost:5173/reset-password?token={token}"
        return jsonify({
            "message": "Password reset link sent to your registered email.",
            "simulated_reset_link": reset_link,
            "token": token
        }), 200
    finally:
        db.close()

@app.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json() or {}
    token = data.get('token', '')
    new_password = data.get('new_password', '')

    valid, msg = validate_password(new_password)
    if not valid:
        return jsonify({"error": msg}), 400

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.reset_token == token).first()
        if not user or not token:
            return jsonify({"error": "Invalid or expired reset token."}), 400

        user.password_hash = hash_password(new_password)
        user.reset_token = None
        db.commit()
        return jsonify({"message": "Password reset successfully. You can now log in."}), 200
    finally:
        db.close()

# ----------------- USERS & STAFF MANAGEMENT ----------------- #

@app.route('/api/users', methods=['GET'])
@jwt_required()
def list_users():
    db = SessionLocal()
    try:
        role_filter = request.args.get('role')
        q = db.query(User)
        if role_filter:
            q = q.filter(User.role == role_filter)
        users = q.order_by(User.id.desc()).all()
        return jsonify([u.to_dict() for u in users]), 200
    finally:
        db.close()

@app.route('/api/users/staff', methods=['POST'])
@jwt_required()
def create_staff():
    """PDF requirement: 'Only the admin can add a new member of staff.'"""
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        if not current_user or current_user.role != 'admin':
            return jsonify({"error": "Forbidden: Only admins can add staff members."}), 403

        data = request.get_json() or {}
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        name = data.get('name', '').strip()

        valid, msg = validate_password(password)
        if not valid:
            return jsonify({"error": msg}), 400

        if db.query(User).filter(User.email == email).first():
            return jsonify({"error": "User with this email already exists."}), 400

        staff = User(
            email=email,
            password_hash=hash_password(password),
            name=name,
            company_name="Brightloop Internal Staff",
            role="staff"
        )
        db.add(staff)
        db.commit()
        return jsonify({"message": "Staff member created successfully", "user": staff.to_dict()}), 201
    finally:
        db.close()

# ----------------- PRODUCTS & VARIANTS ----------------- #

@app.route('/api/products', methods=['GET'])
def get_products():
    db = SessionLocal()
    try:
        products = db.query(Product).order_by(Product.name).all()
        return jsonify([p.to_dict() for p in products]), 200
    finally:
        db.close()

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """PDF: Admin adds product with name, type, sales price, cost price, notes, and variants"""
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        if not current_user or current_user.role != 'admin':
            return jsonify({"error": "Only admins can add products."}), 403

        data = request.get_json() or {}
        product = Product(
            name=data.get('name'),
            type=data.get('type', 'Software'),
            sales_price=float(data.get('sales_price', 0.0)),
            cost_price=float(data.get('cost_price', 0.0)),
            notes=data.get('notes', ''),
            active=bool(data.get('active', True))
        )
        db.add(product)
        db.flush()

        # Add initial variants if provided
        variants_data = data.get('variants', [])
        for v in variants_data:
            variant = ProductVariant(
                product_id=product.id,
                attribute_name=v.get('attribute_name', 'Brand'),
                attribute_value=v.get('attribute_value', ''),
                price_extra=float(v.get('price_extra', 0.0))
            )
            db.add(variant)

        db.commit()
        return jsonify(product.to_dict()), 201
    finally:
        db.close()

@app.route('/api/products/<int:prod_id>/variants', methods=['POST'])
@jwt_required()
def add_product_variant(prod_id):
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        if not current_user or current_user.role != 'admin':
            return jsonify({"error": "Admin access required."}), 403

        data = request.get_json() or {}
        variant = ProductVariant(
            product_id=prod_id,
            attribute_name=data.get('attribute_name', 'Brand'),
            attribute_value=data.get('attribute_value'),
            price_extra=float(data.get('price_extra', 0.0))
        )
        db.add(variant)
        db.commit()
        return jsonify(variant.to_dict()), 201
    finally:
        db.close()

# ----------------- PLANS ----------------- #

@app.route('/api/plans', methods=['GET'])
def get_plans():
    db = SessionLocal()
    try:
        plans = db.query(Plan).order_by(Plan.id.desc()).all()
        return jsonify([p.to_dict() for p in plans]), 200
    finally:
        db.close()

@app.route('/api/plans', methods=['POST'])
@jwt_required()
def create_plan():
    """PDF: what it costs, how often it bills (daily, weekly, monthly, yearly), min qty, dates available, auto close, etc."""
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        if not current_user or current_user.role != 'admin':
            return jsonify({"error": "Only admins can configure plans."}), 403

        data = request.get_json() or {}
        s_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date() if data.get('start_date') else None
        e_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date() if data.get('end_date') else None

        plan = Plan(
            name=data.get('name'),
            product_id=data.get('product_id'),
            cost=float(data.get('cost', 0.0)),
            billing_interval=data.get('billing_interval', 'monthly'),
            min_quantity=int(data.get('min_quantity', 1)),
            start_date=s_date,
            end_date=e_date,
            auto_close=bool(data.get('auto_close', False)),
            allow_early_close=bool(data.get('allow_early_close', True)),
            allow_pause=bool(data.get('allow_pause', True)),
            allow_renew=bool(data.get('allow_renew', True)),
            description=data.get('description', ''),
            active=bool(data.get('active', True))
        )
        db.add(plan)
        db.commit()
        return jsonify(plan.to_dict()), 201
    finally:
        db.close()

# ----------------- QUOTATION TEMPLATES ----------------- #

@app.route('/api/quotation-templates', methods=['GET'])
def get_quotation_templates():
    db = SessionLocal()
    try:
        templates = db.query(QuotationTemplate).all()
        return jsonify([t.to_dict() for t in templates]), 200
    finally:
        db.close()

@app.route('/api/quotation-templates', methods=['POST'])
@jwt_required()
def create_quotation_template():
    db = SessionLocal()
    try:
        data = request.get_json() or {}
        import json
        tpl = QuotationTemplate(
            name=data.get('name'),
            plan_id=int(data.get('plan_id')),
            validity_days=int(data.get('validity_days', 30)),
            lines_json=json.dumps(data.get('lines', [])),
            notes=data.get('notes', '')
        )
        db.add(tpl)
        db.commit()
        return jsonify(tpl.to_dict()), 201
    finally:
        db.close()

# ----------------- TAX RULES ----------------- #

@app.route('/api/taxes', methods=['GET'])
def get_taxes():
    db = SessionLocal()
    try:
        taxes = db.query(TaxRule).order_by(TaxRule.id).all()
        return jsonify([t.to_dict() for t in taxes]), 200
    finally:
        db.close()

@app.route('/api/taxes', methods=['POST'])
@jwt_required()
def create_tax():
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        if not current_user or current_user.role != 'admin':
            return jsonify({"error": "Admin access required."}), 403

        data = request.get_json() or {}
        tax = TaxRule(
            name=data.get('name'),
            rate_percent=float(data.get('rate_percent', 0.0)),
            is_default=bool(data.get('is_default', False)),
            active=bool(data.get('active', True))
        )
        db.add(tax)
        db.commit()
        return jsonify(tax.to_dict()), 201
    finally:
        db.close()

# ----------------- DISCOUNT RULES ----------------- #

@app.route('/api/discounts', methods=['GET'])
def get_discounts():
    db = SessionLocal()
    try:
        discounts = db.query(DiscountRule).order_by(DiscountRule.id.desc()).all()
        return jsonify([d.to_dict() for d in discounts]), 200
    finally:
        db.close()

@app.route('/api/discounts', methods=['POST'])
@jwt_required()
def create_discount():
    """PDF: Only admin can create discount rules: fixed amount or percentage, min purchase/qty, start/end dates, usage limit"""
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        if not current_user or current_user.role != 'admin':
            return jsonify({"error": "Only admins can create discount rules."}), 403

        data = request.get_json() or {}
        s_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date() if data.get('start_date') else None
        e_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date() if data.get('end_date') else None

        disc = DiscountRule(
            code=data.get('code', '').strip().upper(),
            name=data.get('name'),
            discount_type=data.get('discount_type', 'percentage'),
            value=float(data.get('value', 0.0)),
            min_purchase=float(data.get('min_purchase', 0.0)),
            min_quantity=int(data.get('min_quantity', 1)),
            start_date=s_date,
            end_date=e_date,
            max_usage=int(data['max_usage']) if data.get('max_usage') else None,
            applies_to=data.get('applies_to', 'subscription'),
            product_id=data.get('product_id'),
            active=bool(data.get('active', True))
        )
        db.add(disc)
        db.commit()
        return jsonify(disc.to_dict()), 201
    finally:
        db.close()

# ----------------- SUBSCRIPTIONS ----------------- #

@app.route('/api/subscriptions', methods=['GET'])
@jwt_required()
def get_subscriptions():
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        status_filter = request.args.get('status')
        customer_id = request.args.get('customer_id')

        q = db.query(Subscription)

        # PDF: "customers see only their own subscriptions and invoices through a portal"
        if current_user and current_user.role == 'customer':
            q = q.filter(Subscription.customer_id == current_user.id)
        elif customer_id:
            q = q.filter(Subscription.customer_id == int(customer_id))

        if status_filter:
            q = q.filter(Subscription.status == status_filter)

        subs = q.order_by(Subscription.id.desc()).all()
        return jsonify([s.to_dict() for s in subs]), 200
    finally:
        db.close()

@app.route('/api/subscriptions/<int:sub_id>', methods=['GET'])
@jwt_required()
def get_subscription(sub_id):
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        sub = db.query(Subscription).get(sub_id)
        if not sub:
            return jsonify({"error": "Subscription not found"}), 404

        if current_user and current_user.role == 'customer' and sub.customer_id != current_user.id:
            return jsonify({"error": "Unauthorized access to subscription."}), 403

        return jsonify(sub.to_dict()), 200
    finally:
        db.close()

@app.route('/api/subscriptions', methods=['POST'])
@jwt_required()
def create_subscription():
    """PDF: Subscription moves Draft -> Quotation -> Confirmed -> Active -> Closed"""
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        data = request.get_json() or {}

        cust_id = data.get('customer_id')
        if current_user.role == 'customer':
            cust_id = current_user.id

        plan_id = int(data.get('plan_id'))
        plan = db.query(Plan).get(plan_id)
        if not plan:
            return jsonify({"error": "Plan not found"}), 404

        s_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date() if data.get('start_date') else date.today()
        e_date = datetime.strptime(data['expiry_date'], '%Y-%m-%d').date() if data.get('expiry_date') else None

        # Next billing date starts as start_date
        next_bill = s_date

        year = date.today().year
        count = db.query(Subscription).count() + 1
        sub_num = f"SUB-{year}-{count:04d}"

        sub = Subscription(
            sub_number=sub_num,
            customer_id=cust_id,
            plan_id=plan_id,
            start_date=s_date,
            expiry_date=e_date,
            next_billing_date=next_bill,
            payment_terms=data.get('payment_terms', 'Net 15'),
            status=data.get('status', 'Draft'),
            discount_id=data.get('discount_id'),
            notes=data.get('notes', '')
        )
        db.add(sub)
        db.flush()

        lines_data = data.get('lines', [])
        for l in lines_data:
            qty = int(l.get('quantity', 1))
            price = float(l.get('unit_price', 0.0))
            tax = float(l.get('tax_rate', 0.0))
            line_tot = round(qty * price * (1 + tax / 100.0), 2)

            line = SubscriptionLine(
                subscription_id=sub.id,
                product_id=int(l.get('product_id')),
                variant_id=l.get('variant_id'),
                description=l.get('description', ''),
                quantity=qty,
                unit_price=price,
                tax_rate=tax,
                amount=line_tot
            )
            db.add(line)

        db.commit()
        return jsonify(sub.to_dict()), 201
    finally:
        db.close()

@app.route('/api/subscriptions/<int:sub_id>/transition', methods=['POST'])
@jwt_required()
def transition_subscription(sub_id):
    """Handles status changes: Draft -> Quotation -> Confirmed -> Active -> Closed / Paused"""
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        sub = db.query(Subscription).get(sub_id)
        if not sub:
            return jsonify({"error": "Subscription not found"}), 404

        data = request.get_json() or {}
        new_status = data.get('status')
        valid_statuses = ['Draft', 'Quotation', 'Confirmed', 'Active', 'Paused', 'Closed']
        if new_status not in valid_statuses:
            return jsonify({"error": f"Invalid status: {new_status}"}), 400

        # Check plan policies
        if new_status == 'Paused' and sub.plan and not sub.plan.allow_pause:
            return jsonify({"error": "This plan does not permit pausing."}), 400
        if new_status == 'Closed' and sub.plan and not sub.plan.allow_early_close and sub.status == 'Active':
            if sub.expiry_date and date.today() < sub.expiry_date:
                return jsonify({"error": "This plan does not permit early closing."}), 400

        sub.status = new_status
        db.commit()
        return jsonify({"message": f"Status updated to {new_status}", "subscription": sub.to_dict()}), 200
    finally:
        db.close()

@app.route('/api/subscriptions/<int:sub_id>/bill-now', methods=['POST'])
@jwt_required()
def bill_subscription_now(sub_id):
    db = SessionLocal()
    try:
        sub = db.query(Subscription).get(sub_id)
        if not sub:
            return jsonify({"error": "Subscription not found"}), 404

        invoice, msg = process_subscription_billing(db, sub, date.today())
        if not invoice:
            return jsonify({"error": msg}), 400

        return jsonify({"message": msg, "invoice": invoice.to_dict()}), 201
    finally:
        db.close()

# ----------------- INVOICES ----------------- #

@app.route('/api/invoices', methods=['GET'])
@jwt_required()
def get_invoices():
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        status_filter = request.args.get('status')
        customer_id = request.args.get('customer_id')

        q = db.query(Invoice)
        if current_user and current_user.role == 'customer':
            q = q.filter(Invoice.customer_id == current_user.id)
        elif customer_id:
            q = q.filter(Invoice.customer_id == int(customer_id))

        if status_filter == 'Overdue':
            today = date.today()
            q = q.filter(Invoice.status != 'Paid', Invoice.due_date < today)
        elif status_filter:
            q = q.filter(Invoice.status == status_filter)

        invoices = q.order_by(Invoice.id.desc()).all()
        return jsonify([inv.to_dict() for inv in invoices]), 200
    finally:
        db.close()

@app.route('/api/invoices/<int:inv_id>', methods=['GET'])
@jwt_required()
def get_invoice(inv_id):
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        inv = db.query(Invoice).get(inv_id)
        if not inv:
            return jsonify({"error": "Invoice not found"}), 404

        if current_user and current_user.role == 'customer' and inv.customer_id != current_user.id:
            return jsonify({"error": "Unauthorized"}), 403

        return jsonify(inv.to_dict()), 200
    finally:
        db.close()

@app.route('/api/invoices/<int:inv_id>/status', methods=['POST'])
@jwt_required()
def change_invoice_status(inv_id):
    """PDF: The team can confirm, cancel, send or print any invoice"""
    db = SessionLocal()
    try:
        inv = db.query(Invoice).get(inv_id)
        if not inv:
            return jsonify({"error": "Invoice not found"}), 404

        data = request.get_json() or {}
        new_status = data.get('status')
        if new_status not in ['Draft', 'Confirmed', 'Paid', 'Cancelled']:
            return jsonify({"error": "Invalid status"}), 400

        inv.status = new_status
        db.commit()
        return jsonify({"message": f"Invoice updated to {new_status}", "invoice": inv.to_dict()}), 200
    finally:
        db.close()

@app.route('/api/invoices/<int:inv_id>/send', methods=['POST'])
@jwt_required()
def send_invoice_email(inv_id):
    db = SessionLocal()
    try:
        inv = db.query(Invoice).get(inv_id)
        if not inv:
            return jsonify({"error": "Invoice not found"}), 404

        recipient = inv.customer.email if inv.customer else "customer@domain.com"
        return jsonify({
            "message": f"Invoice {inv.invoice_number} successfully dispatched to {recipient}",
            "recipient": recipient,
            "invoice_number": inv.invoice_number,
            "total_amount": inv.total_amount
        }), 200
    finally:
        db.close()

# ----------------- PAYMENTS ----------------- #

@app.route('/api/invoices/<int:inv_id>/payments', methods=['POST'])
@jwt_required()
def record_payment(inv_id):
    """
    PDF: Payments arrive by different methods and on different days.
    Each one needs to be recorded with its method, amount, date and a note, against the right invoice.
    """
    db = SessionLocal()
    try:
        inv = db.query(Invoice).get(inv_id)
        if not inv:
            return jsonify({"error": "Invoice not found"}), 404

        data = request.get_json() or {}
        pay_amount = float(data.get('amount', 0.0))
        if pay_amount <= 0:
            return jsonify({"error": "Payment amount must be greater than zero."}), 400

        pay_method = data.get('payment_method', 'Bank Transfer')
        pay_date = datetime.strptime(data['payment_date'], '%Y-%m-%d').date() if data.get('payment_date') else date.today()
        ref_note = data.get('reference_note', '')

        count = db.query(Payment).count() + 1
        pay_num = f"PAY-{date.today().year}-{count:04d}"

        payment = Payment(
            payment_number=pay_num,
            invoice_id=inv.id,
            amount=round(pay_amount, 2),
            payment_method=pay_method,
            payment_date=pay_date,
            reference_note=ref_note,
            status='Completed'
        )
        db.add(payment)

        # Update invoice amount_paid and status
        inv.amount_paid = round(inv.amount_paid + pay_amount, 2)
        if inv.amount_paid >= inv.total_amount:
            inv.status = 'Paid'

        db.commit()
        return jsonify({
            "message": "Payment recorded successfully",
            "payment": payment.to_dict(),
            "invoice": inv.to_dict()
        }), 201
    finally:
        db.close()

@app.route('/api/payments', methods=['GET'])
@jwt_required()
def list_payments():
    db = SessionLocal()
    try:
        payments = db.query(Payment).order_by(Payment.id.desc()).all()
        return jsonify([p.to_dict() for p in payments]), 200
    finally:
        db.close()

# ----------------- BILLING DAY RUNNER ----------------- #

@app.route('/api/billing/run-day', methods=['POST'])
@jwt_required()
def trigger_billing_day():
    """
    PDF: 'Billing day: It is billing day, and hundreds of subscriptions are due at once.
    Nobody should be typing invoices by hand. Each one should be created from its subscription...
    Nothing should be billed twice or skipped.'
    """
    db = SessionLocal()
    try:
        data = request.get_json() or {}
        target_date = datetime.strptime(data['date'], '%Y-%m-%d').date() if data.get('date') else date.today()
        result = run_billing_day_batch(db, target_date)
        return jsonify(result), 200
    finally:
        db.close()

# ----------------- ANALYTICS & EXECUTIVE REPORTING ----------------- #

@app.route('/api/analytics/summary', methods=['GET'])
@jwt_required()
def get_analytics_summary():
    """
    PDF: 'The finance lead, at the end of the month:
    How many subscriptions are active? How much revenue came in, and how much is still owed?
    Which invoices are overdue? With thousands of subscriptions on the books, every page should still respond in under two seconds.'
    """
    db = SessionLocal()
    try:
        today = date.today()

        active_subs_count = db.query(Subscription).filter(Subscription.status == 'Active').count()
        total_subs_count = db.query(Subscription).count()

        # Calculate MRR (Monthly Recurring Revenue)
        active_subs = db.query(Subscription).filter(Subscription.status == 'Active').all()
        mrr = 0.0
        for sub in active_subs:
            sub_total = sub.calculate_total()
            interval = sub.plan.billing_interval if sub.plan else 'monthly'
            if interval == 'monthly':
                mrr += sub_total
            elif interval == 'yearly':
                mrr += (sub_total / 12.0)
            elif interval == 'weekly':
                mrr += (sub_total * 4.33)
            elif interval == 'daily':
                mrr += (sub_total * 30.0)

        # Revenue and payments
        all_invoices = db.query(Invoice).all()
        total_billed = sum(i.total_amount for i in all_invoices if i.status != 'Cancelled')
        total_revenue_collected = sum(i.amount_paid for i in all_invoices if i.status != 'Cancelled')
        total_owed = sum(max(0.0, i.total_amount - i.amount_paid) for i in all_invoices if i.status in ['Draft', 'Confirmed'])

        # Overdue invoices
        overdue_invoices = db.query(Invoice).filter(
            Invoice.status != 'Paid',
            Invoice.status != 'Cancelled',
            Invoice.due_date < today
        ).all()

        overdue_amount = sum(max(0.0, i.total_amount - i.amount_paid) for i in overdue_invoices)

        return jsonify({
            "active_subscriptions": active_subs_count,
            "total_subscriptions": total_subs_count,
            "mrr": round(mrr, 2),
            "arr": round(mrr * 12.0, 2),
            "total_revenue_collected": round(total_revenue_collected, 2),
            "total_owed": round(total_owed, 2),
            "overdue_count": len(overdue_invoices),
            "overdue_amount": round(overdue_amount, 2),
            "overdue_invoices": [inv.to_dict() for inv in overdue_invoices]
        }), 200
    finally:
        db.close()

# ----------------- CUSTOMER PORTAL ----------------- #

@app.route('/api/portal/overview', methods=['GET'])
@jwt_required()
def customer_portal_overview():
    db = SessionLocal()
    try:
        current_user = get_current_user_obj(db)
        if not current_user:
            return jsonify({"error": "Unauthorized"}), 401

        subs = db.query(Subscription).filter(Subscription.customer_id == current_user.id).all()
        invs = db.query(Invoice).filter(Invoice.customer_id == current_user.id).all()

        active_subs = [s for s in subs if s.status == 'Active']
        total_owed = sum(max(0.0, i.total_amount - i.amount_paid) for i in invs if i.status != 'Paid')

        return jsonify({
            "customer": current_user.to_dict(),
            "active_subscriptions_count": len(active_subs),
            "total_subscriptions_count": len(subs),
            "total_invoices_count": len(invs),
            "balance_due": round(total_owed, 2),
            "subscriptions": [s.to_dict() for s in subs],
            "invoices": [i.to_dict() for i in invs]
        }), 200
    finally:
        db.close()

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

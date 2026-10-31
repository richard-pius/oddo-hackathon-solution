from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime, Text, ForeignKey, Numeric
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default='customer')  # 'admin', 'staff', 'customer'
    name = Column(String(120), nullable=False)
    company_name = Column(String(150), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reset_token = Column(String(100), nullable=True)

    subscriptions = relationship("Subscription", back_populates="customer")
    invoices = relationship("Invoice", back_populates="customer")

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "role": self.role,
            "name": self.name,
            "company_name": self.company_name or "",
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Product(Base):
    __tablename__ = 'products'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    type = Column(String(50), nullable=False, default='Software')  # 'Software', 'Add-on', 'Service'
    sales_price = Column(Float, nullable=False, default=0.0)
    cost_price = Column(Float, nullable=False, default=0.0)
    notes = Column(Text, nullable=True)
    active = Column(Boolean, default=True)

    variants = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")
    plans = relationship("Plan", back_populates="product")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "sales_price": round(self.sales_price, 2),
            "cost_price": round(self.cost_price, 2),
            "notes": self.notes or "",
            "active": self.active,
            "variants": [v.to_dict() for v in self.variants]
        }

class ProductVariant(Base):
    __tablename__ = 'product_variants'

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    attribute_name = Column(String(50), nullable=False)  # e.g., 'Brand', 'Tier'
    attribute_value = Column(String(100), nullable=False)  # e.g., 'Odoo Brand'
    price_extra = Column(Float, nullable=False, default=0.0)  # e.g., 560
    active = Column(Boolean, default=True)

    product = relationship("Product", back_populates="variants")

    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "attribute_name": self.attribute_name,
            "attribute_value": self.attribute_value,
            "price_extra": round(self.price_extra, 2),
            "active": self.active
        }

class Plan(Base):
    __tablename__ = 'plans'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=True)
    cost = Column(Float, nullable=False, default=0.0)
    billing_interval = Column(String(20), nullable=False, default='monthly')  # 'daily', 'weekly', 'monthly', 'yearly'
    min_quantity = Column(Integer, default=1)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    auto_close = Column(Boolean, default=False)
    allow_early_close = Column(Boolean, default=True)
    allow_pause = Column(Boolean, default=True)
    allow_renew = Column(Boolean, default=True)
    description = Column(Text, nullable=True)
    active = Column(Boolean, default=True)

    product = relationship("Product", back_populates="plans")
    subscriptions = relationship("Subscription", back_populates="plan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "product_id": self.product_id,
            "product_name": self.product.name if self.product else None,
            "cost": round(self.cost, 2),
            "billing_interval": self.billing_interval,
            "min_quantity": self.min_quantity,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "auto_close": self.auto_close,
            "allow_early_close": self.allow_early_close,
            "allow_pause": self.allow_pause,
            "allow_renew": self.allow_renew,
            "description": self.description or "",
            "active": self.active
        }

class QuotationTemplate(Base):
    __tablename__ = 'quotation_templates'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    plan_id = Column(Integer, ForeignKey('plans.id'), nullable=False)
    validity_days = Column(Integer, default=30)
    lines_json = Column(Text, nullable=False, default='[]')
    notes = Column(Text, nullable=True)

    plan = relationship("Plan")

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "name": self.name,
            "plan_id": self.plan_id,
            "plan_name": self.plan.name if self.plan else "",
            "validity_days": self.validity_days,
            "lines": json.loads(self.lines_json) if self.lines_json else [],
            "notes": self.notes or ""
        }

class TaxRule(Base):
    __tablename__ = 'tax_rules'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    rate_percent = Column(Float, nullable=False, default=0.0)
    is_default = Column(Boolean, default=False)
    active = Column(Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "rate_percent": round(self.rate_percent, 2),
            "is_default": self.is_default,
            "active": self.active
        }

class DiscountRule(Base):
    __tablename__ = 'discount_rules'

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(150), nullable=False)
    discount_type = Column(String(20), nullable=False, default='percentage')  # 'fixed', 'percentage'
    value = Column(Float, nullable=False, default=0.0)
    min_purchase = Column(Float, default=0.0)
    min_quantity = Column(Integer, default=1)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    max_usage = Column(Integer, nullable=True)  # Limit on how many times it can be used
    times_used = Column(Integer, default=0)
    applies_to = Column(String(30), default='subscription')  # 'subscription', 'product'
    product_id = Column(Integer, ForeignKey('products.id'), nullable=True)
    active = Column(Boolean, default=True)

    product = relationship("Product")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "discount_type": self.discount_type,
            "value": round(self.value, 2),
            "min_purchase": round(self.min_purchase, 2),
            "min_quantity": self.min_quantity,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "max_usage": self.max_usage,
            "times_used": self.times_used,
            "applies_to": self.applies_to,
            "product_id": self.product_id,
            "product_name": self.product.name if self.product else None,
            "active": self.active
        }

class Subscription(Base):
    __tablename__ = 'subscriptions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    sub_number = Column(String(50), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    plan_id = Column(Integer, ForeignKey('plans.id'), nullable=False)
    start_date = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=True)
    next_billing_date = Column(Date, nullable=False)
    payment_terms = Column(String(50), default='Immediate')  # e.g. Immediate, Net 15, Net 30
    status = Column(String(30), default='Draft')  # 'Draft', 'Quotation', 'Confirmed', 'Active', 'Paused', 'Closed'
    discount_id = Column(Integer, ForeignKey('discount_rules.id'), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("User", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")
    discount = relationship("DiscountRule")
    lines = relationship("SubscriptionLine", back_populates="subscription", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="subscription")

    def calculate_total(self):
        return sum(line.amount for line in self.lines)

    def to_dict(self):
        total = self.calculate_total()
        return {
            "id": self.id,
            "sub_number": self.sub_number,
            "customer_id": self.customer_id,
            "customer_name": self.customer.name if self.customer else "Unknown",
            "customer_email": self.customer.email if self.customer else "",
            "company_name": self.customer.company_name if self.customer else "",
            "plan_id": self.plan_id,
            "plan_name": self.plan.name if self.plan else "",
            "billing_interval": self.plan.billing_interval if self.plan else "monthly",
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "next_billing_date": self.next_billing_date.isoformat() if self.next_billing_date else None,
            "payment_terms": self.payment_terms,
            "status": self.status,
            "discount_id": self.discount_id,
            "discount_code": self.discount.code if self.discount else None,
            "notes": self.notes or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "total_amount": round(total, 2),
            "lines": [line.to_dict() for line in self.lines],
            "allow_pause": self.plan.allow_pause if self.plan else True,
            "allow_early_close": self.plan.allow_early_close if self.plan else True,
            "allow_renew": self.plan.allow_renew if self.plan else True
        }

class SubscriptionLine(Base):
    __tablename__ = 'subscription_lines'

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, ForeignKey('subscriptions.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    variant_id = Column(Integer, ForeignKey('product_variants.id'), nullable=True)
    description = Column(String(255), nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, default=0.0)
    tax_rate = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)

    subscription = relationship("Subscription", back_populates="lines")
    product = relationship("Product")
    variant = relationship("ProductVariant")

    def to_dict(self):
        return {
            "id": self.id,
            "subscription_id": self.subscription_id,
            "product_id": self.product_id,
            "product_name": self.product.name if self.product else "",
            "variant_id": self.variant_id,
            "variant_name": f"{self.variant.attribute_name}: {self.variant.attribute_value}" if self.variant else None,
            "description": self.description or (self.product.name if self.product else ""),
            "quantity": self.quantity,
            "unit_price": round(self.unit_price, 2),
            "tax_rate": round(self.tax_rate, 2),
            "discount_amount": round(self.discount_amount, 2),
            "amount": round(self.amount, 2)
        }

class Invoice(Base):
    __tablename__ = 'invoices'

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_number = Column(String(50), unique=True, nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey('subscriptions.id'), nullable=True)
    customer_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    issue_date = Column(Date, nullable=False, default=date.today)
    due_date = Column(Date, nullable=False)
    status = Column(String(30), default='Draft')  # 'Draft', 'Confirmed', 'Paid', 'Cancelled'
    subtotal = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    total_amount = Column(Float, default=0.0)
    amount_paid = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("User", back_populates="invoices")
    subscription = relationship("Subscription", back_populates="invoices")
    lines = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")

    def is_overdue(self):
        return self.status != 'Paid' and self.due_date < date.today()

    def to_dict(self):
        return {
            "id": self.id,
            "invoice_number": self.invoice_number,
            "subscription_id": self.subscription_id,
            "subscription_number": self.subscription.sub_number if self.subscription else None,
            "customer_id": self.customer_id,
            "customer_name": self.customer.name if self.customer else "Unknown",
            "customer_email": self.customer.email if self.customer else "",
            "company_name": self.customer.company_name if self.customer else "",
            "issue_date": self.issue_date.isoformat() if self.issue_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status,
            "is_overdue": self.is_overdue(),
            "subtotal": round(self.subtotal, 2),
            "tax_amount": round(self.tax_amount, 2),
            "discount_amount": round(self.discount_amount, 2),
            "total_amount": round(self.total_amount, 2),
            "amount_paid": round(self.amount_paid, 2),
            "balance_due": round(max(0.0, self.total_amount - self.amount_paid), 2),
            "notes": self.notes or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "lines": [line.to_dict() for line in self.lines],
            "payments": [p.to_dict() for p in self.payments]
        }

class InvoiceLine(Base):
    __tablename__ = 'invoice_lines'

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey('invoices.id'), nullable=False)
    product_name = Column(String(150), nullable=False)
    variant_name = Column(String(100), nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, default=0.0)
    tax_rate = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)

    invoice = relationship("Invoice", back_populates="lines")

    def to_dict(self):
        return {
            "id": self.id,
            "invoice_id": self.invoice_id,
            "product_name": self.product_name,
            "variant_name": self.variant_name,
            "quantity": self.quantity,
            "unit_price": round(self.unit_price, 2),
            "tax_rate": round(self.tax_rate, 2),
            "discount_amount": round(self.discount_amount, 2),
            "amount": round(self.amount, 2)
        }

class Payment(Base):
    __tablename__ = 'payments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_number = Column(String(50), unique=True, nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey('invoices.id'), nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(String(50), nullable=False, default='Bank Transfer')  # 'Credit Card', 'Bank Transfer', 'Stripe', 'UPI', 'Cash'
    payment_date = Column(Date, nullable=False, default=date.today)
    reference_note = Column(Text, nullable=True)
    status = Column(String(20), default='Completed')

    invoice = relationship("Invoice", back_populates="payments")

    def to_dict(self):
        return {
            "id": self.id,
            "payment_number": self.payment_number,
            "invoice_id": self.invoice_id,
            "invoice_number": self.invoice.invoice_number if self.invoice else "",
            "customer_name": self.invoice.customer.name if self.invoice and self.invoice.customer else "",
            "amount": round(self.amount, 2),
            "payment_method": self.payment_method,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "reference_note": self.reference_note or "",
            "status": self.status
        }

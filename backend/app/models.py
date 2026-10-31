"""
Brightloop Domain Models
========================
Every table in this file maps directly to a bounded context in the Brightloop
subscription billing domain. The index strategy is tuned for two hot paths:

  1. Billing Day batch: SELECT subs WHERE status='ACTIVE' AND next_billing_date <= today
     → covered by ix_sub_billing_due (status, next_billing_date)

  2. Customer portal: SELECT subs/invoices WHERE customer_id = :me
     → covered by ix_sub_customer (customer_id, status)

We deliberately avoid generic "created_at" indexes — they help nobody and bloat WAL.
"""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    String, Text, Numeric, Integer, Boolean, Date, DateTime,
    ForeignKey, Index, Enum as SAEnum, UniqueConstraint, CheckConstraint,
    func, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


# ─── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    INTERNAL_STAFF = "INTERNAL_STAFF"
    CUSTOMER = "CUSTOMER"


class ProductType(str, enum.Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    ADDON = "ADDON"
    SERVICE = "SERVICE"


class BillingInterval(str, enum.Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class SubscriptionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    QUOTATION = "QUOTATION"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class DiscountType(str, enum.Enum):
    FIXED = "FIXED"
    PERCENTAGE = "PERCENTAGE"


class DiscountScope(str, enum.Enum):
    PRODUCT = "PRODUCT"
    SUBSCRIPTION = "SUBSCRIPTION"


class PaymentMethod(str, enum.Enum):
    BANK_TRANSFER = "BANK_TRANSFER"
    UPI = "UPI"
    CREDIT_CARD = "CREDIT_CARD"
    CASH = "CASH"
    ACH = "ACH"


# ─── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), nullable=False, default=UserRole.CUSTOMER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Why no company_id FK here: Brightloop is the single tenant. Multi-tenancy
    # would add a tenant_id column + RLS policy, but that's a Phase 2 concern.

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="customer", foreign_keys="Subscription.customer_id")
    recorded_payments: Mapped[list["Payment"]] = relationship(back_populates="recorded_by")


# ─── Password Reset Tokens ───────────────────────────────────────────────────

class PasswordResetToken(Base):
    """
    Why a dedicated table instead of embedding the token in the User row:
    Concurrent reset requests from the same user (e.g., they click "forgot"
    twice) would race on the user row. A separate table with a unique token
    column avoids that and lets us expire tokens via a simple DELETE WHERE
    expires_at < now() cron.
    """
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─── Products & Variants ─────────────────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_type: Mapped[ProductType] = mapped_column(SAEnum(ProductType), nullable=False)
    sales_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    subscription_lines: Mapped[list["SubscriptionLine"]] = relationship(back_populates="product")


class ProductVariant(Base):
    """
    Attribute-value variants with price deltas.
    Example: Product "Odoo ERP License", Variant attribute="Brand" value="Odoo Enterprise"
    price_extra=+560.00 → effective_price = sales_price + 560
    """
    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    attribute_name: Mapped[str] = mapped_column(String(100), nullable=False)
    attribute_value: Mapped[str] = mapped_column(String(200), nullable=False)
    price_extra: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    product: Mapped["Product"] = relationship(back_populates="variants")

    __table_args__ = (
        Index("ix_variant_product", "product_id"),
    )


# ─── Subscription Plans ──────────────────────────────────────────────────────

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    billing_interval: Mapped[BillingInterval] = mapped_column(SAEnum(BillingInterval), nullable=False)
    min_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    available_from: Mapped[date] = mapped_column(Date, nullable=False)
    available_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Why per-plan lifecycle flags: a "Monthly Flex" plan lets customers pause
    # anytime, but an "Annual Commitment" plan locks them in for 12 months.
    # The business owner decides this at plan creation, not the code.
    auto_close_on_expiry: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_early_close: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_pause: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_renewal: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="plan")


# ─── Tax Rules ────────────────────────────────────────────────────────────────

class TaxRule(Base):
    __tablename__ = "tax_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Which product types this tax applies to (e.g., ["SUBSCRIPTION", "ADDON"])
    applies_to_product_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─── Discount Rules ──────────────────────────────────────────────────────────

class DiscountRule(Base):
    """
    Why discount rules are admin-only and self-expiring:
    Sales reps should never invent discounts on the fly — that's how margin
    leaks happen. Admins define the rules; the billing engine mechanically
    applies them. Once max_uses is hit or end_date passes, the discount
    silently stops applying. No manual cleanup needed.
    """
    __tablename__ = "discount_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    discount_type: Mapped[DiscountType] = mapped_column(SAEnum(DiscountType), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    min_purchase_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    min_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    times_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scope: Mapped[DiscountScope] = mapped_column(SAEnum(DiscountScope), nullable=False)
    # Stores product IDs this discount is eligible for. NULL = all products.
    eligible_product_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint("value > 0", name="ck_discount_value_positive"),
    )


# ─── Quotation Templates ─────────────────────────────────────────────────────

class QuotationTemplate(Base):
    """
    Pre-packaged blueprints that let sales reps spin up a subscription with
    one click instead of manually picking plan + products + payment terms.
    """
    __tablename__ = "quotation_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), nullable=False)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    payment_terms: Mapped[str] = mapped_column(String(100), nullable=False, default="Net 30")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped["SubscriptionPlan"] = relationship()
    template_lines: Mapped[list["QuotationTemplateLine"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class QuotationTemplateLine(Base):
    __tablename__ = "quotation_template_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("quotation_templates.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    template: Mapped["QuotationTemplate"] = relationship(back_populates="template_lines")
    product: Mapped["Product"] = relationship()
    variant: Mapped["ProductVariant | None"] = relationship()


# ─── Subscriptions ────────────────────────────────────────────────────────────

class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Why the sub number is a padded string and not just the PK:
    # Finance teams grep invoice PDFs by "SUB-2026-00042" in email. A raw
    # integer PK is useless for that. The sequence is auto-generated in code
    # to avoid Postgres SEQUENCE gaps from rolled-back transactions.
    subscription_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_billing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_terms: Mapped[str] = mapped_column(String(100), default="Net 30")
    status: Mapped[SubscriptionStatus] = mapped_column(
        SAEnum(SubscriptionStatus), nullable=False, default=SubscriptionStatus.DRAFT
    )
    applied_discount_id: Mapped[int | None] = mapped_column(ForeignKey("discount_rules.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    customer: Mapped["User"] = relationship(back_populates="subscriptions", foreign_keys=[customer_id])
    plan: Mapped["SubscriptionPlan"] = relationship(back_populates="subscriptions")
    discount: Mapped["DiscountRule | None"] = relationship()
    lines: Mapped[list["SubscriptionLine"]] = relationship(back_populates="subscription", cascade="all, delete-orphan")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="subscription")
    audit_log: Mapped[list["SubscriptionAudit"]] = relationship(back_populates="subscription", cascade="all, delete-orphan")

    __table_args__ = (
        # Hot-path index #1: Billing Day batch query
        Index("ix_sub_billing_due", "status", "next_billing_date"),
        # Hot-path index #2: Customer portal "my subscriptions"
        Index("ix_sub_customer", "customer_id", "status"),
    )


class SubscriptionLine(Base):
    __tablename__ = "subscription_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Why store tax_ids as JSON instead of a junction table:
    # A subscription line typically has 1-2 tax rules. A junction table would
    # triple the JOINs on the billing batch query for negligible normalization
    # benefit. JSON keeps the billing query fast and the model simple.
    tax_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    subscription: Mapped["Subscription"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship(back_populates="subscription_lines")
    variant: Mapped["ProductVariant | None"] = relationship()


# ─── Subscription Audit Trail ─────────────────────────────────────────────────

class SubscriptionAudit(Base):
    """
    Why a dedicated audit table instead of relying on updated_at:
    Compliance requires knowing WHO changed the status and WHEN, not just
    "something changed." This is the single source of truth for dispute
    resolution ("I never approved closing my subscription!").
    """
    __tablename__ = "subscription_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    subscription: Mapped["Subscription"] = relationship(back_populates="audit_log")
    changed_by: Mapped["User"] = relationship()


# ─── Invoices ─────────────────────────────────────────────────────────────────

class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Why idempotency_key exists: See the Billing Engine module docstring.
    # TL;DR — deterministic hash of (sub_id + period_start) so retries and
    # concurrent cron runs can never create duplicate invoices.
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(SAEnum(InvoiceStatus), nullable=False, default=InvoiceStatus.DRAFT)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    billing_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    billing_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    amount_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    subscription: Mapped["Subscription"] = relationship(back_populates="invoices")
    customer: Mapped["User"] = relationship()
    lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")

    __table_args__ = (
        # Hot-path index #3: overdue invoice dashboard query
        Index("ix_inv_status_due", "status", "due_date", "customer_id"),
        # Idempotency guard — the billing engine's last line of defense
        UniqueConstraint("idempotency_key", name="uq_invoice_idempotency"),
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    invoice: Mapped["Invoice"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship()
    variant: Mapped["ProductVariant | None"] = relationship()


# ─── Payments ─────────────────────────────────────────────────────────────────

class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(SAEnum(PaymentMethod), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    invoice: Mapped["Invoice"] = relationship(back_populates="payments")
    recorded_by: Mapped["User"] = relationship(back_populates="recorded_payments")

    __table_args__ = (
        # Hot-path index #4: payment ledger on dashboard
        Index("ix_payment_invoice_date", "invoice_id", "payment_date"),
    )

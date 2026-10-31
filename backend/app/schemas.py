"""
Pydantic V2 Schemas — Brightloop
=================================
Strict mode everywhere. We'd rather reject a malformed request at the API
boundary than discover bad data during the Billing Day batch at 2 AM.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator, ConfigDict

from app.models import (
    UserRole, ProductType, BillingInterval, SubscriptionStatus,
    InvoiceStatus, DiscountType, DiscountScope, PaymentMethod,
)


# ─── Auth Schemas ─────────────────────────────────────────────────────────────

# Why the regex lives here and not in the model layer:
# The database should never see a plaintext password. Validation happens
# at the Pydantic boundary, hashing happens in the service, and only the
# hash reaches the DB. Defense in depth.
PASSWORD_REGEX = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*[!@#$%^&*(),.?\":{}|<>_\-+=]).{9,}$"
)


class UserRegister(BaseModel):
    email: str = Field(..., max_length=320)
    password: str = Field(..., min_length=9)
    full_name: str = Field(..., min_length=1, max_length=200)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not PASSWORD_REGEX.match(v):
            raise ValueError(
                "Password must be >8 chars and contain at least one uppercase, "
                "one lowercase, and one special character (!@#$%^&*(),.?\":{}|<>_-+=)"
            )
        return v


class UserLogin(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=9)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not PASSWORD_REGEX.match(v):
            raise ValueError(
                "Password must be >8 chars and contain at least one uppercase, "
                "one lowercase, and one special character."
            )
        return v


class StaffCreate(BaseModel):
    """Only admins can create staff accounts — enforced at the router level."""
    email: str = Field(..., max_length=320)
    password: str = Field(..., min_length=9)
    full_name: str = Field(..., min_length=1, max_length=200)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not PASSWORD_REGEX.match(v):
            raise ValueError(
                "Password must be >8 chars and contain at least one uppercase, "
                "one lowercase, and one special character."
            )
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    full_name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


# ─── Product Schemas ──────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str = Field(..., max_length=200)
    product_type: ProductType
    sales_price: Decimal = Field(default=Decimal("0.00"), ge=0)
    cost_price: Decimal = Field(default=Decimal("0.00"), ge=0)
    notes: Optional[str] = None
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    product_type: Optional[ProductType] = None
    sales_price: Optional[Decimal] = None
    cost_price: Optional[Decimal] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class VariantCreate(BaseModel):
    attribute_name: str = Field(..., max_length=100)
    attribute_value: str = Field(..., max_length=200)
    price_extra: Decimal = Field(default=Decimal("0.00"))
    is_active: bool = True


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    attribute_name: str
    attribute_value: str
    price_extra: Decimal
    is_active: bool


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    product_type: ProductType
    sales_price: Decimal
    cost_price: Decimal
    notes: Optional[str]
    is_active: bool
    created_at: datetime
    variants: List[VariantOut] = []


# ─── Plan Schemas ─────────────────────────────────────────────────────────────

class PlanCreate(BaseModel):
    name: str = Field(..., max_length=200)
    base_cost: Decimal = Field(default=Decimal("0.00"), ge=0)
    billing_interval: BillingInterval
    min_quantity: int = Field(default=1, ge=1)
    available_from: date
    available_to: Optional[date] = None
    auto_close_on_expiry: bool = True
    allow_early_close: bool = False
    allow_pause: bool = False
    allow_renewal: bool = True


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    base_cost: Optional[Decimal] = None
    billing_interval: Optional[BillingInterval] = None
    min_quantity: Optional[int] = None
    available_from: Optional[date] = None
    available_to: Optional[date] = None
    auto_close_on_expiry: Optional[bool] = None
    allow_early_close: Optional[bool] = None
    allow_pause: Optional[bool] = None
    allow_renewal: Optional[bool] = None


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    base_cost: Decimal
    billing_interval: BillingInterval
    min_quantity: int
    available_from: date
    available_to: Optional[date]
    auto_close_on_expiry: bool
    allow_early_close: bool
    allow_pause: bool
    allow_renewal: bool
    is_active: bool
    created_at: datetime


# ─── Tax Schemas ──────────────────────────────────────────────────────────────

class TaxRuleCreate(BaseModel):
    name: str = Field(..., max_length=100)
    rate_percent: Decimal = Field(..., ge=0, le=100)
    is_active: bool = True
    applies_to_product_types: Optional[List[str]] = None


class TaxRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    rate_percent: Decimal
    is_active: bool
    applies_to_product_types: Optional[List[str]]
    created_at: datetime


# ─── Discount Schemas ─────────────────────────────────────────────────────────

class DiscountRuleCreate(BaseModel):
    name: str = Field(..., max_length=200)
    code: str = Field(..., max_length=50)
    discount_type: DiscountType
    value: Decimal = Field(..., gt=0)
    min_purchase_amount: Optional[Decimal] = None
    min_quantity: Optional[int] = None
    start_date: date
    end_date: date
    max_uses: Optional[int] = None
    scope: DiscountScope
    eligible_product_ids: Optional[List[int]] = None


class DiscountRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    discount_type: DiscountType
    value: Decimal
    min_purchase_amount: Optional[Decimal]
    min_quantity: Optional[int]
    start_date: date
    end_date: date
    max_uses: Optional[int]
    times_used: int
    scope: DiscountScope
    eligible_product_ids: Optional[List[int]]
    is_active: bool
    created_at: datetime


# ─── Quotation Template Schemas ──────────────────────────────────────────────

class TemplateLineCreate(BaseModel):
    product_id: int
    variant_id: Optional[int] = None
    quantity: int = Field(default=1, ge=1)
    description: Optional[str] = None


class QuotationTemplateCreate(BaseModel):
    name: str = Field(..., max_length=200)
    plan_id: int
    validity_days: int = Field(default=30, ge=1)
    payment_terms: str = Field(default="Net 30", max_length=100)
    notes: Optional[str] = None
    lines: List[TemplateLineCreate] = []


class TemplateLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    template_id: int
    product_id: int
    variant_id: Optional[int]
    quantity: int
    description: Optional[str]


class QuotationTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    plan_id: int
    validity_days: int
    payment_terms: str
    notes: Optional[str]
    is_active: bool
    created_at: datetime
    template_lines: List[TemplateLineOut] = []


# ─── Subscription Schemas ────────────────────────────────────────────────────

class SubscriptionLineCreate(BaseModel):
    product_id: int
    variant_id: Optional[int] = None
    description: str = ""
    quantity: int = Field(default=1, ge=1)


class SubscriptionCreate(BaseModel):
    customer_id: int
    plan_id: int
    start_date: date
    expiry_date: Optional[date] = None
    payment_terms: str = Field(default="Net 30", max_length=100)
    applied_discount_id: Optional[int] = None
    notes: Optional[str] = None
    lines: List[SubscriptionLineCreate] = []


class SubscriptionLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subscription_id: int
    product_id: int
    variant_id: Optional[int]
    description: str
    quantity: int
    unit_price: Decimal
    tax_ids: Optional[List[int]]
    discount_amount: Decimal
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subscription_number: str
    customer_id: int
    plan_id: int
    start_date: date
    expiry_date: Optional[date]
    next_billing_date: Optional[date]
    payment_terms: str
    status: SubscriptionStatus
    applied_discount_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    lines: List[SubscriptionLineOut] = []


class SubscriptionDetailOut(SubscriptionOut):
    """Extended with customer name, plan name for detail views."""
    customer_name: Optional[str] = None
    plan_name: Optional[str] = None
    discount_code: Optional[str] = None


class StatusTransitionRequest(BaseModel):
    target_status: SubscriptionStatus
    notes: Optional[str] = None


# ─── Invoice Schemas ──────────────────────────────────────────────────────────

class InvoiceLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    invoice_id: int
    product_id: int
    variant_id: Optional[int]
    description: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    subtotal: Decimal
    total_amount: Decimal


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    invoice_number: str
    subscription_id: int
    customer_id: int
    status: InvoiceStatus
    issue_date: date
    due_date: date
    billing_period_start: date
    billing_period_end: date
    subtotal: Decimal
    tax_total: Decimal
    discount_total: Decimal
    total_amount: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    notes: Optional[str]
    created_at: datetime
    lines: List[InvoiceLineOut] = []


class InvoiceDetailOut(InvoiceOut):
    customer_name: Optional[str] = None
    subscription_number: Optional[str] = None


# ─── Payment Schemas ─────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    invoice_id: int
    payment_method: PaymentMethod
    amount: Decimal = Field(..., gt=0)
    payment_date: date
    reference_note: Optional[str] = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    invoice_id: int
    payment_method: PaymentMethod
    amount: Decimal
    payment_date: date
    reference_note: Optional[str]
    recorded_by_id: int
    created_at: datetime


class PaymentDetailOut(PaymentOut):
    invoice_number: Optional[str] = None
    customer_name: Optional[str] = None


# ─── Dashboard / Analytics Schemas ───────────────────────────────────────────

class DashboardKPIs(BaseModel):
    active_subscriptions: int = 0
    mrr: Decimal = Decimal("0.00")
    arr: Decimal = Decimal("0.00")
    total_revenue_collected: Decimal = Decimal("0.00")
    total_outstanding: Decimal = Decimal("0.00")
    overdue_invoice_count: int = 0
    draft_invoice_count: int = 0
    total_customers: int = 0


class CursorPage(BaseModel):
    """Generic cursor-paginated response wrapper."""
    items: list
    next_cursor: Optional[str] = None
    has_more: bool = False
    total_estimate: Optional[int] = None


# ─── Audit Schema ────────────────────────────────────────────────────────────

class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subscription_id: int
    from_status: str
    to_status: str
    changed_by_id: int
    changed_at: datetime
    notes: Optional[str]

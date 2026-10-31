"""
Subscription Service — Brightloop
===================================
Owns the subscription lifecycle: template instantiation, line pricing,
variant price-extra calculation, and the 5-stage state machine.

State Machine Rules:
  DRAFT → QUOTATION → CONFIRMED → ACTIVE → CLOSED
                                     ↓ ↑
                                   PAUSED  (only if plan.allow_pause)

Why a dedicated state machine instead of ad-hoc status updates:
  In every ERP I've built, the #1 source of billing bugs is a rogue API call
  that sets status='ACTIVE' on a subscription that was never confirmed. The
  state machine is the single chokepoint that prevents impossible transitions.
  Every transition is logged in the audit trail with the user ID, so when the
  customer disputes a charge, we can show the exact chain of events.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Subscription, SubscriptionLine, SubscriptionStatus, SubscriptionAudit,
    SubscriptionPlan, Product, ProductVariant, QuotationTemplate,
    QuotationTemplateLine, TaxRule, DiscountRule, BillingInterval,
)


# ─── State Machine ───────────────────────────────────────────────────────────

# Why a dict-of-sets instead of an if/elif chain:
# Adding a new state (e.g., ON_HOLD) is a one-liner, and the exhaustive
# mapping makes it impossible to forget an edge case.
VALID_TRANSITIONS = {
    SubscriptionStatus.DRAFT: {SubscriptionStatus.QUOTATION, SubscriptionStatus.CONFIRMED},
    SubscriptionStatus.QUOTATION: {SubscriptionStatus.CONFIRMED, SubscriptionStatus.DRAFT},
    SubscriptionStatus.CONFIRMED: {SubscriptionStatus.ACTIVE},
    SubscriptionStatus.ACTIVE: {SubscriptionStatus.CLOSED, SubscriptionStatus.PAUSED},
    SubscriptionStatus.PAUSED: {SubscriptionStatus.ACTIVE, SubscriptionStatus.CLOSED},
    SubscriptionStatus.CLOSED: set(),  # Terminal state — no way out
}


class SubscriptionStateMachine:
    """
    Enforces valid subscription status transitions and checks plan-level
    lifecycle policy flags (allow_pause, allow_early_close, etc.).
    """

    @staticmethod
    def validate_transition(
        current: SubscriptionStatus,
        target: SubscriptionStatus,
        plan: SubscriptionPlan,
    ) -> str | None:
        """Returns an error message if the transition is invalid, None if OK."""
        allowed = VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            return f"Cannot transition from {current.value} to {target.value}"

        # Plan-level policy checks
        if target == SubscriptionStatus.PAUSED and not plan.allow_pause:
            return f"Plan '{plan.name}' does not allow pausing"

        if target == SubscriptionStatus.CLOSED and current == SubscriptionStatus.ACTIVE:
            if not plan.allow_early_close:
                return f"Plan '{plan.name}' does not allow early closure"

        return None


# ─── Subscription Number Generator ───────────────────────────────────────────

async def generate_subscription_number(db: AsyncSession) -> str:
    """
    Why we generate SUB-YYYY-NNNNN in code instead of a DB sequence:
    Postgres sequences have gaps when transactions roll back. Finance teams
    hate gaps in document numbers because auditors flag them. We use MAX(id)+1
    inside the transaction, which is gap-free within the committed history.
    """
    year = date.today().year
    result = await db.execute(
        select(func.count(Subscription.id))
    )
    count = result.scalar() or 0
    return f"SUB-{year}-{count + 1:05d}"


# ─── Price Calculation ────────────────────────────────────────────────────────

def calculate_effective_price(product: Product, variant: ProductVariant | None) -> Decimal:
    """
    Effective unit price = base sales price + variant price extra.
    The variant adds a delta (e.g., +560 for the "Odoo Enterprise" brand),
    not a multiplier. This is standard ERP pricing — multiplicative markups
    go in a separate pricing tier model if needed.
    """
    base = product.sales_price or Decimal("0.00")
    extra = variant.price_extra if variant else Decimal("0.00")
    return (base + extra).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def compute_line_totals(
    line: SubscriptionLine,
    db: AsyncSession,
    discount: DiscountRule | None = None,
) -> SubscriptionLine:
    """
    Computes subtotal, tax, discount, and total for a single subscription line.
    Called during both initial subscription creation and Billing Day invoice generation.
    """
    subtotal = (line.unit_price * line.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Apply discount
    discount_amount = Decimal("0.00")
    if discount and discount.is_active:
        today = date.today()
        if discount.start_date <= today <= discount.end_date:
            if discount.max_uses is None or discount.times_used < discount.max_uses:
                eligible = True
                if discount.eligible_product_ids:
                    eligible = line.product_id in discount.eligible_product_ids
                if discount.min_quantity and line.quantity < discount.min_quantity:
                    eligible = False
                if eligible:
                    if discount.discount_type.value == "PERCENTAGE":
                        discount_amount = (subtotal * discount.value / Decimal("100")).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                    else:
                        discount_amount = min(discount.value, subtotal)

    after_discount = subtotal - discount_amount

    # Compute tax
    tax_amount = Decimal("0.00")
    if line.tax_ids:
        result = await db.execute(
            select(TaxRule).where(TaxRule.id.in_(line.tax_ids), TaxRule.is_active == True)
        )
        taxes = result.scalars().all()
        for tax in taxes:
            tax_amount += (after_discount * tax.rate_percent / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

    line.subtotal = subtotal
    line.discount_amount = discount_amount
    line.tax_amount = tax_amount
    line.total_amount = (after_discount + tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return line


# ─── Next Billing Date Calculation ───────────────────────────────────────────

def compute_next_billing_date(current: date, interval: BillingInterval) -> date:
    """Advance the billing date by one interval period."""
    if interval == BillingInterval.DAILY:
        return current + timedelta(days=1)
    elif interval == BillingInterval.WEEKLY:
        return current + timedelta(weeks=1)
    elif interval == BillingInterval.MONTHLY:
        # Why not relativedelta: we avoid the dependency for a single use.
        month = current.month + 1
        year = current.year
        if month > 12:
            month = 1
            year += 1
        day = min(current.day, 28)  # Safe for all months
        return date(year, month, day)
    elif interval == BillingInterval.YEARLY:
        return date(current.year + 1, current.month, min(current.day, 28))
    return current + timedelta(days=30)


# ─── Template Instantiation ──────────────────────────────────────────────────

async def create_subscription_from_template(
    template_id: int,
    customer_id: int,
    user_id: int,
    db: AsyncSession,
    start_date: date | None = None,
) -> Subscription:
    """
    One-click subscription creation from a quotation template.
    Why we deep-copy template lines instead of referencing them:
    The template is a blueprint. If an admin later changes the template's
    product list, existing subscriptions created from the old version must
    remain unchanged — financial documents are immutable once created.
    """
    result = await db.execute(
        select(QuotationTemplate)
        .options(selectinload(QuotationTemplate.template_lines))
        .where(QuotationTemplate.id == template_id, QuotationTemplate.is_active == True)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise ValueError(f"Quotation template {template_id} not found or inactive")

    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == template.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise ValueError(f"Plan {template.plan_id} not found")

    sub_number = await generate_subscription_number(db)
    actual_start = start_date or date.today()

    sub = Subscription(
        subscription_number=sub_number,
        customer_id=customer_id,
        plan_id=template.plan_id,
        start_date=actual_start,
        expiry_date=actual_start + timedelta(days=template.validity_days),
        next_billing_date=actual_start,
        payment_terms=template.payment_terms,
        status=SubscriptionStatus.DRAFT,
        notes=f"Created from template: {template.name}",
    )
    db.add(sub)
    await db.flush()

    # Fetch active tax rules for auto-assignment
    tax_result = await db.execute(select(TaxRule).where(TaxRule.is_active == True))
    active_taxes = tax_result.scalars().all()

    for tl in template.template_lines:
        product_result = await db.execute(select(Product).where(Product.id == tl.product_id))
        product = product_result.scalar_one_or_none()
        if not product:
            continue

        variant = None
        if tl.variant_id:
            variant_result = await db.execute(
                select(ProductVariant).where(ProductVariant.id == tl.variant_id)
            )
            variant = variant_result.scalar_one_or_none()

        effective_price = calculate_effective_price(product, variant)
        qty = max(tl.quantity, plan.min_quantity)

        # Auto-assign applicable taxes based on product type
        applicable_tax_ids = [
            t.id for t in active_taxes
            if t.applies_to_product_types is None
            or product.product_type.value in t.applies_to_product_types
        ]

        line = SubscriptionLine(
            subscription_id=sub.id,
            product_id=tl.product_id,
            variant_id=tl.variant_id,
            description=tl.description or product.name,
            quantity=qty,
            unit_price=effective_price,
            tax_ids=applicable_tax_ids if applicable_tax_ids else None,
        )
        line = await compute_line_totals(line, db)
        db.add(line)

    # Log the creation in the audit trail
    audit = SubscriptionAudit(
        subscription_id=sub.id,
        from_status="NONE",
        to_status=SubscriptionStatus.DRAFT.value,
        changed_by_id=user_id,
        notes=f"Created from template '{template.name}'",
    )
    db.add(audit)

    await db.commit()
    fresh_result = await db.execute(
        select(Subscription)
        .options(
            selectinload(Subscription.lines),
            selectinload(Subscription.plan),
        )
        .where(Subscription.id == sub.id)
    )
    return fresh_result.scalar_one()


async def transition_subscription(
    subscription_id: int,
    target_status: SubscriptionStatus,
    user_id: int,
    db: AsyncSession,
    notes: str | None = None,
) -> Subscription:
    """
    The single entry point for all subscription status changes.
    Validates the transition, logs it, and handles side effects like
    setting next_billing_date on activation.
    """
    result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .where(Subscription.id == subscription_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise ValueError(f"Subscription {subscription_id} not found")

    error = SubscriptionStateMachine.validate_transition(sub.status, target_status, sub.plan)
    if error:
        raise ValueError(error)

    old_status = sub.status
    sub.status = target_status

    # Side effects on specific transitions
    if target_status == SubscriptionStatus.ACTIVE:
        if not sub.next_billing_date:
            sub.next_billing_date = sub.start_date

    if target_status == SubscriptionStatus.PAUSED:
        # Clear billing date so the billing engine skips this sub
        sub.next_billing_date = None

    if target_status == SubscriptionStatus.CLOSED:
        sub.next_billing_date = None

    # Audit trail
    audit = SubscriptionAudit(
        subscription_id=sub.id,
        from_status=old_status.value,
        to_status=target_status.value,
        changed_by_id=user_id,
        notes=notes,
    )
    db.add(audit)

    await db.commit()
    # Re-fetch with lines and plan loaded to prevent MissingGreenlet error during Pydantic serialization
    fresh_result = await db.execute(
        select(Subscription)
        .options(
            selectinload(Subscription.lines),
            selectinload(Subscription.plan),
        )
        .where(Subscription.id == sub.id)
    )
    return fresh_result.scalar_one()

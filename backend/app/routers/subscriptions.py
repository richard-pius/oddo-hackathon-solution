"""
Subscriptions Router — Brightloop
====================================
CRUD + state machine transitions for subscriptions. Includes template
instantiation, line management, and cursor-paginated listing.

Why cursor pagination over OFFSET:
  With 50,000+ subscriptions, OFFSET 40000 forces Postgres to scan and
  discard 40,000 rows before returning the next 50. Cursor-based pagination
  (WHERE id > :last_id ORDER BY id LIMIT 50) uses the PK index directly
  and runs in constant time regardless of how deep the user scrolls.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import (
    User, UserRole, Subscription, SubscriptionLine, SubscriptionStatus,
    Product, ProductVariant, TaxRule, SubscriptionPlan,
)
from app.schemas import (
    SubscriptionCreate, SubscriptionOut, SubscriptionDetailOut,
    SubscriptionLineCreate, SubscriptionLineOut,
    StatusTransitionRequest, AuditEntryOut,
)
from app.services.auth_service import get_current_user, require_staff_or_admin
from app.services.subscription_service import (
    generate_subscription_number, calculate_effective_price,
    compute_line_totals, transition_subscription,
    create_subscription_from_template,
)

router = APIRouter(prefix="/api/v1/subscriptions", tags=["Subscriptions"])


# ─── List with cursor pagination ─────────────────────────────────────────────

@router.get("/", response_model=dict)
async def list_subscriptions(
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status_filter: SubscriptionStatus | None = None,
    customer_id: int | None = None,
    plan_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Cursor-paginated subscription listing. Customers are automatically
    scoped to their own subscriptions — no parameter needed.
    """
    query = select(Subscription).options(
        selectinload(Subscription.lines),
        selectinload(Subscription.plan),
        selectinload(Subscription.customer),
    )

    # Why we scope at the SQL level, not in Python:
    # Filtering in Python after fetching all rows is a data leak waiting to
    # happen. A disgruntled customer could just change the cursor to peek at
    # other customers' subscriptions. SQL-level scoping makes it impossible.
    if current_user.role == UserRole.CUSTOMER:
        query = query.where(Subscription.customer_id == current_user.id)
    elif customer_id:
        query = query.where(Subscription.customer_id == customer_id)

    if status_filter:
        query = query.where(Subscription.status == status_filter)
    if plan_id:
        query = query.where(Subscription.plan_id == plan_id)

    # Cursor pagination: use PK for stable ordering
    if cursor > 0:
        query = query.where(Subscription.id > cursor)

    query = query.order_by(Subscription.id).limit(limit + 1)

    result = await db.execute(query)
    subs = result.scalars().all()

    has_more = len(subs) > limit
    items = subs[:limit]

    # Enrich with names for the list view
    sub_dicts = []
    for s in items:
        d = SubscriptionDetailOut.model_validate(s)
        d.customer_name = s.customer.full_name if s.customer else None
        d.plan_name = s.plan.name if s.plan else None
        sub_dicts.append(d)

    return {
        "items": sub_dicts,
        "next_cursor": items[-1].id if has_more and items else None,
        "has_more": has_more,
    }


# ─── Create Subscription ─────────────────────────────────────────────────────

@router.post("/", response_model=SubscriptionOut, status_code=201)
async def create_subscription(
    data: SubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    """Create a new subscription with lines. Staff/Admin only."""
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == data.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    sub_number = await generate_subscription_number(db)

    sub = Subscription(
        subscription_number=sub_number,
        customer_id=data.customer_id,
        plan_id=data.plan_id,
        start_date=data.start_date,
        expiry_date=data.expiry_date,
        next_billing_date=data.start_date,
        payment_terms=data.payment_terms,
        status=SubscriptionStatus.DRAFT,
        applied_discount_id=data.applied_discount_id,
        notes=data.notes,
    )
    db.add(sub)
    await db.flush()

    # Fetch active taxes for auto-assignment
    tax_result = await db.execute(select(TaxRule).where(TaxRule.is_active == True))
    active_taxes = tax_result.scalars().all()

    discount = None
    if data.applied_discount_id:
        from app.models import DiscountRule
        disc_result = await db.execute(
            select(DiscountRule).where(DiscountRule.id == data.applied_discount_id)
        )
        discount = disc_result.scalar_one_or_none()

    for line_data in data.lines:
        prod_result = await db.execute(select(Product).where(Product.id == line_data.product_id))
        product = prod_result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {line_data.product_id} not found")

        variant = None
        if line_data.variant_id:
            var_result = await db.execute(
                select(ProductVariant).where(ProductVariant.id == line_data.variant_id)
            )
            variant = var_result.scalar_one_or_none()

        effective_price = calculate_effective_price(product, variant)
        qty = max(line_data.quantity, plan.min_quantity)

        applicable_tax_ids = [
            t.id for t in active_taxes
            if t.applies_to_product_types is None
            or product.product_type.value in t.applies_to_product_types
        ]

        line = SubscriptionLine(
            subscription_id=sub.id,
            product_id=line_data.product_id,
            variant_id=line_data.variant_id,
            description=line_data.description or product.name,
            quantity=qty,
            unit_price=effective_price,
            tax_ids=applicable_tax_ids if applicable_tax_ids else None,
        )
        line = await compute_line_totals(line, db, discount)
        db.add(line)

    await db.commit()
    await db.refresh(sub)

    # Re-fetch with lines loaded
    result = await db.execute(
        select(Subscription).options(selectinload(Subscription.lines)).where(Subscription.id == sub.id)
    )
    return result.scalar_one()


# ─── Get Single Subscription ─────────────────────────────────────────────────

@router.get("/{subscription_id}", response_model=SubscriptionDetailOut)
async def get_subscription(
    subscription_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Subscription)
        .options(
            selectinload(Subscription.lines),
            selectinload(Subscription.plan),
            selectinload(Subscription.customer),
            selectinload(Subscription.discount),
        )
        .where(Subscription.id == subscription_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Customer can only see their own
    if current_user.role == UserRole.CUSTOMER and sub.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    out = SubscriptionDetailOut.model_validate(sub)
    out.customer_name = sub.customer.full_name if sub.customer else None
    out.plan_name = sub.plan.name if sub.plan else None
    out.discount_code = sub.discount.code if sub.discount else None
    return out


# ─── State Transition ────────────────────────────────────────────────────────

@router.post("/{subscription_id}/transition", response_model=SubscriptionOut)
async def transition_status(
    subscription_id: int,
    data: StatusTransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Advance the subscription through its lifecycle.
    Customers can only perform transitions allowed by their plan's policy flags.
    """
    # Fetch the subscription to check ownership
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if current_user.role == UserRole.CUSTOMER and sub.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        updated = await transition_subscription(
            subscription_id, data.target_status, current_user.id, db, data.notes
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Create from Template ────────────────────────────────────────────────────

@router.post("/from-template/{template_id}", response_model=SubscriptionOut, status_code=201)
async def create_from_template(
    template_id: int,
    customer_id: int,
    start_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    """One-click subscription creation from a quotation template."""
    try:
        sub = await create_subscription_from_template(
            template_id, customer_id, user.id, db, start_date
        )
        return sub
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Audit Trail & Chatter ───────────────────────────────────────────────────

@router.get("/{subscription_id}/audit", response_model=list[AuditEntryOut])
async def get_audit_trail(
    subscription_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Retrieve audit trail for a subscription.
    Staff/Admin can view any; Customers can only view their own contract audit.
    """
    from app.models import SubscriptionAudit, Subscription
    sub = await db.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if user.role == UserRole.CUSTOMER and sub.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(SubscriptionAudit)
        .where(SubscriptionAudit.subscription_id == subscription_id)
        .order_by(SubscriptionAudit.changed_at.desc())
    )
    return result.scalars().all()


class ChatterMessage(BaseModel):
    message: str


@router.post("/{subscription_id}/chatter")
async def post_chatter_message(
    subscription_id: int,
    data: ChatterMessage,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Posts a message to the subscription chatter / audit feed."""
    from app.models import SubscriptionAudit, Subscription
    sub = await db.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Strict isolation: customer can only comment on their own contract
    if user.role == UserRole.CUSTOMER and sub.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    audit = SubscriptionAudit(
        subscription_id=subscription_id,
        changed_by_id=user.id,
        from_status=sub.status.value,
        to_status=sub.status.value,
        notes=f"💬 {user.full_name}: {data.message}",
    )
    db.add(audit)
    await db.commit()
    await db.refresh(audit)
    return {
        "id": audit.id,
        "subscription_id": subscription_id,
        "reason": audit.notes,
        "changed_at": audit.changed_at,
        "user_name": user.full_name,
    }


class ProrateUpgradeRequest(BaseModel):
    line_id: int
    new_quantity: int
    reason: str = "Mid-cycle seat expansion"


@router.post("/{subscription_id}/prorate")
async def prorate_subscription_upgrade(
    subscription_id: int,
    data: ProrateUpgradeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Odoo-grade prorated seat upgrade.
    Calculates remaining cycle days and generates an immediate prorated invoice.
    Strict tenant check: customer can only prorate their own subscription.
    """
    from decimal import Decimal
    from datetime import date, timedelta
    from app.models import Subscription, SubscriptionLine, SubscriptionAudit, Invoice, InvoiceLine, InvoiceStatus
    from app.services.billing_engine import generate_invoice_number
    from app.services.continuous_stream import event_broadcaster

    result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.lines), selectinload(Subscription.plan))
        .where(Subscription.id == subscription_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Strict tenant isolation
    if user.role == UserRole.CUSTOMER and sub.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    line = next((l for l in sub.lines if l.id == data.line_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Subscription line item not found")

    old_qty = line.quantity
    delta_qty = data.new_quantity - old_qty
    if delta_qty <= 0:
        # Downgrade takes effect on the next renewal
        line.quantity = data.new_quantity
        audit = SubscriptionAudit(
            subscription_id=sub.id,
            changed_by_id=user.id,
            from_status=sub.status.value,
            to_status=sub.status.value,
            notes=f"Downgraded line '{line.description}' from {old_qty} to {data.new_quantity} seats (effective next renewal cycle).",
        )
        db.add(audit)
        await db.commit()
        return {
            "status": "downgraded",
            "old_quantity": old_qty,
            "new_quantity": data.new_quantity,
            "prorated_amount": 0.0,
            "invoice_number": None,
        }

    # Calculate days remaining in current billing period
    today = date.today()
    next_bill = sub.next_billing_date or (today + timedelta(days=30))
    days_remaining = max(1, (next_bill - today).days)
    period_length = 30 if sub.plan.billing_interval.value == "month" else 365
    ratio = Decimal(days_remaining) / Decimal(period_length)

    additional_recurring = line.unit_price * Decimal(delta_qty)
    prorated_amount = (additional_recurring * ratio).quantize(Decimal("0.01"))

    # Generate immediate prorated invoice
    inv_num = await generate_invoice_number(db)
    invoice = Invoice(
        invoice_number=inv_num,
        subscription_id=sub.id,
        customer_id=sub.customer_id,
        issue_date=today,
        due_date=today + timedelta(days=14),
        billing_period_start=today,
        billing_period_end=next_bill,
        subtotal=prorated_amount,
        discount_total=Decimal("0.00"),
        tax_total=Decimal("0.00"),
        total_amount=prorated_amount,
        amount_paid=Decimal("0.00"),
        amount_due=prorated_amount,
        status=InvoiceStatus.CONFIRMED,
        idempotency_key=f"PRORATE-{sub.id}-{line.id}-{today.isoformat()}",
    )
    db.add(invoice)
    await db.flush()

    inv_line = InvoiceLine(
        invoice_id=invoice.id,
        product_id=line.product_id,
        variant_id=line.variant_id,
        description=f"Prorated upgrade: +{delta_qty} seats for {line.description} ({days_remaining}/{period_length} days remaining)",
        quantity=delta_qty,
        unit_price=line.unit_price,
        subtotal=prorated_amount,
        tax_amount=Decimal("0.00"),
        total_amount=prorated_amount,
    )
    db.add(inv_line)

    # Update line quantity for future recurring billing
    line.quantity = data.new_quantity

    # Audit log
    audit = SubscriptionAudit(
        subscription_id=sub.id,
        changed_by_id=user.id,
        from_status=sub.status.value,
        to_status=sub.status.value,
        notes=f"Prorated seat expansion from {old_qty} to {data.new_quantity} seats (+{delta_qty}). Generated invoice {inv_num} for ${prorated_amount:,.2f}.",
    )
    db.add(audit)
    await db.commit()

    # Broadcast event via SSE
    await event_broadcaster.broadcast(
        "subscription_transition",
        {
            "detail": f"Subscription {sub.subscription_number} upgraded to {data.new_quantity} seats (Invoice {inv_num}: ${prorated_amount:,.2f})",
            "subscription_id": sub.id,
            "invoice_id": invoice.id,
        }
    )

    return {
        "status": "prorated_success",
        "old_quantity": old_qty,
        "new_quantity": data.new_quantity,
        "delta_quantity": delta_qty,
        "days_remaining": days_remaining,
        "prorated_amount": float(prorated_amount),
        "invoice_id": invoice.id,
        "invoice_number": inv_num,
    }


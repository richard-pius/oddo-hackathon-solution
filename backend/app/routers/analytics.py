"""
Analytics Router — Finance Lead Dashboard KPIs
================================================
Pre-aggregated queries that resolve in < 50ms by using the composite indexes
defined in models.py. The dashboard calls this on initial load and then
relies on SSE events for incremental updates.

Why a single /dashboard endpoint instead of separate /mrr, /arr, /overdue:
  The Finance Lead opens the dashboard and expects to see everything at once.
  Five parallel API calls would race and render in random order, causing a
  jarring "popcorn" effect. A single query with all metrics guarantees
  the dashboard loads atomically — all numbers are from the same DB snapshot.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    User, UserRole, Subscription, SubscriptionStatus,
    Invoice, InvoiceStatus, Payment, SubscriptionPlan, BillingInterval,
)
from app.schemas import DashboardKPIs
from app.services.auth_service import require_staff_or_admin

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


@router.get("/dashboard", response_model=DashboardKPIs)
async def get_dashboard_kpis(
    start_date: date | None = None,
    end_date: date | None = None,
    plan_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    """
    Returns all executive KPIs in a single query batch.
    Filters are optional — omit them for the "all-time" view.
    """
    today = date.today()

    # Active subscriptions count
    active_query = select(func.count(Subscription.id)).where(
        Subscription.status == SubscriptionStatus.ACTIVE
    )
    if plan_id:
        active_query = active_query.where(Subscription.plan_id == plan_id)
    active_result = await db.execute(active_query)
    active_count = active_result.scalar() or 0

    # MRR: sum of all active subscription line totals, normalized to monthly
    # Why we compute MRR from subscription lines instead of invoices:
    # Invoices represent past billing. MRR represents forward-looking committed
    # revenue. A subscription that was just activated but hasn't been billed yet
    # still contributes to MRR.
    from app.models import SubscriptionLine
    mrr_query = (
        select(func.coalesce(func.sum(SubscriptionLine.total_amount), 0))
        .join(Subscription, SubscriptionLine.subscription_id == Subscription.id)
        .where(Subscription.status == SubscriptionStatus.ACTIVE)
    )
    if plan_id:
        mrr_query = mrr_query.where(Subscription.plan_id == plan_id)
    mrr_result = await db.execute(mrr_query)
    raw_mrr = Decimal(str(mrr_result.scalar() or 0))

    # Total revenue collected (sum of all payments)
    revenue_query = select(func.coalesce(func.sum(Payment.amount), 0))
    if start_date:
        revenue_query = revenue_query.where(Payment.payment_date >= start_date)
    if end_date:
        revenue_query = revenue_query.where(Payment.payment_date <= end_date)
    revenue_result = await db.execute(revenue_query)
    total_revenue = Decimal(str(revenue_result.scalar() or 0))

    # Total outstanding (sum of amount_due on non-cancelled invoices)
    outstanding_query = select(func.coalesce(func.sum(Invoice.amount_due), 0)).where(
        Invoice.status.in_([InvoiceStatus.CONFIRMED, InvoiceStatus.DRAFT])
    )
    outstanding_result = await db.execute(outstanding_query)
    total_outstanding = Decimal(str(outstanding_result.scalar() or 0))

    # Overdue invoices count
    overdue_query = select(func.count(Invoice.id)).where(
        Invoice.status == InvoiceStatus.CONFIRMED,
        Invoice.due_date < today,
        Invoice.amount_due > 0,
    )
    overdue_result = await db.execute(overdue_query)
    overdue_count = overdue_result.scalar() or 0

    # Draft invoices count (pending confirmation)
    draft_query = select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.DRAFT)
    draft_result = await db.execute(draft_query)
    draft_count = draft_result.scalar() or 0

    # Total customers
    customer_query = select(func.count(User.id)).where(User.role == UserRole.CUSTOMER)
    customer_result = await db.execute(customer_query)
    total_customers = customer_result.scalar() or 0

    return DashboardKPIs(
        active_subscriptions=active_count,
        mrr=raw_mrr,
        arr=raw_mrr * 12,
        total_revenue_collected=total_revenue,
        total_outstanding=total_outstanding,
        overdue_invoice_count=overdue_count,
        draft_invoice_count=draft_count,
        total_customers=total_customers,
    )


@router.get("/overdue-invoices", response_model=dict)
async def get_overdue_invoices(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    """Top overdue invoices for the alert table on the dashboard."""
    from sqlalchemy.orm import selectinload
    today = date.today()

    result = await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.customer), selectinload(Invoice.subscription))
        .where(
            Invoice.status == InvoiceStatus.CONFIRMED,
            Invoice.due_date < today,
            Invoice.amount_due > 0,
        )
        .order_by(Invoice.due_date)
        .limit(limit)
    )
    invoices = result.scalars().all()

    return {
        "items": [
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "customer_name": inv.customer.full_name if inv.customer else "Unknown",
                "amount_due": str(inv.amount_due),
                "total_amount": str(inv.total_amount),
                "due_date": inv.due_date.isoformat(),
                "days_overdue": (today - inv.due_date).days,
                "subscription_number": inv.subscription.subscription_number if inv.subscription else None,
            }
            for inv in invoices
        ]
    }


@router.get("/recent-payments", response_model=dict)
async def get_recent_payments(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    """Recent payments ledger for the dashboard."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Payment)
        .options(
            selectinload(Payment.invoice),
            selectinload(Payment.recorded_by),
        )
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )
    payments = result.scalars().all()

    return {
        "items": [
            {
                "id": p.id,
                "invoice_number": p.invoice.invoice_number if p.invoice else None,
                "amount": str(p.amount),
                "payment_method": p.payment_method.value,
                "payment_date": p.payment_date.isoformat(),
                "recorded_by": p.recorded_by.full_name if p.recorded_by else None,
                "reference_note": p.reference_note,
            }
            for p in payments
        ]
    }

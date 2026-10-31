"""
Billing & Invoices Router — Brightloop
========================================
Invoice CRUD, manual billing triggers, Confirm/Cancel/Send actions,
and PDF download endpoint.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, BackgroundTasks
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import (
    User, UserRole, Invoice, InvoiceStatus, InvoiceLine,
    Subscription, SubscriptionStatus, Payment,
)
from app.schemas import InvoiceOut, InvoiceDetailOut
from app.services.auth_service import get_current_user, require_staff_or_admin
from app.services.billing_engine import run_billing_batch, generate_invoice_pdf
from app.services.continuous_stream import event_broadcaster

router = APIRouter(prefix="/api/v1/billing", tags=["Billing & Invoices"])


# ─── List Invoices with cursor pagination ────────────────────────────────────

@router.get("/invoices", response_model=dict)
async def list_invoices(
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status_filter: InvoiceStatus | None = None,
    customer_id: int | None = None,
    overdue_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Invoice).options(
        selectinload(Invoice.lines),
        selectinload(Invoice.customer),
        selectinload(Invoice.subscription),
    )

    if current_user.role == UserRole.CUSTOMER:
        query = query.where(Invoice.customer_id == current_user.id)
    elif customer_id:
        query = query.where(Invoice.customer_id == customer_id)

    if status_filter:
        query = query.where(Invoice.status == status_filter)

    if overdue_only:
        # Why we check both status and date: a PAID invoice past its due_date
        # is not overdue — it was paid on time (or late but settled). Only
        # CONFIRMED invoices with amount_due > 0 past due_date are truly overdue.
        query = query.where(
            Invoice.status == InvoiceStatus.CONFIRMED,
            Invoice.due_date < date.today(),
            Invoice.amount_due > 0,
        )

    if cursor > 0:
        query = query.where(Invoice.id > cursor)

    query = query.order_by(Invoice.id.desc()).limit(limit + 1)

    result = await db.execute(query)
    invoices = result.scalars().all()

    has_more = len(invoices) > limit
    items = invoices[:limit]

    inv_dicts = []
    for inv in items:
        d = InvoiceDetailOut.model_validate(inv)
        d.customer_name = inv.customer.full_name if inv.customer else None
        d.subscription_number = inv.subscription.subscription_number if inv.subscription else None
        inv_dicts.append(d)

    return {
        "items": inv_dicts,
        "next_cursor": items[-1].id if has_more and items else None,
        "has_more": has_more,
    }


# ─── Get Single Invoice ──────────────────────────────────────────────────────

@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut)
async def get_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Invoice)
        .options(
            selectinload(Invoice.lines),
            selectinload(Invoice.customer),
            selectinload(Invoice.subscription),
        )
        .where(Invoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if current_user.role == UserRole.CUSTOMER and inv.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    out = InvoiceDetailOut.model_validate(inv)
    out.customer_name = inv.customer.full_name if inv.customer else None
    out.subscription_number = inv.subscription.subscription_number if inv.subscription else None
    return out


# ─── Invoice Actions: Confirm, Cancel, Send ──────────────────────────────────

@router.post("/invoices/{invoice_id}/confirm", response_model=InvoiceOut)
async def confirm_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    """Transition invoice from DRAFT to CONFIRMED."""
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.status != InvoiceStatus.DRAFT:
        raise HTTPException(status_code=400, detail=f"Cannot confirm invoice in {inv.status.value} status")

    inv.status = InvoiceStatus.CONFIRMED
    await db.commit()
    await db.refresh(inv)

    await event_broadcaster.broadcast({
        "type": "invoice_confirmed",
        "invoice_number": inv.invoice_number,
        "amount": str(inv.total_amount),
    })
    return inv


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceOut)
async def cancel_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    """Cancel invoice — only if DRAFT or CONFIRMED with no payments."""
    result = await db.execute(
        select(Invoice).options(selectinload(Invoice.payments)).where(Invoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.status not in (InvoiceStatus.DRAFT, InvoiceStatus.CONFIRMED):
        raise HTTPException(status_code=400, detail="Can only cancel DRAFT or CONFIRMED invoices")
    if inv.payments:
        raise HTTPException(status_code=400, detail="Cannot cancel invoice with existing payments")

    inv.status = InvoiceStatus.CANCELLED
    await db.commit()
    await db.refresh(inv)
    return inv


@router.post("/invoices/{invoice_id}/send")
async def send_invoice(
    invoice_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_staff_or_admin),
):
    """
    Simulate sending invoice via email. In production, this dispatches an
    async email job with the invoice PDF attached.
    """
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # In production: background_tasks.add_task(send_email, inv)
    await event_broadcaster.broadcast({
        "type": "invoice_sent",
        "invoice_number": inv.invoice_number,
    })
    return {"detail": f"Invoice {inv.invoice_number} queued for sending"}


# ─── Invoice PDF Download ────────────────────────────────────────────────────

@router.get("/invoices/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.lines), selectinload(Invoice.customer))
        .where(Invoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if current_user.role == UserRole.CUSTOMER and inv.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    pdf_bytes = generate_invoice_pdf(inv, inv.lines, inv.customer.full_name)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{inv.invoice_number}.pdf"',
        },
    )


# ─── Manual Billing Trigger ──────────────────────────────────────────────────

@router.post("/run-billing")
@router.post("/batch-run")
async def trigger_billing_run(
    billing_date: date | None = None,
    user: User = Depends(require_staff_or_admin),
):
    """
    Staff can manually trigger a billing run. Useful for catch-up runs
    or testing. The billing engine's idempotency guarantees no double-billing
    even if this is called while the nightly cron is running.
    """
    result = await run_billing_batch(billing_date)
    return {"detail": "Billing run complete", **result}

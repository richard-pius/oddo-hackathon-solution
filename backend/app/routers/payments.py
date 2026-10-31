"""
Payments Router — Brightloop
===============================
Records payments against invoices, handles auto-reconciliation
(marking invoices as PAID when amount_due hits zero), and provides
a ledger view with cursor pagination.

Why auto-reconciliation is immediate:
  In a recurring billing system, a payment arriving between billing runs
  must immediately update the invoice status. If we batch-reconcile once
  a day, the Finance Lead's dashboard shows stale "OVERDUE" alerts for
  invoices that were actually paid hours ago, causing unnecessary panic.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import User, UserRole, Payment, Invoice, InvoiceStatus
from app.schemas import PaymentCreate, PaymentOut, PaymentDetailOut
from app.services.auth_service import get_current_user, require_staff_or_admin
from app.services.continuous_stream import event_broadcaster

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])


@router.post("", response_model=PaymentOut, status_code=201, include_in_schema=False)
@router.post("/", response_model=PaymentOut, status_code=201)
async def record_payment(
    data: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Record a payment against an invoice. Supports partial payments.
    When amount_due hits zero, the invoice auto-transitions to PAID.
    Customers can pay their own invoices; staff/admin can record for any invoice.
    """
    result = await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.customer))
        .where(Invoice.id == data.invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if user.role == UserRole.CUSTOMER and inv.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Cannot pay another customer's invoice")

    if inv.status not in (InvoiceStatus.CONFIRMED, InvoiceStatus.DRAFT):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot record payment for invoice in {inv.status.value} status"
        )

    # Why we don't block overpayments: in some businesses, customers
    # prepay or round up. The overpayment becomes a credit that staff
    # manually applies to the next invoice. We record it faithfully.
    if data.amount > inv.amount_due:
        raise HTTPException(
            status_code=400,
            detail=f"Payment amount ({data.amount}) exceeds amount due ({inv.amount_due})"
        )

    payment = Payment(
        invoice_id=data.invoice_id,
        payment_method=data.payment_method,
        amount=data.amount,
        payment_date=data.payment_date,
        reference_note=data.reference_note,
        recorded_by_id=user.id,
    )
    db.add(payment)

    # Update invoice balances atomically
    inv.amount_paid = inv.amount_paid + data.amount
    inv.amount_due = inv.amount_due - data.amount

    # Auto-reconciliation: if fully paid, transition to PAID
    if inv.amount_due <= Decimal("0.00"):
        inv.amount_due = Decimal("0.00")
        inv.status = InvoiceStatus.PAID
        await event_broadcaster.broadcast({
            "type": "invoice_paid",
            "invoice_number": inv.invoice_number,
            "customer_name": inv.customer.full_name if inv.customer else "Unknown",
            "amount": str(inv.total_amount),
        })

    await db.commit()
    await db.refresh(payment)

    # Broadcast payment event for live dashboard
    await event_broadcaster.broadcast({
        "type": "payment_received",
        "invoice_number": inv.invoice_number,
        "amount": str(data.amount),
        "method": data.payment_method.value,
    })

    return payment


@router.get("", response_model=dict, include_in_schema=False)
@router.get("/", response_model=dict)
async def list_payments(
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    invoice_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cursor-paginated payment ledger."""
    query = select(Payment).options(
        selectinload(Payment.invoice),
        selectinload(Payment.recorded_by),
    )

    if current_user.role == UserRole.CUSTOMER:
        # Customers can only see payments on their own invoices
        query = query.join(Invoice).where(Invoice.customer_id == current_user.id)
    elif invoice_id:
        query = query.where(Payment.invoice_id == invoice_id)

    if cursor > 0:
        query = query.where(Payment.id > cursor)

    query = query.order_by(Payment.id.desc()).limit(limit + 1)

    result = await db.execute(query)
    payments = result.scalars().all()

    has_more = len(payments) > limit
    items = payments[:limit]

    pay_dicts = []
    for p in items:
        d = PaymentDetailOut.model_validate(p)
        d.invoice_number = p.invoice.invoice_number if p.invoice else None
        d.customer_name = p.recorded_by.full_name if p.recorded_by else None
        pay_dicts.append(d)

    return {
        "items": pay_dicts,
        "next_cursor": items[-1].id if has_more and items else None,
        "has_more": has_more,
    }

"""
Billing Engine — Brightloop
=============================
The heart of the recurring revenue system. Runs as a scheduled job (APScheduler)
every night at 00:05 and can also be triggered manually by staff.

Zero Double-Billing Guarantee:
  Each invoice carries an idempotency_key = "INV-{sub_id}-{period_start}".
  A UNIQUE constraint on this column means the DB itself rejects duplicates
  even if two workers race. We also use SELECT ... FOR UPDATE SKIP LOCKED
  to ensure concurrent batch runs grab different chunks instead of deadlocking.

Why SKIP LOCKED instead of advisory locks:
  Advisory locks require the caller to remember to release them. SKIP LOCKED
  is built into the row-level lock semantics — the lock dies with the
  transaction, so a crashed worker can never leave orphan locks.
"""

import io
import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, text, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session_factory
from app.models import (
    Subscription, SubscriptionStatus, SubscriptionLine,
    Invoice, InvoiceStatus, InvoiceLine,
    TaxRule, DiscountRule, BillingInterval,
)
from app.services.subscription_service import compute_next_billing_date
from app.services.continuous_stream import event_broadcaster

logger = logging.getLogger("brightloop.billing")


# ─── Invoice Number Generator ────────────────────────────────────────────────

async def generate_invoice_number(db: AsyncSession) -> str:
    year = date.today().year
    result = await db.execute(select(func.count(Invoice.id)))
    count = result.scalar() or 0
    return f"INV-{year}-{count + 1:05d}"


# ─── Single Subscription Invoice Generator ───────────────────────────────────

async def generate_invoice_for_subscription(
    sub: Subscription,
    sub_lines: list[SubscriptionLine],
    db: AsyncSession,
    billing_date: date | None = None,
) -> Invoice | None:
    """
    Creates a draft invoice for a single subscription's current billing period.
    Returns None if an invoice already exists for this period (idempotency).
    """
    today = billing_date or date.today()
    period_start = sub.next_billing_date or today
    period_end = compute_next_billing_date(period_start, sub.plan.billing_interval) - timedelta(days=1)

    # Idempotency key prevents double-billing even across retries
    idempotency_key = f"INV-{sub.id}-{period_start.isoformat()}"

    # Check if already generated — fast path without a write lock
    existing = await db.execute(
        select(Invoice.id).where(Invoice.idempotency_key == idempotency_key)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info(f"Skipping {sub.subscription_number}: invoice already exists for {period_start}")
        return None

    invoice_number = await generate_invoice_number(db)

    # Fetch active taxes and the subscription's discount (if any)
    tax_result = await db.execute(select(TaxRule).where(TaxRule.is_active == True))
    active_taxes = {t.id: t for t in tax_result.scalars().all()}

    discount = None
    if sub.applied_discount_id:
        disc_result = await db.execute(
            select(DiscountRule).where(DiscountRule.id == sub.applied_discount_id)
        )
        discount = disc_result.scalar_one_or_none()

    invoice = Invoice(
        invoice_number=invoice_number,
        subscription_id=sub.id,
        customer_id=sub.customer_id,
        idempotency_key=idempotency_key,
        status=InvoiceStatus.DRAFT,
        issue_date=today,
        # Why Net 30 as default: aligns with the subscription's payment terms,
        # giving customers a reasonable window before we flag them overdue.
        due_date=today + timedelta(days=30),
        billing_period_start=period_start,
        billing_period_end=period_end,
    )
    db.add(invoice)
    await db.flush()

    inv_subtotal = Decimal("0.00")
    inv_tax_total = Decimal("0.00")
    inv_discount_total = Decimal("0.00")

    for sl in sub_lines:
        line_subtotal = (sl.unit_price * sl.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Evaluate discount eligibility for this line
        line_discount = Decimal("0.00")
        if discount and discount.is_active:
            if discount.start_date <= today <= discount.end_date:
                if discount.max_uses is None or discount.times_used < discount.max_uses:
                    eligible = True
                    if discount.eligible_product_ids:
                        eligible = sl.product_id in discount.eligible_product_ids
                    if discount.min_quantity and sl.quantity < discount.min_quantity:
                        eligible = False
                    if discount.min_purchase_amount and line_subtotal < discount.min_purchase_amount:
                        eligible = False
                    if eligible:
                        if discount.discount_type.value == "PERCENTAGE":
                            line_discount = (line_subtotal * discount.value / Decimal("100")).quantize(
                                Decimal("0.01"), rounding=ROUND_HALF_UP
                            )
                        else:
                            line_discount = min(discount.value, line_subtotal)

        after_discount = line_subtotal - line_discount

        # Compute taxes
        line_tax = Decimal("0.00")
        if sl.tax_ids:
            for tid in sl.tax_ids:
                tax = active_taxes.get(tid)
                if tax and tax.is_active:
                    line_tax += (after_discount * tax.rate_percent / Decimal("100")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )

        inv_line = InvoiceLine(
            invoice_id=invoice.id,
            product_id=sl.product_id,
            variant_id=sl.variant_id,
            description=sl.description,
            quantity=sl.quantity,
            unit_price=sl.unit_price,
            discount_amount=line_discount,
            tax_amount=line_tax,
            subtotal=line_subtotal,
            total_amount=(after_discount + line_tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        )
        db.add(inv_line)

        inv_subtotal += line_subtotal
        inv_tax_total += line_tax
        inv_discount_total += line_discount

    invoice.subtotal = inv_subtotal
    invoice.tax_total = inv_tax_total
    invoice.discount_total = inv_discount_total
    invoice.total_amount = (inv_subtotal - inv_discount_total + inv_tax_total).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    invoice.amount_due = invoice.total_amount
    invoice.amount_paid = Decimal("0.00")

    # Atomically increment discount usage if we applied one
    if discount and inv_discount_total > 0:
        await db.execute(
            update(DiscountRule)
            .where(
                DiscountRule.id == discount.id,
                # Why this WHERE clause: it's the atomic CAS guard.
                # If another worker already incremented times_used past max_uses,
                # this UPDATE affects 0 rows, which is fine — the discount was
                # already legitimately applied by whoever got there first.
                (DiscountRule.max_uses.is_(None)) | (DiscountRule.times_used < DiscountRule.max_uses),
            )
            .values(times_used=DiscountRule.times_used + 1)
        )

    # Advance the subscription's next billing date atomically
    sub.next_billing_date = compute_next_billing_date(period_start, sub.plan.billing_interval)

    return invoice


# ─── Batch Billing Run ────────────────────────────────────────────────────────

async def run_billing_batch(billing_date: date | None = None):
    """
    The main Billing Day entry point. Processes all ACTIVE subscriptions
    whose next_billing_date <= today in chunks of BILLING_BATCH_SIZE.

    Why we use a fresh session per chunk:
    A single transaction spanning 5,000 subscriptions would hold row locks
    for minutes, blocking staff who are trying to manually adjust subscriptions.
    Chunked commits release locks every 500 subs, keeping the system responsive.
    """
    today = billing_date or date.today()
    batch_size = settings.BILLING_BATCH_SIZE
    total_generated = 0
    total_skipped = 0
    total_closed = 0

    logger.info(f"🔄 Billing batch starting for date {today}")

    offset = 0
    while True:
        async with async_session_factory() as db:
            # Why FOR UPDATE SKIP LOCKED: if a staff member triggered a manual
            # billing run while the cron is mid-flight, the manual run grabs
            # the next unlocked batch instead of deadlocking or double-billing.
            result = await db.execute(
                select(Subscription)
                .options(
                    selectinload(Subscription.lines),
                    selectinload(Subscription.plan),
                )
                .where(
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.next_billing_date <= today,
                )
                .with_for_update(skip_locked=True)
                .limit(batch_size)
            )
            subs = result.scalars().all()

            if not subs:
                break

            for sub in subs:
                try:
                    invoice = await generate_invoice_for_subscription(sub, sub.lines, db, today)
                    if invoice:
                        total_generated += 1
                        # Broadcast SSE event for live dashboard updates
                        await event_broadcaster.broadcast({
                            "type": "invoice_created",
                            "invoice_number": invoice.invoice_number,
                            "subscription_number": sub.subscription_number,
                            "amount": str(invoice.total_amount),
                        })
                    else:
                        total_skipped += 1

                    # Auto-close check: if the plan says auto-close on expiry
                    # and we've reached or passed the expiry date, close it
                    if (
                        sub.plan.auto_close_on_expiry
                        and sub.expiry_date
                        and today >= sub.expiry_date
                    ):
                        sub.status = SubscriptionStatus.CLOSED
                        sub.next_billing_date = None
                        total_closed += 1
                        await event_broadcaster.broadcast({
                            "type": "subscription_closed",
                            "subscription_number": sub.subscription_number,
                            "reason": "auto_close_on_expiry",
                        })

                except Exception as e:
                    logger.error(f"Error billing {sub.subscription_number}: {e}", exc_info=True)
                    continue

            await db.commit()
            offset += batch_size

    logger.info(
        f"✅ Billing batch complete: {total_generated} invoices generated, "
        f"{total_skipped} skipped (idempotent), {total_closed} auto-closed"
    )

    await event_broadcaster.broadcast({
        "type": "billing_batch_complete",
        "date": today.isoformat(),
        "invoices_generated": total_generated,
        "subscriptions_closed": total_closed,
    })

    return {
        "invoices_generated": total_generated,
        "skipped": total_skipped,
        "auto_closed": total_closed,
    }


# ─── Invoice PDF Generation ──────────────────────────────────────────────────

def generate_invoice_pdf(invoice: Invoice, lines: list[InvoiceLine], customer_name: str) -> bytes:
    """
    Generates a clean, professional PDF invoice using ReportLab.
    Why ReportLab over WeasyPrint: ReportLab is pure Python with no system
    dependencies (no wkhtmltopdf, no Cairo). It runs in Alpine Docker images
    without extra apt packages.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    elements = []

    # Header
    title_style = ParagraphStyle(
        'InvoiceTitle', parent=styles['Heading1'],
        fontSize=24, textColor=colors.HexColor("#4338ca"),
        spaceAfter=6*mm,
    )
    elements.append(Paragraph("BRIGHTLOOP", title_style))
    elements.append(Paragraph(f"Invoice: {invoice.invoice_number}", styles['Heading2']))
    elements.append(Spacer(1, 4*mm))

    # Meta info
    meta_data = [
        ["Customer:", customer_name],
        ["Issue Date:", str(invoice.issue_date)],
        ["Due Date:", str(invoice.due_date)],
        ["Billing Period:", f"{invoice.billing_period_start} to {invoice.billing_period_end}"],
        ["Status:", invoice.status.value],
    ]
    meta_table = Table(meta_data, colWidths=[100, 300])
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 8*mm))

    # Line items table
    header = ["#", "Description", "Qty", "Unit Price", "Discount", "Tax", "Total"]
    table_data = [header]
    for i, line in enumerate(lines, 1):
        table_data.append([
            str(i),
            line.description[:50],
            str(line.quantity),
            f"${line.unit_price:,.2f}",
            f"${line.discount_amount:,.2f}",
            f"${line.tax_amount:,.2f}",
            f"${line.total_amount:,.2f}",
        ])

    line_table = Table(table_data, colWidths=[30, 180, 40, 80, 70, 60, 80])
    line_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4338ca")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 6*mm))

    # Totals
    totals_data = [
        ["Subtotal:", f"${invoice.subtotal:,.2f}"],
        ["Discount:", f"-${invoice.discount_total:,.2f}"],
        ["Tax:", f"${invoice.tax_total:,.2f}"],
        ["Total:", f"${invoice.total_amount:,.2f}"],
        ["Paid:", f"${invoice.amount_paid:,.2f}"],
        ["Amount Due:", f"${invoice.amount_due:,.2f}"],
    ]
    totals_table = Table(totals_data, colWidths=[420, 120])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(totals_table)

    doc.build(elements)
    return buffer.getvalue()

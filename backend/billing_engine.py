from datetime import date, datetime, timedelta
import calendar
from models import (
    Subscription, SubscriptionLine, Invoice, InvoiceLine,
    DiscountRule, TaxRule, User, Plan
)

def add_interval(orig_date: date, interval: str) -> date:
    if interval == 'daily':
        return orig_date + timedelta(days=1)
    elif interval == 'weekly':
        return orig_date + timedelta(days=7)
    elif interval == 'yearly':
        try:
            return orig_date.replace(year=orig_date.year + 1)
        except ValueError:
            return orig_date + timedelta(days=365)
    else:  # monthly default
        # Add 1 month safely
        year = orig_date.year + (orig_date.month // 12)
        month = (orig_date.month % 12) + 1
        day = min(orig_date.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

def compute_due_date(issue_date: date, payment_terms: str) -> date:
    terms = (payment_terms or "Immediate").lower()
    if "15" in terms:
        return issue_date + timedelta(days=15)
    elif "30" in terms:
        return issue_date + timedelta(days=30)
    elif "60" in terms:
        return issue_date + timedelta(days=60)
    return issue_date

def generate_invoice_number(db) -> str:
    year = date.today().year
    count = db.query(Invoice).count() + 1
    return f"INV-{year}-{count:04d}"

def process_subscription_billing(db, sub: Subscription, billing_date: date) -> tuple[Invoice | None, str]:
    """
    Creates an invoice for an active subscription ensuring idempotency (no double billing).
    """
    if sub.status != 'Active':
        return None, f"Subscription {sub.sub_number} is not active ({sub.status})"

    # Check lifecycle auto-close
    if sub.plan and sub.plan.auto_close and sub.expiry_date and billing_date >= sub.expiry_date:
        sub.status = 'Closed'
        db.commit()
        return None, f"Subscription {sub.sub_number} reached expiry date and was automatically closed."

    # Avoid duplicate invoice on same issue date for this subscription
    existing = db.query(Invoice).filter(
        Invoice.subscription_id == sub.id,
        Invoice.issue_date == billing_date,
        Invoice.status != 'Cancelled'
    ).first()
    if existing:
        return None, f"Subscription {sub.sub_number} already billed on {billing_date} ({existing.invoice_number})"

    # Check if a discount applies
    discount = None
    if sub.discount_id:
        disc_rule = db.query(DiscountRule).get(sub.discount_id)
        if disc_rule and disc_rule.active:
            # Check dates
            not_started = disc_rule.start_date and billing_date < disc_rule.start_date
            expired = disc_rule.end_date and billing_date > disc_rule.end_date
            limit_hit = disc_rule.max_usage is not None and disc_rule.times_used >= disc_rule.max_usage

            if not not_started and not expired and not limit_hit:
                discount = disc_rule

    due_date = compute_due_date(billing_date, sub.payment_terms)
    inv_num = generate_invoice_number(db)

    invoice = Invoice(
        invoice_number=inv_num,
        subscription_id=sub.id,
        customer_id=sub.customer_id,
        issue_date=billing_date,
        due_date=due_date,
        status='Confirmed',
        subtotal=0.0,
        tax_amount=0.0,
        discount_amount=0.0,
        total_amount=0.0,
        amount_paid=0.0,
        notes=f"Auto-generated for subscription {sub.sub_number} ({sub.plan.name if sub.plan else ''})"
    )
    db.add(invoice)
    db.flush()  # get invoice.id

    subtotal = 0.0
    tax_total = 0.0
    total_qty = sum(l.quantity for l in sub.lines)

    # Process lines
    for line in sub.lines:
        line_base = line.unit_price * line.quantity
        line_tax = round(line_base * (line.tax_rate / 100.0), 2)
        subtotal += line_base
        tax_total += line_tax

        v_name = None
        if line.variant:
            v_name = f"{line.variant.attribute_name}: {line.variant.attribute_value}"

        inv_line = InvoiceLine(
            invoice_id=invoice.id,
            product_name=line.product.name if line.product else (line.description or "Product"),
            variant_name=v_name,
            quantity=line.quantity,
            unit_price=line.unit_price,
            tax_rate=line.tax_rate,
            discount_amount=0.0,
            amount=round(line_base + line_tax, 2)
        )
        db.add(inv_line)

    # Apply whole-subscription discount if applicable
    discount_amount = 0.0
    if discount:
        # Check minimums
        meets_qty = total_qty >= discount.min_quantity
        meets_purchase = subtotal >= discount.min_purchase

        if meets_qty and meets_purchase:
            if discount.discount_type == 'percentage':
                discount_amount = round(subtotal * (discount.value / 100.0), 2)
            else:
                discount_amount = round(min(discount.value, subtotal), 2)

            # Increment usage count
            discount.times_used += 1
            if discount.max_usage is not None and discount.times_used >= discount.max_usage:
                # auto-expire
                discount.active = False
                sub.discount_id = None

    invoice.subtotal = round(subtotal, 2)
    invoice.tax_amount = round(tax_total, 2)
    invoice.discount_amount = round(discount_amount, 2)
    invoice.total_amount = round(max(0.0, subtotal + tax_total - discount_amount), 2)

    # Advance next billing date
    interval = sub.plan.billing_interval if sub.plan else 'monthly'
    sub.next_billing_date = add_interval(billing_date, interval)

    db.commit()
    return invoice, f"Successfully created invoice {invoice.invoice_number}"

def run_billing_day_batch(db, target_date: date = None):
    """
    Runs automated billing batch for all due subscriptions.
    Guarantees no double billing and skips non-due ones.
    """
    if target_date is None:
        target_date = date.today()

    due_subs = db.query(Subscription).filter(
        Subscription.status == 'Active',
        Subscription.next_billing_date <= target_date
    ).all()

    created_invoices = []
    messages = []

    for sub in due_subs:
        inv, msg = process_subscription_billing(db, sub, target_date)
        if inv:
            created_invoices.append(inv.to_dict())
        messages.append(msg)

    return {
        "target_date": target_date.isoformat(),
        "total_due_found": len(due_subs),
        "invoices_created_count": len(created_invoices),
        "invoices": created_invoices,
        "logs": messages
    }

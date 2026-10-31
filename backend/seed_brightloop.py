"""
Brightloop Seed Script
========================
Populates the database with realistic Brightloop Software subscription data
so the system can be tested immediately after docker-compose up.

Seed Data Includes:
  - Admin, Staff, and Customer users
  - Products: ERP licenses, add-ons, services with Odoo brand variant (+560)
  - Plans: Monthly Flex, Annual Commitment, Daily Dev
  - Tax rules: GST 18%, IGST 18%
  - Discount rules: EARLY20 (20% off), BULK10 (10% for 10+ seats)
  - Quotation templates
  - Active subscriptions with varied statuses and billing dates
  - Invoices (some paid, some overdue) with payments

Why we check for existing data before seeding:
  The seed script runs on every docker-compose up. Without the guard,
  restarting the container would duplicate all records. The email
  uniqueness constraint would catch users, but products/plans would
  multiply like rabbits.
"""

import asyncio
import sys
import os
from datetime import date, timedelta, datetime
from decimal import Decimal
from typing import TypedDict, Optional

# Reconfigure stdout/stderr to UTF-8 to prevent Windows cp1252 UnicodeEncodeError on emojis
if hasattr(sys.stdout, 'reconfigure'):
    getattr(sys.stdout, 'reconfigure')(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    getattr(sys.stderr, 'reconfigure')(encoding='utf-8')

# Add the parent directory to the path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select
from app.database import async_session_factory, engine, Base
from app.models import (
    User, UserRole, Product, ProductType, ProductVariant,
    SubscriptionPlan, BillingInterval, TaxRule, DiscountRule, DiscountType,
    DiscountScope, QuotationTemplate, QuotationTemplateLine,
    Subscription, SubscriptionStatus, SubscriptionLine,
    Invoice, InvoiceStatus, InvoiceLine, Payment, PaymentMethod,
    SubscriptionAudit,
)
from app.services.auth_service import hash_password


class SubSeedConfig(TypedDict):
    customer: User
    plan: SubscriptionPlan
    status: SubscriptionStatus
    start: date
    expiry: Optional[date]
    next_bill: Optional[date]
    discount: Optional[DiscountRule]


async def seed():
    force_reset = "--reset" in sys.argv or "--force" in sys.argv

    # Create tables
    async with engine.begin() as conn:
        if force_reset:
            print("🔄 Reset flag detected — dropping and recreating tables...")
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with async_session_factory() as db:
            # Check if already seeded
            if not force_reset:
                result = await db.execute(select(User).limit(1))
                if result.scalar_one_or_none():
                    print("Database already seeded — skipping (use --reset to re-seed)")
                    return

        print("🌱 Seeding Brightloop database...")

        # ─── Users ────────────────────────────────────────────────────
        admin = User(
            email="admin@brightloop.io",
            hashed_password=hash_password("BrightloopAdmin2026!"),
            full_name="Alex Morgan",
            role=UserRole.ADMIN,
        )
        staff1 = User(
            email="finance@brightloop.io",
            hashed_password=hash_password("BrightloopFinance2026!"),
            full_name="Sarah Chen",
            role=UserRole.INTERNAL_STAFF,
        )
        staff2 = User(
            email="ops@brightloop.io",
            hashed_password=hash_password("BrightloopStaff2026!"),
            full_name="Rahul Verma",
            role=UserRole.INTERNAL_STAFF,
        )
        customer_primary = User(
            email="customer@brightloop.io",
            hashed_password=hash_password("BrightloopCustomer2026!"),
            full_name="Acmez Enterprise",
            role=UserRole.CUSTOMER,
        )
        customers = [customer_primary]
        customer_data = [
            ("customer1@acme.com", "Vikram Desai", "Acme Corp"),
            ("customer2@techstart.io", "Sarah Chen", "TechStart Inc"),
            ("customer3@globalfin.com", "Amit Gupta", "Global Finance Ltd"),
            ("customer4@retailmax.com", "Lisa Wang", "RetailMax"),
            ("customer5@healthtech.io", "Raj Patel", "HealthTech Solutions"),
            ("customer6@edulearn.com", "Maria Garcia", "EduLearn Platform"),
            ("customer7@logistics.co", "David Kim", "Swift Logistics"),
            ("customer8@mediagroup.com", "Fatima Ali", "MediaGroup Digital"),
        ]
        for email, name, company in customer_data:
            c = User(
                email=email,
                hashed_password=hash_password("BrightloopCustomer2026!"),
                full_name=name,
                role=UserRole.CUSTOMER,
            )
            customers.append(c)

        db.add_all([admin, staff1, staff2] + customers)
        await db.flush()
        print(f"  👤 Created {3 + len(customers)} users")

        # ─── Products ────────────────────────────────────────────────
        products = [
            Product(name="Odoo ERP License", product_type=ProductType.SUBSCRIPTION,
                    sales_price=Decimal("1200.00"), cost_price=Decimal("400.00"),
                    notes="Core ERP platform license per seat"),
            Product(name="CRM Module", product_type=ProductType.ADDON,
                    sales_price=Decimal("350.00"), cost_price=Decimal("100.00"),
                    notes="Customer relationship management add-on"),
            Product(name="HR & Payroll Module", product_type=ProductType.ADDON,
                    sales_price=Decimal("450.00"), cost_price=Decimal("150.00"),
                    notes="Human resources and payroll processing"),
            Product(name="E-Commerce Module", product_type=ProductType.ADDON,
                    sales_price=Decimal("550.00"), cost_price=Decimal("200.00"),
                    notes="Online storefront and checkout integration"),
            Product(name="Implementation Service", product_type=ProductType.SERVICE,
                    sales_price=Decimal("5000.00"), cost_price=Decimal("2000.00"),
                    notes="One-time ERP implementation and data migration"),
            Product(name="Premium Support", product_type=ProductType.SERVICE,
                    sales_price=Decimal("800.00"), cost_price=Decimal("300.00"),
                    notes="24/7 priority support package"),
            Product(name="Inventory Module", product_type=ProductType.ADDON,
                    sales_price=Decimal("400.00"), cost_price=Decimal("120.00"),
                    notes="Warehouse and inventory management"),
            Product(name="Accounting Module", product_type=ProductType.ADDON,
                    sales_price=Decimal("500.00"), cost_price=Decimal("180.00"),
                    notes="General ledger and financial reporting"),
        ]
        db.add_all(products)
        await db.flush()
        print(f"  📦 Created {len(products)} products")

        # ─── Variants ────────────────────────────────────────────────
        # The Odoo Enterprise variant adds +560 to the base price — this is
        # the key demo data point showing variant price extras in action.
        variants = [
            ProductVariant(product_id=products[0].id, attribute_name="Brand",
                          attribute_value="Odoo Community", price_extra=Decimal("0.00")),
            ProductVariant(product_id=products[0].id, attribute_name="Brand",
                          attribute_value="Odoo Enterprise", price_extra=Decimal("560.00")),
            ProductVariant(product_id=products[0].id, attribute_name="Hosting",
                          attribute_value="Cloud", price_extra=Decimal("200.00")),
            ProductVariant(product_id=products[0].id, attribute_name="Hosting",
                          attribute_value="On-Premise", price_extra=Decimal("0.00")),
            ProductVariant(product_id=products[1].id, attribute_name="Tier",
                          attribute_value="Standard", price_extra=Decimal("0.00")),
            ProductVariant(product_id=products[1].id, attribute_name="Tier",
                          attribute_value="Advanced", price_extra=Decimal("150.00")),
        ]
        db.add_all(variants)
        await db.flush()
        print(f"  🏷️  Created {len(variants)} product variants")

        # ─── Plans ───────────────────────────────────────────────────
        plans = [
            SubscriptionPlan(
                name="Monthly Flex",
                base_cost=Decimal("99.00"),
                billing_interval=BillingInterval.MONTHLY,
                min_quantity=1,
                available_from=date(2026, 1, 1),
                auto_close_on_expiry=True,
                allow_early_close=True,
                allow_pause=True,
                allow_renewal=True,
            ),
            SubscriptionPlan(
                name="Annual Commitment",
                base_cost=Decimal("999.00"),
                billing_interval=BillingInterval.YEARLY,
                min_quantity=5,
                available_from=date(2026, 1, 1),
                auto_close_on_expiry=True,
                allow_early_close=False,  # Locked in for the year
                allow_pause=False,
                allow_renewal=True,
            ),
            SubscriptionPlan(
                name="Daily Dev Sandbox",
                base_cost=Decimal("9.99"),
                billing_interval=BillingInterval.DAILY,
                min_quantity=1,
                available_from=date(2026, 1, 1),
                auto_close_on_expiry=False,
                allow_early_close=True,
                allow_pause=True,
                allow_renewal=True,
            ),
            SubscriptionPlan(
                name="Weekly Sprint",
                base_cost=Decimal("49.00"),
                billing_interval=BillingInterval.WEEKLY,
                min_quantity=1,
                available_from=date(2026, 6, 1),
                auto_close_on_expiry=True,
                allow_early_close=True,
                allow_pause=True,
                allow_renewal=True,
            ),
        ]
        db.add_all(plans)
        await db.flush()
        print(f"  📋 Created {len(plans)} subscription plans")

        # ─── Tax Rules ───────────────────────────────────────────────
        taxes = [
            TaxRule(name="GST 18%", rate_percent=Decimal("18.00"),
                    applies_to_product_types=["SUBSCRIPTION", "ADDON"]),
            TaxRule(name="IGST 18%", rate_percent=Decimal("18.00"),
                    applies_to_product_types=["SERVICE"]),
            TaxRule(name="Cess 1%", rate_percent=Decimal("1.00"),
                    applies_to_product_types=["SUBSCRIPTION"]),
        ]
        db.add_all(taxes)
        await db.flush()
        print(f"  💰 Created {len(taxes)} tax rules")

        # ─── Discount Rules ──────────────────────────────────────────
        discounts = [
            DiscountRule(
                name="Early Bird 20%", code="EARLY20",
                discount_type=DiscountType.PERCENTAGE, value=Decimal("20.00"),
                start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
                max_uses=100, scope=DiscountScope.SUBSCRIPTION,
            ),
            DiscountRule(
                name="Bulk Seats 10%", code="BULK10",
                discount_type=DiscountType.PERCENTAGE, value=Decimal("10.00"),
                min_quantity=10,
                start_date=date(2026, 1, 1), end_date=date(2027, 6, 30),
                scope=DiscountScope.PRODUCT,
            ),
            DiscountRule(
                name="Flat $200 Off", code="FLAT200",
                discount_type=DiscountType.FIXED, value=Decimal("200.00"),
                min_purchase_amount=Decimal("1000.00"),
                start_date=date(2026, 6, 1), end_date=date(2026, 12, 31),
                max_uses=50, scope=DiscountScope.SUBSCRIPTION,
            ),
        ]
        db.add_all(discounts)
        await db.flush()
        print(f"  🎁 Created {len(discounts)} discount rules")

        # ─── Quotation Templates ─────────────────────────────────────
        template1 = QuotationTemplate(
            name="Odoo Enterprise Starter Pack",
            plan_id=plans[0].id,
            validity_days=30,
            payment_terms="Net 30",
            notes="Perfect for small teams getting started with Odoo Enterprise",
        )
        template2 = QuotationTemplate(
            name="Enterprise Annual Suite",
            plan_id=plans[1].id,
            validity_days=15,
            payment_terms="Net 15",
            notes="Full ERP suite with annual commitment discount",
        )
        db.add_all([template1, template2])
        await db.flush()

        # Template lines
        template_lines = [
            QuotationTemplateLine(template_id=template1.id, product_id=products[0].id,
                                  variant_id=variants[1].id, quantity=5,
                                  description="Odoo Enterprise License (5 seats)"),
            QuotationTemplateLine(template_id=template1.id, product_id=products[1].id,
                                  variant_id=variants[4].id, quantity=5,
                                  description="CRM Module - Standard"),
            QuotationTemplateLine(template_id=template2.id, product_id=products[0].id,
                                  variant_id=variants[1].id, quantity=20,
                                  description="Odoo Enterprise License (20 seats)"),
            QuotationTemplateLine(template_id=template2.id, product_id=products[1].id,
                                  variant_id=variants[5].id, quantity=20,
                                  description="CRM Module - Advanced"),
            QuotationTemplateLine(template_id=template2.id, product_id=products[2].id,
                                  quantity=20, description="HR & Payroll Module"),
            QuotationTemplateLine(template_id=template2.id, product_id=products[7].id,
                                  quantity=20, description="Accounting Module"),
        ]
        db.add_all(template_lines)
        await db.flush()
        print(f"  📝 Created 2 quotation templates with {len(template_lines)} lines")

        # ─── Subscriptions ───────────────────────────────────────────
        today = date.today()

        sub_configs: list[SubSeedConfig] = [
            # Active subscriptions with upcoming billing
            {"customer": customers[0], "plan": plans[0], "status": SubscriptionStatus.ACTIVE,
             "start": today - timedelta(days=60), "expiry": today + timedelta(days=300),
             "next_bill": today + timedelta(days=2), "discount": discounts[0]},
            {"customer": customers[1], "plan": plans[1], "status": SubscriptionStatus.ACTIVE,
             "start": today - timedelta(days=180), "expiry": today + timedelta(days=185),
             "next_bill": today - timedelta(days=1), "discount": None},  # Due yesterday — will generate overdue
            {"customer": customers[2], "plan": plans[0], "status": SubscriptionStatus.ACTIVE,
             "start": today - timedelta(days=30), "expiry": today + timedelta(days=335),
             "next_bill": today, "discount": discounts[1]},
            {"customer": customers[3], "plan": plans[2], "status": SubscriptionStatus.ACTIVE,
             "start": today - timedelta(days=10), "expiry": None,
             "next_bill": today, "discount": None},
            {"customer": customers[4], "plan": plans[0], "status": SubscriptionStatus.ACTIVE,
             "start": today - timedelta(days=90), "expiry": today + timedelta(days=275),
             "next_bill": today + timedelta(days=5), "discount": None},
            # Paused subscription
            {"customer": customers[5], "plan": plans[0], "status": SubscriptionStatus.PAUSED,
             "start": today - timedelta(days=45), "expiry": today + timedelta(days=320),
             "next_bill": None, "discount": None},
            # Draft/Quotation subscriptions
            {"customer": customers[6], "plan": plans[1], "status": SubscriptionStatus.DRAFT,
             "start": today, "expiry": today + timedelta(days=365),
             "next_bill": today, "discount": discounts[2]},
            {"customer": customers[7], "plan": plans[0], "status": SubscriptionStatus.QUOTATION,
             "start": today + timedelta(days=5), "expiry": today + timedelta(days=370),
             "next_bill": today + timedelta(days=5), "discount": None},
            # Closed subscription
            {"customer": customers[0], "plan": plans[2], "status": SubscriptionStatus.CLOSED,
             "start": today - timedelta(days=120), "expiry": today - timedelta(days=30),
             "next_bill": None, "discount": None},
        ]

        subscriptions = []
        for i, cfg in enumerate(sub_configs):
            cust: User = cfg["customer"]
            p: SubscriptionPlan = cfg["plan"]
            disc: Optional[DiscountRule] = cfg["discount"]
            sub = Subscription(
                subscription_number=f"SUB-2026-{i + 1:05d}",
                customer_id=int(cust.id),
                plan_id=int(p.id),
                start_date=cfg["start"],
                expiry_date=cfg["expiry"],
                next_billing_date=cfg["next_bill"],
                payment_terms="Net 30",
                status=cfg["status"],
                applied_discount_id=int(disc.id) if disc else None,
            )
            subscriptions.append(sub)

        db.add_all(subscriptions)
        await db.flush()

        # Add lines to each subscription
        gst_tax_ids = [taxes[0].id]
        all_tax_ids = [taxes[0].id, taxes[2].id]

        for sub in subscriptions:
            # Main ERP license line (with Enterprise variant = +560)
            line1 = SubscriptionLine(
                subscription_id=sub.id,
                product_id=products[0].id,
                variant_id=variants[1].id,  # Odoo Enterprise
                description="Odoo Enterprise ERP License",
                quantity=max(5, plans[0].min_quantity),
                unit_price=Decimal("1760.00"),  # 1200 + 560
                tax_ids=all_tax_ids,
                subtotal=Decimal("8800.00"),
                tax_amount=Decimal("1672.00"),
                total_amount=Decimal("10472.00"),
            )
            # CRM add-on
            line2 = SubscriptionLine(
                subscription_id=sub.id,
                product_id=products[1].id,
                variant_id=variants[4].id,
                description="CRM Module - Standard",
                quantity=5,
                unit_price=Decimal("350.00"),
                tax_ids=gst_tax_ids,
                subtotal=Decimal("1750.00"),
                tax_amount=Decimal("315.00"),
                total_amount=Decimal("2065.00"),
            )
            db.add_all([line1, line2])

        await db.flush()
        print(f"  📄 Created {len(subscriptions)} subscriptions with lines")

        # ─── Audit Entries ───────────────────────────────────────────
        for sub in subscriptions:
            audit = SubscriptionAudit(
                subscription_id=sub.id,
                from_status="NONE",
                to_status=sub.status.value,
                changed_by_id=staff1.id,
                notes="Initial creation via seed script",
            )
            db.add(audit)

        # ─── Invoices ────────────────────────────────────────────────
        invoices = []

        # Past invoices for active subscriptions (some paid, some overdue)
        for j, sub in enumerate(subscriptions[:5]):
            for month_offset in range(1, 3):
                period_start = sub.start_date + timedelta(days=30 * (month_offset - 1))
                period_end = period_start + timedelta(days=29)
                issue = period_start
                due = issue + timedelta(days=30)

                inv = Invoice(
                    invoice_number=f"INV-2026-{len(invoices) + 1:05d}",
                    subscription_id=sub.id,
                    customer_id=sub.customer_id,
                    idempotency_key=f"INV-{sub.id}-{period_start.isoformat()}",
                    status=InvoiceStatus.PAID if month_offset == 1 else InvoiceStatus.CONFIRMED,
                    issue_date=issue,
                    due_date=due,
                    billing_period_start=period_start,
                    billing_period_end=period_end,
                    subtotal=Decimal("10550.00"),
                    tax_total=Decimal("1987.00"),
                    discount_total=Decimal("0.00"),
                    total_amount=Decimal("12537.00"),
                    amount_paid=Decimal("12537.00") if month_offset == 1 else Decimal("0.00"),
                    amount_due=Decimal("0.00") if month_offset == 1 else Decimal("12537.00"),
                )
                invoices.append(inv)

        db.add_all(invoices)
        await db.flush()

        # Add invoice lines
        for inv in invoices:
            inv_line1 = InvoiceLine(
                invoice_id=inv.id, product_id=products[0].id,
                variant_id=variants[1].id,
                description="Odoo Enterprise ERP License",
                quantity=5, unit_price=Decimal("1760.00"),
                discount_amount=Decimal("0.00"), tax_amount=Decimal("1672.00"),
                subtotal=Decimal("8800.00"), total_amount=Decimal("10472.00"),
            )
            inv_line2 = InvoiceLine(
                invoice_id=inv.id, product_id=products[1].id,
                variant_id=variants[4].id,
                description="CRM Module - Standard",
                quantity=5, unit_price=Decimal("350.00"),
                discount_amount=Decimal("0.00"), tax_amount=Decimal("315.00"),
                subtotal=Decimal("1750.00"), total_amount=Decimal("2065.00"),
            )
            db.add_all([inv_line1, inv_line2])

        # ─── Payments ────────────────────────────────────────────────
        payments = []
        for inv in invoices:
            if inv.status == InvoiceStatus.PAID:
                payment = Payment(
                    invoice_id=inv.id,
                    payment_method=PaymentMethod.BANK_TRANSFER,
                    amount=inv.total_amount,
                    payment_date=inv.issue_date + timedelta(days=15),
                    reference_note=f"Payment for {inv.invoice_number}",
                    recorded_by_id=staff1.id,
                )
                payments.append(payment)

        db.add_all(payments)
        await db.flush()
        print(f"  🧾 Created {len(invoices)} invoices and {len(payments)} payments")

        await db.commit()
        print("✅ Brightloop seed complete!")
        print()
        print("  Login credentials (1-Click Switcher in UI):")
        print("  ─────────────────────────────────────────────────────────────")
        print("  Admin:    admin@brightloop.io    / BrightloopAdmin2026!")
        print("  Finance:  finance@brightloop.io  / BrightloopFinance2026!")
        print("  Customer: customer@brightloop.io / BrightloopCustomer2026!")
        print("  ─────────────────────────────────────────────────────────────")
        print()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

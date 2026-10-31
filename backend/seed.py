from datetime import date, datetime, timedelta
import json
from database import SessionLocal, init_db
from models import (
    User, Product, ProductVariant, Plan, QuotationTemplate,
    TaxRule, DiscountRule, Subscription, SubscriptionLine,
    Invoice, InvoiceLine, Payment
)
from auth_utils import hash_password

def seed_database():
    init_db()
    db = SessionLocal()

    # Clear existing if any
    db.query(Payment).delete()
    db.query(InvoiceLine).delete()
    db.query(Invoice).delete()
    db.query(SubscriptionLine).delete()
    db.query(Subscription).delete()
    db.query(DiscountRule).delete()
    db.query(TaxRule).delete()
    db.query(QuotationTemplate).delete()
    db.query(Plan).delete()
    db.query(ProductVariant).delete()
    db.query(Product).delete()
    db.query(User).delete()
    db.commit()

    print("Seeding Users...")
    admin = User(
        email="admin@brightloop.com",
        password_hash=hash_password("Admin@1234"),
        role="admin",
        name="Elena Vance (Admin)",
        company_name="Brightloop Software HQ"
    )
    staff1 = User(
        email="sarah.sales@brightloop.com",
        password_hash=hash_password("Staff@1234"),
        role="staff",
        name="Sarah Jenkins (Sales Rep)",
        company_name="Brightloop Software"
    )
    staff2 = User(
        email="mike.ops@brightloop.com",
        password_hash=hash_password("Staff@1234"),
        role="staff",
        name="Mike Kowalski (Billing Ops)",
        company_name="Brightloop Software"
    )

    cust1 = User(
        email="contact@apexretail.com",
        password_hash=hash_password("Customer@1234"),
        role="customer",
        name="Marcus Sterling",
        company_name="Apex Retail Global"
    )
    cust2 = User(
        email="finance@novatech.io",
        password_hash=hash_password("Customer@1234"),
        role="customer",
        name="Aria Montgomery",
        company_name="NovaTech Systems"
    )
    cust3 = User(
        email="owner@sunriseshop.com",
        password_hash=hash_password("Customer@1234"),
        role="customer",
        name="Dev Patel",
        company_name="Sunrise Corner Store"
    )
    cust4 = User(
        email="tech@lumencorp.org",
        password_hash=hash_password("Customer@1234"),
        role="customer",
        name="Chloe Bennett",
        company_name="Lumen Healthcare"
    )

    db.add_all([admin, staff1, staff2, cust1, cust2, cust3, cust4])
    db.commit()

    print("Seeding Taxes...")
    tax_gst = TaxRule(name="GST Standard (18%)", rate_percent=18.0, is_default=True, active=True)
    tax_vat = TaxRule(name="VAT Tech (15%)", rate_percent=15.0, is_default=False, active=True)
    tax_sales = TaxRule(name="Sales Tax (10%)", rate_percent=10.0, is_default=False, active=True)
    tax_zero = TaxRule(name="Export / Zero-Rated (0%)", rate_percent=0.0, is_default=False, active=True)
    db.add_all([tax_gst, tax_vat, tax_sales, tax_zero])
    db.commit()

    print("Seeding Products and Variants...")
    # Product 1: Brightloop ERP Core
    prod_erp = Product(
        name="Brightloop ERP Core",
        type="Software",
        sales_price=1200.0,
        cost_price=400.0,
        notes="Core enterprise resource planning module for supply chain, sales, and operations.",
        active=True
    )
    # Product 2: CRM Cloud Pro
    prod_crm = Product(
        name="CRM Cloud Pro",
        type="Software",
        sales_price=350.0,
        cost_price=90.0,
        notes="Lead pipeline, customer engagement, automated deal stages.",
        active=True
    )
    # Product 3: Automated Recurring Billing Module
    prod_billing = Product(
        name="Automated Recurring Billing Add-on",
        type="Add-on",
        sales_price=150.0,
        cost_price=30.0,
        notes="Automates subscription invoicing, dunning, tax rules, and payments.",
        active=True
    )
    # Product 4: 24/7 Dedicated Support SLA
    prod_sla = Product(
        name="24/7 Priority Support SLA",
        type="Service",
        sales_price=500.0,
        cost_price=180.0,
        notes="Dedicated Slack channel, 15-minute response time, monthly health review.",
        active=True
    )
    # Product 5: Multi-Location Warehouse Sync
    prod_sync = Product(
        name="Multi-Warehouse Inventory Sync",
        type="Add-on",
        sales_price=220.0,
        cost_price=50.0,
        notes="Real-time multi-branch stock reconciliation.",
        active=True
    )
    db.add_all([prod_erp, prod_crm, prod_billing, prod_sla, prod_sync])
    db.commit()

    # Variants (as stated in PDF: "for example by brand, where choosing the Odoo brand adds 560 to the price")
    var_odoo = ProductVariant(
        product_id=prod_erp.id,
        attribute_name="Brand Integration",
        attribute_value="Odoo Brand Edition",
        price_extra=560.0,
        active=True
    )
    var_standard = ProductVariant(
        product_id=prod_erp.id,
        attribute_name="Brand Integration",
        attribute_value="Brightloop Standard Edition",
        price_extra=0.0,
        active=True
    )
    var_crm_white = ProductVariant(
        product_id=prod_crm.id,
        attribute_name="Branding",
        attribute_value="White Label Custom Domain",
        price_extra=120.0,
        active=True
    )
    db.add_all([var_odoo, var_standard, var_crm_white])
    db.commit()

    print("Seeding Plans...")
    plan_monthly_pro = Plan(
        name="Professional Monthly Business Suite",
        product_id=prod_erp.id,
        cost=1200.0,
        billing_interval="monthly",
        min_quantity=1,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
        auto_close=False,
        allow_early_close=True,
        allow_pause=True,
        allow_renew=True,
        description="Standard monthly recurring billing plan for small-to-mid companies.",
        active=True
    )
    plan_yearly_ent = Plan(
        name="Enterprise Annual Contract",
        product_id=prod_erp.id,
        cost=12500.0,
        billing_interval="yearly",
        min_quantity=1,
        start_date=date(2026, 1, 1),
        end_date=date(2028, 12, 31),
        auto_close=False,
        allow_early_close=True,
        allow_pause=False,
        allow_renew=True,
        description="Comprehensive yearly contract with discounted bulk rates and dedicated account manager.",
        active=True
    )
    plan_weekly_starter = Plan(
        name="Growth Starter Weekly",
        product_id=prod_crm.id,
        cost=95.0,
        billing_interval="weekly",
        min_quantity=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        auto_close=False,
        allow_early_close=True,
        allow_pause=True,
        allow_renew=True,
        description="Flexible short-cycle weekly billing for seasonal operations.",
        active=True
    )
    plan_daily_pilot = Plan(
        name="High-Compute Daily Pilot",
        product_id=prod_sync.id,
        cost=45.0,
        billing_interval="daily",
        min_quantity=1,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 11, 15),
        auto_close=True,  # closes on its own when it ends
        allow_early_close=True,
        allow_pause=False,
        allow_renew=False,
        description="15-day pilot compute plan that automatically closes upon reaching expiry date.",
        active=True
    )
    db.add_all([plan_monthly_pro, plan_yearly_ent, plan_weekly_starter, plan_daily_pilot])
    db.commit()

    print("Seeding Quotation Templates...")
    template_ent = QuotationTemplate(
        name="Enterprise Cloud & SLA Bundle",
        plan_id=plan_yearly_ent.id,
        validity_days=30,
        lines_json=json.dumps([
            {"product_id": prod_erp.id, "variant_id": var_odoo.id, "quantity": 1, "unit_price": 1760.0, "tax_rate": 18.0},
            {"product_id": prod_crm.id, "variant_id": None, "quantity": 5, "unit_price": 350.0, "tax_rate": 18.0},
            {"product_id": prod_sla.id, "variant_id": None, "quantity": 1, "unit_price": 500.0, "tax_rate": 18.0}
        ]),
        notes="Standard Enterprise proposal template for mid-market clients."
    )
    template_starter = QuotationTemplate(
        name="Small Shop Retail QuickStart",
        plan_id=plan_monthly_pro.id,
        validity_days=15,
        lines_json=json.dumps([
            {"product_id": prod_crm.id, "variant_id": None, "quantity": 2, "unit_price": 350.0, "tax_rate": 10.0},
            {"product_id": prod_sync.id, "variant_id": None, "quantity": 1, "unit_price": 220.0, "tax_rate": 10.0}
        ]),
        notes="Ready-to-use quote for retail corner stores."
    )
    db.add_all([template_ent, template_starter])
    db.commit()

    print("Seeding Discount Rules...")
    # Admin discount rules
    disc_volume = DiscountRule(
        code="SEAT15",
        name="Volume Seat Discount (15% Off)",
        discount_type="percentage",
        value=15.0,
        min_purchase=0.0,
        min_quantity=5,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        max_usage=100,
        times_used=12,
        applies_to="subscription",
        active=True
    )
    disc_fixed = DiscountRule(
        code="WELCOME250",
        name="New Business Welcome ($250 Credit)",
        discount_type="fixed",
        value=250.0,
        min_purchase=800.0,
        min_quantity=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        max_usage=50,
        times_used=8,
        applies_to="subscription",
        active=True
    )
    disc_summer = DiscountRule(
        code="GROWTH10",
        name="10% Seasonal Growth Discount",
        discount_type="percentage",
        value=10.0,
        min_purchase=500.0,
        min_quantity=1,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 11, 30),
        max_usage=200,
        times_used=45,
        applies_to="subscription",
        active=True
    )
    db.add_all([disc_volume, disc_fixed, disc_summer])
    db.commit()

    print("Seeding Subscriptions & Lines...")
    today = date.today()

    # Sub 1: Active Monthly Apex Retail
    sub1 = Subscription(
        sub_number="SUB-2026-0001",
        customer_id=cust1.id,
        plan_id=plan_monthly_pro.id,
        start_date=today - timedelta(days=60),
        expiry_date=today + timedelta(days=300),
        next_billing_date=today, # Due today for billing day testing!
        payment_terms="Net 15",
        status="Active",
        discount_id=disc_volume.id,
        notes="Apex Retail headquarters 10 seat subscription."
    )
    db.add(sub1)
    db.flush()

    line1_1 = SubscriptionLine(
        subscription_id=sub1.id,
        product_id=prod_erp.id,
        variant_id=var_odoo.id,
        description="Brightloop ERP Core (Odoo Brand)",
        quantity=1,
        unit_price=1760.0,  # 1200 + 560
        tax_rate=18.0,
        amount=round(1760.0 * 1.18, 2)
    )
    line1_2 = SubscriptionLine(
        subscription_id=sub1.id,
        product_id=prod_crm.id,
        variant_id=None,
        description="CRM Cloud Pro (5 user seats)",
        quantity=5,
        unit_price=350.0,
        tax_rate=18.0,
        amount=round(5 * 350.0 * 1.18, 2)
    )
    db.add_all([line1_1, line1_2])

    # Sub 2: Active Yearly NovaTech
    sub2 = Subscription(
        sub_number="SUB-2026-0002",
        customer_id=cust2.id,
        plan_id=plan_yearly_ent.id,
        start_date=today - timedelta(days=90),
        expiry_date=today + timedelta(days=275),
        next_billing_date=today + timedelta(days=275),
        payment_terms="Net 30",
        status="Active",
        discount_id=disc_fixed.id,
        notes="Annual contract with dedicated SLA."
    )
    db.add(sub2)
    db.flush()

    line2_1 = SubscriptionLine(
        subscription_id=sub2.id,
        product_id=prod_erp.id,
        variant_id=var_standard.id,
        description="Brightloop ERP Enterprise",
        quantity=1,
        unit_price=12000.0,
        tax_rate=18.0,
        amount=round(12000.0 * 1.18, 2)
    )
    line2_2 = SubscriptionLine(
        subscription_id=sub2.id,
        product_id=prod_sla.id,
        variant_id=None,
        description="24/7 Dedicated Support SLA",
        quantity=1,
        unit_price=5000.0,
        tax_rate=18.0,
        amount=round(5000.0 * 1.18, 2)
    )
    db.add_all([line2_1, line2_2])

    # Sub 3: Paused Sunrise Shop
    sub3 = Subscription(
        sub_number="SUB-2026-0003",
        customer_id=cust3.id,
        plan_id=plan_monthly_pro.id,
        start_date=today - timedelta(days=45),
        expiry_date=today + timedelta(days=320),
        next_billing_date=today + timedelta(days=15),
        payment_terms="Immediate",
        status="Paused",
        discount_id=None,
        notes="Customer requested pause during seasonal renovation."
    )
    db.add(sub3)
    db.flush()

    line3_1 = SubscriptionLine(
        subscription_id=sub3.id,
        product_id=prod_crm.id,
        variant_id=None,
        description="CRM Cloud Pro",
        quantity=2,
        unit_price=350.0,
        tax_rate=10.0,
        amount=round(2 * 350.0 * 1.10, 2)
    )
    db.add(line3_1)

    # Sub 4: Quotation Stage Lumen Healthcare
    sub4 = Subscription(
        sub_number="SUB-2026-0004",
        customer_id=cust4.id,
        plan_id=plan_monthly_pro.id,
        start_date=today + timedelta(days=5),
        expiry_date=today + timedelta(days=370),
        next_billing_date=today + timedelta(days=5),
        payment_terms="Net 30",
        status="Quotation",
        discount_id=disc_summer.id,
        notes="Draft quotation awaiting customer digital signature."
    )
    db.add(sub4)
    db.flush()

    line4_1 = SubscriptionLine(
        subscription_id=sub4.id,
        product_id=prod_billing.id,
        variant_id=None,
        description="Automated Billing Suite",
        quantity=3,
        unit_price=150.0,
        tax_rate=15.0,
        amount=round(3 * 150.0 * 1.15, 2)
    )
    db.add(line4_1)

    # Sub 5: Closed Subscription
    sub5 = Subscription(
        sub_number="SUB-2026-0005",
        customer_id=cust3.id,
        plan_id=plan_daily_pilot.id,
        start_date=today - timedelta(days=30),
        expiry_date=today - timedelta(days=5),
        next_billing_date=today - timedelta(days=5),
        payment_terms="Immediate",
        status="Closed",
        discount_id=None,
        notes="High-Compute Pilot completed and automatically closed."
    )
    db.add(sub5)
    db.flush()

    line5_1 = SubscriptionLine(
        subscription_id=sub5.id,
        product_id=prod_sync.id,
        variant_id=None,
        description="Daily Pilot Multi-Warehouse Sync",
        quantity=1,
        unit_price=45.0,
        tax_rate=10.0,
        amount=49.50
    )
    db.add(line5_1)
    db.commit()

    print("Seeding Invoices and Payments...")
    # Invoice 1: Paid invoice for NovaTech
    inv1 = Invoice(
        invoice_number="INV-2026-0001",
        subscription_id=sub2.id,
        customer_id=cust2.id,
        issue_date=today - timedelta(days=90),
        due_date=today - timedelta(days=60),
        status="Paid",
        subtotal=17000.0,
        tax_amount=3060.0,
        discount_amount=250.0,
        total_amount=19810.0,
        amount_paid=19810.0,
        notes="Annual contract payment in full via Wire Transfer."
    )
    db.add(inv1)
    db.flush()

    db.add(InvoiceLine(
        invoice_id=inv1.id,
        product_name="Brightloop ERP Enterprise",
        variant_name="Standard",
        quantity=1,
        unit_price=12000.0,
        tax_rate=18.0,
        discount_amount=0.0,
        amount=14160.0
    ))
    db.add(InvoiceLine(
        invoice_id=inv1.id,
        product_name="24/7 Dedicated Support SLA",
        variant_name=None,
        quantity=1,
        unit_price=5000.0,
        tax_rate=18.0,
        discount_amount=0.0,
        amount=5900.0
    ))

    pay1 = Payment(
        payment_number="PAY-2026-0001",
        invoice_id=inv1.id,
        amount=19810.0,
        payment_method="Bank Transfer",
        payment_date=today - timedelta(days=85),
        reference_note="SWIFT/Fedwire Ref: NOVA-TECH-ANNUAL-2026",
        status="Completed"
    )
    db.add(pay1)

    # Invoice 2: Overdue invoice for Apex Retail
    inv2 = Invoice(
        invoice_number="INV-2026-0002",
        subscription_id=sub1.id,
        customer_id=cust1.id,
        issue_date=today - timedelta(days=40),
        due_date=today - timedelta(days=25), # Past due!
        status="Confirmed",
        subtotal=3510.0,
        tax_amount=631.80,
        discount_amount=526.50,
        total_amount=3615.30,
        amount_paid=0.0,
        notes="Previous month billing cycle. Overdue by 25 days."
    )
    db.add(inv2)
    db.flush()

    db.add(InvoiceLine(
        invoice_id=inv2.id,
        product_name="Brightloop ERP Core (Odoo Brand)",
        variant_name="Brand Integration: Odoo Brand Edition",
        quantity=1,
        unit_price=1760.0,
        tax_rate=18.0,
        discount_amount=0.0,
        amount=2076.80
    ))
    db.add(InvoiceLine(
        invoice_id=inv2.id,
        product_name="CRM Cloud Pro (5 user seats)",
        variant_name=None,
        quantity=5,
        unit_price=350.0,
        tax_rate=18.0,
        discount_amount=0.0,
        amount=2065.00
    ))

    # Invoice 3: Partially paid / Confirmed
    inv3 = Invoice(
        invoice_number="INV-2026-0003",
        subscription_id=sub3.id,
        customer_id=cust3.id,
        issue_date=today - timedelta(days=15),
        due_date=today + timedelta(days=15),
        status="Confirmed",
        subtotal=700.0,
        tax_amount=70.0,
        discount_amount=0.0,
        total_amount=770.0,
        amount_paid=300.0,
        notes="Partial deposit received by cash/card."
    )
    db.add(inv3)
    db.flush()

    db.add(InvoiceLine(
        invoice_id=inv3.id,
        product_name="CRM Cloud Pro",
        variant_name=None,
        quantity=2,
        unit_price=350.0,
        tax_rate=10.0,
        discount_amount=0.0,
        amount=770.0
    ))

    pay2 = Payment(
        payment_number="PAY-2026-0002",
        invoice_id=inv3.id,
        amount=300.0,
        payment_method="Credit Card",
        payment_date=today - timedelta(days=10),
        reference_note="Stripe Auth: ch_3N4kL900xZ",
        status="Completed"
    )
    db.add(pay2)

    # Invoice 4: Draft invoice
    inv4 = Invoice(
        invoice_number="INV-2026-0004",
        subscription_id=sub4.id,
        customer_id=cust4.id,
        issue_date=today,
        due_date=today + timedelta(days=30),
        status="Draft",
        subtotal=450.0,
        tax_amount=67.50,
        discount_amount=45.0,
        total_amount=472.50,
        amount_paid=0.0,
        notes="Quotation-based draft invoice."
    )
    db.add(inv4)

    db.commit()
    db.close()
    print("Database seeding completed successfully!")

if __name__ == '__main__':
    seed_database()

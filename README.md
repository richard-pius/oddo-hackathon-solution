# Brightloop Software Subscription & Recurring Billing ERP
### *Oddo Hackathon Solution — Enterprise Recurring Revenue & Subscription Platform*

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16--Alpine-336791.svg?style=flat&logo=postgresql)](https://www.postgresql.org)
[![Astro](https://img.shields.io/badge/Astro-5.0-BC52EE.svg?style=flat&logo=astro)](https://astro.build)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-v4.0-38B2AC.svg?style=flat&logo=tailwind-css)](https://tailwindcss.com)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 📖 Executive Summary & Engineering Philosophy

**Brightloop Software Subscription Management System** is a mission-critical, financial-grade recurring billing and subscription ERP built for high-throughput SaaS operations. Inspired by **Odoo ERP’s ergonomics**, it unifies catalog management, variant price matrices, contract state machines, automated batch billing, multi-tier discount engines, tax jurisdictions, payment reconciliation, and real-time financial reporting.

### Core Engineering Invariants:
1. **Comment the "Why", Not the "What"**: Code documents business invariants, concurrency models, and security principles (e.g. why `SKIP LOCKED` prevents deadlock during batch billing).
2. **Zero Double-Billing Guarantee**: Enforced by composite database constraints (`INV-{sub_id}-{period_start}`) combined with atomic row locks.
3. **Odoo-Inspired ERP Ergonomics**: Chevron workflow ribbons, smart breadcrumbs, multi-tab contract forms, interactive audit chatter feeds, and 1-click persona switching.
4. **Complete Implementation**: Zero placeholders, zero mock endpoints. Every button triggers real backend transactions and state transitions.

---

## 🏛️ System Architecture

```mermaid
graph TB
    subgraph Client["Frontend Layer (Astro 5 + Tailwind CSS v4)"]
        Dashboard["Executive & Finance Dashboard"]
        SubMgmt["Odoo-Style Subscription Forms"]
        QuoteWiz["Quotation Builder & Template Engine"]
        InvLedger["Invoices & Payment Reconciliation"]
        CustPortal["Customer Self-Service Portal"]
        SSEListener["Real-Time SSE Event Ticker"]
    end

    subgraph API["Backend Layer (FastAPI Async)"]
        AuthRouter["Auth & RBAC Router (/api/v1/auth)"]
        CatalogRouter["Products & Variants Router (/api/v1/catalog)"]
        SubRouter["Subscription Lifecycle Router (/api/v1/subscriptions)"]
        BillingRouter["Billing Engine Router (/api/v1/billing)"]
        PaymentRouter["Payments & Reconciliation (/api/v1/payments)"]
        AnalyticsRouter["KPI Analytics Router (/api/v1/analytics)"]
        StreamRouter["SSE Stream Router (/api/v1/stream)"]
    end

    subgraph Engines["Core Domain Services"]
        BillingEng["Nightly Billing Batch (Idempotent SKIP LOCKED)"]
        ProrateEng["Mid-Cycle Proration Engine"]
        TaxDiscEng["Tax & Multi-Tier Volume Discount Engine"]
        ReportLabPDF["ReportLab Vector PDF Invoice Generator"]
        EventBroadcaster["Async SSE Event Broadcaster"]
    end

    subgraph Storage["Data & Jobs Layer"]
        Postgres[("PostgreSQL 16 Relational DB")]
        Scheduler["APScheduler (Nightly Cron @ 00:05)"]
    end

    Client --> API
    API --> Engines
    Engines --> Storage
    SSEListener -.->|SSE Persistent Stream| StreamRouter
```

---

## 📂 Project Structure

```text
oddo-hackathon-solution/
├── .env.example               # Complete environment variable template
├── .gitignore                  # Production Git ignore rules
├── docker-compose.yml          # Multi-container orchestration (DB, API, UI)
├── README.md                   # System documentation and evaluator guide
│
├── backend/
│   ├── Dockerfile              # Python 3.11 Slim container definition
│   ├── requirements.txt        # Pinned production Python dependencies
│   ├── seed_brightloop.py      # Enterprise seed script with realistic data
│   ├── alembic.ini             # Database migration configuration
│   ├── alembic/                # Migration scripts and environment
│   └── app/
│       ├── main.py             # FastAPI entrypoint, lifespan, CORS, and cron
│       ├── config.py           # Pydantic v2 settings management
│       ├── database.py         # Async SQLAlchemy engine & session factory
│       ├── models.py           # 13 relational entities with composite indexes
│       ├── schemas.py          # Strict Pydantic input/output validation schemas
│       ├── services/
│       │   ├── auth_service.py         # JWT, Argon2/Bcrypt, and RBAC guards
│       │   ├── billing_engine.py       # Batch billing, dunning, and ReportLab PDF
│       │   ├── subscription_service.py # Lifecycle state machine & proration
│       │   └── continuous_stream.py    # Async SSE broadcaster
│       └── routers/
│           ├── auth.py                 # Login, register, me, API keys
│           ├── catalog.py              # Products, variants (+560), plans, discounts
│           ├── subscriptions.py        # Lifecycle transitions, chatter, prorating
│           ├── billing.py              # Invoices, batch billing, PDF stream
│           ├── payments.py             # Ledger recording, auto-reconciliation
│           ├── analytics.py            # MRR, ARR, churn, aging report
│           └── stream.py               # Real-time SSE push endpoint
│
└── frontend/
    ├── Dockerfile              # Node 22 container definition
    ├── package.json            # Astro 5 & Tailwind CSS dependencies
    ├── astro.config.mjs        # Astro configuration with Vite Tailwind plugin
    └── src/
        ├── layouts/
        │   └── Layout.astro    # Master ERP layout, SSE listener, role switcher
        ├── styles/
        │   └── global.css      # ERP status ribbon styles & theme tokens
        ├── lib/
        │   └── api.ts          # Centralized API client & JWT storage
        └── pages/
            ├── index.astro                 # Executive Finance Dashboard
            ├── subscriptions/
            │   ├── index.astro             # Subscriptions ledger with status filters
            │   ├── new.astro               # Quotation wizard & template auto-fill
            │   └── [id].astro              # Odoo form view with chatter & proration
            ├── invoices/
            │   ├── index.astro             # Invoices ledger & payment modal
            │   └── [id].astro              # Tax invoice document & PDF download
            ├── payments/
            │   └── index.astro             # Payment history & ledger
            ├── catalog/
            │   └── index.astro             # Product matrices & variant extra prices
            ├── rules/
            │   └── index.astro             # Plans, 18% GST tax rules & discounts
            └── portal/
                └── index.astro             # Customer self-service checkout portal
```

---

## 🌟 Key Domain Features & Business Logic

### 1. Odoo ERP User Experience
- **Chevron Status Ribbon**: Visual state pipeline on subscriptions (`DRAFT` ➔ `QUOTATION` ➔ `CONFIRMED` ➔ `ACTIVE` ➔ `CLOSED`).
- **Interactive Chatter & Audit Trail**: Real-time logging of status transitions, timestamps, user actions, and team collaboration notes.
- **1-Click Persona Switcher**: Top-right dropdown allows examiners to instantly toggle between **Admin**, **Finance Lead**, and **Customer** personas without re-typing credentials.

### 2. Product Catalog & Variant Matrices
- Products support configurable attributes with price extra surcharges (e.g. Brand: **Odoo Variant adds +$560.00** to the line price).
- Support for **Service** (recurring SaaS), **Consumable**, and **Storable** product types.
- Pre-configured **Quotation Templates** that populate bundles, plans, and terms in a single click.

### 3. Automated Recurring Billing Engine
- **APScheduler** triggers nightly batch run at 00:05 UTC (can also be triggered manually on-demand from the UI).
- **Zero Double-Billing Guarantee**:
  - Row-level lock: `SELECT ... FOR UPDATE SKIP LOCKED` ensures concurrent billing workers never process the same chunk or cause deadlocks.
  - Unique composite constraint: `INV-{subscription_id}-{period_start}` causes database-level rejection of any duplicate charge attempt.
- **Automated Dunning Sequences**: Retries and flags overdue invoices across Days 1, 3, 5, and 7.

### 4. Mid-Cycle Prorated Seat Expansions
- When a customer expands seats mid-period, the proration engine calculates:
  $$\text{Prorated Charge} = (\Delta\text{Seats} \times \text{Unit Price}) \times \frac{\text{Days Remaining}}{\text{Total Cycle Days}}$$
- Generates an immediate prorated invoice while updating future recurring subscription quantities for subsequent cycles.

### 5. ReportLab Vector PDF Invoice Generator
- Server-side generated high-resolution vector PDF invoices.
- Features itemized line items, tax breakdowns, company registration numbers, customer addresses, and official status stamps.
- Downloadable directly from the UI or via API endpoint `/api/v1/billing/invoices/{id}/pdf`.

### 6. Real-Time Telemetry via Server-Sent Events (SSE)
- Persistent HTTP connection at `/api/v1/stream/events` with query token auth support.
- Live event broadcasts when payments are recorded, invoices generated, or contracts transition state.
- Dynamic sidebar activity ticker and visual pulse indicator update with zero page reloads.

---

## ⚡ Quickstart Guide

### Option 1: Docker Compose (All-in-One — Recommended)

Start PostgreSQL 16, the FastAPI backend, and the Astro frontend with pre-seeded data in one step:

```bash
docker-compose up --build
```

Access the services:
- **Web ERP & Customer Portal**: [http://localhost:4321](http://localhost:4321)
- **FastAPI Interactive Swagger**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **SSE Real-Time Stream**: [http://localhost:8000/api/v1/stream/events](http://localhost:8000/api/v1/stream/events)

---

### Option 2: Local Development (Without Docker — Zero Config)

> **Zero Database Setup**: When run outside Docker, Brightloop automatically defaults to an async SQLite database (`brightloop.db`), so you do not need PostgreSQL or Docker installed on your host machine. In Docker, it automatically switches to PostgreSQL 16 via environment variables.

#### 1. Backend Setup (FastAPI)
```bash
cd backend

# Create & activate virtual environment (optional)
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Seed the database (creates tables & realistic software subscription data)
python seed_brightloop.py

# Launch FastAPI development server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

#### 2. Frontend Setup (Astro 5)
```bash
cd frontend

# Install frontend dependencies
npm install

# Start Astro live ERP dev server
npm run dev
```

Visit the ERP application at [http://localhost:4321](http://localhost:4321). All API requests automatically proxy to the local backend at `http://127.0.0.1:8000`.

---

## 👥 Pre-Seeded Demo Personas

The database is populated with realistic software subscription contracts. You can switch personas using the top-right role switcher in the ERP:

| Persona | Role | Email | Password | Permissions |
|---|---|---|---|---|
| **Alex Morgan** | Administrator | `admin@brightloop.io` | `BrightloopAdmin2026!` | Full administrative access across all modules |
| **Sarah Chen** | Finance Lead | `finance@brightloop.io` | `BrightloopFinance2026!` | Billing runs, payment reconciliation, aging reports |
| **Acmez Enterprise** | Customer Tenant | `customer@brightloop.io` | `BrightloopCustomer2026!` | Self-service portal, view contracts, card payments |

---

## 🧪 Evaluator Verification Walkthrough (7 Steps)

Follow this structured workflow to test every capability of the platform:

```mermaid
sequenceDiagram
    autonumber
    actor Judge as Evaluator / Judge
    participant UI as Astro ERP UI
    participant API as FastAPI Backend
    participant Engine as Billing & Proration Engine
    participant DB as PostgreSQL DB

    Judge->>UI: 1. Open Executive Dashboard
    UI->>API: GET /api/v1/analytics/dashboard
    API-->>UI: Real-Time MRR, ARR, Churn, Aging
    Note over UI: SSE indicator turns green (Live Stream Connected)

    Judge->>UI: 2. Navigate to "New Subscription"
    UI->>Judge: Displays Quotation Template Selector
    Judge->>UI: Select "Enterprise Odoo Suite" Template
    Note over UI: Auto-populates products + variant (+$560 Odoo surcharge)
    Judge->>UI: Click "Create Subscription Quotation"
    UI->>API: POST /api/v1/subscriptions
    API-->>UI: Created in DRAFT state

    Judge->>UI: 3. Advance Odoo State Ribbon
    Judge->>UI: Click "Send Quotation" -> "Confirm Order" -> "Activate"
    UI->>API: POST /api/v1/subscriptions/{id}/transition
    API-->>UI: Contract status updated to ACTIVE
    Note over UI: Audit Chatter records transition timestamp & user

    Judge->>UI: 4. Test Mid-Cycle Prorated Upgrade
    Judge->>UI: Click "Prorated Upgrade (Seats)"
    Judge->>UI: Increase seats from 5 to 10
    Note over UI: Modal calculates remaining days and prorated charge
    Judge->>UI: Click "Confirm Upgrade & Invoice"
    UI->>API: POST /api/v1/subscriptions/{id}/prorate
    API->>Engine: Generate immediate pro-rata invoice
    API-->>UI: Prorated invoice generated & SSE broadcast sent

    Judge->>UI: 5. Trigger Nightly Batch Billing
    Judge->>UI: Click "Trigger Billing Batch" in header
    UI->>API: POST /api/v1/billing/batch-run
    API->>Engine: Run SELECT ... FOR UPDATE SKIP LOCKED
    API-->>UI: Returns processed count & verifies 0 double-billings

    Judge->>UI: 6. Download Vector PDF Invoice
    Judge->>UI: Click "Download PDF" on any invoice
    UI->>API: GET /api/v1/billing/invoices/{id}/pdf
    API-->>Judge: Downloads official ReportLab vector PDF with stamp

    Judge->>UI: 7. Test Customer Portal Checkout
    Judge->>UI: Switch persona to "Acmez Enterprise (Customer)"
    Judge->>UI: Go to /portal and click "Pay Now" on open invoice
    UI->>API: POST /api/v1/payments
    API-->>UI: Auto-reconciles: status becomes PAID ($0.00 due)
```

---

## 📡 REST API Reference

All endpoints are versioned under `/api/v1/` (with automatic backward-compatible path rewriting for `/api/`):

### Authentication & Users
- `POST /api/v1/auth/login` — Authenticate and receive JWT access token.
- `POST /api/v1/auth/register` — Create new user account.
- `GET /api/v1/auth/me` — Retrieve active profile and role.
- `GET /api/v1/auth/users` — List customer accounts for quotation builder.

### Catalog & Pricing
- `GET /api/v1/catalog/products` — List products with variant matrices and price extras.
- `POST /api/v1/catalog/products` — Create new catalog item.
- `GET /api/v1/catalog/plans` — List billing plans (Monthly Flex, Annual Commitment, Daily Dev).
- `GET /api/v1/catalog/discounts` — List volume tiers and promotional coupons.
- `GET /api/v1/catalog/taxes` — List active tax jurisdictions (18% GST / IGST).
- `GET /api/v1/catalog/quotation-templates` — List enterprise bundles.

### Subscriptions & Contracts
- `GET /api/v1/subscriptions` — Paginated contract ledger with status filters.
- `POST /api/v1/subscriptions` — Create new subscription contract.
- `GET /api/v1/subscriptions/{id}` — Retrieve full subscription form data.
- `POST /api/v1/subscriptions/{id}/transition` — Advance state machine (`quotation`, `confirmed`, `active`, `paused`, `cancelled`, `closed`).
- `POST /api/v1/subscriptions/{id}/prorate` — Mid-cycle seat upgrade with immediate pro-rata invoice.
- `GET /api/v1/subscriptions/{id}/audit` — Retrieve audit trail.
- `POST /api/v1/subscriptions/{id}/chatter` — Post a discussion note to contract chatter.

### Invoices & Billing
- `GET /api/v1/billing/invoices` — List invoices with balance due and status filters.
- `GET /api/v1/billing/invoices/{id}` — Invoice detail view.
- `POST /api/v1/billing/batch-run` — Trigger idempotent batch billing run.
- `POST /api/v1/billing/subscriptions/{id}/invoice` — Generate on-demand invoice for subscription.
- `GET /api/v1/billing/invoices/{id}/pdf` — Download ReportLab vector PDF invoice.

### Payments & Reconciliation
- `GET /api/v1/payments` — Payment ledger and transaction history.
- `POST /api/v1/payments` — Record payment; auto-reconciles invoice to `PAID` when balance is cleared.

### Analytics & Stream
- `GET /api/v1/analytics/dashboard` — Unified KPIs (MRR, ARR, active contracts, churn, overdue aging).
- `GET /api/v1/stream/events` — Server-Sent Events (SSE) live push stream.

---

## 🗄️ Database Schema & Entities

The system uses 13 relational models with strict constraints and indexes:

1. **`users`**: RBAC roles (`admin`, `internal_staff`, `customer`), hashed passwords, active status.
2. **`products`**: Type (`service`, `consumable`, `storable`), base price, active flag.
3. **`product_variants`**: Attributes JSON, price extra surcharge (e.g. `+$560.00`), SKU.
4. **`subscription_plans`**: Billing interval (`day`, `week`, `month`, `year`), interval count, renewal policies.
5. **`tax_rules`**: Tax rate percentage, jurisdiction, compound flag, product type applicability.
6. **`discount_rules`**: Type (`percentage`, `fixed_amount`, `tiered_quantity`), value, minimum quantity thresholds.
7. **`quotation_templates` & `quotation_template_lines`**: Predefined quotation structures.
8. **`subscriptions`**: State machine, billing dates, customer ID, plan ID, payment terms.
9. **`subscription_lines`**: Product, variant, quantity, unit price, tax IDs, line subtotal.
10. **`subscription_audits`**: State change ledger, user ID, reason, timestamp.
11. **`invoices`**: Idempotency key, issue/due dates, subtotal, tax total, amount paid, amount due, status.
12. **`invoice_lines`**: Itemized invoice line items with taxes and discounts.
13. **`payments`**: Payment method, amount, reference note, transaction date, recorded by.

---

## 📄 License

This solution is developed for the **Oddo Hackathon** under the MIT License.

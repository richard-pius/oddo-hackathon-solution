# Brightloop ERP — Frontend UI (Astro 5 + Tailwind CSS v4)

The user-facing web interface for the Brightloop Software Subscription & Recurring Billing ERP, built with **Astro 5** and **Tailwind CSS v4**.

> [!IMPORTANT]
> **Working Directory Notice**: You must execute all frontend commands from inside this `frontend/` directory:
> ```bash
> cd frontend
> ```

---

## 🚀 Quick Start Guide

### 1. Install Dependencies
```bash
cd frontend
npm install
```

### 2. Launch Development Server
```bash
npm run dev
```
The frontend application will start at [http://localhost:4321](http://localhost:4321).

### 3. Build for Production
```bash
npm run build
```
Builds 200+ static routes and assets to the `./dist/` directory.

---

## 🎨 Features & Capabilities

- **Executive & Finance Dashboard**: Real-time SaaS KPIs (MRR, ARR, active contracts, uncollected receivables).
- **Odoo-Style Subscription Forms**: Chevron status pipeline ribbon, mid-cycle seat proration wizard, chatter activity feed, and on-demand invoice generation.
- **Product Catalog & Variant Matrices**: Master catalog with attribute price modifiers (e.g. Odoo brand surcharge `+$560.00`, Cloud hosting `+$200.00`), baseline pricing, and "+ Add Variant" direct configuration.
- **Invoice & Ledger Management**: Filter by status (Posted, Paid, Overdue, Draft), on-demand invoice generation modal, ReportLab vector PDF downloads, and payment auto-reconciliation.
- **Identity & Staff Management (`/admin`)**:
  - Full RBAC visibility across Administrators, Internal Staff, and Customer Tenants.
  - Staff provisioning form with live 4-point password complexity checks.
  - Admin controls to **Change Passwords** and **Delete User Accounts** with safety modals.
- **Strict Tenant-Isolated Customer Portal (`/portal`)**: Secure self-service portal for customers to view active subscriptions and settle open invoices with card payments.
- **Session & Identity Bar**: Clean header display showing the authenticated user's name, avatar, and role badge (no mock persona switching), plus a dedicated Sign Out button.

# Brightloop ERP Frontend

The user-facing web interface for the Brightloop Software Subscription & Recurring Billing ERP, built with **Astro 5** and **Tailwind CSS v4**.

## Features

- **Executive & Finance Dashboard**: Real-time SaaS KPIs (MRR, ARR, churn rate, aging breakdown).
- **Odoo-Style Subscription Forms**: Chevron status ribbons, proration wizard, and chatter feed.
- **Invoice & Ledger Management**: Direct invoice inspection, vector PDF download, and payment reconciliation.
- **Quotation Wizard**: Multi-item bundle selection with automatic pricing extras and discount calculations.
- **Customer Self-Service Portal**: Instant customer invoice checkout and payment recording.
- **Real-Time Telemetry**: Persistent SSE updates via event tickers and status indicators.

## Running Locally

From the `frontend` directory:

```bash
# Install dependencies
npm install

# Start development server
npm run dev
```

The frontend will start at [http://localhost:4321](http://localhost:4321).

## Production Build

```bash
# Build static / server output to ./dist/
npm run build

# Preview the production build locally
npm run preview
```

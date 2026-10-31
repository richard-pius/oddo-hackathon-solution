# Brightloop ERP — Backend Engine (FastAPI)

The asynchronous FastAPI backend for Brightloop Software Subscription & Recurring Billing ERP.

> [!IMPORTANT]
> **Working Directory Notice**: You must execute all backend commands from inside this `backend/` directory:
> ```bash
> cd backend
> ```

---

## 🚀 Quick Start Guide

### 1. Install Dependencies
```bash
# (Optional) Create and activate a virtual environment
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On macOS / Linux:
# source venv/bin/activate

# Install pinned dependencies
pip install -r requirements.txt
```

### 2. Seed Database
Creates the database schema and loads realistic enterprise contracts, products, variants, taxes, and demo accounts:
```bash
python seed_brightloop.py
```

### 3. Launch the API Server
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
API Swagger Documentation will be available at: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 🧪 Running Automated Tests

All tests must be run from inside the `backend` directory:

```bash
# Run the entire test suite (15 tests)
python -m unittest discover tests -v

# Run the Evaluator Walkthrough suite
python -m unittest tests.test_evaluator_walkthrough -v

# Run Auth & RBAC lifecycle tests (including account deletion & password change)
python -m unittest tests.test_auth -v
```

---

## 🔑 Key Endpoints Added

- `DELETE /api/v1/auth/users/{user_id}`: Admin-only account deletion with self-deletion protection and automated dependency cleanup.
- `PUT /api/v1/auth/users/{user_id}/password`: Admin-only account password reset with enterprise complexity validation.
- `POST /api/v1/subscriptions/{subscription_id}/generate-invoice`: Staff/Admin on-demand itemized invoice generation for active contracts.
- `GET /api/v1/billing/invoices/{invoice_id}/pdf`: Vector PDF invoice download powered by ReportLab (supports `?token=` parameter for zero-friction browser downloads).

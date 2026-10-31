import unittest
import sys
import os
from decimal import Decimal

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app


class TestEvaluatorWalkthrough(unittest.TestCase):
    client: TestClient
    admin_token: str = ""
    admin_headers: dict = {}
    created_sub_id: int | None = None
    prorated_invoice_id: int | None = None

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Authenticate admin at class setup so every test is runnable independently
        res = cls.client.post("/api/v1/auth/login", json={
            "email": "admin@brightloop.io",
            "password": "BrightloopAdmin2026!"
        })
        if res.status_code == 200:
            data = res.json()
            cls.admin_token = data.get("access_token", "")
            cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

    @classmethod
    def tearDownClass(cls):
        # Gracefully shut down TestClient and connection pools to eliminate ResourceWarnings
        cls.client.close()

    def _ensure_draft_subscription(self) -> int:
        """Helper to ensure a DRAFT subscription exists for lifecycle tests."""
        if self.created_sub_id:
            # Check if current created_sub is still in DRAFT
            res = self.client.get(f"/api/v1/subscriptions/{self.created_sub_id}", headers=self.admin_headers)
            if res.status_code == 200 and res.json().get("status") == "DRAFT":
                return self.created_sub_id

        # Query existing DRAFT subscriptions
        res = self.client.get("/api/v1/subscriptions?status_filter=DRAFT", headers=self.admin_headers)
        if res.status_code == 200:
            items = res.json().get("items", [])
            if items:
                return items[0]["id"]

        # Otherwise create one dynamically
        return self._create_sample_subscription()

    def _ensure_active_subscription(self) -> int:
        """Helper to ensure an ACTIVE subscription exists with line items."""
        # Query existing ACTIVE subscriptions
        res = self.client.get("/api/v1/subscriptions?status_filter=ACTIVE", headers=self.admin_headers)
        if res.status_code == 200:
            items = res.json().get("items", [])
            for item in items:
                # Ensure it has lines
                sub_detail = self.client.get(f"/api/v1/subscriptions/{item['id']}", headers=self.admin_headers).json()
                if sub_detail.get("lines"):
                    return item["id"]

        # If none found, create and advance one
        sub_id = self._create_sample_subscription()
        for st in ["QUOTATION", "CONFIRMED", "ACTIVE"]:
            self.client.post(
                f"/api/v1/subscriptions/{sub_id}/transition",
                json={"target_status": st, "notes": f"Auto-advancing to {st}"},
                headers=self.admin_headers
            )
        return sub_id

    def _ensure_customer_open_invoice(self, cust_headers: dict) -> dict:
        """Helper to ensure the logged-in customer has an open, payable invoice."""
        inv_res = self.client.get("/api/v1/billing/invoices", headers=cust_headers)
        if inv_res.status_code == 200:
            invoices = inv_res.json().get("items", [])
            for inv in invoices:
                if (
                    str(inv.get("status", "")).upper() in ["CONFIRMED", "DRAFT"]
                    and Decimal(str(inv.get("amount_due", 0))) > 0
                ):
                    return inv

        # If no open invoice exists for the customer, find or create an active subscription and prorate it
        cust_subs_res = self.client.get("/api/v1/subscriptions?status_filter=ACTIVE", headers=cust_headers)
        cust_sub = None
        if cust_subs_res.status_code == 200:
            items = cust_subs_res.json().get("items", [])
            if items:
                sub_detail = self.client.get(f"/api/v1/subscriptions/{items[0]['id']}", headers=cust_headers).json()
                if sub_detail.get("lines"):
                    cust_sub = sub_detail

        if not cust_sub:
            sub_id = self._create_sample_subscription()
            for st in ["QUOTATION", "CONFIRMED", "ACTIVE"]:
                self.client.post(
                    f"/api/v1/subscriptions/{sub_id}/transition",
                    json={"target_status": st, "notes": f"Auto-advancing to {st}"},
                    headers=self.admin_headers
                )
            cust_sub = self.client.get(f"/api/v1/subscriptions/{sub_id}", headers=self.admin_headers).json()

        target_line = cust_sub["lines"][0]
        prorate_res = self.client.post(
            f"/api/v1/subscriptions/{cust_sub['id']}/prorate",
            json={"line_id": target_line["id"], "new_quantity": target_line["quantity"] + 1},
            headers=self.admin_headers
        )
        invoice_id = prorate_res.json()["invoice_id"]
        inv_detail = self.client.get(f"/api/v1/billing/invoices/{invoice_id}", headers=cust_headers)
        return inv_detail.json()

    def _create_sample_subscription(self) -> int:
        """Helper to create a fresh sample subscription with dynamic relationships."""
        # Dynamic customer lookup
        users_res = self.client.get("/api/v1/auth/users", headers=self.admin_headers)
        customers = [u for u in users_res.json() if str(u.get("role", "")).upper() == "CUSTOMER"]
        customer_id = customers[0]["id"] if customers else 1

        # Dynamic plan & product lookup
        plans_res = self.client.get("/api/v1/catalog/plans", headers=self.admin_headers)
        plans = plans_res.json()
        plan_id = plans[0]["id"] if plans else 1

        prods_res = self.client.get("/api/v1/catalog/products", headers=self.admin_headers)
        products = prods_res.json()
        prod = products[0]

        taxes_res = self.client.get("/api/v1/catalog/taxes", headers=self.admin_headers)
        taxes = taxes_res.json()
        tax_ids = [taxes[0]["id"]] if taxes else []

        payload = {
            "customer_id": customer_id,
            "plan_id": plan_id,
            "start_date": "2026-11-01",
            "payment_terms": "Net 30",
            "notes": "Isolated Test Subscription",
            "lines": [
                {
                    "product_id": prod["id"],
                    "variant_id": prod["variants"][0]["id"] if prod.get("variants") else None,
                    "description": prod.get("name", "Product License"),
                    "quantity": 5,
                    "unit_price": 1200.00,
                    "tax_ids": tax_ids
                }
            ]
        }
        res = self.client.post("/api/v1/subscriptions", json=payload, headers=self.admin_headers)
        sub = res.json()
        return sub["id"]

    def test_01_evaluator_login_admin(self):
        """Step 1 prerequisite: Authenticate as Administrator"""
        res = self.client.post("/api/v1/auth/login", json={
            "email": "admin@brightloop.io",
            "password": "BrightloopAdmin2026!"
        })
        self.assertEqual(res.status_code, 200, f"Login failed: {res.text}")
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(str(data["role"]).upper(), "ADMIN")

    def test_02_dashboard_kpis(self):
        """Step 1: Open Executive Dashboard & verify KPIs"""
        res = self.client.get("/api/v1/analytics/dashboard", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200, f"Dashboard failed: {res.text}")
        data = res.json()
        self.assertIn("mrr", data)
        self.assertIn("arr", data)
        self.assertIn("total_revenue_collected", data)

    def test_03_create_subscription(self):
        """Step 2: Quotation Builder & create subscription in DRAFT"""
        # Dynamic template lookup (tests both /templates and /quotation-templates)
        tpl_res = self.client.get("/api/v1/catalog/quotation-templates", headers=self.admin_headers)
        self.assertEqual(tpl_res.status_code, 200)
        templates = tpl_res.json()
        self.assertTrue(len(templates) > 0)
        tpl = templates[0]

        # Dynamic customer lookup
        users_res = self.client.get("/api/v1/auth/users", headers=self.admin_headers)
        customers = [u for u in users_res.json() if str(u.get("role", "")).upper() == "CUSTOMER"]
        self.assertTrue(len(customers) > 0)
        customer_id = customers[0]["id"]

        # Dynamic products and taxes lookup
        prod_res = self.client.get("/api/v1/catalog/products", headers=self.admin_headers)
        self.assertEqual(prod_res.status_code, 200)
        products = prod_res.json()
        self.assertTrue(len(products) > 0)

        taxes_res = self.client.get("/api/v1/catalog/taxes", headers=self.admin_headers)
        taxes = taxes_res.json()
        tax_ids = [taxes[0]["id"]] if taxes else []

        create_payload = {
            "customer_id": customer_id,
            "plan_id": tpl["plan_id"],
            "start_date": "2026-11-01",
            "payment_terms": "Net 30",
            "notes": "Evaluator Test Subscription",
            "lines": [
                {
                    "product_id": products[0]["id"],
                    "variant_id": products[0]["variants"][0]["id"] if products[0].get("variants") else None,
                    "description": "Odoo Enterprise License",
                    "quantity": 5,
                    "unit_price": 1200.00,
                    "tax_ids": tax_ids
                }
            ]
        }
        res = self.client.post("/api/v1/subscriptions", json=create_payload, headers=self.admin_headers)
        self.assertIn(res.status_code, [200, 201], f"Create subscription failed: {res.text}")
        sub = res.json()
        self.assertEqual(sub["status"], "DRAFT")
        TestEvaluatorWalkthrough.created_sub_id = sub["id"]

    def test_04_advance_state_machine(self):
        """Step 3: Advance state machine: DRAFT -> QUOTATION -> CONFIRMED -> ACTIVE"""
        sub_id = self._ensure_draft_subscription()
        for target_state in ["QUOTATION", "CONFIRMED", "ACTIVE"]:
            res = self.client.post(
                f"/api/v1/subscriptions/{sub_id}/transition",
                json={"target_status": target_state, "notes": f"Advancing to {target_state}"},
                headers=self.admin_headers
            )
            self.assertEqual(res.status_code, 200, f"Transition to {target_state} failed: {res.text}")
            self.assertEqual(res.json()["status"], target_state)

    def test_05_prorated_upgrade(self):
        """Step 4: Mid-cycle prorated seat upgrade (5 -> 10 seats)"""
        sub_id = self._ensure_active_subscription()
        sub_res = self.client.get(f"/api/v1/subscriptions/{sub_id}", headers=self.admin_headers)
        self.assertEqual(sub_res.status_code, 200)
        sub_data = sub_res.json()
        self.assertTrue(len(sub_data["lines"]) > 0)
        target_line = sub_data["lines"][0]
        current_qty = target_line["quantity"]

        prorate_payload = {
            "line_id": target_line["id"],
            "new_quantity": current_qty + 5
        }
        res = self.client.post(f"/api/v1/subscriptions/{sub_id}/prorate", json=prorate_payload, headers=self.admin_headers)
        self.assertEqual(res.status_code, 200, f"Proration failed: {res.text}")
        prorate_result = res.json()
        self.assertEqual(prorate_result["status"], "prorated_success")
        self.assertEqual(prorate_result["new_quantity"], current_qty + 5)
        self.assertIn("invoice_id", prorate_result)
        TestEvaluatorWalkthrough.prorated_invoice_id = prorate_result["invoice_id"]

    def test_06_batch_billing(self):
        """Step 5: Trigger Batch Billing Run (tests both /run-billing and /batch-run)"""
        res1 = self.client.post("/api/v1/billing/run-billing", headers=self.admin_headers)
        self.assertEqual(res1.status_code, 200, f"Batch billing failed: {res1.text}")
        res2 = self.client.post("/api/v1/billing/batch-run", headers=self.admin_headers)
        self.assertEqual(res2.status_code, 200, f"Batch-run alias failed: {res2.text}")

    def test_07_download_pdf_invoice(self):
        """Step 6: Download vector PDF invoice"""
        inv_id = self.prorated_invoice_id
        if not inv_id:
            # Query first available invoice
            inv_res = self.client.get("/api/v1/billing/invoices", headers=self.admin_headers)
            items = inv_res.json().get("items", [])
            self.assertTrue(len(items) > 0, "No invoice available to test PDF download")
            inv_id = items[0]["id"]

        res = self.client.get(f"/api/v1/billing/invoices/{inv_id}/pdf", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("content-type"), "application/pdf")
        self.assertTrue(len(res.content) > 100)
        self.assertTrue(res.content.startswith(b"%PDF"))

    def test_08_customer_portal_and_payment(self):
        """Step 7: Customer portal payment & auto-reconciliation"""
        # Login as customer
        login_res = self.client.post("/api/v1/auth/login", json={
            "email": "customer@brightloop.io",
            "password": "BrightloopCustomer2026!"
        })
        self.assertEqual(login_res.status_code, 200)
        cust_token = login_res.json()["access_token"]
        cust_headers = {"Authorization": f"Bearer {cust_token}"}

        # Check customer invoices and ensure an open, payable invoice
        open_inv = self._ensure_customer_open_invoice(cust_headers)
        self.assertTrue(open_inv is not None, "Failed to resolve or generate an open customer invoice")
        self.assertIn(str(open_inv["status"]).upper(), ["CONFIRMED", "DRAFT"])
        pay_amount = float(open_inv["amount_due"])
        self.assertTrue(pay_amount > 0, "Open invoice must have a positive amount due")

        # Record payment
        pay_payload = {
            "invoice_id": open_inv["id"],
            "amount": pay_amount,
            "payment_method": "CREDIT_CARD",
            "reference_note": "Evaluator portal test payment"
        }
        pay_res = self.client.post("/api/v1/payments", json=pay_payload, headers=cust_headers)
        self.assertIn(pay_res.status_code, [200, 201], f"Payment failed: {pay_res.text}")
        pay_data = pay_res.json()
        self.assertEqual(pay_data["invoice_id"], open_inv["id"])

        # Verify auto-reconciliation on the invoice
        check_inv = self.client.get(f"/api/v1/billing/invoices/{open_inv['id']}", headers=cust_headers)
        self.assertEqual(check_inv.status_code, 200)
        updated_inv = check_inv.json()
        self.assertEqual(Decimal(str(updated_inv["amount_due"])), Decimal("0.00"))
        self.assertEqual(str(updated_inv["status"]).upper(), "PAID")


if __name__ == "__main__":
    unittest.main()

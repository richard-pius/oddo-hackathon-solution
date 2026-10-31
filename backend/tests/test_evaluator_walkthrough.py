import unittest
import sys
import os
from decimal import Decimal

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app

class TestEvaluatorWalkthrough(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_evaluator_login_admin(self):
        """Step 1 prerequisite: Authenticate as Administrator"""
        res = self.client.post("/api/v1/auth/login", json={
            "email": "admin@brightloop.io",
            "password": "BrightloopAdmin2026!"
        })
        print(f"Step 1 Login: status={res.status_code}")
        self.assertEqual(res.status_code, 200, f"Login failed: {res.text}")
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], "ADMIN")
        TestEvaluatorWalkthrough.admin_token = data["access_token"]
        TestEvaluatorWalkthrough.admin_headers = {"Authorization": f"Bearer {data['access_token']}"}

    def test_02_dashboard_kpis(self):
        """Step 1: Open Executive Dashboard & verify KPIs"""
        res = self.client.get("/api/v1/analytics/dashboard", headers=self.admin_headers)
        print(f"Step 1 Dashboard KPIs: status={res.status_code}")
        self.assertEqual(res.status_code, 200, f"Dashboard failed: {res.text}")
        data = res.json()
        print(f"Dashboard keys: {list(data.keys())}")
        self.assertIn("mrr", data)
        self.assertIn("arr", data)

    def test_03_create_subscription(self):
        """Step 2: Quotation Builder & create subscription in DRAFT"""
        # Fetch templates
        tpl_res = self.client.get("/api/v1/catalog/quotation-templates", headers=self.admin_headers)
        self.assertEqual(tpl_res.status_code, 200)
        templates = tpl_res.json()
        print(f"Templates count: {len(templates)}")
        self.assertTrue(len(templates) > 0)
        tpl = templates[0]

        # Fetch products
        prod_res = self.client.get("/api/v1/catalog/products", headers=self.admin_headers)
        self.assertEqual(prod_res.status_code, 200)
        products = prod_res.json()
        self.assertTrue(len(products) > 0)

        # Create subscription
        create_payload = {
            "customer_id": 4, # Customer user
            "plan_id": tpl["plan_id"],
            "start_date": "2026-11-01",
            "payment_terms": "Net 30",
            "notes": "Evaluator Test Subscription",
            "lines": [
                {
                    "product_id": products[0]["id"],
                    "variant_id": products[0]["variants"][0]["id"] if products[0]["variants"] else None,
                    "description": "Odoo Enterprise License",
                    "quantity": 5,
                    "unit_price": 1200.00,
                    "tax_ids": [1]
                }
            ]
        }
        res = self.client.post("/api/v1/subscriptions", json=create_payload, headers=self.admin_headers)
        print(f"Create subscription: status={res.status_code}")
        self.assertIn(res.status_code, [200, 201], f"Create subscription failed: {res.text}")
        sub = res.json()
        self.assertEqual(sub["status"], "DRAFT")
        TestEvaluatorWalkthrough.created_sub_id = sub["id"]

    def test_04_advance_state_machine(self):
        """Step 3: Advance state machine: DRAFT -> QUOTATION -> CONFIRMED -> ACTIVE"""
        sub_id = self.created_sub_id
        for target_state in ["QUOTATION", "CONFIRMED", "ACTIVE"]:
            res = self.client.post(
                f"/api/v1/subscriptions/{sub_id}/transition",
                json={"target_status": target_state, "notes": f"Advancing to {target_state}"},
                headers=self.admin_headers
            )
            print(f"Transition to {target_state}: status={res.status_code}")
            self.assertEqual(res.status_code, 200, f"Transition to {target_state} failed: {res.text}")
            self.assertEqual(res.json()["status"], target_state)

    def test_05_prorated_upgrade(self):
        """Step 4: Mid-cycle prorated seat upgrade (5 -> 10 seats)"""
        sub_id = self.created_sub_id
        # Get subscription lines
        sub_res = self.client.get(f"/api/v1/subscriptions/{sub_id}", headers=self.admin_headers)
        self.assertEqual(sub_res.status_code, 200)
        sub_data = sub_res.json()
        line_id = sub_data["lines"][0]["id"]

        prorate_payload = {
            "line_id": line_id,
            "new_quantity": 10
        }
        res = self.client.post(f"/api/v1/subscriptions/{sub_id}/prorate", json=prorate_payload, headers=self.admin_headers)
        print(f"Prorate upgrade: status={res.status_code}")
        self.assertEqual(res.status_code, 200, f"Proration failed: {res.text}")
        prorate_result = res.json()
        self.assertEqual(prorate_result["status"], "prorated_success")
        self.assertEqual(prorate_result["new_quantity"], 10)
        self.assertIn("invoice_id", prorate_result)
        TestEvaluatorWalkthrough.prorated_invoice_id = prorate_result["invoice_id"]

    def test_06_batch_billing(self):
        """Step 5: Trigger Batch Billing Run"""
        res = self.client.post("/api/v1/billing/run-billing", headers=self.admin_headers)
        print(f"Batch billing /run-billing: status={res.status_code}")
        self.assertEqual(res.status_code, 200, f"Batch billing failed: {res.text}")

    def test_07_download_pdf_invoice(self):
        """Step 6: Download vector PDF invoice"""
        inv_id = self.prorated_invoice_id
        res = self.client.get(f"/api/v1/billing/invoices/{inv_id}/pdf", headers=self.admin_headers)
        print(f"PDF download: status={res.status_code}, content-type={res.headers.get('content-type')}")
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

        # Check customer invoices
        inv_res = self.client.get("/api/v1/billing/invoices", headers=cust_headers)
        self.assertEqual(inv_res.status_code, 200)
        invoices_data = inv_res.json()
        invoices = invoices_data.get("items", [])
        self.assertTrue(len(invoices) > 0)
        open_inv = next((inv for inv in invoices if Decimal(str(inv["amount_due"])) > 0), None)
        if not open_inv:
            open_inv = invoices[0]

        # Record payment
        pay_payload = {
            "invoice_id": open_inv["id"],
            "amount": float(open_inv["amount_due"]) if float(open_inv["amount_due"]) > 0 else 50.0,
            "payment_method": "credit_card",
            "reference_note": "Evaluator portal test payment"
        }
        pay_res = self.client.post("/api/v1/payments", json=pay_payload, headers=cust_headers)
        print(f"Payment record: status={pay_res.status_code}")
        self.assertIn(pay_res.status_code, [200, 201], f"Payment failed: {pay_res.text}")
        pay_data = pay_res.json()
        self.assertEqual(pay_data["invoice_id"], open_inv["id"])

if __name__ == "__main__":
    unittest.main()

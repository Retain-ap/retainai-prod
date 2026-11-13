import copy
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from flask import Flask

os.environ.setdefault("RUN_SCHEDULER", "0")
import partner_commissions as ledger


def invoice(identifier="in_one", stamp=1767225600, total=2260, base=2000):
    return {"id": identifier, "customer": "cus_example", "livemode": False, "status": "paid", "amount_paid": total,
        "total": total, "total_excluding_tax": base, "currency": "cad", "status_transitions": {"paid_at": stamp},
        "lines": {"has_more": False, "data": [{"amount": base, "quantity": 1, "pricing": {"price_details": {"price": "price_base"}}, "parent": {"subscription_item_details": {"subscription": "sub_example", "proration": False}}, "discount_amounts": [], "taxes": []}]}}


def charge(total=2260, refunded=0):
    return {"id": "ch_example", "customer": "cus_example", "livemode": False, "currency": "cad", "amount": total,
        "amount_refunded": refunded, "paid": True, "captured": True, "status": "succeeded"}


class PartnerAccountingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.patch = patch.object(ledger, "SQLITE_PATH", os.path.join(self.directory.name, "test.db"))
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.env = patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_fixture", "STRIPE_PRICE_ID": "price_base"})
        self.env.start(); self.addCleanup(self.env.stop)
        self.app = Flask(__name__); self.app.secret_key = "fixture-session-key"
        self.app.register_blueprint(ledger.partners_bp)
        self.client = self.app.test_client()
        with ledger.state_write() as state:
            state["partners"].append({"code": "salon-coach", "name": "Example Coach", "email": "coach@example.com", "active": True})

    def test_tax_discount_addons_and_minor_unit_rounding(self):
        i = invoice()
        self.assertEqual(ledger.calculate(i, charge(), 2000, i["status_transitions"]["paid_at"], 1800000000)["commissionMinor"], 600)
        c = invoice(total=999, base=999)
        self.assertEqual(ledger.calculate(c, charge(999), 999, c["status_transitions"]["paid_at"], 1800000000)["commissionMinor"], 300)
        line = i["lines"]["data"][0]; line["discount_amounts"] = [{"amount": 500}]
        i["lines"]["data"].append({"amount": 1000, "pricing": {"price_details": {"price": "price_addon"}}})
        self.assertEqual(ledger.base_amount(i, "price_base"), 1500)

    def test_refunds_disputes_and_unknown_allocations_never_overpay(self):
        i = invoice(); first = i["status_transitions"]["paid_at"]
        self.assertEqual(ledger.calculate(i, charge(refunded=1130), 2000, first, first+3000000, ["price_base"])["commissionMinor"], 300)
        self.assertEqual(ledger.calculate(i, charge(refunded=2260), 2000, first, first+3000000)["commissionMinor"], 0)
        for mutation in ({"disputed": True}, {"customer": "cus_else"}, {"livemode": True}, {"captured": False}, {"currency": "usd"}):
            result = ledger.calculate(i, {**charge(), **mutation}, 2000, first, first+3000000)
            self.assertEqual((result["commissionMinor"], result["status"]), (0, "review"))
        i["post_payment_credit_notes_amount"] = 50
        self.assertEqual(ledger.calculate(i, charge(), 2000, first, first+3000000)["status"], "review")

    def test_partial_mixed_refunds_hold_without_guessing_base_or_addon_allocation(self):
        i = invoice(total=3000)
        i["total_excluding_tax"] = 3000
        i["lines"]["data"].append({"amount": 1000, "pricing": {"price_details": {"price": "price_addon"}}})
        first, now = i["status_transitions"]["paid_at"], 1800000000
        for refunded in (1000, 2000):
            result = ledger.calculate(i, charge(3000, refunded), 2000, first, now, ["price_base"])
            self.assertEqual((result["status"], result["commissionMinor"]), ("review", 0))
            self.assertIn("Partial refund allocation", result["reason"])
        full = ledger.calculate(i, charge(3000, 3000), 2000, first, now, ["price_base"])
        self.assertEqual((full["status"], full["commissionMinor"]), ("available", 0))
        self.assertEqual(ledger.calculate(i, charge(3000), 2000, first, now, ["price_base"])["commissionMinor"], 600)
        # Tax alone does not make a membership invoice mixed.
        base_only = ledger.calculate(invoice(), charge(refunded=1130), 2000, first, now, ["price_base"])
        self.assertEqual((base_only["status"], base_only["commissionMinor"]), ("available", 300))
        self.assertEqual(ledger.calculate(invoice(), charge(refunded=1130), 2000, first, now)["status"], "review")
        for data in ([], [{**invoice()["lines"]["data"][0], "amount": 0}]):
            missing_base = {**invoice(), "lines": {"has_more": False, "data": data}}
            self.assertEqual(ledger.calculate(missing_base, charge(refunded=1130), 2000, first, now, ["price_base"])["status"], "review")
        i["total_excluding_tax"] = 2000
        i["lines"]["data"].append({"amount": -1000})
        self.assertEqual(ledger.calculate(i, charge(3000, 1000), 2000, first, now, ["price_base"])["status"], "review")

    def test_legacy_refunds_hold_owner_export_and_recording_until_safe_refresh(self):
        ledger.bind_customer("member@example.com", "cus_example", "salon-coach", "2026-01-01", False)
        first = invoice()["status_transitions"]["paid_at"]
        prior = {**ledger.calculate(invoice(), charge(), 2000, first, int(time.time())), "customerId": "cus_example",
            "code": "salon-coach", "livemode": False, "commissionMinor": 300, "reason": "Refund adjusted"}
        del prior["refundAllocationVersion"]
        payout = {"code": "salon-coach", "currency": "cad", "livemode": False, "amountMinor": 100, "reference": "historical-payment", "recordedAt": first}
        with ledger.state_write() as state:
            state["referrals"][0].update({"firstPaidAt": first, "syncedAt": int(time.time()), "error": ""})
            state["invoices"] = [prior, {**prior, "invoiceId": "in_legacyzero", "commissionMinor": 0}]; state["payouts"] = [payout]
            self.assertEqual(ledger.available(state, "salon-coach", "cad", False, int(time.time())), -100)
        current_invoice = invoice(total=3000)
        current_invoice["total_excluding_tax"] = 3000
        current_invoice["lines"]["data"].append({"amount": 1000, "pricing": {"price_details": {"price": "price_addon"}}})
        refunded = 1000
        def provider(path):
            if path.startswith("invoices?"): return {"data": [current_invoice], "has_more": False}
            if path.startswith("invoice_payments?"): return {"data": [{"invoice": "in_one", "livemode": False, "amount_paid": current_invoice["total"], "payment": {"payment_intent": "pi_example"}}], "has_more": False}
            if path.startswith("payment_intents/"): return {"latest_charge": charge(current_invoice["total"], refunded)}
            raise AssertionError(path)
        with patch.object(ledger, "_require_owner", return_value=("owner@retainai.ca", None)), patch.object(ledger, "bind_known_customers"), patch.object(ledger, "stripe_get", provider):
            data = self.client.get("/api/owner/partners").get_json()
            self.assertEqual((data["invoices"][0]["status"], data["invoices"][0]["commissionMinor"]), ("review", 0))
            self.assertEqual(data["invoices"][0]["previousCommissionMinor"], 300)
            self.assertEqual(data["invoices"][1]["status"], "review")
            self.assertEqual(data["invoices"][1]["previousCommissionMinor"], 0)
            self.assertEqual(data["balances"][0]["amountMinor"], -100); self.assertEqual(data["payouts"], [payout])
            record = {"op": "record", "code": "salon-coach", "currency": "cad", "amountMinor": 200, "reference": "must-not-record"}
            response = self.client.post("/api/owner/partners", json=record)
            self.assertEqual(response.status_code, 400); self.assertIn("review holds", response.get_json()["error"])
            ledger.sync_customer("cus_example"); ledger.sync_customer("cus_example")
            self.assertEqual(len(ledger.read_state()["invoices"]), 1)
            self.assertEqual(ledger.read_state()["invoices"][0]["status"], "review")
            self.assertEqual(self.client.post("/api/owner/partners", json=record).status_code, 400)
            current_invoice = invoice(); refunded = 1130
            ledger.sync_customer("cus_example")
            restored = self.client.get("/api/owner/partners").get_json()
            self.assertEqual((restored["invoices"][0]["status"], restored["invoices"][0]["commissionMinor"]), ("available", 300))
            self.assertEqual(restored["invoices"][0]["refundAllocationVersion"], 1)
            self.assertEqual(restored["balances"][0]["amountMinor"], 200)
            self.assertEqual(restored["referrals"][0]["firstPaidAt"], first)
            self.assertEqual(self.client.post("/api/owner/partners", json={**record, "reference": "reconciled-fixture"}).status_code, 200)
            self.assertEqual(len(ledger.read_state()["payouts"]), 2)

    def test_zero_trials_hold_and_exact_anniversary(self):
        i = invoice(); first = i["status_transitions"]["paid_at"]
        self.assertEqual(ledger.calculate(i, charge(), 2000, first, first)["status"], "pending")
        i["status_transitions"]["paid_at"] = ledger.anniversary(first)
        self.assertEqual(ledger.calculate(i, charge(), 2000, first, first+40000000)["commissionMinor"], 0)
        i["amount_paid"] = 0
        self.assertEqual(ledger.calculate(i, charge(), 2000, first, first)["commissionMinor"], 0)
        self.assertEqual(ledger.anniversary(1709208000), 1740744000)  # leap-day noon -> Feb 28

    def test_signed_link_first_touch_self_referrals_and_recreation(self):
        response = self.client.get("/api/partners/r/salon-coach")
        self.assertEqual(response.status_code, 302)
        self.assertIn("Secure", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        cookie = response.headers["Set-Cookie"].split(";", 1)[0]
        with self.app.test_request_context(headers={"Cookie": cookie}):
            self.assertEqual(ledger.signup_partner("member@example.com"), "salon-coach")
            self.assertEqual(ledger.signup_partner("coach+alias@example.com"), "")
        with self.app.test_request_context(headers={"Cookie": cookie + "tampered"}):
            self.assertEqual(ledger.signup_partner("member@example.com"), "")
        second = self.client.get("/api/partners/r/salon-coach")
        self.assertNotIn("Set-Cookie", second.headers)
        ledger.bind_customer("member@example.com", "cus_example", "salon-coach", "2026-01-01", False)
        ledger.bind_customer("member+again@example.com", "cus_duplicate", "salon-coach", "2026-01-01", False)
        self.assertEqual(len(ledger.read_state()["referrals"]), 1)
        with self.app.test_request_context(headers={"Cookie": cookie}):
            self.assertEqual(ledger.signup_partner("member@example.com"), "")

    def test_sync_retries_refund_clawback_and_outage_block_payout(self):
        ledger.bind_customer("member@example.com", "cus_example", "salon-coach", "2026-01-01", False)
        current_charge = charge()
        def provider(path):
            if path.startswith("invoices?"): return {"data": [invoice()], "has_more": False}
            if path.startswith("invoice_payments?"): return {"data": [{"invoice": "in_one", "livemode": False, "amount_paid": 2260, "payment": {"payment_intent": "pi_example"}}], "has_more": False}
            if path.startswith("payment_intents/"): return {"latest_charge": current_charge}
            raise AssertionError(path)
        with patch.object(ledger, "stripe_get", provider):
            ledger.sync_customer("cus_example")
            os.environ["STRIPE_PRICE_ID"] = "price_new"
            ledger.sync_customer("cus_example")
            self.assertEqual(ledger.read_state()["referrals"][0]["basePriceIds"], ["price_base", "price_new"])
            self.assertEqual(len(ledger.read_state()["invoices"]), 1)
            with ledger.state_write() as state:
                state["payouts"].append({"code": "salon-coach", "currency": "cad", "livemode": False, "amountMinor": 600})
            current_charge["amount_refunded"] = 2260
            ledger.sync_customer("cus_example")
            self.assertEqual(ledger.available(ledger.read_state(), "salon-coach", "cad", False, int(time.time())), -600)
        with patch.object(ledger, "stripe_get", side_effect=ValueError("Stripe reconciliation unavailable")):
            with self.assertRaises(ValueError): ledger.sync_customer("cus_example")
        self.assertTrue(ledger.read_state()["referrals"][0]["error"])

    def test_owner_auth_and_disabled_links(self):
        self.assertEqual(self.client.get("/api/owner/partners").status_code, 401)
        with self.client.session_transaction() as session: session["user_email"] = "member@example.com"
        self.assertEqual(self.client.post("/api/owner/partners", json={"op": "create"}).status_code, 403)
        with ledger.state_write() as state: state["partners"][0]["active"] = False
        response = self.client.get("/api/partners/r/salon-coach")
        self.assertEqual(response.headers["Location"], "https://www.retainai.ca/partners")
        self.assertNotIn("Set-Cookie", response.headers)


if __name__ == "__main__":
    unittest.main()

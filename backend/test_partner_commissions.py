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
        self.assertEqual(ledger.calculate(i, charge(refunded=1130), 2000, first, first+3000000)["commissionMinor"], 300)
        self.assertEqual(ledger.calculate(i, charge(refunded=2260), 2000, first, first+3000000)["commissionMinor"], 0)
        for mutation in ({"disputed": True}, {"customer": "cus_else"}, {"livemode": True}, {"captured": False}, {"currency": "usd"}):
            result = ledger.calculate(i, {**charge(), **mutation}, 2000, first, first+3000000)
            self.assertEqual((result["commissionMinor"], result["status"]), (0, "review"))
        i["post_payment_credit_notes_amount"] = 50
        self.assertEqual(ledger.calculate(i, charge(), 2000, first, first+3000000)["status"], "review")

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

"""Invoice webhooks only change billing for the workspace's current subscription.

Stripe does not order invoice events and retries them for days, so a late
invoice.paid for a cancelled or earlier subscription must not reactivate a
workspace, and one for the current subscription must keep working.
"""

import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch


_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402


OWNER = "owner@example.com"
OTHER = "other@example.com"


class InvoiceWebhookTests(unittest.TestCase):
    def setUp(self):
        self.users = {
            OWNER: {"email": OWNER, "status": "active", "billing_status": "active",
                    "stripe_customer_id": "cus_owner", "stripe_subscription_id": "sub_current"},
            OTHER: {"email": OTHER, "status": "active", "billing_status": "active",
                    "stripe_customer_id": "cus_other", "stripe_subscription_id": "sub_other"},
        }
        self.saved = []
        patchers = [
            patch.object(retainai, "load_users", side_effect=lambda: copy.deepcopy(self.users)),
            patch.object(retainai, "save_users", side_effect=self._save),
            patch.object(retainai, "send_email_with_template", return_value=True),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _save(self, users):
        self.saved.append(copy.deepcopy(users))
        self.users = copy.deepcopy(users)

    def _send(self, event_type, invoice, event_id="evt_1"):
        event = {"id": event_id, "type": event_type, "created": 1_800_000_000, "data": {"object": invoice}}
        with patch.object(retainai.stripe.Webhook, "construct_event", return_value=event):
            return retainai.app.test_client().post("/api/stripe/webhook", data=json.dumps(event),
                                                   headers={"stripe-signature": "t=1,v1=x"})

    def _cancel_owner(self):
        response = self._send("customer.subscription.deleted",
                              {"object": "subscription", "id": "sub_current", "customer": "cus_owner", "status": "canceled"},
                              event_id="evt_deleted")
        self.assertEqual(response.status_code, 200)
        self.assertEqual((self.users[OWNER]["status"], self.users[OWNER]["billing_status"]), ("inactive", "canceled"))

    def test_a_late_invoice_for_the_cancelled_subscription_does_not_reactivate(self):
        self._cancel_owner()
        for shape in ({"subscription": "sub_current"},
                      {"parent": {"type": "subscription_details", "subscription_details": {"subscription": "sub_current"}}}):
            with self.subTest(shape=shape):
                self.saved.clear()
                for event_type in ("invoice.paid", "invoice.payment_succeeded", "invoice.payment_failed"):
                    response = self._send(event_type, {"object": "invoice", "customer": "cus_owner", **shape},
                                          event_id=f"evt_{event_type}")
                    self.assertEqual(response.status_code, 200)
                self.assertEqual(self.saved, [])
                self.assertEqual((self.users[OWNER]["status"], self.users[OWNER]["billing_status"]), ("inactive", "canceled"))

    def test_an_invoice_for_an_earlier_or_missing_subscription_changes_nothing(self):
        self.users[OWNER]["billing_status"] = "past_due"
        for invoice in ({"subscription": "sub_earlier"}, {}):
            self._send("invoice.paid", {"object": "invoice", "customer": "cus_owner", **invoice})
            self.assertEqual(self.users[OWNER]["billing_status"], "past_due")
        self.assertEqual(self.saved, [])

    def test_an_email_match_cannot_move_another_customers_invoice_onto_this_workspace(self):
        self.users[OWNER].update(status="inactive", billing_status="canceled", stripe_subscription_id="")
        self._send("invoice.paid", {"object": "invoice", "customer": "cus_other", "customer_email": OWNER, "subscription": "sub_other"})
        self.assertEqual((self.users[OWNER]["status"], self.users[OWNER]["billing_status"]), ("inactive", "canceled"))
        self.assertEqual(self.saved, [])

    def test_the_current_subscriptions_invoices_still_update_billing(self):
        self._send("invoice.payment_failed", {"object": "invoice", "customer": "cus_owner", "subscription": "sub_current"}, "evt_failed")
        self.assertEqual(self.users[OWNER]["billing_status"], "past_due")
        self._send("invoice.paid", {"object": "invoice", "customer": "cus_owner",
                                    "parent": {"subscription_details": {"subscription": {"id": "sub_current"}}}}, "evt_paid")
        self.assertEqual((self.users[OWNER]["status"], self.users[OWNER]["billing_status"]), ("active", "active"))

    def test_resubscribing_after_cancellation_reactivates_through_checkout(self):
        self._cancel_owner()
        # The new subscription's first invoice can arrive before checkout completes.
        self._send("invoice.paid", {"object": "invoice", "customer": "cus_owner", "subscription": "sub_new"}, "evt_early")
        self.assertEqual(self.users[OWNER]["status"], "inactive")
        self.users[OWNER]["trial_eligible"] = False
        self._send("checkout.session.completed", {"object": "checkout.session", "id": "cs_new", "customer": "cus_owner",
                                                  "subscription": "sub_new", "metadata": {"user_email": OWNER}}, "evt_checkout")
        self.assertEqual((self.users[OWNER]["status"], self.users[OWNER]["billing_status"]), ("active", "active"))
        self._send("invoice.paid", {"object": "invoice", "customer": "cus_owner", "subscription": "sub_new"}, "evt_renewal")
        self.assertEqual(self.users[OWNER]["stripe_subscription_id"], "sub_new")


if __name__ == "__main__":
    unittest.main()

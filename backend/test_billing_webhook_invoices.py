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

    def test_stripe_ids_beat_an_edited_billing_email(self):
        # The other customer's billing email was changed to this account's email.
        self.users[OWNER].update(status="inactive", billing_status="canceled", stripe_subscription_id="")
        for shape in ({"subscription": "sub_other"},
                      {"parent": {"subscription_details": {"subscription": "sub_other"}}}):
            with self.subTest(shape=shape):
                self.users[OTHER]["billing_status"] = "active"
                self._send("invoice.payment_failed", {"object": "invoice", "customer": "cus_other", "customer_email": OWNER, **shape},
                           event_id=f"evt_failed_{len(shape)}_{list(shape)[0]}")
                self.assertEqual(self.users[OTHER]["billing_status"], "past_due", "the real customer must be updated")
                self.assertEqual((self.users[OWNER]["status"], self.users[OWNER]["billing_status"]), ("inactive", "canceled"))
        self._send("invoice.paid", {"object": "invoice", "customer": "cus_other", "customer_email": OWNER, "subscription": "sub_other"}, "evt_paid")
        self.assertEqual(self.users[OTHER]["billing_status"], "active")
        self.assertEqual((self.users[OWNER]["status"], self.users[OWNER]["billing_status"]), ("inactive", "canceled"))

    def test_subscription_events_also_match_by_id_before_email(self):
        self._send("customer.subscription.updated", {"object": "subscription", "id": "sub_other", "customer": "cus_other",
                                                     "status": "past_due", "customer_email": OWNER, "items": {"data": []}}, "evt_sub")
        self.assertEqual(self.users[OTHER]["billing_status"], "past_due")
        self.assertEqual(self.users[OWNER]["billing_status"], "active")

    def test_checkout_trusts_the_metadata_retainai_set_over_the_entered_email(self):
        self.users[OWNER].update(status="inactive", billing_status="canceled", stripe_subscription_id="", trial_eligible=False)
        self._send("checkout.session.completed", {"object": "checkout.session", "id": "cs_1", "customer": "cus_owner", "subscription": "sub_new",
                                                  "customer_details": {"email": OTHER}, "metadata": {"user_email": OWNER}}, "evt_checkout")
        self.assertEqual((self.users[OWNER]["status"], self.users[OWNER]["billing_status"], self.users[OWNER]["stripe_subscription_id"]),
                         ("active", "active", "sub_new"))
        self.assertEqual(self.users[OTHER]["stripe_subscription_id"], "sub_other")

    def test_an_email_is_still_the_fallback_when_no_stored_id_matches(self):
        self.users[OWNER].update(stripe_customer_id="", stripe_subscription_id="")
        self._send("customer.subscription.updated", {"object": "subscription", "id": "sub_first", "customer": "cus_first",
                                                     "status": "active", "metadata": {"user_email": OWNER}, "items": {"data": []}}, "evt_first")
        self.assertEqual((self.users[OWNER]["stripe_subscription_id"], self.users[OWNER]["stripe_customer_id"]), ("sub_first", "cus_first"))

    def test_a_delayed_update_for_a_replaced_subscription_cannot_take_over(self):
        # sub_current replaced an earlier subscription; its late updates are ignored.
        for status in ("canceled", "past_due", "active"):
            with self.subTest(status=status):
                self._send("customer.subscription.updated", {"object": "subscription", "id": "sub_replaced", "customer": "cus_owner",
                                                             "status": status, "items": {"data": []}}, f"evt_old_{status}")
                self.assertEqual((self.users[OWNER]["stripe_subscription_id"], self.users[OWNER]["status"], self.users[OWNER]["billing_status"]),
                                 ("sub_current", "active", "active"))
        # Its later deletion stays ignored because it is not the current subscription.
        self._send("customer.subscription.deleted", {"object": "subscription", "id": "sub_replaced", "customer": "cus_owner", "status": "canceled"}, "evt_old_deleted")
        self.assertEqual((self.users[OWNER]["status"], self.users[OWNER]["billing_status"]), ("active", "active"))

    def test_a_live_subscription_is_adopted_when_the_workspace_has_no_live_billing(self):
        self.users[OWNER].update(status="inactive", billing_status="canceled")
        self._send("customer.subscription.updated", {"object": "subscription", "id": "sub_live", "customer": "cus_owner",
                                                     "status": "active", "items": {"data": []}}, "evt_live")
        self.assertEqual((self.users[OWNER]["stripe_subscription_id"], self.users[OWNER]["status"], self.users[OWNER]["billing_status"]),
                         ("sub_live", "active", "active"))

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

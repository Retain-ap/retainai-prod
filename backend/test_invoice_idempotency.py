"""Retrying an invoice submission must never create or send a second invoice."""

import os
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402

ORIGIN = {"Origin": "http://localhost:3000"}
BODY = {"customer_name": "Ana", "customer_email": "ana@example.com", "description": "Cut", "amount": 80,
        "currency": "cad", "quantity": 1, "idempotency_key": "retry-key-0001"}


def fake_invoice():
    return SimpleNamespace(id="in_1", currency="cad", amount_due=8000, total=8000, amount_paid=0, status="open",
                           customer_email="ana@example.com", hosted_invoice_url="https://example.test/i", due_date=None,
                           number="N-1", metadata={"customer_name": "Ana"}, customer=None)


class InvoiceIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        users = {self.owner: {"email": self.owner, "role": "owner", "status": "active", "security_version": 0,
                              "stripe_account_id": "acct_owner"}}
        patcher = patch.object(retainai, "load_users", return_value=users)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.stripe = {
            "customer_list": patch.object(retainai.stripe.Customer, "list", return_value=SimpleNamespace(data=[])),
            "customer_create": patch.object(retainai.stripe.Customer, "create", return_value=SimpleNamespace(id="cus_1")),
            "invoice_create": patch.object(retainai.stripe.Invoice, "create", return_value=fake_invoice()),
            "item_create": patch.object(retainai.stripe.InvoiceItem, "create", return_value=SimpleNamespace(id="ii_1")),
            "finalize": patch.object(retainai.stripe.Invoice, "finalize_invoice", return_value=fake_invoice()),
            "send": patch.object(retainai.stripe.Invoice, "send_invoice", return_value=fake_invoice()),
            "invoice_list": patch.object(retainai.stripe.Invoice, "list", return_value=SimpleNamespace(data=[])),
        }
        self.mocks = {name: p.start() for name, p in self.stripe.items()}
        for p in self.stripe.values():
            self.addCleanup(p.stop)

    def client(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = self.owner
            signed["org_email"] = self.owner
            signed["security_version"] = 0
        return client

    def keys(self, name):
        return [call.kwargs.get("idempotency_key") for call in self.mocks[name].call_args_list]

    def test_every_creating_step_carries_a_stable_key_scoped_to_the_submission(self):
        outcomes = iter([RuntimeError("network")])

        def send(*args, **kwargs):
            failure = next(outcomes, None)
            if failure:
                raise failure
            return fake_invoice()

        self.mocks["send"].side_effect = send
        first = self.client().post("/api/stripe/invoice", json=BODY, headers=ORIGIN)
        self.assertEqual(first.status_code, 500)
        self.assertIn("Trying again is safe", first.get_json()["error"])
        self.assertNotIn("network", first.get_json()["error"])
        retry = self.client().post("/api/stripe/invoice", json=BODY, headers=ORIGIN)
        self.assertEqual(retry.status_code, 200)
        for name, step in (("customer_create", "customer"), ("invoice_create", "invoice"), ("item_create", "item"),
                           ("finalize", "finalize"), ("send", "send")):
            keys = self.keys(name)
            self.assertEqual(len(set(keys)), 1, name)  # the retry reused exactly the same Stripe key
            self.assertTrue(keys[0].startswith("ra-inv-") and keys[0].endswith(f"-{step}"), keys[0])
            self.assertNotIn(self.owner, keys[0])
        other = self.client().post("/api/stripe/invoice", json={**BODY, "idempotency_key": "another-key-02"}, headers=ORIGIN)
        self.assertEqual(other.status_code, 200)
        self.assertNotEqual(self.keys("invoice_create")[-1], self.keys("invoice_create")[0])

    def test_requests_without_a_key_still_work_and_bad_keys_are_rejected(self):
        legacy = {k: v for k, v in BODY.items() if k != "idempotency_key"}
        self.assertEqual(self.client().post("/api/stripe/invoice", json=legacy, headers=ORIGIN).status_code, 200)
        self.assertIsNone(self.mocks["invoice_create"].call_args.kwargs.get("idempotency_key"))
        bad = self.client().post("/api/stripe/invoice", json={**BODY, "idempotency_key": "x y"}, headers=ORIGIN)
        self.assertEqual(bad.status_code, 400)

    def test_stripe_errors_show_stripes_own_message_but_never_python_internals(self):
        self.mocks["invoice_create"].side_effect = retainai.stripe.error.InvalidRequestError(
            "Currency xyz is not supported.", param="currency"
        )
        response = self.client().post("/api/stripe/invoice", json=BODY, headers=ORIGIN)
        self.assertEqual((response.status_code, response.get_json()["error"]), (502, "Currency xyz is not supported."))
        self.mocks["invoice_create"].side_effect = KeyError("secret_internal_field")
        response = self.client().post("/api/stripe/invoice", json=BODY, headers=ORIGIN)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret_internal_field", response.get_json()["error"])

if __name__ == "__main__":
    unittest.main()

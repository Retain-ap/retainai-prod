"""Workspace deletion and export cover the Value Receipt, Square and Calendly stores."""

import json
import os
import tempfile
import unittest
import uuid

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app  # noqa: E402,F401  (registers blueprints)
import app_account  # noqa: E402
import app_value  # noqa: E402
import storage  # noqa: E402
from unittest.mock import patch  # noqa: E402

ORIGIN = {"Origin": "http://localhost:3000"}


class WorkspaceLifecycleTests(unittest.TestCase):
    """Deleting or exporting a workspace covers the new stores without leaking another's."""

    def setUp(self):
        self.a, self.b = f"a-{uuid.uuid4().hex[:6]}@example.com", f"b-{uuid.uuid4().hex[:6]}@example.com"
        self.files = {
            "revenue_evidence.json": {self.a: {"records": {"manual:k": {"id": "manual:k", "amount_minor": 100}}}, self.b: {"records": {"manual:j": {"id": "manual:j"}}}},
            "followup_log.json": {self.a: [{"id": "f1", "lead_id": "x"}], self.b: [{"id": "f2"}]},
            "square_connections.json": {self.a: {"merchant_id": "M-A", "access_token_enc": "gAAAA-secret", "refresh_token_enc": "gAAAA-r", "connected_at": "2026-11-01"},
                                        self.b: {"merchant_id": "M-B", "access_token_enc": "gAAAA-b"}},
            "calendly_connections.json": {self.a: {"user_uri": "https://api.calendly.com/users/A", "access_token_enc": "gAAAA-cal", "refresh_token_enc": "gAAAA-cr", "connected_at": "2026-11-05"},
                                          self.b: {"user_uri": "https://api.calendly.com/users/B", "access_token_enc": "gAAAA-cb"}},
        }
        for name, value in self.files.items():
            with open(os.path.join(storage.DATA_ROOT, name), "w") as handle:
                json.dump(value, handle)

    def read(self, name):
        with open(os.path.join(storage.DATA_ROOT, name)) as handle:
            return json.load(handle)

    def test_purge_removes_only_the_deleted_workspace_from_every_new_store(self):
        app_account._purge_workspace_json(self.a)
        for name in self.files:
            data = self.read(name)
            self.assertNotIn(self.a, data, name)
            self.assertIn(self.b, data, name)

    def test_export_includes_payments_follow_ups_and_bookings_without_tokens(self):
        records = app_account._workspace_records(self.a)
        self.assertEqual([row["id"] for row in records["payments"]], ["manual:k"])
        self.assertEqual(records["follow_ups"], [{"id": "f1", "lead_id": "x"}])
        self.assertEqual(records["square"], {"merchant_id": "M-A", "connected_at": "2026-11-01"})
        self.assertEqual(records["calendly"], {"user_uri": "https://api.calendly.com/users/A", "connected_at": "2026-11-05"})
        self.assertNotIn("gAAAA", json.dumps(records))
        self.assertNotIn("manual:j", json.dumps(records))

class StaleWriterTests(unittest.TestCase):
    """A request authenticated before the workspace was deleted must not write
    it back once deletion has finished (purge removes the users first)."""

    def setUp(self):
        for name in ("revenue_evidence.json", "followup_log.json"):
            path = os.path.join(storage.DATA_ROOT, name)
            if os.path.exists(path):
                os.remove(path)
        self.owner = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        self.users = {self.owner: {"email": self.owner, "role": "owner", "org_id": self.owner, "status": "active",
                                   "security_version": 0, "stripe_account_id": "acct_test", "terms_accepted_at": "2026-11-01T00:00:00+00:00"}}
        patcher = patch.object(app, "load_users", side_effect=lambda: self.users)
        patcher.start()
        self.addCleanup(patcher.stop)
        storage.save_user_leads(self.owner, [{"id": "ana", "name": "Ana", "email": "ana@example.com"}])
        self.client = app.app.test_client()
        with self.client.session_transaction() as signed:
            signed["user_email"] = signed["org_email"] = self.owner
            signed["security_version"] = 0

    def delete_workspace(self, *_args, **_kwargs):
        if self.owner in self.users:
            self.users.pop(self.owner)
            app_account._purge_workspace_json(self.owner)

    def stored(self, name):
        path = os.path.join(storage.DATA_ROOT, name)
        if not os.path.exists(path):
            return {}
        with open(path) as handle:
            return json.load(handle)

    def payment(self):
        return {"lead_id": "ana", "amount": "95.00", "currency": "CAD", "paid_at": "2026-11-01", "idempotency_key": uuid.uuid4().hex}

    def test_a_manual_payment_saved_after_deletion_is_refused(self):
        real = app.load_appointments

        def deleting_load():
            self.delete_workspace()  # deletion finishes between authentication and the write
            return real()

        with patch.object(app, "load_appointments", side_effect=deleting_load):
            response = self.client.post("/api/value-receipt/payments", json=self.payment(), headers=ORIGIN)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(self.owner, self.stored("revenue_evidence.json"))

    def test_a_stripe_sync_finishing_after_deletion_is_refused(self):
        class Listing:
            def auto_paging_iter(self):
                return iter([])

        def deleting_list(**_kwargs):
            self.delete_workspace()
            return Listing()

        with patch.object(app.stripe.Invoice, "list", side_effect=deleting_list):
            response = self.client.post("/api/value-receipt/sync", headers=ORIGIN)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(self.owner, self.stored("revenue_evidence.json"))

    def test_refund_and_delete_after_deletion_are_refused(self):
        record = self.client.post("/api/value-receipt/payments", json=self.payment(), headers=ORIGIN).get_json()["record"]
        ctx_holder = {}
        real = app_value._owner_context

        def stale_context():
            ctx, error = real()
            ctx_holder["ctx"] = ctx
            self.delete_workspace()
            return ctx, error

        with patch.object(app_value, "_owner_context", side_effect=stale_context):
            refund = self.client.post(f"/api/value-receipt/payments/{record['id']}/refund", json={"refunded_amount": "10"}, headers=ORIGIN)
            self.assertEqual(refund.status_code, 401)
        self.users[self.owner] = dict(ctx_holder["ctx"]["owner"])  # restore only to re-run the second check
        with patch.object(app_value, "_owner_context", side_effect=stale_context):
            removed = self.client.delete(f"/api/value-receipt/payments/{record['id']}", headers=ORIGIN)
        self.assertEqual(removed.status_code, 401)
        self.assertNotIn(self.owner, self.stored("revenue_evidence.json"))

    def test_a_follow_up_recorded_after_deletion_is_dropped(self):
        self.assertIsNotNone(app_value.record_followup(self.owner, lead_id="ana", channel="email", source="test"))
        self.delete_workspace()
        self.assertIsNone(app_value.record_followup(self.owner, lead_id="ana", channel="email", source="test"))
        self.assertNotIn(self.owner, self.stored("followup_log.json"))

    def test_a_writer_from_a_deleted_account_cannot_write_into_a_recreated_one(self):
        real = app.load_appointments

        def recreate(*_args):
            if self.users[self.owner]["terms_accepted_at"].startswith("2026-11-01"):
                self.delete_workspace()
                self.users[self.owner] = {"email": self.owner, "role": "owner", "org_id": self.owner, "status": "active",
                                          "security_version": 0, "terms_accepted_at": "2026-11-07T00:00:00+00:00"}
            return real()

        with patch.object(app, "load_appointments", side_effect=recreate):
            response = self.client.post("/api/value-receipt/payments", json=self.payment(), headers=ORIGIN)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(self.owner, self.stored("revenue_evidence.json"))


if __name__ == "__main__":
    unittest.main()

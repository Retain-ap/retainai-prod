"""Workspace deletion and export cover the Value Receipt and Square stores."""

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
import storage  # noqa: E402


class WorkspaceLifecycleTests(unittest.TestCase):
    """Deleting or exporting a workspace covers the new stores without leaking another's."""

    def setUp(self):
        self.a, self.b = f"a-{uuid.uuid4().hex[:6]}@example.com", f"b-{uuid.uuid4().hex[:6]}@example.com"
        self.files = {
            "revenue_evidence.json": {self.a: {"records": {"manual:k": {"id": "manual:k", "amount_minor": 100}}}, self.b: {"records": {"manual:j": {"id": "manual:j"}}}},
            "followup_log.json": {self.a: [{"id": "f1", "lead_id": "x"}], self.b: [{"id": "f2"}]},
            "square_connections.json": {self.a: {"merchant_id": "M-A", "access_token_enc": "gAAAA-secret", "refresh_token_enc": "gAAAA-r", "connected_at": "2026-11-01"},
                                        self.b: {"merchant_id": "M-B", "access_token_enc": "gAAAA-b"}},
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

    def test_export_includes_payments_follow_ups_and_square_without_tokens(self):
        records = app_account._workspace_records(self.a)
        self.assertEqual([row["id"] for row in records["payments"]], ["manual:k"])
        self.assertEqual(records["follow_ups"], [{"id": "f1", "lead_id": "x"}])
        self.assertEqual(records["square"], {"merchant_id": "M-A", "connected_at": "2026-11-01"})
        self.assertNotIn("gAAAA", json.dumps(records))
        self.assertNotIn("manual:j", json.dumps(records))



if __name__ == "__main__":
    unittest.main()

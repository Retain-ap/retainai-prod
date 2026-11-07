"""The optional salon/barber setup preset: owner-set, validated, general by default."""

import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402

ORIGIN = {"Origin": "http://localhost:3000"}


class SetupPresetTests(unittest.TestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        self.member = f"member-{uuid.uuid4().hex[:8]}@example.com"
        self.users = {
            self.owner: {"email": self.owner, "role": "owner", "org_id": self.owner, "status": "active",
                         "billing_status": "active", "security_version": 0, "businessType": "Hair salon"},
            self.member: {"email": self.member, "role": "member", "org_id": self.owner, "status": "active", "security_version": 0},
            f"user::{self.member}": {"email": self.member, "role": "member", "org_id": self.owner, "security_version": 0},
        }
        patchers = [
            patch.object(retainai, "load_users", side_effect=lambda: self.users),
            patch.object(retainai, "save_users", side_effect=lambda users: self.users.update(users)),
            patch.object(retainai, "_org_is_active", return_value=True),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def client(self, email):
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = email
            signed["org_email"] = self.owner
            signed["security_version"] = 0
        return client

    def test_general_is_the_default_for_every_workspace(self):
        self.assertEqual(self.client(self.owner).get("/api/profile").get_json()["setup_preset"], "general")
        self.users[self.owner]["setup_preset"] = "something-else"
        self.assertEqual(self.client(self.owner).get("/api/profile").get_json()["setup_preset"], "general")
        self.assertEqual(retainai._user_payload(self.owner, self.users[self.owner])["setup_preset"], "general")

    def test_owner_can_choose_the_salon_preset_and_switch_back(self):
        owner = self.client(self.owner)
        saved = owner.post("/api/profile", json={"setup_preset": "salon_barber"}, headers=ORIGIN)
        self.assertEqual((saved.status_code, saved.get_json()["setup_preset"]), (200, "salon_barber"))
        self.assertEqual(self.users[self.owner]["setup_preset"], "salon_barber")
        self.assertEqual(self.users[self.owner]["businessType"], "Hair salon")  # nothing else changed
        self.assertEqual(self.client(self.member).get("/api/profile").get_json()["setup_preset"], "salon_barber")
        owner.post("/api/profile", json={"setup_preset": "general"}, headers=ORIGIN)
        self.assertEqual(self.users[self.owner]["setup_preset"], "general")

    def test_unknown_presets_are_rejected_and_members_cannot_change_it(self):
        bad = self.client(self.owner).post("/api/profile", json={"setup_preset": "dentist"}, headers=ORIGIN)
        self.assertEqual(bad.status_code, 400)
        self.client(self.member).post("/api/profile", json={"setup_preset": "salon_barber"}, headers=ORIGIN)
        self.assertNotEqual(self.users[self.owner].get("setup_preset"), "salon_barber")


if __name__ == "__main__":
    unittest.main()

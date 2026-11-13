"""A manual follow-up that was actually sent is recorded on the contact.

The rebooking list uses the contact time to stop showing a customer the owner
has just followed up with. Nothing here sends automatically: only a successful
owner-initiated send (or the owner marking the contact) records it.
"""

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


class ContactRecordingTests(unittest.TestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        self.users = {self.owner: {"email": self.owner, "role": "owner", "org_id": self.owner, "status": "active",
                                   "security_version": 0, "name": "Morgan", "business": "North Star Studio"}}
        patchers = [patch.object(retainai, "load_users", side_effect=lambda: self.users),
                    patch.object(retainai, "SG_TEMPLATE_FOLLOWUP_LEAD", "template-followup"),
                    patch.object(retainai, "add_notification"),
                    patch.object(retainai, "record_followup")]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.old = "2026-09-01T10:00:00Z"
        retainai.save_user_leads(self.owner, [
            {"id": "due", "name": "Ava Example", "email": "ava@example.com", "last_contacted": self.old, "status": "cold"},
            {"id": "opted-out", "name": "Ben Sample", "email": "ben@example.com", "email_opt_out": True, "last_contacted": self.old},
            {"id": "other", "name": "Cam Other", "email": "cam@example.com", "last_contacted": self.old},
        ])
        self.client = retainai.app.test_client()
        with self.client.session_transaction() as signed:
            signed["user_email"] = signed["org_email"] = self.owner
            signed["security_version"] = 0

    def _lead(self, lead_id):
        return next(lead for lead in retainai.load_user_leads(self.owner) if lead["id"] == lead_id)

    def _send(self, lead_id, delivered=True):
        with patch.object(retainai, "send_email_with_template", return_value=delivered) as send:
            response = self.client.post("/api/send-ai-message", json={"leadId": lead_id, "message": "Time to rebook?", "promptType": "followup"}, headers=ORIGIN)
        return response, send

    def test_a_delivered_follow_up_records_the_contact_on_that_customer_only(self):
        response, send = self._send("due")
        self.assertEqual(response.status_code, 200, response.get_json())
        send.assert_called_once()
        lead = self._lead("due")
        self.assertGreater(lead["last_contacted"], self.old)
        self.assertEqual(lead["last_activity_at"], lead["last_contacted"])
        self.assertEqual(lead["last_outreach_at"], lead["last_contacted"])
        self.assertEqual(lead["status"], "active")
        self.assertEqual(self._lead("other")["last_contacted"], self.old)

    def test_a_failed_send_records_nothing(self):
        response, _ = self._send("due", delivered=False)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self._lead("due")["last_contacted"], self.old)
        self.assertNotIn("last_outreach_at", self._lead("due"))

    def test_an_unsubscribed_customer_is_not_emailed_or_marked(self):
        response, send = self._send("opted-out")
        self.assertEqual(response.status_code, 403)
        send.assert_not_called()
        self.assertEqual(self._lead("opted-out")["last_contacted"], self.old)

    def test_marking_contacted_by_hand_uses_the_same_fields(self):
        response = self.client.post("/api/leads/contacted", json={"leadId": "due"}, headers=ORIGIN)
        self.assertEqual(response.status_code, 200)
        lead = self._lead("due")
        self.assertGreater(lead["last_contacted"], self.old)
        self.assertEqual((lead["last_activity_at"], lead["last_outreach_at"], lead["status"]), (lead["last_contacted"], lead["last_contacted"], "active"))
        self.assertEqual(self.client.post("/api/leads/contacted", json={"leadId": "missing"}, headers=ORIGIN).status_code, 404)


if __name__ == "__main__":
    unittest.main()

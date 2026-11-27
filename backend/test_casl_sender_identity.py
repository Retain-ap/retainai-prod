"""Canada's anti-spam law (CASL): every customer email names the business, gives its mailing
address and a contact, and offers an unsubscribe link. Sends wait until the address is set."""

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


def _owner(**extra):
    return {"email": OWNER, "org_id": OWNER, "role": "owner", "status": "active", "security_version": 0,
            "name": "Morgan", "business": "North Star Studio", **extra}


def _client():
    client = retainai.app.test_client()
    with client.session_transaction() as signed:
        signed["user_email"] = OWNER
        signed["org_email"] = OWNER
        signed["security_version"] = 0
    return client


class SenderIdentityTests(unittest.TestCase):
    def test_footer_names_the_business_its_address_contact_and_unsubscribe(self):
        body = retainai._append_unsubscribe_footer(
            "<html><body><p>Hi</p></body></html>", "https://api.example/unsub?t=1", "North <Star>",
            "12 Main St, Toronto ON M5V 1A1", "hello@northstar.example")
        footer = body[body.index("You received"):]
        self.assertIn("North &lt;Star&gt;, 12 Main St, Toronto ON M5V 1A1.", footer)
        self.assertIn("Contact: hello@northstar.example.", footer)
        self.assertIn('href="https://api.example/unsub?t=1"', footer)
        self.assertLess(body.index("You received"), body.index("</body>"))

    def test_sender_details_trim_bound_and_fall_back_to_the_workspace_email(self):
        details = retainai._workspace_sender_details({"mailingAddress": "  12  Main St\n Toronto ", "businessContact": ""}, OWNER)
        self.assertEqual(details, {"address": "12 Main St Toronto", "contact": OWNER})
        self.assertEqual(retainai._workspace_sender_details({"mailingAddress": "x" * 400}, OWNER)["address"], "x" * 300)
        self.assertEqual(retainai._workspace_sender_details(None, OWNER), {"address": "", "contact": OWNER})

    def test_profile_saves_and_returns_address_and_contact_with_limits(self):
        users = {OWNER: _owner()}
        with patch.object(retainai, "load_users", return_value=users), patch.object(retainai, "save_users") as save:
            client = _client()
            ok = client.post("/api/profile", json={"mailingAddress": " 12 Main St,\n Toronto ON ", "businessContact": "416-555-0100"})
            self.assertEqual(ok.status_code, 200, ok.get_data(as_text=True))
            self.assertEqual(users[OWNER]["mailingAddress"], "12 Main St, Toronto ON")
            self.assertEqual(users[OWNER]["businessContact"], "416-555-0100")
            self.assertTrue(save.called)
            self.assertEqual(client.get("/api/profile").get_json()["mailingAddress"], "12 Main St, Toronto ON")
            too_long = client.post("/api/profile", json={"mailingAddress": "x" * 301})
            self.assertEqual(too_long.status_code, 400)

    def test_ai_send_waits_for_a_mailing_address_and_then_includes_it(self):
        lead = {"id": "lead-1", "name": "Jordan Lee", "email": "jordan@example.com"}
        request = {"leadId": "lead-1", "message": "Just checking in.", "promptType": "followup"}
        with patch.object(retainai, "load_users", return_value={OWNER: _owner()}), \
                patch.object(retainai, "load_leads", return_value={OWNER: [lead]}), \
                patch.object(retainai, "send_email_with_template", return_value=True) as send:
            blocked = _client().post("/api/send-ai-message", json=request)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.get_json()["code"], "business_profile_required")
        self.assertIn("mailing address", blocked.get_json()["error"])
        send.assert_not_called()

        users = {OWNER: _owner(mailingAddress="12 Main St, Toronto ON M5V 1A1")}
        with patch.object(retainai, "load_users", return_value=users), \
                patch.object(retainai, "load_leads", return_value={OWNER: [lead]}), \
                patch.object(retainai, "SG_TEMPLATE_FOLLOWUP_LEAD", "template-followup"), \
                patch.object(retainai, "send_email_with_template", return_value=True) as send:
            sent = _client().post("/api/send-ai-message", json=request)
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))
        data = send.call_args.kwargs["dynamic_data"]
        self.assertEqual(data["business_address"], "12 Main St, Toronto ON M5V 1A1")
        self.assertEqual(data["business_contact"], OWNER)

    def test_birthday_email_carries_the_sender_details(self):
        with patch.object(retainai, "send_email_with_template", return_value=True) as send:
            retainai.send_birthday_email("jordan@example.com", "Jordan", "North Star Studio", "https://u",
                                         business_address="12 Main St", business_contact="416-555-0100")
        data = send.call_args.kwargs["dynamic_data"]
        self.assertEqual((data["business_address"], data["business_contact"]), ("12 Main St", "416-555-0100"))


if __name__ == "__main__":
    unittest.main()

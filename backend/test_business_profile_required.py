"""Customer drafts and manual sends need the owner's real business name.

Signup no longer asks for business details, so a workspace can exist without a
name. These tests prove the four customer-message endpoints answer
409 business_profile_required before any AI or email provider is called, that
no placeholder business is invented, and that configured workspaces and the
automation blocker behave as before.
"""

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
LEAD = {"id": "lead-1", "name": "Jordan Lee", "email": "jordan@example.com", "notes": "Asked about Tuesday."}
REQUESTS = {
    "generate-message": ("/api/generate-message", {"lead": {"id": "lead-1"}}),
    "generate_prompt": ("/api/generate_prompt", {"leadId": "lead-1", "promptType": "followup"}),
    "ai-prompt": ("/api/ai-prompt", {"lead_id": "lead-1"}),
    "send-ai-message": ("/api/send-ai-message", {"leadId": "lead-1", "message": "Just checking in.", "promptType": "followup"}),
}
# Profiles a shortened signup can leave behind. A business type is not a name.
UNNAMED_PROFILES = {
    "missing": {},
    "empty": {"businessName": "", "business": ""},
    "whitespace": {"businessName": "   ", "business": "\t \n"},
    "type only": {"businessType": "Salon", "lineOfBusiness": "Salon"},
}


def _owner(**profile):
    return {"email": OWNER, "org_id": OWNER, "role": "owner", "status": "active",
            "security_version": 0, "name": "Morgan", **profile}


class BusinessProfileRequiredTests(unittest.TestCase):
    def _post(self, user, name):
        path, body = REQUESTS[name]
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = signed["org_email"] = OWNER
            signed["security_version"] = 0
        complete = patch.object(retainai, "_complete_openrouter_prompt",
                                return_value=(True, "Hi Jordan, happy to help.", {"model": "test"}))
        with patch.object(retainai, "OPENROUTER_API_KEY", "test-key"), \
                patch.object(retainai, "SG_TEMPLATE_FOLLOWUP_LEAD", "template-followup"), \
                patch.object(retainai, "load_users", side_effect=lambda: {OWNER: user}), \
                patch.object(retainai, "load_leads", side_effect=lambda: {OWNER: [dict(LEAD)]}), \
                patch.object(retainai, "load_chats", side_effect=lambda: {}), \
                patch.object(retainai, "save_leads"), \
                complete as ai, \
                patch.object(retainai.pyrequests, "post") as raw_http, \
                patch.object(retainai, "send_email_with_template", return_value=True) as send_email:
            response = client.post(path, json=body)
        return response, ai, raw_http, send_email

    def test_unnamed_workspace_gets_409_before_any_provider_call(self):
        for label, profile in UNNAMED_PROFILES.items():
            for name in REQUESTS:
                with self.subTest(profile=label, endpoint=name):
                    response, ai, raw_http, send_email = self._post(_owner(**profile), name)
                    self.assertEqual(response.status_code, 409)
                    body = response.get_json()
                    self.assertEqual(body["code"], "business_profile_required")
                    self.assertEqual(body["settings_path"], "/app?tab=profile")
                    self.assertIn("business name in Settings", body["error"])
                    ai.assert_not_called()
                    raw_http.assert_not_called()
                    send_email.assert_not_called()

    def test_manual_send_keeps_its_ok_false_shape(self):
        response, *_ = self._post(_owner(), "send-ai-message")
        self.assertIs(response.get_json()["ok"], False)

    def test_forged_business_in_the_request_does_not_satisfy_the_check(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = signed["org_email"] = OWNER
            signed["security_version"] = 0
        with patch.object(retainai, "load_users", side_effect=lambda: {OWNER: _owner()}), \
                patch.object(retainai, "load_leads", side_effect=lambda: {OWNER: [dict(LEAD)]}), \
                patch.object(retainai, "load_chats", side_effect=lambda: {}), \
                patch.object(retainai, "send_email_with_template") as send_email:
            send = client.post("/api/send-ai-message", json={**REQUESTS["send-ai-message"][1], "businessName": "Forged"})
            draft = client.post("/api/generate-message", json={"lead": {"id": "lead-1"}, "user_business": "Forged"})
        self.assertEqual((send.status_code, draft.status_code), (409, 409))
        send_email.assert_not_called()

    def test_named_workspace_still_drafts_and_sends_with_its_real_name(self):
        for field in ("businessName", "business"):
            user = _owner(**{field: "  North Star Studio  "})
            for name in REQUESTS:
                with self.subTest(field=field, endpoint=name):
                    response, ai, raw_http, send_email = self._post(user, name)
                    self.assertEqual(response.status_code, 200, response.get_json())
                    raw_http.assert_not_called()
                    if name == "send-ai-message":
                        ai.assert_not_called()
                        send_email.assert_called_once()
                        self.assertEqual(send_email.call_args.kwargs["dynamic_data"]["business_name"], "North Star Studio")
                    else:
                        ai.assert_called_once()
                        send_email.assert_not_called()
                        prompt = "\n".join(str(m.get("content")) for m in ai.call_args.args[0])
                        self.assertIn("North Star Studio", prompt)
                        self.assertNotIn("this business", prompt)
                        self.assertNotIn("Your Business", prompt)

    def test_automations_without_a_name_keep_their_fixed_fallback_and_blocker(self):
        # Unchanged: no AI call, and templates that name the business carry the
        # missing-value marker that stops an unattended send.
        for trigger, names_business in (("new_lead", True), ("appointment_completed", True), ("no_reply", False)):
            with self.subTest(trigger=trigger), patch.object(retainai, "OPENROUTER_API_KEY", "test-key"), \
                    patch.object(retainai, "_complete_openrouter_prompt") as ai:
                draft = retainai.ai_draft_message({"business_name": "  ", "booking_link": "https://book.example/owner",
                                                   "lead": {"name": "Jordan"}, "flow": {"trigger": {"type": trigger}}})
                ai.assert_not_called()
                self.assertEqual(retainai.contains_blockers(draft), names_business)
                self.assertNotIn("Your Business", draft)
                self.assertNotIn("this business", draft)


if __name__ == "__main__":
    unittest.main()

"""Regression tests for signup consent and customer email opt-outs."""

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


class EmailConsentTests(unittest.TestCase):
    owner = "owner@example.com"

    @staticmethod
    def _active_user(email):
        return {
            "email": email,
            "org_id": email,
            "role": "owner",
            "status": "active",
            "security_version": 0,
            "name": "Morgan",
            "business": "North Star Studio",
        }

    def _signed_client(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = self.owner
            signed_session["org_email"] = self.owner
            signed_session["security_version"] = 0
        return client

    def test_unsubscribe_get_requires_confirmation_and_post_records_withdrawal(self):
        lead = {"id": "lead-1", "email": "jordan@example.com"}
        rows = [lead]
        token = retainai._email_unsubscribe_token(self.owner, lead["id"], lead["email"])
        client = retainai.app.test_client()

        with patch.object(retainai, "load_leads", return_value={self.owner: rows}), patch.object(
            retainai, "save_user_leads"
        ) as save:
            preview = client.get("/api/email/unsubscribe", query_string={"token": token})
            self.assertEqual(preview.status_code, 200)
            self.assertIn(b"Confirm unsubscribe", preview.data)
            save.assert_not_called()

            response = client.post("/api/email/unsubscribe", data={"token": token})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(lead["email_opt_out"])
        self.assertEqual(lead["email_consent_status"], "withdrawn")
        save.assert_called_once_with(self.owner, rows)

    def test_ai_email_is_blocked_after_customer_unsubscribes(self):
        client = self._signed_client()
        lead = {
            "id": "lead-1",
            "name": "Jordan Lee",
            "email": "jordan@example.com",
            "email_opt_out": True,
        }
        with patch.object(
            retainai, "load_users", return_value={self.owner: self._active_user(self.owner)}
        ), patch.object(
            retainai, "load_leads", return_value={self.owner: [lead]}
        ), patch.object(retainai, "send_email_with_template") as send:
            response = client.post(
                "/api/send-ai-message",
                json={"leadId": "lead-1", "message": "Just checking in."},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "email_opt_out")
        send.assert_not_called()

    def test_signup_requires_server_verified_terms_acceptance(self):
        client = retainai.app.test_client()
        with patch.object(retainai, "_signup_rate_limited", return_value=False):
            response = client.post(
                "/api/auth/signup",
                json={"email": "new@example.com", "password": "Valid password 123!"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "terms_required")

    def test_signup_rate_limit_is_bounded_per_email(self):
        retainai._SIGNUP_REQUESTS.clear()
        with retainai.app.test_request_context(
            "/api/auth/signup",
            headers={"X-Forwarded-For": "203.0.113.8"},
        ):
            for _ in range(retainai.SIGNUP_MAX_PER_EMAIL):
                self.assertFalse(retainai._signup_rate_limited("new@example.com"))
            self.assertTrue(retainai._signup_rate_limited("new@example.com"))


if __name__ == "__main__":
    unittest.main()

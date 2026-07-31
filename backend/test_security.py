"""Security-focused regression tests for RetainAI authentication helpers."""

import os
import tempfile
import time
import unittest
from unittest.mock import patch


_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402


class PasswordResetSecurityTests(unittest.TestCase):
    def setUp(self):
        self.email = "customer@example.com"
        self.user = {
            "email": self.email,
            "password": retainai.generate_password_hash("Original password 123!"),
        }

    def test_token_is_bound_to_current_password(self):
        users = {self.email: dict(self.user)}
        token = retainai._password_reset_token(self.email, users[self.email])
        email, _ = retainai._decode_password_reset_token(token, users)
        self.assertEqual(email, self.email)

        users[self.email]["password"] = retainai.generate_password_hash("Different password 456!")
        with self.assertRaises(ValueError):
            retainai._decode_password_reset_token(token, users)

    def test_expired_token_is_rejected(self):
        users = {self.email: dict(self.user)}
        token = retainai._password_reset_token(self.email, users[self.email])
        with patch.object(retainai.time, "time", return_value=time.time() + 1900):
            with self.assertRaises(ValueError):
                retainai._decode_password_reset_token(token, users)

    def test_forgot_password_does_not_reveal_account_existence(self):
        client = retainai.app.test_client()
        with patch.object(retainai, "load_users", return_value={}):
            response = client.post(
                "/api/auth/password/forgot",
                json={"email": "missing@example.com"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("missing", response.get_json()["message"].lower())

    def test_email_verification_token_is_signed(self):
        token = retainai._email_verification_token(self.email)
        self.assertEqual(
            retainai._decode_email_verification_token(token),
            self.email,
        )
        encoded, signature = token.split(".", 1)
        tampered = f"{encoded}.{signature[:-1]}0"
        with self.assertRaises(ValueError):
            retainai._decode_email_verification_token(tampered)


if __name__ == "__main__":
    unittest.main()

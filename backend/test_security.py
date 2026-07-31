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
import app_account  # noqa: E402
import storage  # noqa: E402


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


class RequestBoundarySecurityTests(unittest.TestCase):
    def test_cross_origin_authenticated_write_is_rejected(self):
        client = retainai.app.test_client()
        email = "customer@example.com"
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = email
            signed_session["org_email"] = email
            signed_session["security_version"] = 0
        with patch.object(
            retainai,
            "load_users",
            return_value={email: {"email": email, "security_version": 0}},
        ):
            response = client.post(
                "/api/leads",
                json={"leads": []},
                headers={"Origin": "https://malicious.example"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "untrusted_request_origin")


class WorkspaceStorageTests(unittest.TestCase):
    def test_saving_one_workspace_preserves_another(self):
        with tempfile.TemporaryDirectory() as data_root:
            leads_path = os.path.join(data_root, "leads.json")
            with patch.object(storage, "USE_SQLITE", False), patch.object(
                storage, "LEADS_JSON", leads_path
            ):
                storage._write_json(
                    leads_path,
                    {"first@example.com": [{"id": "first"}]},
                )
                storage.save_user_leads(
                    "second@example.com",
                    [{"id": "second"}],
                )
                saved = storage._read_json(leads_path, {})
        self.assertEqual(saved["first@example.com"][0]["id"], "first")
        self.assertEqual(saved["second@example.com"][0]["id"], "second")


class BillingCleanupTests(unittest.TestCase):
    def test_account_deletion_cancels_every_live_subscription(self):
        subscriptions = [
            {"id": "sub_primary", "status": "active"},
            {"id": "sub_duplicate", "status": "trialing"},
            {"id": "sub_finished", "status": "canceled"},
        ]
        page = type(
            "StripePage",
            (),
            {"auto_paging_iter": lambda self: iter(subscriptions)},
        )()
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_value"}), patch.object(
            app_account.stripe.Subscription,
            "list",
            return_value=page,
        ), patch.object(
            app_account.stripe.Subscription,
            "cancel",
        ) as cancel:
            count = app_account._cancel_workspace_subscriptions(
                {
                    "stripe_customer_id": "cus_test",
                    "stripe_subscription_id": "sub_primary",
                }
            )
        self.assertEqual(count, 2)
        self.assertEqual(
            {call.args[0] for call in cancel.call_args_list},
            {"sub_primary", "sub_duplicate"},
        )


if __name__ == "__main__":
    unittest.main()

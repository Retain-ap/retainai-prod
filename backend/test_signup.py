"""Signup may defer a business profile, but never identity, consent or billing."""

import os
import tempfile
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "signup-test-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "signup-test-independent-data-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402

_REAL_GOOGLE_VERIFY = retainai.id_token.verify_oauth2_token


class SignupTests(unittest.TestCase):
    def setUp(self):
        self.client = retainai.app.test_client()
        self.users = {}
        self.payload = {
            "email": "new@example.com", "name": "Sample Owner",
            "password": "Example password 123!", "termsAccepted": True,
        }
        self.identity = {
            "email": "new@example.com", "email_verified": True,
            "aud": "test-google-client", "iss": "https://accounts.google.com", "sub": "google-subject-1",
        }
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(retainai, "STRIPE_SECRET_KEY", "test-billing-enabled"))
        self.stack.enter_context(patch.object(retainai, "STRIPE_PRICE_ID", "price_test"))
        self.stack.enter_context(patch.object(retainai, "GOOGLE_CLIENT_ID", "test-google-client"))
        self.stack.enter_context(patch.object(retainai, "load_users", return_value=self.users))
        self.save = self.stack.enter_context(patch.object(retainai, "save_users", side_effect=lambda users: self.users.update(users)))
        self.limit = self.stack.enter_context(patch.object(retainai, "_signup_rate_limited", return_value=False))
        self.trial_used = self.stack.enter_context(patch.object(retainai, "trial_previously_used", return_value=False))
        self.stack.enter_context(patch.object(retainai, "signup_partner", return_value=""))
        self.mail = self.stack.enter_context(patch.object(retainai, "_send_verification_email"))
        self.checkout = self.stack.enter_context(patch.object(retainai, "_create_or_reuse_billing_checkout", return_value={
            "url": "https://checkout.stripe.com/test-only", "state": "new_checkout",
        }))
        self.verify = self.stack.enter_context(patch.object(retainai.id_token, "verify_oauth2_token", return_value=self.identity))

    def post(self, **changes):
        return self.client.post("/api/auth/signup", json={**self.payload, **changes})

    def google(self, **changes):
        return self.post(password="", googleCredential="test-signed-token", **changes)

    def test_email_signup_defers_profile_but_keeps_checkout_and_verification(self):
        result = self.post()
        self.assertEqual(result.status_code, 200)
        saved = self.users["new@example.com"]
        self.assertEqual(saved["status"], "pending_payment")
        self.assertEqual(saved["trial_start"], "")
        self.assertFalse(saved["email_verified"])
        self.assertEqual(saved["business"], "")
        self.assertEqual(saved["teamSize"], "")
        self.assertTrue(retainai.check_password_hash(saved["password"], self.payload["password"]))
        self.assertTrue(saved["terms_accepted_at"])
        self.assertEqual(self.checkout.call_args.kwargs["trial_days"], retainai.TRIAL_DAYS)
        self.mail.assert_called_once_with("new@example.com")
        self.verify.assert_not_called()
        with self.client.session_transaction() as session:
            self.assertNotIn("user_email", session)

    def test_old_clients_may_supply_valid_business_profile(self):
        self.assertEqual(self.post(businessName="Sample Salon", businessType="Salon", location="Toronto", teamSize=2).status_code, 200)
        self.assertEqual(self.users["new@example.com"]["teamSize"], "2")

    def test_optional_profile_values_still_have_limits(self):
        for values in ({"businessName": "x" * 161}, {"location": "x" * 201}, {"teamSize": 0}, {"teamSize": 1001}, {"teamSize": "bad"}):
            with self.subTest(values=values):
                self.assertEqual(self.post(**values).status_code, 400)
        self.checkout.assert_not_called()
        self.save.assert_not_called()

    def test_consent_is_required_for_email_and_google(self):
        for consent in (False, "true", None):
            self.assertEqual(self.post(termsAccepted=consent).status_code, 400)
            self.assertEqual(self.google(termsAccepted=consent).status_code, 400)
        self.verify.assert_not_called()
        self.checkout.assert_not_called()

    def test_password_rules_are_not_relaxed_for_email_signup(self):
        for password in ("", "short", "long without numbers", "ALLUPPERCASE123!", "lowercaseonly123!", "NoSymbol123456"):
            with self.subTest(password=password):
                self.assertEqual(self.post(password=password).status_code, 400)
        self.checkout.assert_not_called()

    def test_google_signature_and_identity_are_verified_before_checkout(self):
        self.assertEqual(self.google().status_code, 200)
        self.verify.assert_called_once()
        self.assertEqual(self.verify.call_args.args[0], "test-signed-token")
        self.assertEqual(self.verify.call_args.args[2], "test-google-client")
        saved = self.users["new@example.com"]
        self.assertEqual(saved["google_sub"], "google-subject-1")
        self.assertEqual(saved["password"], "")
        self.assertTrue(saved["email_verified"])
        self.assertEqual(saved["status"], "pending_payment")
        self.assertEqual(saved["trial_start"], "")
        self.mail.assert_not_called()

    def test_google_rejects_invalid_signature_without_storing_identity(self):
        self.verify.side_effect = ValueError("Invalid signature or expired token")
        self.assertEqual(self.google().status_code, 401)
        self.save.assert_not_called()
        self.checkout.assert_not_called()

    def test_actual_google_verifier_rejects_a_forged_token(self):
        # Exercise Google's installed verifier, not the identity mock. Its cert
        # HTTP transport is local and empty, so no provider request is made.
        def verify_without_network(token, _request, audience):
            cert_response = SimpleNamespace(status=200, data=b"{}")
            return _REAL_GOOGLE_VERIFY(token, lambda **_kwargs: cert_response, audience)

        self.verify.side_effect = verify_without_network
        result = self.google()
        self.assertEqual(result.status_code, 401)
        self.save.assert_not_called()
        self.checkout.assert_not_called()

    def test_google_rejects_wrong_audience_issuer_email_or_unverified_email(self):
        for changed in ({"aud": "other-client"}, {"iss": "https://attacker.example"}, {"email": "someone-else@example.com"}, {"email_verified": False}, {"email_verified": "true"}, {"sub": ""}):
            with self.subTest(changed=changed):
                self.verify.return_value = {**self.identity, **changed}
                result = self.google()
                self.assertEqual(result.status_code, 401)
                self.assertEqual(result.get_json()["code"], "google_token_invalid")
        self.save.assert_not_called()
        self.checkout.assert_not_called()

    def test_google_verification_is_rate_limited_before_provider_call(self):
        self.limit.return_value = True
        self.assertEqual(self.google().status_code, 429)
        self.verify.assert_not_called()
        self.checkout.assert_not_called()

    def test_google_does_not_link_or_overwrite_an_existing_password_account(self):
        self.users["new@example.com"] = {"status": "pending_payment", "password": retainai.generate_password_hash("Existing pass 123!"), "name": "Existing Owner"}
        self.assertEqual(self.google().status_code, 409)
        self.assertEqual(self.users["new@example.com"]["name"], "Existing Owner")
        self.checkout.assert_not_called()
        self.save.assert_not_called()

    def test_google_resume_requires_same_provider_subject_and_pending_status(self):
        for status, subject in (("active", "google-subject-1"), ("pending_payment", "other-subject")):
            self.users["new@example.com"] = {"status": status, "auth_provider": "google", "google_sub": subject}
            self.assertEqual(self.google().status_code, 409)
        self.checkout.assert_not_called()

    def test_google_resume_preserves_account_and_reuses_checkout_path(self):
        account = {"status": "pending_payment", "auth_provider": "google", "google_sub": "google-subject-1", "name": "Existing name", "email_verified": True, "terms_accepted_at": "2026-11-01"}
        self.users["new@example.com"] = account
        self.assertEqual(self.google().status_code, 200)
        self.assertEqual(account["name"], "Existing name")
        self.assertIs(self.checkout.call_args.args[1], account)

    def test_email_resume_requires_original_password(self):
        account = {"status": "pending_payment", "password": retainai.generate_password_hash(self.payload["password"]), "terms_accepted_at": "2026-11-01"}
        self.users["new@example.com"] = account
        self.assertEqual(self.post(password="Other password 123!").status_code, 409)
        self.assertEqual(self.post().status_code, 200)

    def test_previously_used_trial_does_not_get_another_free_trial(self):
        self.trial_used.return_value = True
        self.assertEqual(self.post().status_code, 200)
        self.assertFalse(self.users["new@example.com"]["trial_eligible"])
        self.assertEqual(self.checkout.call_args.kwargs["trial_days"], 0)

    def test_billing_unavailable_never_creates_or_unlocks_account(self):
        with patch.object(retainai, "STRIPE_SECRET_KEY", ""):
            self.assertEqual(self.post().status_code, 503)
        self.save.assert_not_called()
        self.checkout.assert_not_called()

    def test_google_login_cannot_use_an_unverified_email(self):
        self.identity["email_verified"] = False
        result = self.client.post("/api/oauth/google", json={"credential": "test-signed-token"})
        self.assertEqual(result.status_code, 401)
        self.save.assert_not_called()

    def test_google_login_preserves_the_original_provider_subject(self):
        self.users["new@example.com"] = {"auth_provider": "google", "google_sub": "different-subject"}
        result = self.client.post("/api/oauth/google", json={"credential": "test-signed-token"})
        self.assertEqual(result.status_code, 401)
        self.save.assert_not_called()

    def test_google_created_account_can_sign_in_after_billing_unlocks_it(self):
        self.assertEqual(self.google().status_code, 200)
        self.users["new@example.com"]["status"] = "active"
        result = self.client.post("/api/oauth/google", json={"credential": "test-signed-token"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()["user"]["email"], "new@example.com")
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_email"], "new@example.com")
            self.assertNotIn("recovery_only", session)
        self.assertTrue(self.client.get("/api/session").get_json()["authenticated"])


if __name__ == "__main__":
    unittest.main()

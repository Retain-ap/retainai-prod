"""Regression tests for production runtime and webhook hardening."""

import base64
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet, InvalidToken


_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-that-is-not-an-encryption-key")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "test-data-encryption-key-that-is-independent")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402


class ProductionSecretTests(unittest.TestCase):
    def test_production_requires_both_independent_secrets(self):
        with self.assertRaisesRegex(RuntimeError, "SESSION_SECRET"):
            retainai._validate_production_secrets(True, "", "data-key")
        with self.assertRaisesRegex(RuntimeError, "DATA_ENCRYPTION_KEY"):
            retainai._validate_production_secrets(True, "session-key", "")
        with self.assertRaisesRegex(RuntimeError, "independent"):
            retainai._validate_production_secrets(True, "same-key", "same-key")
        retainai._validate_production_secrets(True, "session-key", "data-key")

    def test_encrypted_data_cannot_be_decrypted_with_session_secret(self):
        with patch.object(retainai, "SESSION_SECRET", "session-signing-key"), patch.object(
            retainai, "DATA_ENCRYPTION_KEY", "independent-data-key"
        ), patch.object(retainai, "PREVIOUS_DATA_ENCRYPTION_KEY", ""):
            encrypted = retainai._encrypt_mfa_secret("sensitive-value")
        session_key = Fernet(
            base64.urlsafe_b64encode(
                hashlib.sha256(b"session-signing-key").digest()
            )
        )
        with self.assertRaises(InvalidToken):
            session_key.decrypt(encrypted.encode("utf-8"))

    def test_explicit_previous_encryption_key_supports_safe_transition(self):
        legacy = retainai._data_cipher("old-explicit-data-key").encrypt(b"legacy-value")
        with patch.object(retainai, "DATA_ENCRYPTION_KEY", "new-data-key"), patch.object(
            retainai, "PREVIOUS_DATA_ENCRYPTION_KEY", "old-explicit-data-key"
        ):
            self.assertEqual(
                retainai._decrypt_mfa_secret(legacy.decode("utf-8")),
                "legacy-value",
            )


class SchedulerExposureTests(unittest.TestCase):
    def test_scheduler_management_api_is_disabled(self):
        self.assertFalse(retainai.app.config["SCHEDULER_API_ENABLED"])
        exposed = [
            rule.rule
            for rule in retainai.app.url_map.iter_rules()
            if rule.rule.startswith("/scheduler")
        ]
        self.assertEqual(exposed, [])


class WhatsAppWebhookRetryTests(unittest.TestCase):
    secret = "test-meta-signing-secret"

    @classmethod
    def _signature(cls, body: bytes) -> str:
        digest = hmac.new(cls.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def _post(self, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        client = retainai.app.test_client()
        with patch.object(retainai, "APP_SECRET", self.secret):
            return client.post(
                "/api/whatsapp/webhook",
                data=body,
                content_type="application/json",
                headers={"X-Hub-Signature-256": self._signature(body)},
            )

    def test_invalid_signed_payload_is_not_retried(self):
        response = self._post({"object": "wrong", "entry": []})
        self.assertEqual(response.status_code, 400)

    def test_transient_processing_failure_requests_retry(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "phone-id"},
                                "statuses": [{"id": "wamid.test", "status": "sent"}],
                            }
                        }
                    ]
                }
            ],
        }
        with patch.object(retainai, "load_statuses", side_effect=OSError("temporary")):
            response = self._post(payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers.get("Retry-After"), "30")

    def test_invalid_signature_remains_forbidden(self):
        client = retainai.app.test_client()
        with patch.object(retainai, "APP_SECRET", self.secret):
            response = client.post(
                "/api/whatsapp/webhook",
                data=b"{}",
                content_type="application/json",
                headers={"X-Hub-Signature-256": "sha256=invalid"},
            )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()

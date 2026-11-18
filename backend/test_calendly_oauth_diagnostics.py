"""Pure OAuth diagnostics tests: no app storage, real HTTP or credentials."""
import json
import unittest
from unittest.mock import Mock

import calendly_bookings as cal


class OAuthDiagnosticsTests(unittest.TestCase):
    def test_known_oauth_failure_has_only_fixed_fields(self):
        self.assertEqual(cal.oauth_failure_diagnostic("token_exchange", status=401, category="invalid_client"), {
            "stage": "token_exchange", "reason": "token_exchange", "status": 401, "category": "invalid_client",
        })

    def test_untrusted_values_cannot_appear_in_diagnostics(self):
        canary = "synthetic-private-token-code-secret-state"
        for value in (canary, {"secret": canary}, [canary], None, True):
            with self.subTest(value_type=type(value).__name__):
                result = cal.oauth_failure_diagnostic(value, status=value, category=value)
                self.assertEqual(result, {"stage": "unknown", "reason": "unknown", "status": 0, "category": "other"})
                self.assertNotIn(canary, json.dumps(result))

    def test_status_bounds_and_unknown_provider_titles_fail_closed(self):
        for value in (-1, 0, 99, 600, 401.0, "401", True):
            self.assertEqual(cal.oauth_failure_diagnostic("token_exchange", status=value)["status"], 0)
        self.assertEqual(cal.oauth_failure_diagnostic("token_exchange", category="Unauthorized: sensitive detail")["category"], "other")

    def test_distinct_callback_stages_do_not_require_provider_contents(self):
        for reason, stage in {
            "provider_error": "provider_callback", "missing_code": "callback_parameters",
            "not_configured": "configuration", "missing_access_token": "token_response",
            "invalid_owner_uri": "token_response", "store_unavailable": "connection_store",
            "workspace_gone": "connection_store",
        }.items():
            self.assertEqual(cal.oauth_failure_diagnostic(reason)["stage"], stage)

    def test_401_keeps_machine_error_for_safe_classification_without_retry(self):
        canary = "synthetic-private-provider-description"
        response = Mock(status_code=401)
        response.json.return_value = {"error": "invalid_client", "title": canary, "error_description": canary}
        session = Mock()
        session.request.return_value = response
        client = cal.CalendlyClient(client_id="synthetic-client", client_secret="synthetic-secret", redirect_uri="https://example.test/callback", session=session)
        with self.assertRaises(cal.CalendlyAuthError) as failure:
            client.exchange_code("synthetic-code", "synthetic-verifier")
        result = cal.oauth_failure_diagnostic("token_exchange", status=failure.exception.status, category=failure.exception.code)
        self.assertEqual(result["category"], "invalid_client")
        self.assertEqual(result["status"], 401)
        self.assertNotIn(canary, json.dumps(result))
        self.assertEqual(session.request.call_count, 1)


if __name__ == "__main__":
    unittest.main()

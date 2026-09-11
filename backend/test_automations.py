"""Regression tests for RetainAI's automation engine and delivery controls."""

import datetime
import os
import tempfile
import unittest
from unittest.mock import Mock, patch


_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402


class QuietHoursTests(unittest.TestCase):
    def test_accepts_minute_precision_and_legacy_integer_hours(self):
        self.assertEqual(retainai._normalize_quiet_time("21:30"), "21:30")
        self.assertEqual(retainai._normalize_quiet_time(8), "08:00")
        with self.assertRaises(ValueError):
            retainai._normalize_quiet_time("24:00")

    def test_overnight_window_uses_configured_timezone(self):
        profile = {
            "quiet_hours_start": "21:30",
            "quiet_hours_end": "08:00",
            "timezone": "America/Toronto",
        }
        during = datetime.datetime(2026, 8, 22, 3, 0, tzinfo=datetime.timezone.utc)
        outside = datetime.datetime(2026, 8, 22, 16, 0, tzinfo=datetime.timezone.utc)
        self.assertTrue(retainai.in_quiet_hours(during, profile))
        self.assertFalse(retainai.in_quiet_hours(outside, profile))

    def test_date_parser_normalizes_naive_values(self):
        parsed = retainai.dt_parse("2026-08-21T12:00:00")
        self.assertEqual(parsed.tzinfo, datetime.timezone.utc)


class AppointmentTriggerTests(unittest.TestCase):
    def test_recent_no_show_triggers_but_old_no_show_does_not(self):
        recent = (retainai.now_utc() - datetime.timedelta(hours=2)).isoformat()
        old = (retainai.now_utc() - datetime.timedelta(days=10)).isoformat()
        self.assertTrue(retainai.trig_no_show({"appointments": [{"status": "no-show", "updated_at": recent}]}))
        self.assertFalse(retainai.trig_no_show({"appointments": [{"status": "no_show", "updated_at": old}]}))

    def test_completed_appointment_trigger_requires_a_recent_past_completion(self):
        recent = (retainai.now_utc() - datetime.timedelta(hours=3)).isoformat()
        old = (retainai.now_utc() - datetime.timedelta(days=5)).isoformat()
        future = (retainai.now_utc() + datetime.timedelta(hours=3)).isoformat()
        self.assertTrue(retainai.trig_completed_appointment({
            "appointments": [{"status": "completed", "appointment_time": recent}]
        }, within_days=2))
        self.assertFalse(retainai.trig_completed_appointment({
            "appointments": [{"completed": True, "appointment_time": old}]
        }, within_days=2))
        self.assertFalse(retainai.trig_completed_appointment({
            "appointments": [{"status": "completed", "appointment_time": future}]
        }, within_days=2))

    def test_engine_joins_calendar_appointments_to_customers(self):
        flow = {
            "id": "flow-1",
            "owner": "owner@example.com",
            "enabled": True,
            "trigger": {"type": "appointment_no_show"},
            "steps": [{"type": "add_tag", "tag": "Needs Attention"}],
            "caps": {"per_lead_per_day": 1, "respect_quiet_hours": True},
        }
        customer = {"id": "customer-1", "email": "customer@example.com", "owner": "owner@example.com"}
        appointment = {
            "lead_id": "customer-1",
            "lead_email": "customer@example.com",
            "status": "no-show",
            "updated_at": retainai.now_utc().isoformat(),
        }
        captured = []

        def fake_execute(flow, step, lead, run, caps, profile):
            captured.append(lead)
            return True

        with patch.object(retainai, "read_json", return_value={"users": {"owner@example.com": [flow]}}), \
             patch.object(retainai, "load_state", return_value={}), \
             patch.object(retainai, "load_leads", return_value={"owner@example.com": [customer]}), \
             patch.object(retainai, "load_appointments", return_value={"owner@example.com": [appointment]}), \
             patch.object(retainai, "load_user_profile", return_value={}), \
             patch.object(retainai, "execute_step", side_effect=fake_execute), \
             patch.object(retainai, "save_state"):
            retainai.engine_tick()

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["appointments"][0]["status"], "no-show")


class WhatsAppValidationTests(unittest.TestCase):
    def test_active_flow_requires_every_expected_template_parameter(self):
        flow = {
            "steps": [{
                "type": "send_whatsapp",
                "template": {"name": "follow_up", "language": "en", "params": []},
            }],
        }
        response = Mock(ok=True)
        response.json.return_value = {"data": [{"name": "follow_up", "status": "APPROVED"}]}
        metadata = {
            "name": "follow_up",
            "status": "APPROVED",
            "normalized_language": "en",
            "body_param_count": 2,
            "supported_by_automations": True,
        }
        with patch.object(retainai, "wa_resolve_waba_id", return_value="waba"), \
             patch.object(retainai, "wa_fetch_templates_for_waba", return_value=response), \
             patch.object(retainai, "wa_extract_template_metadata", return_value=metadata):
            errors = retainai.validate_flow_whatsapp_templates(flow)
        self.assertTrue(errors)
        self.assertIn("expects 2", errors[0])


class LiveDeliverySafetyTests(unittest.TestCase):
    def test_live_test_requires_explicit_confirmation(self):
        client = retainai.app.test_client()
        users = {
            "owner@example.com": {
                "email": "owner@example.com",
                "org_id": "owner@example.com",
                "role": "owner",
                "status": "active",
                "security_version": 0,
            }
        }
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = "owner@example.com"
            signed_session["org_email"] = "owner@example.com"
            signed_session["security_version"] = 0
        with patch.object(retainai, "load_users", return_value=users):
            response = client.post(
                "/api/automations/test-live",
                json={"lead_email": "customer@example.com", "flow": {"steps": []}},
            )
        status = response.status_code
        self.assertEqual(status, 400)
        self.assertEqual(response.get_json()["error"], "live_confirmation_required")

    def test_missing_email_provider_is_not_reported_as_a_success(self):
        with patch.object(retainai, "SENDGRID_API_KEY", ""):
            with self.assertRaises(RuntimeError):
                retainai.send_email_sendgrid_auto(
                    "customer@example.com",
                    "Test",
                    "<p>Test</p>",
                    "RetainAI",
                )


if __name__ == "__main__":
    unittest.main()

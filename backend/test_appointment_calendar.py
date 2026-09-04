"""Regression coverage for appointment and Google Calendar time semantics."""

import datetime
import json
import os
import tempfile
import unittest
import urllib.parse
from unittest.mock import patch


os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402
import app_imports as google_imports  # noqa: E402
import app_wa_auto_appointments as wa_appointments  # noqa: E402


def _users():
    return {
        "owner@example.com": {
            "email": "owner@example.com",
            "name": "Owner",
            "business": "Example Studio",
            "status": "active",
            "security_version": 0,
        }
    }


class _GoogleResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class AppointmentTimeTests(unittest.TestCase):
    def _client(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = "owner@example.com"
            signed_session["org_email"] = "owner@example.com"
            signed_session["security_version"] = 0
        return client

    def test_create_interprets_datetime_local_in_workspace_timezone(self):
        saved = {}
        users = _users()
        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "load_user_profile", return_value={"timezone": "America/Toronto"}
        ), patch.object(
            retainai,
            "load_leads",
            return_value={"owner@example.com": [{"id": "lead-1", "name": "Jenna"}]},
        ), patch.object(retainai, "load_appointments", return_value={}), patch.object(
            retainai, "save_appointments", side_effect=lambda rows: saved.update(rows)
        ), patch.object(retainai, "create_ics_file"), patch.object(
            retainai, "send_email_with_template", return_value=False
        ), patch.object(retainai, "add_notification"):
            response = self._client().post(
                "/api/appointments/owner@example.com",
                json={
                    "lead_id": "lead-1",
                    "title": "Consultation",
                    "appointment_time": "2030-07-02T10:30:00",
                    "duration": 30,
                },
            )

        self.assertEqual(response.status_code, 201)
        created = saved["owner@example.com"][0]
        self.assertEqual(created["appointment_time"], "2030-07-02T10:30:00-04:00")
        self.assertEqual(created["timezone"], "America/Toronto")
        self.assertEqual(created["status"], "scheduled")
        self.assertFalse(created["done"])

    def test_get_normalizes_legacy_nested_store_and_naive_time(self):
        users = _users()
        legacy = {
            "owner@example.com": [
                {
                    "id": "legacy-1",
                    "appointment_time": "2030-01-02T10:30:00",
                    "status": "booked",
                }
            ]
        }
        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "load_user_profile", return_value={"timezone": "America/Toronto"}
        ), patch.object(retainai, "load_appointments", return_value=legacy):
            response = self._client().get("/api/appointments/owner@example.com")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["timezone"], "America/Toronto")
        row = payload["appointments"][0]
        self.assertEqual(row["appointment_time"], "2030-01-02T10:30:00-05:00")
        self.assertEqual(row["date"], "2030-01-02")
        self.assertEqual(row["time"], "10:30")

    def test_nonexistent_dst_wall_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "daylight-saving transition"):
            retainai._appointment_time(
                "2030-03-10T02:30:00",
                "America/Toronto",
            )

    def test_ics_and_google_link_represent_the_same_instant(self):
        appointment = {
            "id": "appointment-1",
            "appointment_time": "2030-07-02T10:30:00-04:00",
            "timezone": "America/Toronto",
            "duration": 45,
            "user_name": "Owner",
            "business_name": "Example Studio",
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            retainai, "ICS_DIR", directory
        ):
            filename = retainai.create_ics_file(appointment)
            with open(os.path.join(directory, filename), "r", encoding="utf-8") as handle:
                contents = handle.read()

        self.assertIn("DTSTART:20300702T143000Z", contents)
        self.assertIn("DTEND:20300702T151500Z", contents)
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(retainai.make_google_calendar_link(appointment)).query
        )
        self.assertEqual(query["dates"], ["20300702T143000Z/20300702T151500Z"])
        self.assertEqual(query["ctz"], ["America/Toronto"])

    def test_update_reschedule_and_completion_stay_consistent(self):
        users = _users()
        appointments = {
            "owner@example.com": [
                {
                    "id": "appointment-1",
                    "appointment_time": "2030-01-02T10:30:00-05:00",
                    "timezone": "America/Toronto",
                    "duration": 30,
                    "title": "Consultation",
                    "status": "scheduled",
                }
            ]
        }
        saved = {}
        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "load_user_profile", return_value={"timezone": "America/Toronto"}
        ), patch.object(retainai, "load_appointments", return_value=appointments), patch.object(
            retainai, "save_appointments", side_effect=lambda rows: saved.update(rows)
        ), patch.object(retainai, "create_ics_file"), patch.object(
            retainai, "add_notification"
        ):
            response = self._client().put(
                "/api/appointments/owner@example.com/appointment-1",
                json={
                    "appointment_time": "2030-01-03T09:15:00",
                    "timezone": "America/Toronto",
                    "done": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        updated = saved["owner@example.com"][0]
        self.assertEqual(updated["appointment_time"], "2030-01-03T09:15:00-05:00")
        self.assertEqual(updated["status"], "completed")
        self.assertTrue(updated["done"])
        self.assertTrue(updated["completed"])
        self.assertTrue(updated["is_done"])


class GoogleCalendarContractTests(unittest.TestCase):
    def _client(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = "owner@example.com"
            signed_session["org_email"] = "owner@example.com"
            signed_session["security_version"] = 0
        return client

    def test_auth_url_requests_read_only_scope(self):
        users = _users()
        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "GOOGLE_CLIENT_ID", "client-id"
        ), patch.object(retainai, "GOOGLE_CLIENT_SECRET", "client-secret"), patch.object(
            retainai, "GOOGLE_REDIRECT_URI", "https://api.example.com/api/google/oauth-callback"
        ):
            response = self._client().get("/api/google/auth-url")

        self.assertEqual(response.status_code, 200)
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(response.get_json()["url"]).query
        )
        scopes = query["scope"][0].split()
        self.assertIn("https://www.googleapis.com/auth/calendar.calendarlist.readonly", scopes)
        self.assertIn("https://www.googleapis.com/auth/calendar.events.readonly", scopes)
        self.assertNotIn("https://www.googleapis.com/auth/calendar.readonly", scopes)
        self.assertNotIn("https://www.googleapis.com/auth/calendar", scopes)

    def test_auth_url_fails_clearly_when_server_is_not_configured(self):
        with patch.object(retainai, "load_users", return_value=_users()), patch.object(
            retainai, "GOOGLE_CLIENT_ID", ""
        ), patch.object(retainai, "GOOGLE_CLIENT_SECRET", ""), patch.object(
            retainai, "GOOGLE_REDIRECT_URI", ""
        ):
            response = self._client().get("/api/google/auth-url")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "google_calendar_not_configured")

    def test_events_are_paginated_and_normalized_to_workspace_timezone(self):
        users = _users()
        users["owner@example.com"].update({
            "gcal_connected": True,
            "gcal_access_token": "access-token",
            "gcal_refresh_token": "refresh-token",
            "gcal_calendars": [{"id": "primary", "primary": True}],
        })
        responses = [
            _GoogleResponse({
                "items": [
                    {
                        "id": "timed",
                        "summary": "Timed event",
                        "start": {"dateTime": "2030-07-02T14:30:00Z", "timeZone": "UTC"},
                        "end": {"dateTime": "2030-07-02T15:00:00Z", "timeZone": "UTC"},
                    },
                    {
                        "id": "all-day",
                        "summary": "All-day event",
                        "start": {"date": "2030-07-03"},
                        "end": {"date": "2030-07-04"},
                    },
                ],
                "nextPageToken": "page-2",
            }),
            _GoogleResponse({
                "items": [{
                    "id": "second-page",
                    "summary": "Second page",
                    "start": {"dateTime": "2030-07-04T09:00:00-04:00"},
                    "end": {"dateTime": "2030-07-04T10:00:00-04:00"},
                }]
            }),
        ]
        persisted_users = {}
        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "save_users", side_effect=lambda rows: persisted_users.update(rows)
        ), patch.object(
            retainai, "load_user_profile", return_value={"timezone": "America/Toronto"}
        ), patch.object(retainai.pyrequests, "get", side_effect=responses) as mocked_get:
            response = self._client().get(
                "/api/google/events/owner@example.com?calendarId=primary"
                "&timeMin=2030-07-01T00:00:00-04:00&timeMax=2030-08-01T00:00:00-04:00"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["raw_count"], 3)
        self.assertEqual(payload["timezone"], "America/Toronto")
        self.assertEqual(payload["items"][0]["start"]["dateTime"], "2030-07-02T10:30:00-04:00")
        self.assertEqual(payload["items"][1]["start"]["date"], "2030-07-03")
        self.assertTrue(payload["items"][1]["allDay"])
        self.assertEqual(mocked_get.call_count, 2)
        self.assertEqual(mocked_get.call_args_list[1].kwargs["params"]["pageToken"], "page-2")
        self.assertEqual(mocked_get.call_args_list[0].kwargs["params"]["timeZone"], "America/Toronto")
        migrated = persisted_users["owner@example.com"]
        self.assertNotIn("gcal_access_token", migrated)
        self.assertNotIn("gcal_refresh_token", migrated)
        self.assertTrue(migrated["gcal_access_token_encrypted"])
        self.assertTrue(migrated["gcal_refresh_token_encrypted"])


class GooglePeopleTokenStorageTests(unittest.TestCase):
    def test_people_tokens_are_encrypted_and_legacy_plaintext_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            google_imports, "TOKENS_FILE", os.path.join(directory, "google_tokens.json")
        ):
            google_imports._set_token("owner@example.com", {
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "scope": "contacts.readonly",
            })
            stored = google_imports._load_json(google_imports.TOKENS_FILE, {})[
                "owner@example.com"
            ]
            self.assertNotIn("access_token", stored)
            self.assertNotIn("refresh_token", stored)
            self.assertNotIn("access-secret", json.dumps(stored))
            self.assertNotIn("refresh-secret", json.dumps(stored))
            loaded = google_imports._get_token("owner@example.com")
            self.assertEqual(loaded["access_token"], "access-secret")
            self.assertEqual(loaded["refresh_token"], "refresh-secret")

            google_imports._save_json(
                google_imports.TOKENS_FILE,
                {"legacy@example.com": {
                    "access_token": "legacy-access",
                    "refresh_token": "legacy-refresh",
                }},
            )
            migrated = google_imports._get_token("legacy@example.com")
            self.assertEqual(migrated["access_token"], "legacy-access")
            disk_record = google_imports._load_json(
                google_imports.TOKENS_FILE, {}
            )["legacy@example.com"]
            self.assertNotIn("access_token", disk_record)
            self.assertNotIn("refresh_token", disk_record)


class WhatsAppAppointmentCompatibilityTests(unittest.TestCase):
    def test_nested_legacy_store_is_migrated_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            wa_appointments, "FILE_APPTS", os.path.join(directory, "appointments.json")
        ):
            wa_appointments._write_json(
                wa_appointments.FILE_APPTS,
                {"appointments": {"owner@example.com": [{"id": "legacy"}]}},
            )
            self.assertEqual(
                wa_appointments._get_appointments("owner@example.com")[0]["id"],
                "legacy",
            )
            wa_appointments._save_appointments(
                "owner@example.com",
                [{"id": "legacy"}, {"id": "new"}],
            )
            stored = wa_appointments._read_json(wa_appointments.FILE_APPTS, {})

        self.assertNotIn("appointments", stored)
        self.assertEqual(len(stored["owner@example.com"]), 2)

    def test_time_proposal_uses_business_timezone_even_on_utc_server(self):
        now = datetime.datetime(2030, 7, 1, 18, 0, tzinfo=datetime.timezone.utc)
        parsed = wa_appointments.parse_datetime_from_text(
            "okay tomorrow at 3 pm",
            "America/Toronto",
            now=now,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.isoformat(), "2030-07-02T15:00:00-04:00")


if __name__ == "__main__":
    unittest.main()

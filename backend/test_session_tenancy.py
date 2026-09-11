"""Regression tests for signed-session tenancy and owner authorization."""

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
import app_team  # noqa: E402


def _active_owner(email="owner@example.com"):
    return {
        "email": email,
        "role": "owner",
        "org_id": email,
        "status": "active",
        "security_version": 0,
    }


def _member_users():
    owner_email = "owner@example.com"
    member_email = "member@example.com"
    owner = _active_owner(owner_email)
    membership = {
        "email": member_email,
        "role": "member",
        "org_id": owner_email,
        "team_status": "active",
    }
    login = {
        "email": member_email,
        "role": "member",
        "org_id": owner_email,
        "status": "active",
        "security_version": 0,
    }
    return {
        owner_email: owner,
        member_email: login,
        f"user::{member_email}": membership,
    }


class SessionMembershipTests(unittest.TestCase):
    def test_missing_actor_record_revokes_session(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = "removed@example.com"
            signed_session["org_email"] = "owner@example.com"
            signed_session["security_version"] = 0

        with patch.object(retainai, "load_users", return_value={}):
            response = client.get("/api/leads")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "session_revoked")
        with client.session_transaction() as signed_session:
            self.assertNotIn("user_email", signed_session)

    def test_changed_membership_org_revokes_stale_cookie(self):
        client = retainai.app.test_client()
        users = _member_users()
        users["member@example.com"]["org_id"] = "new-owner@example.com"
        users["user::member@example.com"]["org_id"] = "new-owner@example.com"
        users["new-owner@example.com"] = _active_owner("new-owner@example.com")
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = "member@example.com"
            signed_session["org_email"] = "owner@example.com"
            signed_session["security_version"] = 0

        with patch.object(retainai, "load_users", return_value=users):
            response = client.get("/api/leads")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "session_revoked")


class OwnerAuthorizationTests(unittest.TestCase):
    def _member_client(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = "member@example.com"
            signed_session["org_email"] = "owner@example.com"
            signed_session["security_version"] = 0
        return client

    def test_forged_owner_header_cannot_authorize_team_action(self):
        users = _member_users()
        client = self._member_client()
        with patch.object(retainai, "load_users", return_value=users), patch.object(
            app_team, "load_users", return_value=users
        ):
            response = client.post(
                "/api/team/invite",
                json={"email": "new@example.com", "role": "member"},
                headers={"X-User-Email": "owner@example.com"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "forbidden")

    def test_member_cannot_open_billing_checkout_or_portal(self):
        users = _member_users()
        client = self._member_client()
        with patch.object(retainai, "load_users", return_value=users):
            checkout = client.post("/api/billing/checkout")
            portal = client.post("/api/billing/portal")

        self.assertEqual(checkout.status_code, 403)
        self.assertEqual(checkout.get_json()["error"], "forbidden")
        self.assertEqual(portal.status_code, 403)
        self.assertEqual(portal.get_json()["error"], "forbidden")

    def test_team_removal_uses_storage_delete_for_both_records(self):
        users = _member_users()
        client = retainai.app.test_client()
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = "owner@example.com"
            signed_session["org_email"] = "owner@example.com"
            signed_session["security_version"] = 0

        with patch.object(retainai, "load_users", return_value=users), patch.object(
            app_team, "load_users", return_value=users
        ), patch.object(app_team, "delete_users") as delete_users:
            response = client.post(
                "/api/team/remove",
                json={"email": "member@example.com"},
            )

        self.assertEqual(response.status_code, 200)
        delete_users.assert_called_once_with(
            ["user::member@example.com", "member@example.com"]
        )


class AppointmentTenancyTests(unittest.TestCase):
    def _member_client(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed_session:
            signed_session["user_email"] = "member@example.com"
            signed_session["org_email"] = "owner@example.com"
            signed_session["security_version"] = 0
        return client

    def test_appointment_path_cannot_switch_workspace(self):
        client = self._member_client()
        users = _member_users()
        appointments = {
            "owner@example.com": [{"id": "owner-appointment"}],
            "victim@example.com": [{"id": "victim-appointment"}],
        }
        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "load_appointments", return_value=appointments
        ):
            response = client.get("/api/appointments/victim@example.com")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "forbidden_identity")

    def test_create_derives_customer_and_business_from_workspace(self):
        client = self._member_client()
        users = _member_users()
        users["owner@example.com"].update({"business": "Trusted Business", "name": "Owner"})
        users["member@example.com"]["name"] = "Staff Member"
        leads = {
            "owner@example.com": [
                {"id": "lead-1", "name": "Real Customer", "email": "real@example.com"}
            ]
        }
        saved = {}

        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "load_leads", return_value=leads
        ), patch.object(retainai, "load_appointments", return_value={}), patch.object(
            retainai, "save_appointments", side_effect=lambda rows: saved.update(rows)
        ), patch.object(retainai, "create_ics_file"), patch.object(
            retainai, "send_email_with_template", return_value=True
        ), patch.object(retainai, "add_notification"):
            response = client.post(
                "/api/appointments/owner@example.com",
                json={
                    "lead_id": "lead-1",
                    "lead_email": "spoofed@example.com",
                    "lead_full_name": "Spoofed Person",
                    "business_name": "Spoofed Business",
                    "user_name": "Spoofed User",
                    "title": "Consultation",
                    "appointment_time": "2030-01-02T10:30:00",
                    "duration": 45,
                },
            )

        self.assertEqual(response.status_code, 201)
        created = saved["owner@example.com"][0]
        self.assertEqual(created["lead_email"], "real@example.com")
        self.assertEqual(created["lead_full_name"], "Real Customer")
        self.assertEqual(created["business_name"], "Trusted Business")
        self.assertEqual(created["user_name"], "Staff Member")
        self.assertEqual(created["user_email"], "owner@example.com")

    def test_update_cannot_overwrite_appointment_identity(self):
        client = self._member_client()
        users = _member_users()
        appointments = {
            "owner@example.com": [
                {
                    "id": "appt-1",
                    "lead_id": "lead-1",
                    "lead_email": "real@example.com",
                    "user_email": "owner@example.com",
                    "appointment_time": "2030-01-02T10:30:00",
                    "duration": 30,
                    "title": "Original",
                    "status": "scheduled",
                }
            ]
        }
        saved = {}
        with patch.object(retainai, "load_users", return_value=users), patch.object(
            retainai, "load_appointments", return_value=appointments
        ), patch.object(
            retainai, "save_appointments", side_effect=lambda rows: saved.update(rows)
        ), patch.object(retainai, "create_ics_file"):
            response = client.put(
                "/api/appointments/owner@example.com/appt-1",
                json={
                    "title": "Updated",
                    "lead_email": "attacker@example.com",
                    "lead_id": "foreign-lead",
                    "id": "replaced-id",
                },
            )

        self.assertEqual(response.status_code, 200)
        updated = saved["owner@example.com"][0]
        self.assertEqual(updated["title"], "Updated")
        self.assertEqual(updated["id"], "appt-1")
        self.assertEqual(updated["lead_id"], "lead-1")
        self.assertEqual(updated["lead_email"], "real@example.com")
        self.assertEqual(updated["user_email"], "owner@example.com")


if __name__ == "__main__":
    unittest.main()

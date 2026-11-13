"""Read-only Square Bookings: honest availability, safe OAuth, idempotent tenant-scoped import."""

import datetime as dt
import json
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402
import app_account  # noqa: E402
import app_square  # noqa: E402
import square_bookings as sq  # noqa: E402
import storage  # noqa: E402

ORIGIN = {"Origin": "http://localhost:3000"}
CONFIG = {"SQUARE_APPLICATION_ID": "sq0idp-test", "SQUARE_APPLICATION_SECRET": "sq0csp-secret", "SQUARE_ENVIRONMENT": "sandbox"}
NOW = dt.datetime.now(dt.timezone.utc)


def stamp(days):
    return (NOW + dt.timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Response:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


class FakeSquare:
    """Answers like Square's API; records every request."""

    def __init__(self):
        self.calls = []
        self.queue = {}
        self.bookings = []
        self.customers = {}
        self.list_calls = 0

    def push(self, path, *responses):
        self.queue.setdefault(path, []).extend(responses)

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        path = urlparse(url).path
        self.calls.append({"method": method, "path": path, "headers": headers or {}, "json": json, "params": params})
        if self.queue.get(path):
            return self.queue[path].pop(0)
        if path == "/oauth2/token":
            if (json or {}).get("grant_type") == "refresh_token":
                return Response(200, {"access_token": "access-2", "refresh_token": "refresh-2", "expires_at": stamp(30)})
            return Response(200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_at": stamp(30), "merchant_id": "MERCHANT1"})
        if path == "/oauth2/revoke":
            return Response(200, {"success": True})
        if path == "/v2/bookings":
            self.list_calls += 1
            start = dt.datetime.fromisoformat(params["start_at_min"].replace("Z", "+00:00"))
            end = dt.datetime.fromisoformat(params["start_at_max"].replace("Z", "+00:00"))
            inside = [b for b in self.bookings if start <= dt.datetime.fromisoformat(b["start_at"].replace("Z", "+00:00")) < end]
            return Response(200, {"bookings": inside})
        if path.startswith("/v2/customers/"):
            customer = self.customers.get(path.rsplit("/", 1)[-1])
            return Response(200, {"customer": customer}) if customer else Response(404, {"errors": [{"code": "NOT_FOUND"}]})
        return Response(404, {})


def booking(booking_id, days, status="ACCEPTED", customer="C1", version=1):
    return {"id": booking_id, "version": version, "status": status, "start_at": stamp(days), "created_at": stamp(days - 7),
            "updated_at": stamp(days - 7), "location_id": "L1", "customer_id": customer,
            "appointment_segments": [{"duration_minutes": 45}]}


class SquareTests(unittest.TestCase):
    def setUp(self):
        for path in (app_square.CONNECTIONS_FILE, os.path.join(storage.DATA_ROOT, "appointments.json")):
            if os.path.exists(path):
                os.remove(path)
        self.owner = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        self.other = f"other-{uuid.uuid4().hex[:8]}@example.com"
        self.member = f"member-{uuid.uuid4().hex[:8]}@example.com"
        self.users = {
            self.owner: {"email": self.owner, "role": "owner", "org_id": self.owner, "status": "active", "security_version": 0},
            self.other: {"email": self.other, "role": "owner", "org_id": self.other, "status": "active", "security_version": 0},
            self.member: {"email": self.member, "role": "member", "org_id": self.owner, "status": "active", "security_version": 0},
            f"user::{self.member}": {"email": self.member, "role": "member", "org_id": self.owner, "security_version": 0},
        }
        patcher = patch.object(retainai, "load_users", side_effect=lambda: self.users)
        patcher.start()
        self.addCleanup(patcher.stop)
        retainai.save_user_profile(self.owner, {"timezone": "America/Toronto"})
        storage.save_user_leads(self.owner, [{"id": "ana", "name": "Ana", "email": "ana@example.com", "phone": "+1 416 555 0101"}])
        storage.save_user_leads(self.other, [{"id": "xu", "name": "Xu", "email": "ana@example.com"}])
        self.square = FakeSquare()
        self.square.customers = {"C1": {"id": "C1", "email_address": "Ana@Example.com"}, "C2": {"id": "C2", "email_address": "stranger@example.com"}}
        for target, value in ((sq.requests, "Session"),):
            p = patch.object(target, value, return_value=self.square)
            p.start()
            self.addCleanup(p.stop)
        sleeper = patch.object(sq.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def client(self, email):
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = email
            signed["org_email"] = self.owner if email == self.member else email
            signed["security_version"] = 0
        return client

    def connect(self, email=None):
        client = self.client(email or self.owner)
        with patch.dict(os.environ, CONFIG):
            url = client.post("/api/square/connect", headers=ORIGIN).get_json()["url"]
            state = parse_qs(urlparse(url).query)["state"][0]
            response = client.get(f"/api/square/oauth/callback?code=CODE&state={state}&response_type=code")
        return client, url, response

    def stored(self):
        with open(app_square.CONNECTIONS_FILE) as handle:
            return json.load(handle)

    def appointments(self, workspace=None):
        return (retainai.load_appointments() or {}).get(workspace or self.owner) or []

    def sync(self, client):
        with patch.dict(os.environ, CONFIG):
            return client.post("/api/square/sync", headers=ORIGIN)

    def test_sync_uses_profile_timezone_before_account_across_dst_and_date_rollover(self):
        self.assertNotIn("timezone", self.users[self.owner])
        self.users[self.owner]["timezone"] = "UTC"
        cases = {
            "before-dst": ("2026-11-01T04:30:00Z", "2026-11-01T00:30:00"),
            "after-dst": ("2026-11-01T08:30:00Z", "2026-11-01T03:30:00"),
            "previous-day": ("2026-11-02T02:30:00Z", "2026-11-01T21:30:00"),
        }
        self.square.bookings = [dict(booking(key, 1), start_at=start) for key, (start, _) in cases.items()]
        fixed_now = dt.datetime(2026, 10, 31, 12, tzinfo=dt.timezone.utc)
        with patch.object(app_square, "_now", return_value=fixed_now):
            client, _, _ = self.connect()
            with patch.object(retainai, "_workspace_appointment_timezone",
                              wraps=retainai._workspace_appointment_timezone) as resolved:
                response = self.sync(client)
            self.assertEqual(response.status_code, 200)
            resolved.assert_called_once_with(self.owner)
        self.assertEqual(response.get_json()["imported"], 3)
        rows = {row["square_booking_id"]: row for row in self.appointments()}
        for key, (start, local_time) in cases.items():
            with self.subTest(booking=key):
                self.assertEqual((rows[key]["timezone"], rows[key]["appointment_time"]), ("America/Toronto", local_time))
                local = dt.datetime.fromisoformat(local_time).replace(tzinfo=ZoneInfo("America/Toronto"))
                self.assertEqual(local.astimezone(dt.timezone.utc), sq._utc(start))

    def test_legacy_utc_resync_keeps_owner_edits_and_provider_cancellation_wins(self):
        start = "2026-11-14T15:00:00Z"
        self.square.bookings = [dict(booking("qa-time", 1), start_at=start)]
        fixed_now = dt.datetime(2026, 11, 13, 8, tzinfo=dt.timezone.utc)
        with patch.object(app_square, "_now", return_value=fixed_now):
            client, _, _ = self.connect()
            for owner_status in ("completed", "no-show"):
                with self.subTest(status=owner_status):
                    retainai.save_user_profile(self.owner, {"timezone": "UTC"})
                    self.sync(client)
                    data = retainai.load_appointments()
                    original = data[self.owner][0]
                    original.pop("square_synced_status", None)
                    original.update(status=owner_status, done=True, is_done=True,
                                    completed=owner_status == "completed", notes="Keep the owner's note")
                    retainai.save_appointments(data)
                    original_id = original["id"]
                    retainai.save_user_profile(self.owner, {"timezone": "America/Toronto"})
                    result = self.sync(client).get_json()
                    self.assertEqual((result["imported"], result["updated"], result["unchanged"]), (0, 1, 0))
                    self.assertEqual(len(self.appointments()), 1)
                    row = self.appointments()[0]
                    self.assertEqual((row["id"], row["lead_id"], row["square_booking_id"]), (original_id, "ana", "qa-time"))
                    self.assertEqual((row["created_at"], row["updated_at"]), (original["created_at"], original["updated_at"]))
                    self.assertEqual((row["appointment_time"], row["timezone"]), ("2026-11-14T10:00:00", "America/Toronto"))
                    local = dt.datetime.fromisoformat(row["appointment_time"]).replace(tzinfo=ZoneInfo(row["timezone"]))
                    self.assertEqual(local.astimezone(dt.timezone.utc), sq._utc(start))
                    self.assertEqual((row["status"], row["notes"], row["completed"]),
                                     (owner_status, "Keep the owner's note", owner_status == "completed"))
                    again = self.sync(client).get_json()
                    self.assertEqual((again["imported"], again["updated"], again["unchanged"]), (0, 0, 1))
            self.square.bookings[0].update(status="CANCELLED_BY_SELLER", version=2)
            self.assertEqual(self.sync(client).get_json()["updated"], 1)
            row = self.appointments()[0]
            self.assertEqual((row["status"], row["notes"], row["completed"]), ("cancelled", "Keep the owner's note", False))
            self.assertTrue(row["done"])
            self.assertEqual(len(self.appointments()), 1)

    def test_legacy_scheduled_rows_advance_with_provider_and_stay_idempotent(self):
        self.square.bookings = [dict(booking("legacy-scheduled", 1), start_at="2026-11-14T15:00:00Z")]
        before = dt.datetime(2026, 11, 13, 8, tzinfo=dt.timezone.utc)
        after = dt.datetime(2026, 11, 15, 8, tzinfo=dt.timezone.utc)
        with patch.object(app_square, "_now", return_value=before):
            client, _, _ = self.connect()
            self.assertEqual(self.sync(client).get_json()["imported"], 1)
        legacy = dict(self.appointments()[0])
        legacy.pop("square_synced_status")
        legacy["notes"] = "Keep the appointment note"
        self.assertEqual(legacy["status"], "scheduled")
        for provider_status, expected in (("ACCEPTED", "completed"), ("NO_SHOW", "no-show")):
            with self.subTest(provider_status=provider_status), patch.object(app_square, "_now", return_value=after):
                data = retainai.load_appointments()
                data[self.owner] = [dict(legacy)]
                retainai.save_appointments(data)
                self.square.bookings[0]["status"] = provider_status
                result = self.sync(client).get_json()
                self.assertEqual((result["imported"], result["updated"]), (0, 1))
                row = self.appointments()[0]
                self.assertEqual((row["status"], row["square_synced_status"]), (expected, expected))
                self.assertEqual((row["done"], row["is_done"], row["completed"]), (True, True, expected == "completed"))
                self.assertEqual((row["id"], row["notes"]), (legacy["id"], legacy["notes"]))
                again = self.sync(client).get_json()
                self.assertEqual((again["imported"], again["updated"], again["unchanged"]), (0, 0, 1))
                self.assertEqual(len(self.appointments()), 1)

    def test_without_credentials_square_is_honestly_unavailable(self):
        client = self.client(self.owner)
        with patch.dict(os.environ, {"SQUARE_APPLICATION_ID": "", "SQUARE_APPLICATION_SECRET": ""}):
            status = client.get("/api/square/status").get_json()
            self.assertEqual((status["configured"], status["connected"]), (False, False))
            self.assertEqual(client.post("/api/square/connect", headers=ORIGIN).status_code, 503)
            self.assertEqual(client.post("/api/square/sync", headers=ORIGIN).status_code, 503)
        self.assertEqual(self.square.calls, [])
        self.assertEqual(self.client(self.member).get("/api/square/status").status_code, 403)
        self.assertEqual(retainai.app.test_client().get("/api/square/status").status_code, 401)

    def test_connect_requests_read_scopes_and_stores_only_encrypted_tokens(self):
        client, url, response = self.connect()
        query = parse_qs(urlparse(url).query)
        self.assertEqual(urlparse(url).netloc, "connect.squareupsandbox.com")
        self.assertEqual(query["scope"], ["APPOINTMENTS_READ APPOINTMENTS_ALL_READ CUSTOMERS_READ"])
        self.assertTrue(response.headers["Location"].endswith("/app/import?square=connected"))
        exchange = next(call for call in self.square.calls if call["path"] == "/oauth2/token")
        self.assertEqual(exchange["json"]["grant_type"], "authorization_code")
        raw = open(app_square.CONNECTIONS_FILE).read()
        self.assertNotIn("access-1", raw)
        self.assertNotIn("refresh-1", raw)
        status = client.get("/api/square/status").get_json()
        self.assertEqual((status["connected"], status["merchant"]), (True, "…ANT1"))
        self.assertNotIn("access_token_enc", json.dumps(status))

    def test_callback_rejects_bad_state_and_a_different_signed_in_owner(self):
        with patch.dict(os.environ, CONFIG):
            bad = self.client(self.owner).get("/api/square/oauth/callback?code=CODE&state=forged")
            self.assertIn("square_error=expired", bad.headers["Location"])
            url = self.client(self.owner).post("/api/square/connect", headers=ORIGIN).get_json()["url"]
            state = parse_qs(urlparse(url).query)["state"][0]
            hijack = self.client(self.other).get(f"/api/square/oauth/callback?code=CODE&state={state}")
        self.assertIn("square_error=session_mismatch", hijack.headers["Location"])
        self.assertFalse(os.path.exists(app_square.CONNECTIONS_FILE) and self.stored())
        self.assertFalse(any(call["path"] == "/oauth2/token" for call in self.square.calls))

    def test_one_square_seller_cannot_be_linked_to_two_workspaces(self):
        self.connect()
        _, _, second = self.connect(self.other)
        self.assertIn("square_error=merchant_linked_elsewhere", second.headers["Location"])
        self.assertNotIn(self.other, self.stored())
        self.assertTrue(any(call["path"] == "/oauth2/revoke" for call in self.square.calls))

    def test_sync_maps_statuses_matches_existing_contacts_only_and_is_idempotent(self):
        self.square.bookings = [
            booking("past-ok", -20), booking("future-ok", 5), booking("cancelled", -10, "CANCELLED_BY_CUSTOMER"),
            booking("noshow", -5, "NO_SHOW"), booking("stale-pending", -3, "PENDING"), booking("stranger", -2, customer="C2"),
        ]
        client, _, _ = self.connect()
        with patch.dict(os.environ, CONFIG):
            first = client.post("/api/square/sync", headers=ORIGIN).get_json()
        self.assertEqual((first["read"], first["imported"], first["unmatched"], first["skipped"]), (6, 4, 1, 1))
        by_id = {row["square_booking_id"]: row for row in self.appointments()}
        self.assertEqual({k: v["status"] for k, v in by_id.items()},
                         {"past-ok": "completed", "future-ok": "scheduled", "cancelled": "cancelled", "noshow": "no-show"})
        self.assertTrue(all(row["lead_id"] == "ana" and row["source"] == "square" for row in by_id.values()))
        self.assertEqual(by_id["past-ok"]["timezone"], "America/Toronto")
        self.assertEqual(len(storage.load_user_leads(self.owner)), 1)  # nobody added
        with patch.dict(os.environ, CONFIG):
            again = client.post("/api/square/sync", headers=ORIGIN).get_json()
        self.assertEqual((again["imported"], again["updated"], again["unchanged"]), (0, 0, 4))
        self.square.bookings[1] = booking("future-ok", 5, "CANCELLED_BY_SELLER", version=2)
        with patch.dict(os.environ, CONFIG):
            third = client.post("/api/square/sync", headers=ORIGIN).get_json()
        self.assertEqual(third["updated"], 1)
        self.assertEqual(len(self.appointments()), 4)
        self.assertEqual({r["square_booking_id"]: r["status"] for r in self.appointments()}["future-ok"], "cancelled")
        self.assertFalse(any(call["method"] != "GET" for call in self.square.calls if call["path"].startswith("/v2/")))

    def test_expired_access_refreshes_once_and_a_refused_refresh_asks_to_reconnect(self):
        self.square.bookings = [booking("past-ok", -20)]
        client, _, _ = self.connect()
        self.square.push("/v2/bookings", Response(401, {"errors": [{"code": "UNAUTHORIZED"}]}))
        with patch.dict(os.environ, CONFIG):
            ok = client.post("/api/square/sync", headers=ORIGIN)
        self.assertEqual((ok.status_code, ok.get_json()["imported"]), (200, 1))
        self.assertEqual([c["json"]["grant_type"] for c in self.square.calls if c["path"] == "/oauth2/token"], ["authorization_code", "refresh_token"])
        self.square.push("/v2/bookings", Response(401, {}))
        self.square.push("/oauth2/token", Response(401, {"errors": [{"code": "UNAUTHORIZED"}]}))
        with patch.dict(os.environ, CONFIG):
            refused = client.post("/api/square/sync", headers=ORIGIN)
            self.assertEqual(refused.status_code, 409)
            self.assertTrue(client.get("/api/square/status").get_json()["needs_reconnect"])
            self.assertEqual(client.post("/api/square/sync", headers=ORIGIN).status_code, 409)

    def test_rate_limits_are_retried_and_persistent_failures_change_nothing(self):
        self.square.bookings = [booking("past-ok", -20)]
        client, _, _ = self.connect()
        self.square.push("/v2/bookings", Response(429, {}), Response(503, {}))
        with patch.dict(os.environ, CONFIG):
            retried = client.post("/api/square/sync", headers=ORIGIN)
        self.assertEqual((retried.status_code, retried.get_json()["imported"]), (200, 1))
        self.square.push("/v2/bookings", Response(500, {}), Response(500, {}), Response(500, {}))
        with patch.dict(os.environ, CONFIG):
            failed = client.post("/api/square/sync", headers=ORIGIN)
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(len(self.appointments()), 1)

    def test_tokens_are_renewed_when_older_than_seven_days(self):
        client, _, _ = self.connect()
        data = self.stored()
        data[self.owner]["token_refreshed_at"] = stamp(-8)
        with open(app_square.CONNECTIONS_FILE, "w") as handle:
            json.dump(data, handle)
        with patch.dict(os.environ, CONFIG):
            client.post("/api/square/sync", headers=ORIGIN)
        self.assertIn("refresh_token", [c["json"]["grant_type"] for c in self.square.calls if c["path"] == "/oauth2/token"])

    def test_workspaces_never_touch_each_others_square_data(self):
        self.square.bookings = [booking("past-ok", -20)]
        client, _, _ = self.connect()
        with patch.dict(os.environ, CONFIG):
            client.post("/api/square/sync", headers=ORIGIN)
            other = self.client(self.other)
            self.assertEqual(other.post("/api/square/sync", headers=ORIGIN).status_code, 400)
            self.assertFalse(other.get("/api/square/status").get_json()["connected"])
            self.assertEqual(other.post("/api/square/disconnect", headers=ORIGIN).get_json()["was_connected"], False)
        self.assertEqual(self.appointments(self.other), [])
        self.assertEqual(len(self.appointments()), 1)
        self.assertIn(self.owner, self.stored())

    def test_disconnect_revokes_with_the_app_secret_and_deletes_tokens(self):
        client, _, _ = self.connect()
        with patch.dict(os.environ, CONFIG):
            result = client.post("/api/square/disconnect", headers=ORIGIN).get_json()
        self.assertEqual((result["revoked"], result["was_connected"]), (True, True))
        revoke = next(call for call in self.square.calls if call["path"] == "/oauth2/revoke")
        self.assertEqual(revoke["headers"]["Authorization"], "Client sq0csp-secret")
        self.assertEqual(revoke["json"]["access_token"], "access-1")
        self.assertNotIn(self.owner, self.stored())

    def test_a_sync_authenticated_before_deletion_writes_nothing_after_it(self):
        import app_account

        self.square.bookings = [booking("past-ok", -20)]
        client, _, _ = self.connect()
        real = self.square.request

        def delete_mid_read(method, url, **kwargs):
            if "/v2/customers/" in url and self.owner in self.users:
                self.users.pop(self.owner)  # purge order: users first, then each store under its lock
                app_account._purge_workspace_json(self.owner)
            return real(method, url, **kwargs)

        self.square.request = delete_mid_read
        with patch.dict(os.environ, CONFIG):
            response = client.post("/api/square/sync", headers=ORIGIN)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(self.owner, retainai.load_appointments() or {})
        self.assertNotIn(self.owner, self.stored())


if __name__ == "__main__":
    unittest.main()

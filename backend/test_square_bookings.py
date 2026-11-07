"""Read-only Square Bookings: honest availability, safe OAuth, idempotent tenant-scoped import."""

import datetime as dt
import json
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

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
            self.owner: {"email": self.owner, "role": "owner", "org_id": self.owner, "status": "active", "security_version": 0, "timezone": "America/Toronto"},
            self.other: {"email": self.other, "role": "owner", "org_id": self.other, "status": "active", "security_version": 0},
            self.member: {"email": self.member, "role": "member", "org_id": self.owner, "status": "active", "security_version": 0},
            f"user::{self.member}": {"email": self.member, "role": "member", "org_id": self.owner, "security_version": 0},
        }
        patcher = patch.object(retainai, "load_users", side_effect=lambda: self.users)
        patcher.start()
        self.addCleanup(patcher.stop)
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

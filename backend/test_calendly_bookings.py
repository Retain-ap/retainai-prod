"""Read-only Calendly: honest availability, PKCE OAuth bound to the owner, rotating
refresh, idempotent tenant-scoped import that never infers consent or contacts."""

import base64
import datetime as dt
import hashlib
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
import app_calendly  # noqa: E402
import calendly_bookings as cal  # noqa: E402
import storage  # noqa: E402

ORIGIN = {"Origin": "http://localhost:3000"}
REDIRECT = "https://api.retainai.ca/api/calendly/oauth/callback"
CONFIG = {"CALENDLY_CLIENT_ID": "cal-client", "CALENDLY_CLIENT_SECRET": "cal-secret", "CALENDLY_REDIRECT_URI": REDIRECT}
NOW = dt.datetime.now(dt.timezone.utc)
API = "https://api.calendly.com"


def stamp(days, hours=0):
    return (NOW + dt.timedelta(days=days, hours=hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Response:
    def __init__(self, status, body, headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}

    def json(self):
        return self.body


def event(uuid_, days, status="active", name="Consultation"):
    return {"uri": f"{API}/scheduled_events/{uuid_}", "name": name, "status": status,
            "start_time": stamp(days), "end_time": stamp(days, 1), "created_at": stamp(days - 7)}


def invitee(event_uuid, uuid_, email="Ana@Example.com", **extra):
    return {"uri": f"{API}/scheduled_events/{event_uuid}/invitees/{uuid_}", "email": email, "status": "active",
            "timezone": "Europe/Paris", "rescheduled": False, "no_show": None, "created_at": stamp(-30),
            "name": "Ana Example", "questions_and_answers": [{"question": "Notes", "answer": "private"}], **extra}


class FakeCalendly:
    """Answers like Calendly's API and OAuth server; records every request."""

    def __init__(self):
        self.calls = []
        self.queue = {}
        self.events = []
        self.invitees = {}
        self.owner_uri = f"{API}/users/USER1"
        self.scope = "scheduled_events:read"
        self.refresh_count = 0
        self.loop_events = self.loop_invitees = False

    def push(self, path, *responses):
        self.queue.setdefault(path, []).extend(responses)

    def request(self, method, url, headers=None, data=None, params=None, auth=None, timeout=None):
        parsed = urlparse(url)
        path = parsed.path
        self.calls.append({"method": method, "host": parsed.netloc, "path": path, "headers": headers or {},
                           "data": data, "params": params, "auth": auth})
        if self.queue.get(path):
            return self.queue[path].pop(0)
        if path == "/oauth/token":
            if data["grant_type"] == "refresh_token":
                self.refresh_count += 1
                n = self.refresh_count + 1
                return Response(200, {"access_token": f"access-{n}", "refresh_token": f"refresh-{n}", "expires_in": 7200, "token_type": "Bearer",
                                      "owner": self.owner_uri, "organization": f"{API}/organizations/ORG1", "scope": self.scope})
            return Response(200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 7200, "token_type": "Bearer",
                                  "owner": self.owner_uri, "organization": f"{API}/organizations/ORG1", "scope": self.scope})
        if path == "/oauth/revoke":
            return Response(200, {})
        if path == "/scheduled_events" and self.loop_events:
            return Response(200, {"collection": self.events[:1], "pagination": {"next_page_token": "same"}})
        if path == "/scheduled_events":
            ordered = sorted(self.events, key=lambda e: str(e.get("start_time") or ""))
            start = int((params or {}).get("page_token") or 0)
            size = int(params["count"])
            page = ordered[start:start + size]
            nxt = str(start + size) if start + size < len(ordered) else None
            return Response(200, {"collection": page, "pagination": {"next_page_token": nxt}})
        if path.startswith("/scheduled_events/") and path.endswith("/invitees"):
            if self.loop_invitees:
                return Response(200, {"collection": self.invitees.get(path.split("/")[2], [])[:1], "pagination": {"next_page_token": "again"}})
            return Response(200, {"collection": self.invitees.get(path.split("/")[2], []), "pagination": {"next_page_token": None}})
        return Response(404, {"title": "Resource Not Found"})


class CalendlyTests(unittest.TestCase):
    def setUp(self):
        for path in (app_calendly.CONNECTIONS_FILE, os.path.join(storage.DATA_ROOT, "appointments.json")):
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
        storage.save_user_leads(self.owner, [{"id": "ana", "name": "Ana", "email": "ana@example.com"}])
        storage.save_user_leads(self.other, [{"id": "xu", "name": "Xu", "email": "ana@example.com"}])
        self.fake = FakeCalendly()
        p = patch.object(cal.requests, "Session", return_value=self.fake)
        p.start()
        self.addCleanup(p.stop)
        self.sleeper = patch.object(cal.time, "sleep")
        self.sleep = self.sleeper.start()
        self.addCleanup(self.sleeper.stop)

    # helpers ---------------------------------------------------------------
    def client(self, email):
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = email
            signed["org_email"] = self.owner if email == self.member else email
            signed["security_version"] = 0
        return client

    def start(self, client):
        with patch.dict(os.environ, CONFIG):
            url = client.post("/api/calendly/connect", headers=ORIGIN).get_json()["url"]
        return url, parse_qs(urlparse(url).query)["state"][0]

    def connect(self, email=None):
        client = self.client(email or self.owner)
        url, state = self.start(client)
        with patch.dict(os.environ, CONFIG):
            response = client.get(f"/api/calendly/oauth/callback?code=CODE&state={state}")
        return client, url, response

    def stored(self):
        with open(app_calendly.CONNECTIONS_FILE) as handle:
            return json.load(handle)

    def save(self, data):
        with open(app_calendly.CONNECTIONS_FILE, "w") as handle:
            json.dump(data, handle)

    def sync(self, client):
        with patch.dict(os.environ, CONFIG):
            return client.post("/api/calendly/sync", headers=ORIGIN)

    def appointments(self, workspace=None):
        return (retainai.load_appointments() or {}).get(workspace or self.owner) or []

    def token_calls(self):
        return [c for c in self.fake.calls if c["path"] == "/oauth/token"]

    # tests -----------------------------------------------------------------
    def test_without_credentials_calendly_is_visibly_unavailable(self):
        client = self.client(self.owner)
        with patch.dict(os.environ, {"CALENDLY_CLIENT_ID": "", "CALENDLY_CLIENT_SECRET": "", "CALENDLY_REDIRECT_URI": ""}):
            status = client.get("/api/calendly/status").get_json()
            self.assertEqual((status["configured"], status["connected"]), (False, False))
            self.assertEqual(client.post("/api/calendly/connect", headers=ORIGIN).status_code, 503)
            self.assertEqual(client.post("/api/calendly/sync", headers=ORIGIN).status_code, 503)
        with patch.dict(os.environ, {**CONFIG, "CALENDLY_REDIRECT_URI": "http://api.retainai.ca/cb"}):
            self.assertFalse(client.get("/api/calendly/status").get_json()["configured"])  # https only
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.client(self.member).get("/api/calendly/status").status_code, 403)
        with patch.dict(os.environ, CONFIG):
            self.assertEqual(self.client(self.member).post("/api/calendly/connect", headers=ORIGIN).status_code, 403)
        self.assertEqual(retainai.app.test_client().get("/api/calendly/status").status_code, 401)

    def test_connect_uses_pkce_s256_and_stores_only_encrypted_tokens(self):
        client, url, response = self.connect()
        parsed, query = urlparse(url), parse_qs(urlparse(url).query)
        self.assertEqual((parsed.netloc, parsed.path), ("auth.calendly.com", "/oauth/authorize"))
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual((query["client_id"], query["redirect_uri"], query["response_type"]), (["cal-client"], [REDIRECT], ["code"]))
        self.assertEqual(query["scope"], ["scheduled_events:read"])  # no users:read, no webhook scopes
        self.assertTrue(response.headers["Location"].endswith("/app/import?calendly=connected"))
        exchange = self.token_calls()[0]
        self.assertEqual(exchange["host"], "auth.calendly.com")
        self.assertEqual(exchange["auth"], ("cal-client", "cal-secret"))
        self.assertEqual((exchange["data"]["grant_type"], exchange["data"]["redirect_uri"]), ("authorization_code", REDIRECT))
        verifier = exchange["data"]["code_verifier"]
        self.assertTrue(43 <= len(verifier) <= 128)
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self.assertEqual(query["code_challenge"], [expected])
        self.assertNotIn(verifier, url)
        raw = json.dumps(self.stored())
        for secret in ("access-1", "refresh-1", verifier):
            self.assertNotIn(secret, raw)
        status = client.get("/api/calendly/status").get_json()
        self.assertEqual((status["connected"], status["account"]), (True, "…SER1"))
        self.assertEqual(status["scopes"], ["scheduled_events:read"])
        self.assertEqual(self.stored()[self.owner]["user_uri"], f"{API}/users/USER1")
        self.assertFalse(any(c["path"] == "/users/me" for c in self.fake.calls))
        self.assertNotIn("token", json.dumps(status))

    def test_callback_rejects_forged_state_another_owner_and_a_session_without_the_verifier(self):
        with patch.dict(os.environ, CONFIG):
            bad = self.client(self.owner).get("/api/calendly/oauth/callback?code=CODE&state=forged")
        self.assertIn("calendly_error=expired", bad.headers["Location"])
        _, state = self.start(self.client(self.owner))
        with patch.dict(os.environ, CONFIG):
            hijack = self.client(self.other).get(f"/api/calendly/oauth/callback?code=CODE&state={state}")
        self.assertIn("calendly_error=session_mismatch", hijack.headers["Location"])
        _, state = self.start(self.client(self.owner))
        with patch.dict(os.environ, CONFIG):  # same owner, but not the browser session that started it
            replay = self.client(self.owner).get(f"/api/calendly/oauth/callback?code=CODE&state={state}")
        self.assertIn("calendly_error=session_mismatch", replay.headers["Location"])
        self.assertEqual(self.token_calls(), [])
        self.assertFalse(os.path.exists(app_calendly.CONNECTIONS_FILE) and self.stored())

    def test_state_is_single_use(self):
        client = self.client(self.owner)
        _, state = self.start(client)
        with patch.dict(os.environ, CONFIG):
            client.get(f"/api/calendly/oauth/callback?code=CODE&state={state}")
            again = client.get(f"/api/calendly/oauth/callback?code=CODE&state={state}")
        self.assertIn("calendly_error=", again.headers["Location"])
        self.assertEqual(len(self.token_calls()), 1)

    def test_a_token_without_the_read_scope_is_revoked_and_not_stored(self):
        self.fake.scope = "users:read"
        _, _, response = self.connect()
        self.assertIn("calendly_error=missing_scope", response.headers["Location"])
        self.assertFalse(os.path.exists(app_calendly.CONNECTIONS_FILE) and self.stored())
        self.assertEqual([c["data"]["token"] for c in self.fake.calls if c["path"] == "/oauth/revoke"], ["refresh-1", "access-1"])

    def test_one_calendly_user_cannot_be_linked_to_two_workspaces(self):
        self.connect()
        _, _, second = self.connect(self.other)
        self.assertIn("calendly_error=account_linked_elsewhere", second.headers["Location"])
        self.assertNotIn(self.other, self.stored())
        revoked = [c["data"]["token"] for c in self.fake.calls if c["path"] == "/oauth/revoke"]
        self.assertEqual(revoked, ["refresh-1", "access-1"])

    def test_sync_preserves_cancellation_reschedule_timezone_and_never_adds_contacts(self):
        self.fake.events = [event("PAST", -20), event("FUTURE", 5), event("CANCELED", -10, "canceled"),
                            event("NOSHOW", -5), event("MOVED", -3), event("STRANGER", -2)]
        self.fake.invitees = {
            "PAST": [invitee("PAST", "I1")], "FUTURE": [invitee("FUTURE", "I2")],
            "CANCELED": [invitee("CANCELED", "I3", status="canceled", cancellation={"canceler_type": "invitee", "reason": "sick"})],
            "NOSHOW": [invitee("NOSHOW", "I4", no_show={"uri": "x", "created_at": stamp(-5)})],
            "MOVED": [invitee("MOVED", "I5", status="canceled", rescheduled=True, new_invitee=f"{API}/scheduled_events/FUTURE/invitees/I2")],
            "STRANGER": [invitee("STRANGER", "I6", email="stranger@example.com")],
        }
        client, _, _ = self.connect()
        first = self.sync(client).get_json()
        self.assertEqual((first["events"], first["invitees"], first["imported"], first["unmatched"]), (6, 6, 5, 1))
        self.assertEqual((first["cancelled"], first["rescheduled"], first["truncated"]), (2, 1, False))
        rows = {row["calendly_event_id"]: row for row in self.appointments()}
        self.assertEqual({k: v["status"] for k, v in rows.items()},
                         {"PAST": "completed", "FUTURE": "scheduled", "CANCELED": "cancelled", "NOSHOW": "no-show", "MOVED": "cancelled"})
        self.assertTrue(rows["MOVED"]["calendly_rescheduled"])
        self.assertEqual(rows["MOVED"]["calendly_new_invitee"], "I2")
        self.assertEqual(rows["CANCELED"]["calendly_canceled_by"], "invitee")
        past = rows["PAST"]
        self.assertEqual((past["timezone"], past["invitee_timezone"], past["lead_id"], past["source"]),
                         ("America/Toronto", "Europe/Paris", "ana", "calendly"))
        local = dt.datetime.fromisoformat(past["appointment_time"]).replace(tzinfo=__import__("zoneinfo").ZoneInfo("America/Toronto"))
        self.assertEqual(local.astimezone(dt.timezone.utc), cal._utc(past["calendly_start_utc"]))
        self.assertNotIn("private", json.dumps(self.appointments()))  # booking answers are not stored
        self.assertEqual(storage.load_user_leads(self.owner), [{"id": "ana", "name": "Ana", "email": "ana@example.com"}])
        self.assertFalse(any("consent" in key for row in self.appointments() for key in row))

        again = self.sync(client).get_json()
        self.assertEqual((again["imported"], again["updated"], again["unchanged"]), (0, 0, 5))
        self.fake.events[1] = event("FUTURE", 6, "canceled")
        third = self.sync(client).get_json()
        self.assertEqual(third["updated"], 1)
        self.assertEqual(len(self.appointments()), 5)
        self.assertEqual({r["calendly_event_id"]: r["status"] for r in self.appointments()}["FUTURE"], "cancelled")
        api_calls = [c for c in self.fake.calls if c["host"] == "api.calendly.com"]
        self.assertTrue(api_calls and all(c["method"] == "GET" for c in api_calls))
        self.assertTrue(all(c["params"]["user"] == f"{API}/users/USER1" for c in api_calls if c["path"] == "/scheduled_events"))

    def test_sync_leaves_appointments_from_other_sources_alone(self):
        manual = {"id": "manual-1", "lead_id": "ana", "status": "scheduled", "appointment_time": "2026-12-01T10:00:00"}
        retainai.save_appointments({self.owner: [manual]})
        self.fake.events = [event("PAST", -20)]
        self.fake.invitees = {"PAST": [invitee("PAST", "I1")]}
        client, _, _ = self.connect()
        self.sync(client)
        self.assertEqual([row["id"] for row in self.appointments()], ["manual-1", "calendly:PAST:I1"])
        self.assertEqual(self.appointments()[0], manual)

    def test_expired_access_uses_the_rotated_refresh_token_and_stores_the_new_one(self):
        client, _, _ = self.connect()
        for expected in ("refresh-1", "refresh-2"):
            data = self.stored()
            data[self.owner]["expires_at"] = stamp(-1)
            self.save(data)
            self.assertEqual(self.sync(client).status_code, 200)
            self.assertEqual(self.token_calls()[-1]["data"]["refresh_token"], expected)
            self.assertEqual(self.token_calls()[-1]["auth"], ("cal-client", "cal-secret"))
        self.assertNotIn("refresh-3", json.dumps(self.stored()))
        events_calls = [c for c in self.fake.calls if c["path"] == "/scheduled_events"]
        self.assertEqual(events_calls[-1]["headers"]["Authorization"], "Bearer access-3")

    def test_a_rejected_access_token_refreshes_once_and_a_refused_refresh_asks_to_reconnect(self):
        self.fake.events = [event("PAST", -20)]
        self.fake.invitees = {"PAST": [invitee("PAST", "I1")]}
        client, _, _ = self.connect()
        self.fake.push("/scheduled_events", Response(401, {"title": "Unauthenticated"}))
        ok = self.sync(client)
        self.assertEqual((ok.status_code, ok.get_json()["imported"]), (200, 1))
        self.assertEqual([c["data"]["grant_type"] for c in self.token_calls()], ["authorization_code", "refresh_token"])
        self.fake.push("/scheduled_events", Response(401, {}))
        self.fake.push("/oauth/token", Response(400, {"error": "invalid_grant"}))
        refused = self.sync(client)
        self.assertEqual(refused.status_code, 409)
        with patch.dict(os.environ, CONFIG):
            self.assertTrue(client.get("/api/calendly/status").get_json()["needs_reconnect"])
        before = len(self.token_calls())
        self.assertEqual(self.sync(client).status_code, 409)
        self.assertEqual(len(self.token_calls()), before)  # a dead refresh token is not retried

    def invitee_calls(self):
        return [c for c in self.fake.calls if c["path"].endswith("/invitees")]

    def many(self, count, per_event=1, start=-100):
        self.fake.events = [event(f"E{i:03d}", start + i) for i in range(count)]
        self.fake.invitees = {f"E{i:03d}": [invitee(f"E{i:03d}", f"I{i}x{j}") for j in range(per_event)] for i in range(count)}

    def test_the_event_cap_is_exact_and_every_capped_event_keeps_all_its_invitees(self):
        self.many(5, per_event=2)
        client, _, _ = self.connect()
        with patch.object(cal, "MAX_EVENTS", 3):
            result = self.sync(client).get_json()
        self.assertEqual((result["events"], result["invitees"], result["imported"]), (3, 6, 6))
        self.assertEqual((result["truncated"], result["pass_complete"], result["notes"]), (True, True, ["event_limit"]))
        self.assertEqual(len(self.invitee_calls()), 3)

    def test_the_event_cap_holds_across_pages_and_a_full_page_at_the_cap(self):
        self.many(6)
        client, _, _ = self.connect()
        with patch.object(cal, "MAX_EVENTS", 4), patch.object(cal, "PAGE_SIZE", 2), patch.object(cal, "SYNC_REQUEST_BUDGET", 100):
            result = self.sync(client).get_json()
        self.assertEqual((result["events"], result["imported"], result["truncated"]), (4, 4, True))
        self.assertEqual(sorted(r["calendly_event_id"] for r in self.appointments()), ["E000", "E001", "E002", "E003"])

    def test_the_invitee_cap_is_exact(self):
        self.many(3, per_event=2)
        client, _, _ = self.connect()
        with patch.object(cal, "MAX_INVITEES", 3):
            result = self.sync(client).get_json()
        self.assertEqual((result["invitees"], result["imported"], result["truncated"]), (3, 3, True))

    def test_repeating_page_tokens_end_the_pass_instead_of_looping(self):
        self.many(1, per_event=2)
        client, _, _ = self.connect()
        self.fake.loop_events = self.fake.loop_invitees = True
        result = self.sync(client).get_json()
        self.assertTrue(result["truncated"])
        self.assertIn("pagination_loop", result["notes"])
        self.assertLessEqual(len([c for c in self.fake.calls if c["host"] == "api.calendly.com"]), 6)

    def test_each_sync_is_bounded_and_resumes_until_the_pass_completes_then_rereads_for_cancellations(self):
        self.many(6)
        client, _, _ = self.connect()
        with patch.object(cal, "PAGE_SIZE", 2), patch.object(cal, "SYNC_REQUEST_BUDGET", 4):
            first = self.sync(client).get_json()
            self.assertEqual((first["stopped"], first["pass_complete"], first["imported"]), ("budget", False, 2))
            self.assertEqual(len([c for c in self.fake.calls if c["host"] == "api.calendly.com"]), 4)
            with patch.dict(os.environ, CONFIG):
                status = client.get("/api/calendly/status").get_json()
            self.assertTrue(status["sync_in_progress"])
            self.assertNotIn("seen_pages", json.dumps(status))  # the cursor stays on the server
            import app_account
            self.assertNotIn("sync_cursor", json.dumps(app_account._workspace_records(self.owner)))
            seen, rounds = first["imported"], 1
            while True:
                step = self.sync(client).get_json()
                rounds += 1
                seen += step["imported"]
                self.assertTrue(step["continued"])
                if step["pass_complete"]:
                    break
                self.assertLess(rounds, 10)
            self.assertEqual((seen, len(self.appointments())), (6, 6))
            # A cancellation on the last page is picked up by the next pass.
            self.fake.events[-1] = event("E005", -95, "canceled")
            for _ in range(10):
                step = self.sync(client).get_json()
                if step["pass_complete"]:
                    break
        self.assertEqual({r["calendly_event_id"]: r["status"] for r in self.appointments()}["E005"], "cancelled")
        self.assertEqual(len(self.appointments()), 6)
        self.assertFalse([c for c in self.sleep.call_args_list if c.args and c.args[0] > 1])

    def test_a_rate_limit_stops_without_waiting_saves_progress_and_the_next_sync_continues(self):
        self.many(2)
        client, _, _ = self.connect()
        self.fake.push("/scheduled_events/E001/invitees", Response(429, {}, {"X-RateLimit-Reset": "37"}))
        limited = self.sync(client)
        body = limited.get_json()
        self.assertEqual(limited.status_code, 200)
        self.assertEqual((body["stopped"], body["retry_after"], body["imported"]), ("rate_limited", 37, 1))
        self.sleep.assert_not_called()
        after = self.sync(client).get_json()
        self.assertEqual((after["continued"], after["imported"], after["pass_complete"]), (True, 1, True))
        self.assertEqual(len(self.appointments()), 2)

    def test_a_persistent_server_error_saves_nothing(self):
        self.many(1)
        client, _, _ = self.connect()
        self.fake.push("/scheduled_events", Response(500, {}), Response(500, {}))
        failed = self.sync(client)
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(self.appointments(), [])

    def test_malformed_events_and_unknown_statuses_are_skipped_not_counted(self):
        no_time = {**event("NOTIME", -3, "canceled"), "start_time": None}
        bad_time = {**event("BADTIME", -3), "start_time": "yesterday"}
        self.fake.events = [event("PENDING", -2, "pending"), event("ODD", -1), no_time, bad_time]
        self.fake.invitees = {"PENDING": [invitee("PENDING", "I1")], "ODD": [invitee("ODD", "I2", status="weird")],
                              "NOTIME": [invitee("NOTIME", "I3", no_show={"uri": "x"})], "BADTIME": [invitee("BADTIME", "I4")]}
        client, _, _ = self.connect()
        result = self.sync(client)
        self.assertEqual(result.status_code, 200)
        self.assertEqual((result.get_json()["skipped"], result.get_json()["imported"]), (4, 0))
        self.assertEqual(self.appointments(), [])

    def run_racing_sync(self, client, *, during, budget=None):
        """Start sync A; while A is reading Calendly, ``during`` runs (sync B).
        Returns A's response."""
        real = self.fake.request
        state = {"fired": False}

        def racing(method, url, **kwargs):
            if url.endswith("/invitees") and not state["fired"]:
                state["fired"] = True
                self.fake.request = real
                during()  # B starts after A read its events page, and commits first
                self.fake.request = racing
            return real(method, url, **kwargs)

        self.fake.request = racing
        try:
            if budget is None:
                return self.sync(client)
            with patch.object(cal, "SYNC_REQUEST_BUDGET", budget):
                return self.sync(client)
        finally:
            self.fake.request = real

    def test_an_older_sync_finishing_last_cannot_undo_a_newer_cancellation(self):
        self.many(2)
        client, _, _ = self.connect()
        self.assertEqual(self.sync(client).get_json()["imported"], 2)
        revision = self.stored()[self.owner]["sync_revision"]

        def newer_sync_sees_a_cancellation():
            self.fake.events[0] = event("E000", -100, "canceled")
            newer = self.sync(self.client(self.owner)).get_json()
            self.assertEqual(newer["updated"], 1)

        older = self.run_racing_sync(client, during=newer_sync_sees_a_cancellation)
        self.assertEqual(older.status_code, 409)
        self.assertTrue(older.get_json()["superseded"])
        statuses = {r["calendly_event_id"]: r["status"] for r in self.appointments()}
        self.assertEqual(statuses["E000"], "cancelled")  # A had read it as active; its stale view was not written
        self.assertEqual(self.stored()[self.owner]["sync_revision"], revision + 1)
        self.assertEqual(self.stored()[self.owner]["last_sync"]["updated"], 1)

    def test_an_older_sync_finishing_last_cannot_reset_a_newer_continuation(self):
        self.many(6)
        client, _, _ = self.connect()
        with patch.object(cal, "PAGE_SIZE", 2):
            with patch.object(cal, "SYNC_REQUEST_BUDGET", 3):
                self.sync(client)  # pass in progress
            before = self.stored()[self.owner]["sync_cursor"]
            after_newer = {}

            def newer_sync_advances():
                with patch.object(cal, "SYNC_REQUEST_BUDGET", 3):
                    self.sync(self.client(self.owner))
                after_newer.update(self.stored()[self.owner]["sync_cursor"])

            older = self.run_racing_sync(client, during=newer_sync_advances, budget=3)
        self.assertEqual(older.status_code, 409)
        cursor = self.stored()[self.owner]["sync_cursor"]
        self.assertEqual(cursor, after_newer)
        self.assertGreater(cursor["events_seen"], before["events_seen"])

    def test_sequential_syncs_each_advance_the_revision(self):
        self.many(1)
        client, _, _ = self.connect()
        self.sync(client)
        self.sync(client)
        self.assertEqual(self.stored()[self.owner]["sync_revision"], 2)

    def test_a_sync_that_outlives_a_disconnect_writes_nothing(self):
        self.many(2)
        client, _, _ = self.connect()
        real = self.fake.request

        def disconnect_mid_read(method, url, **kwargs):
            if url.endswith("/E001/invitees") and self.owner in self.stored():
                app_calendly.revoke_workspace(self.owner)
            return real(method, url, **kwargs)

        self.fake.request = disconnect_mid_read
        with patch.dict(os.environ, CONFIG):
            response = client.post("/api/calendly/sync", headers=ORIGIN)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.appointments(), [])
        self.assertNotIn(self.owner, self.stored())

    def test_a_sync_that_outlives_a_reconnect_writes_nothing_and_its_cursor_is_not_reused(self):
        self.many(2)
        client, _, _ = self.connect()
        real = self.fake.request

        def reconnect_mid_read(method, url, **kwargs):
            if url.endswith("/E001/invitees"):
                data = self.stored()
                data[self.owner]["connection_id"] = "a-newer-connection"
                self.save(data)
            return real(method, url, **kwargs)

        self.fake.request = reconnect_mid_read
        self.assertEqual(self.sync(client).status_code, 409)
        self.assertEqual(self.appointments(), [])
        self.fake.request = real
        with patch.object(cal, "SYNC_REQUEST_BUDGET", 2):
            partial = self.sync(client).get_json()
        self.assertEqual(partial["stopped"], "budget")
        data = self.stored()
        data[self.owner]["connection_id"] = "yet-another"
        self.save(data)
        fresh = self.sync(client).get_json()
        self.assertFalse(fresh["continued"])  # a cursor from another connection starts over

    def test_workspaces_never_touch_each_others_calendly_data(self):
        self.fake.events = [event("PAST", -20)]
        self.fake.invitees = {"PAST": [invitee("PAST", "I1")]}
        client, _, _ = self.connect()
        self.sync(client)
        other = self.client(self.other)
        self.assertEqual(self.sync(other).status_code, 400)
        with patch.dict(os.environ, CONFIG):
            self.assertFalse(other.get("/api/calendly/status").get_json()["connected"])
            self.assertFalse(other.post("/api/calendly/disconnect", headers=ORIGIN).get_json()["was_connected"])
        self.assertEqual(self.appointments(self.other), [])
        self.assertEqual(len(self.appointments()), 1)
        self.assertIn(self.owner, self.stored())

    def test_disconnect_revokes_both_tokens_with_the_client_credentials_and_deletes_them(self):
        client, _, _ = self.connect()
        with patch.dict(os.environ, CONFIG):
            result = client.post("/api/calendly/disconnect", headers=ORIGIN).get_json()
        self.assertEqual((result["revoked"], result["was_connected"]), (True, True))
        revokes = [c for c in self.fake.calls if c["path"] == "/oauth/revoke"]
        self.assertEqual([c["data"]["token"] for c in revokes], ["refresh-1", "access-1"])
        self.assertEqual({(c["data"]["client_id"], c["data"]["client_secret"]) for c in revokes}, {("cal-client", "cal-secret")})
        self.assertNotIn(self.owner, self.stored())

    def test_a_failed_revoke_still_deletes_the_tokens_and_says_so(self):
        client, _, _ = self.connect()
        self.fake.push("/oauth/revoke", *[Response(500, {})] * 4)
        with patch.dict(os.environ, CONFIG):
            result = client.post("/api/calendly/disconnect", headers=ORIGIN).get_json()
        self.assertFalse(result["revoked"])
        self.assertIn("integrations", result["message"])
        self.assertNotIn(self.owner, self.stored())

    def test_workspace_purge_revokes_calendly(self):
        import app_account

        self.connect()
        with patch.dict(os.environ, CONFIG):
            app_account._purge_workspace(self.owner, dict(self.users))
        self.assertTrue(any(c["path"] == "/oauth/revoke" for c in self.fake.calls))
        self.assertNotIn(self.owner, self.stored())


    def delete_owner_workspace(self):
        """Account deletion as the purge does it: users first, then each store under its lock."""
        import app_account

        self.users.pop(self.owner)
        app_account._purge_workspace_json(self.owner)

    def test_a_sync_authenticated_before_deletion_writes_nothing_after_it(self):
        self.fake.events = [event("PAST", -20)]
        self.fake.invitees = {"PAST": [invitee("PAST", "I1")]}
        client, _, _ = self.connect()
        real = self.fake.request

        def delete_mid_read(method, url, **kwargs):
            if "/invitees" in url and self.owner in self.users:
                self.delete_owner_workspace()  # completes before the sync persists anything
            return real(method, url, **kwargs)

        self.fake.request = delete_mid_read
        response = self.sync(client)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.appointments(), [])
        self.assertNotIn(self.owner, retainai.load_appointments() or {})
        self.assertNotIn(self.owner, self.stored())

    def test_a_refresh_after_deletion_does_not_bring_the_connection_back(self):
        client, _, _ = self.connect()
        data = self.stored()
        data[self.owner]["expires_at"] = stamp(-1)
        self.save(data)
        original = app_calendly._update

        def deleting_update(change, guard=None):
            if self.owner in self.users:
                self.delete_owner_workspace()
            return original(change, guard)

        with patch.object(app_calendly, "_update", side_effect=deleting_update):
            self.assertEqual(self.sync(client).status_code, 401)
        self.assertNotIn(self.owner, self.stored())
        self.assertEqual([c["data"]["grant_type"] for c in self.token_calls()], ["authorization_code"])

    def test_a_writer_from_a_deleted_account_cannot_write_into_a_new_one_with_the_same_email(self):
        self.users[self.owner]["terms_accepted_at"] = "2026-11-01T00:00:00+00:00"
        self.fake.events = [event("PAST", -20)]
        self.fake.invitees = {"PAST": [invitee("PAST", "I1")]}
        client, _, _ = self.connect()
        real = self.fake.request

        def recreate_mid_read(method, url, **kwargs):
            if "/invitees" in url and self.users[self.owner].get("terms_accepted_at", "").startswith("2026-11-01"):
                self.delete_owner_workspace()
                self.users[self.owner] = {"email": self.owner, "role": "owner", "org_id": self.owner, "status": "active",
                                          "security_version": 0, "terms_accepted_at": "2026-11-07T00:00:00+00:00"}
            return real(method, url, **kwargs)

        self.fake.request = recreate_mid_read
        self.assertEqual(self.sync(client).status_code, 401)
        self.assertEqual(self.appointments(), [])


class StatusMappingTests(unittest.TestCase):
    def test_mapping(self):
        now = NOW
        cases = [
            (event("A", -1), {"status": "active"}, ("completed", False)),
            (event("A", 1), {"status": "active"}, ("scheduled", False)),
            (event("A", -1, "canceled"), {"status": "active"}, ("cancelled", False)),
            (event("A", 1), {"status": "canceled", "rescheduled": True}, ("cancelled", True)),
            (event("A", -1), {"status": "active", "no_show": {"uri": "x"}}, ("no-show", False)),
            ({"uri": "x", "status": "active", "start_time": "not a date"}, {"status": "active"}, (None, False)),
            ({"uri": "x", "status": "canceled", "start_time": None}, {"status": "canceled"}, (None, False)),
            ({"uri": "x", "status": "active", "start_time": None}, {"status": "active", "no_show": {"uri": "x"}}, (None, False)),
            (event("A", -1, "pending"), {"status": "active"}, (None, False)),
            (event("A", -1), {"status": "unknown"}, (None, False)),
            (event("A", -1), {}, (None, False)),
        ]
        for ev, inv, expected in cases:
            self.assertEqual(cal.map_status(ev, inv, now), expected)


if __name__ == "__main__":
    unittest.main()

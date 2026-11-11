"""Read-only Calendly booking import (owner-authorized, the owner's own events).

Follows Calendly's official developer docs (read November 6, 2026):

* Authorize at ``https://auth.calendly.com/oauth/authorize`` with ``client_id``,
  ``response_type=code``, ``redirect_uri`` and a PKCE challenge
  (``code_challenge_method=S256``). PKCE with S256 is required for every Calendly
  OAuth app. Scopes are selected when the app is registered and requested
  explicitly with ``scope`` (space separated). RetainAI requests only
  ``scheduled_events:read``, which covers ``GET /scheduled_events`` and
  ``GET /scheduled_events/{uuid}/invitees``. ``users:read`` is not needed: the
  token response names the connecting user (``owner``) and ``organization``.
  No webhook scope is requested; sync is manual.
* ``POST https://auth.calendly.com/oauth/token`` (form-encoded). A server app
  sends HTTP Basic client authentication plus ``client_id`` and ``code_verifier``.
  Access tokens last 2 hours. Refresh tokens rotate: each one works once and is
  revoked immediately on a successful refresh, so the new one must be stored
  before anything else happens.
* ``POST https://auth.calendly.com/oauth/revoke`` with ``token``, ``client_id``
  and ``client_secret`` in the form body.
* ``GET /scheduled_events?user=<owner uri>`` lists that
  user's own events (``status`` active/canceled, ``cancellation``), paged by
  ``pagination.next_page_token``. ``GET /scheduled_events/{uuid}/invitees``
  gives each invitee's ``email``, ``status``, ``timezone``, ``rescheduled``,
  ``new_invitee``, ``cancellation`` and ``no_show``.
* Rate limits: 50 requests/minute (free plans), 500 (paid). A 429 says to wait
  ``X-RateLimit-Reset`` seconds. RetainAI never sleeps for that inside a web
  request: a sync stops, saves where it got to, and reports when to try again.

Sync is incremental: each "Sync now" makes at most ``SYNC_REQUEST_BUDGET``
requests and starts no new request after about ``SYNC_TIME_BUDGET_SECONDS``
(not a hard deadline: the request already in flight can add up to its
``TIMEOUT_SECONDS``), and saves a server-side cursor (window,
page and position, bound to the connection and Calendly user; no credentials).
The next Sync continues from it. When the whole window has been read the cursor
is cleared, so the following Sync starts a fresh pass and picks up later
cancellations and reschedules.

Only an invitee's email is used, to match a contact the business already has.
No answers to booking questions, tracking parameters or payment details are
stored. Nothing here sends messages, starts automations or records consent.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import secrets
import time
from urllib.parse import urlencode

import requests

AUTH_BASE = "https://auth.calendly.com"
API_BASE = "https://api.calendly.com"
REQUIRED_SCOPES = ("scheduled_events:read",)
USER_URI_PREFIX = "https://api.calendly.com/users/"
LOOKBACK_DAYS, LOOKAHEAD_DAYS = 180, 60
MAX_EVENTS = 1000                 # per full pass over the window
MAX_INVITEES = 2000               # per full pass over the window
MAX_INVITEE_PAGES_PER_EVENT = 5
PAGE_SIZE = 100
REFRESH_MARGIN = dt.timedelta(minutes=5)
TIMEOUT_SECONDS = 10
SYNC_REQUEST_BUDGET = 40          # under the free plan's 50 requests/minute
SYNC_TIME_BUDGET_SECONDS = 20     # no new request after this; one in flight may add TIMEOUT_SECONDS
CURSOR_MAX_AGE = dt.timedelta(hours=24)
MAX_PAGES_PER_PASS = MAX_EVENTS // PAGE_SIZE + 5


class CalendlyError(RuntimeError):
    def __init__(self, message, *, status=0, code=""):
        super().__init__(message)
        self.status = status
        self.code = code


class CalendlyAuthError(CalendlyError):
    """The stored authorization no longer works; the owner must reconnect."""


class RateLimited(CalendlyError):
    def __init__(self, retry_after):
        super().__init__("Calendly's rate limit was reached.", status=429, code="rate_limited")
        self.retry_after = retry_after


class BudgetExhausted(CalendlyError):
    """This sync has used its request or time allowance; the next one continues."""


class Budget:
    def __init__(self, requests=None, seconds=None, clock=time.monotonic):
        self.clock = clock
        self.left = SYNC_REQUEST_BUDGET if requests is None else requests
        self.deadline = clock() + (SYNC_TIME_BUDGET_SECONDS if seconds is None else seconds)
        self.used = 0

    def spend(self):
        if self.left <= 0 or self.clock() >= self.deadline:
            raise BudgetExhausted("This sync reached its request or time limit.", code="budget")
        self.left -= 1
        self.used += 1


def pkce_pair():
    """A PKCE verifier (43-128 chars) and its S256 challenge."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    return verifier, challenge


def authorize_url(client_id, redirect_uri, state, challenge):
    return f"{AUTH_BASE}/oauth/authorize?" + urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri,
        "code_challenge_method": "S256", "code_challenge": challenge, "state": state,
        "scope": " ".join(REQUIRED_SCOPES),
    })


def granted_scopes_ok(tokens):
    """The token must carry scheduled_events:read. Calendly marks ``scope`` as
    optional in the token response; when it is absent, the first API read
    decides (a 403 there is reported, nothing is stored from it)."""
    scope = tokens.get("scope")
    if scope is None:
        return True
    granted = set(str(scope).split())
    # A ``:write`` scope includes its ``:read`` scope.
    return all(s in granted or s.replace(":read", ":write") in granted for s in REQUIRED_SCOPES)


def _utc(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    return parsed if 2000 <= parsed.year <= 2100 else None


def _iso(moment):
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def uuid_from_uri(uri):
    return str(uri or "").rstrip("/").rsplit("/", 1)[-1]


class CalendlyClient:
    def __init__(self, *, client_id, client_secret, redirect_uri, session=None, sleep=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = session or requests.Session()
        self.sleep = sleep or (lambda seconds: time.sleep(seconds))

    def _send(self, method, url, *, token=None, data=None, params=None, basic=False, attempts=2, budget=None):
        """One request, plus one short retry for a network or server error.
        A 429 is never waited out here: it is raised with Calendly's reset time."""
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        auth = (self.client_id, self.client_secret) if basic else None
        for attempt in range(attempts):
            if budget is not None:
                budget.spend()
            try:
                response = self.http.request(method, url, headers=headers, data=data, params=params, auth=auth, timeout=TIMEOUT_SECONDS)
            except requests.RequestException:
                if attempt == attempts - 1:
                    raise CalendlyError("Calendly could not be reached.", code="network") from None
                self.sleep(1)
                continue
            if response.status_code == 429:
                try:
                    reset = max(1, int((response.headers or {}).get("X-RateLimit-Reset") or 60))
                except (TypeError, ValueError):
                    reset = 60
                raise RateLimited(min(reset, 3600))
            if response.status_code >= 500:
                if attempt == attempts - 1:
                    raise CalendlyError("Calendly is busy; try again in a minute.", status=response.status_code, code="unavailable")
                self.sleep(1)
                continue
            try:
                body = response.json()
            except ValueError:
                body = {}
            body = body if isinstance(body, dict) else {}
            if response.status_code == 401:
                raise CalendlyAuthError("Calendly no longer accepts RetainAI's authorization.", status=401, code=str(body.get("title") or "unauthorized"))
            if response.status_code >= 400:
                raise CalendlyError(str(body.get("message") or body.get("error_description") or "Calendly rejected the request.")[:300],
                                    status=response.status_code, code=str(body.get("error") or body.get("title") or ""))
            return body
        raise CalendlyError("Calendly request failed.")  # pragma: no cover

    # OAuth -----------------------------------------------------------------
    def exchange_code(self, code, verifier):
        return self._send("POST", f"{AUTH_BASE}/oauth/token", basic=True, attempts=1, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
            "client_id": self.client_id, "code_verifier": verifier,
        })

    def refresh(self, refresh_token):
        """One attempt only: a rotated refresh token can't be reused after a lost response."""
        try:
            return self._send("POST", f"{AUTH_BASE}/oauth/token", basic=True, attempts=1, data={
                "grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.client_id,
            })
        except CalendlyError as exc:
            if exc.status in (400, 401):
                raise CalendlyAuthError("Calendly refused to renew the authorization.", status=exc.status, code=exc.code) from None
            raise

    def revoke(self, token):
        return self._send("POST", f"{AUTH_BASE}/oauth/revoke", attempts=2, data={
            "token": token, "client_id": self.client_id, "client_secret": self.client_secret,
        })

    # API (GET only) ----------------------------------------------------------
    def events(self, token, user_uri, start, end, page_token=None, budget=None):
        params = {"user": user_uri, "min_start_time": _iso(start), "max_start_time": _iso(end),
                  "count": PAGE_SIZE, "sort": "start_time:asc"}
        if page_token:
            params["page_token"] = page_token
        return self._send("GET", f"{API_BASE}/scheduled_events", token=token, params=params, budget=budget)

    def invitees(self, token, event_uuid, page_token=None, budget=None):
        params = {"count": PAGE_SIZE}
        if page_token:
            params["page_token"] = page_token
        return self._send("GET", f"{API_BASE}/scheduled_events/{event_uuid}/invitees", token=token, params=params, budget=budget)


def _token_key(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:16]


def new_cursor(connection_id, user_uri, now):
    """A pass over a fixed window, so page tokens stay consistent across syncs."""
    return {
        "connection_id": connection_id, "user_uri": user_uri,
        "window_start": _iso(now - dt.timedelta(days=LOOKBACK_DAYS)),
        "window_end": _iso(now + dt.timedelta(days=LOOKAHEAD_DAYS)),
        "started_at": _iso(now), "page": None, "skip": 0,
        "events_seen": 0, "invitees_seen": 0, "seen_pages": [],
    }


def cursor_for(stored, connection_id, user_uri, now):
    """Continue a saved pass only if it belongs to this connection and user and is recent."""
    started = _utc((stored or {}).get("started_at")) if isinstance(stored, dict) else None
    if (started and stored.get("connection_id") == connection_id and stored.get("user_uri") == user_uri
            and now - started <= CURSOR_MAX_AGE and _utc(stored.get("window_start")) and _utc(stored.get("window_end"))
            and isinstance(stored.get("seen_pages"), list) and isinstance(stored.get("skip"), int)):
        return dict(stored), True
    return new_cursor(connection_id, user_uri, now), False


def _collection(body):
    return [item for item in (body.get("collection") or []) if isinstance(item, dict) and item.get("uri")]


def _next_page(body):
    token = (body.get("pagination") or {}).get("next_page_token") if isinstance(body.get("pagination"), dict) else None
    return str(token) if token else None


def _event_invitees(client, call, event, remaining, budget):
    """All of one event's invitees, at most ``remaining``. Returns (invitees, partial)."""
    out, page, seen = [], None, set()
    for _ in range(MAX_INVITEE_PAGES_PER_EVENT):
        body = call(lambda token: client.invitees(token, uuid_from_uri(event["uri"]), page, budget=budget))
        for invitee in _collection(body):
            out.append(invitee)
            if len(out) >= remaining:
                return out, True
        nxt = _next_page(body)
        if not nxt:
            return out, False
        if nxt == page or nxt in seen:  # a repeating page token would never end
            return out, True
        seen.add(nxt)
        page = nxt
    return out, True


def fetch_step(client, call, cursor, budget):
    """Read as far as this sync's budget allows, from ``cursor``.

    ``call(fn)`` runs ``fn(access_token)`` and renews the token once on a 401.
    Returns a dict: ``pairs`` (event, invitee) for every event read completely
    in this step, ``events``, the advanced ``cursor``, and ``state``:
    ``complete`` / ``truncated`` (pass finished), or ``budget`` /
    ``rate_limited`` (stopped early; the cursor says where to continue).
    """
    cur = dict(cursor)
    cur["seen_pages"] = list(cur.get("seen_pages") or [])
    start, end = _utc(cur["window_start"]), _utc(cur["window_end"])
    pairs, events, notes = [], 0, set()

    def result(state, retry_after=None):
        return {"pairs": pairs, "events": events, "cursor": cur, "state": state,
                "retry_after": retry_after, "notes": sorted(notes)}

    try:
        while True:
            page = cur.get("page")
            body = call(lambda token: client.events(token, cur["user_uri"], start, end, page, budget=budget))
            collection = _collection(body)
            for index in range(int(cur.get("skip") or 0), len(collection)):
                if cur["events_seen"] >= MAX_EVENTS:
                    notes.add("event_limit")
                    return result("truncated")
                event = collection[index]
                remaining = MAX_INVITEES - cur["invitees_seen"]
                invitees, partial = _event_invitees(client, call, event, remaining, budget)
                # Only now, with the whole event read, does the cursor move past it.
                pairs.extend((event, invitee) for invitee in invitees)
                events += 1
                cur["skip"] = index + 1
                cur["events_seen"] += 1
                cur["invitees_seen"] += len(invitees)
                if partial:
                    notes.add("invitee_limit" if cur["invitees_seen"] >= MAX_INVITEES else "event_invitees_capped")
                if cur["invitees_seen"] >= MAX_INVITEES:
                    return result("truncated")
            nxt = _next_page(body)
            if not nxt:
                return result("complete")
            key = _token_key(nxt)
            if nxt == page or key in cur["seen_pages"]:
                notes.add("pagination_loop")
                return result("truncated")
            if len(cur["seen_pages"]) >= MAX_PAGES_PER_PASS:
                notes.add("event_limit")
                return result("truncated")
            cur["seen_pages"].append(key)
            cur["page"], cur["skip"] = nxt, 0
    except BudgetExhausted:
        return result("budget")
    except RateLimited as exc:
        return result("rate_limited", exc.retry_after)


EVENT_STATUSES = {"active", "canceled"}
INVITEE_STATUSES = {"active", "canceled"}


def map_status(event, invitee, now):
    """Calendly event + invitee -> (RetainAI status, rescheduled), or (None, False) to skip.

    Malformed rows (no valid start time) and statuses Calendly doesn't
    document are skipped whatever else they say, so nothing unknown is ever
    counted as a visit.
    """
    start = _utc(event.get("start_time"))
    event_status = str(event.get("status") or "").lower()
    invitee_status = str(invitee.get("status") or "").lower()
    if not start or event_status not in EVENT_STATUSES or invitee_status not in INVITEE_STATUSES:
        return None, False
    rescheduled = bool(invitee.get("rescheduled"))
    if "canceled" in (event_status, invitee_status):
        return "cancelled", rescheduled
    if invitee.get("no_show"):
        return "no-show", False
    # Calendly has no "completed" status: an active booking whose start time has
    # passed, not canceled and not marked no-show, is treated as completed.
    return ("completed" if start <= now else "scheduled"), False


def email_index(leads):
    index = {}
    for lead in leads or []:
        email = str((lead or {}).get("email") or "").strip().lower() if isinstance(lead, dict) else ""
        if email and lead.get("id"):
            index.setdefault(email, []).append(lead)
    return index


def to_appointment(event, invitee, lead, *, workspace, timezone_name, status, rescheduled):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    start, end = _utc(event.get("start_time")), _utc(event.get("end_time"))
    if not start:
        raise ValueError("A Calendly event without a valid start time can't be imported.")
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = dt.timezone.utc
    duration = int((end - start).total_seconds() // 60) if start and end and end > start else 30
    terminal = status in ("completed", "cancelled", "no-show")
    event_id, invitee_id = uuid_from_uri(event["uri"]), uuid_from_uri(invitee["uri"])
    cancellation = invitee.get("cancellation") or event.get("cancellation") or {}
    cancellation = cancellation if isinstance(cancellation, dict) else {}
    return {
        "id": f"calendly:{event_id}:{invitee_id}",
        "source": "calendly",
        "calendly_event_id": event_id,
        "calendly_invitee_id": invitee_id,
        "calendly_status": str(event.get("status") or ""),
        "calendly_invitee_status": str(invitee.get("status") or ""),
        "calendly_rescheduled": rescheduled,
        "calendly_new_invitee": uuid_from_uri(invitee.get("new_invitee")) if invitee.get("new_invitee") else "",
        "calendly_canceled_by": str(cancellation.get("canceler_type") or "")[:20],
        "calendly_start_utc": event.get("start_time") or "",
        "invitee_timezone": str(invitee.get("timezone") or "")[:64],
        "lead_id": str(lead.get("id")),
        "lead_email": str(lead.get("email") or "").strip().lower(),
        "lead_full_name": lead.get("name") or "",
        "user_email": workspace,
        "title": str(event.get("name") or "Calendly booking")[:160],
        "appointment_time": start.astimezone(zone).strftime("%Y-%m-%dT%H:%M:%S"),
        "timezone": getattr(zone, "key", "UTC"),
        "duration": max(5, min(duration, 1440)),
        "status": status,
        # The status this sync last wrote. A different current status was set
        # by the owner in RetainAI (see app_calendly's merge on re-sync).
        "calendly_synced_status": status,
        "done": terminal,
        "completed": status == "completed",
        "is_done": terminal,
        # When the invitee booked: the confirmation time the Value Receipt uses
        # if the owner ties a payment to this booking.
        "created_at": invitee.get("created_at") or event.get("created_at") or "",
        "updated_at": invitee.get("updated_at") or event.get("updated_at") or "",
        "notes": "",
    }

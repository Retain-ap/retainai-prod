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
  ``X-RateLimit-Reset`` seconds.

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
MAX_EVENTS = 1000
MAX_INVITEES = 2000
PAGE_SIZE = 100
REFRESH_MARGIN = dt.timedelta(minutes=5)
TIMEOUT_SECONDS = 15
MAX_RATE_LIMIT_WAIT = 65


class CalendlyError(RuntimeError):
    def __init__(self, message, *, status=0, code=""):
        super().__init__(message)
        self.status = status
        self.code = code


class CalendlyAuthError(CalendlyError):
    """The stored authorization no longer works; the owner must reconnect."""


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

    def _send(self, method, url, *, token=None, data=None, params=None, basic=False, attempts=3):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        auth = (self.client_id, self.client_secret) if basic else None
        for attempt in range(attempts):
            try:
                response = self.http.request(method, url, headers=headers, data=data, params=params, auth=auth, timeout=TIMEOUT_SECONDS)
            except requests.RequestException:
                if attempt == attempts - 1:
                    raise CalendlyError("Calendly could not be reached.", code="network") from None
                self.sleep(2 ** attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == attempts - 1:
                    raise CalendlyError("Calendly is busy; try again in a minute.", status=response.status_code, code="unavailable")
                wait = 2 ** attempt
                if response.status_code == 429:
                    try:
                        wait = min(MAX_RATE_LIMIT_WAIT, max(1, int((response.headers or {}).get("X-RateLimit-Reset") or 60)))
                    except (TypeError, ValueError):
                        wait = 60
                self.sleep(wait)
                continue
            try:
                body = response.json()
            except ValueError:
                body = {}
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
    def events(self, token, user_uri, start, end, page_token=None):
        params = {"user": user_uri, "min_start_time": _iso(start), "max_start_time": _iso(end),
                  "count": PAGE_SIZE, "sort": "start_time:asc"}
        if page_token:
            params["page_token"] = page_token
        return self._send("GET", f"{API_BASE}/scheduled_events", token=token, params=params)

    def invitees(self, token, event_uuid, page_token=None):
        params = {"count": PAGE_SIZE}
        if page_token:
            params["page_token"] = page_token
        return self._send("GET", f"{API_BASE}/scheduled_events/{event_uuid}/invitees", token=token, params=params)


def fetch(client, token, user_uri, now):
    """The user's events from LOOKBACK_DAYS ago to LOOKAHEAD_DAYS ahead, with invitees, bounded."""
    start, end = now - dt.timedelta(days=LOOKBACK_DAYS), now + dt.timedelta(days=LOOKAHEAD_DAYS)
    events, truncated, page = [], False, None
    while True:
        body = client.events(token, user_uri, start, end, page)
        for event in body.get("collection") or []:
            if isinstance(event, dict) and event.get("uri"):
                events.append(event)
                if len(events) >= MAX_EVENTS:
                    truncated = True
                    break
        page = (body.get("pagination") or {}).get("next_page_token")
        if truncated or not page:
            break
    pairs, invitee_count = [], 0
    for event in events:
        page = None
        while True:
            body = client.invitees(token, uuid_from_uri(event["uri"]), page)
            for invitee in body.get("collection") or []:
                if isinstance(invitee, dict) and invitee.get("uri"):
                    pairs.append((event, invitee))
                    invitee_count += 1
            page = (body.get("pagination") or {}).get("next_page_token")
            if invitee_count >= MAX_INVITEES:
                truncated = True
                break
            if not page:
                break
        if truncated:
            break
    return events, pairs, truncated


def map_status(event, invitee, now):
    """Calendly event + invitee -> (RetainAI status, rescheduled)."""
    rescheduled = bool(invitee.get("rescheduled"))
    if str(event.get("status") or "").lower() == "canceled" or str(invitee.get("status") or "").lower() == "canceled":
        return "cancelled", rescheduled
    if invitee.get("no_show"):
        return "no-show", False
    start = _utc(event.get("start_time"))
    if not start:
        return None, False
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
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = dt.timezone.utc
    duration = int((end - start).total_seconds() // 60) if start and end and end > start else 30
    terminal = status in ("completed", "cancelled", "no-show")
    event_id, invitee_id = uuid_from_uri(event["uri"]), uuid_from_uri(invitee["uri"])
    cancellation = invitee.get("cancellation") or event.get("cancellation") or {}
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
        "done": terminal,
        "completed": status == "completed",
        "is_done": terminal,
        # When the invitee booked: the confirmation time the Value Receipt uses
        # if the owner ties a payment to this booking.
        "created_at": invitee.get("created_at") or event.get("created_at") or "",
        "updated_at": invitee.get("updated_at") or event.get("updated_at") or "",
        "notes": "",
    }

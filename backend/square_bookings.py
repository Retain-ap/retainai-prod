"""Read-only Square Bookings import (seller-level, owner-authorized).

Follows Square's official OAuth and Bookings docs (read November 6, 2026):

* Authorize at ``{base}/oauth2/authorize`` with ``client_id``, space-separated
  ``scope``, ``session=false`` (production) and a server-generated ``state``.
* Code flow for this confidential server: ``POST {base}/oauth2/token`` with
  ``grant_type=authorization_code`` and the application secret. Square
  documents PKCE for public clients (it replaces the secret and makes refresh
  tokens single-use and 90-day expiring), so it is not used here; the CSRF
  ``state`` is single-use, short-lived and bound to the owner's session.
* Access tokens expire after 30 days; Square recommends renewing every 7 days
  or less (``grant_type=refresh_token``). Revoke with ``POST
  {base}/oauth2/revoke`` and ``Authorization: Client <secret>``.
* ``GET /v2/bookings`` (APPOINTMENTS_READ + APPOINTMENTS_ALL_READ for seller
  level) pages by ``cursor``; ``start_at_max`` defaults to 31 days after
  ``start_at_min``, so the import walks 31-day windows.
* ``GET /v2/customers/{id}`` (CUSTOMERS_READ) gives the email/phone used only
  to match existing RetainAI contacts. No contact is ever created.
* Booking statuses: PENDING, CANCELLED_BY_CUSTOMER, CANCELLED_BY_SELLER,
  DECLINED, ACCEPTED, NO_SHOW. Square has no "completed" status.

Nothing here sends messages, starts automations or records consent.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from urllib.parse import urlencode

import requests

SCOPES = ("APPOINTMENTS_READ", "APPOINTMENTS_ALL_READ", "CUSTOMERS_READ")
BASE_URLS = {"production": "https://connect.squareup.com", "sandbox": "https://connect.squareupsandbox.com"}
WINDOW_DAYS = 31
LOOKBACK_DAYS, LOOKAHEAD_DAYS = 180, 60
MAX_BOOKINGS = 2000
MAX_CUSTOMER_LOOKUPS = 500
REFRESH_AFTER = dt.timedelta(days=7)
TIMEOUT_SECONDS = 15


class SquareError(RuntimeError):
    def __init__(self, message, *, status=0, code=""):
        super().__init__(message)
        self.status = status
        self.code = code


class SquareAuthError(SquareError):
    """The stored authorization no longer works; the owner must reconnect."""


def _utc(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    return parsed if 2000 <= parsed.year <= 2100 else None


def _iso(moment):
    return moment.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def authorize_url(base, client_id, state, environment):
    params = {"client_id": client_id, "scope": " ".join(SCOPES), "state": state}
    if environment == "production":
        params["session"] = "false"
    return f"{base}/oauth2/authorize?{urlencode(params)}"


class SquareClient:
    """Minimal HTTP client with bounded retries for 429/5xx."""

    def __init__(self, base, *, client_id, client_secret, session=None, sleep=time.sleep):
        self.base = base.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = session or requests.Session()
        self.sleep = sleep

    def _request(self, method, path, *, token=None, json=None, params=None, auth_header=None, attempts=3):
        # No Square-Version header: Square then applies the API version set on
        # the application in its Developer Console.
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if auth_header:
            headers["Authorization"] = auth_header
        for attempt in range(attempts):
            try:
                response = self.http.request(method, f"{self.base}{path}", headers=headers, json=json, params=params, timeout=TIMEOUT_SECONDS)
            except requests.RequestException:
                if attempt == attempts - 1:
                    raise SquareError("Square could not be reached.", code="network") from None
                self.sleep(2 ** attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == attempts - 1:
                    raise SquareError("Square is busy; try again later.", status=response.status_code, code="unavailable")
                self.sleep(2 ** attempt)
                continue
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.status_code == 401:
                raise SquareAuthError("Square no longer accepts RetainAI's authorization.", status=401, code="unauthorized")
            if response.status_code >= 400:
                errors = body.get("errors") or [{}]
                raise SquareError(str(errors[0].get("detail") or body.get("message") or "Square rejected the request.")[:300],
                                  status=response.status_code, code=str(errors[0].get("code") or body.get("type") or ""))
            return body
        raise SquareError("Square request failed.")  # pragma: no cover

    def exchange_code(self, code):
        return self._request("POST", "/oauth2/token", json={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "code": code, "grant_type": "authorization_code",
        }, attempts=1)

    def refresh(self, refresh_token):
        try:
            return self._request("POST", "/oauth2/token", json={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "refresh_token": refresh_token, "grant_type": "refresh_token",
            })
        except SquareError as exc:
            if exc.status in (400, 401):
                raise SquareAuthError("Square refused to renew the authorization.", status=exc.status, code=exc.code) from None
            raise

    def revoke(self, access_token):
        return self._request("POST", "/oauth2/revoke", json={"client_id": self.client_id, "access_token": access_token},
                             auth_header=f"Client {self.client_secret}", attempts=2)

    def list_bookings(self, token, start_min, start_max, cursor=None):
        params = {"limit": 100, "start_at_min": _iso(start_min), "start_at_max": _iso(start_max)}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/v2/bookings", token=token, params=params)

    def get_customer(self, token, customer_id):
        return self._request("GET", f"/v2/customers/{customer_id}", token=token).get("customer") or {}


def map_status(square_status, start_at, now):
    """Square status -> RetainAI status, or None to skip the booking."""
    status = str(square_status or "").upper()
    if status in ("CANCELLED_BY_CUSTOMER", "CANCELLED_BY_SELLER", "DECLINED"):
        return "cancelled"
    if status == "NO_SHOW":
        return "no-show"
    if status == "ACCEPTED":
        # Square has no completed status: a past accepted booking that was not
        # cancelled or marked no-show is treated as completed.
        return "completed" if start_at <= now else "scheduled"
    if status == "PENDING":
        return "scheduled" if start_at > now else None  # never confirmed and now past
    return None


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))[-10:]


def contact_index(leads):
    by_email, by_phone = {}, {}
    for lead in leads or []:
        if not isinstance(lead, dict) or not lead.get("id"):
            continue
        email = str(lead.get("email") or "").strip().lower()
        phone = _digits(lead.get("phone"))
        if email:
            by_email.setdefault(email, []).append(lead)
        if len(phone) == 10:
            by_phone.setdefault(phone, []).append(lead)
    return by_email, by_phone


def match_contact(customer, by_email, by_phone):
    """Exactly one existing contact by email, else by phone; never guesses."""
    email = str(customer.get("email_address") or "").strip().lower()
    if email and len(by_email.get(email) or []) == 1:
        return by_email[email][0]
    phone = _digits(customer.get("phone_number"))
    if len(phone) == 10 and len(by_phone.get(phone) or []) == 1:
        return by_phone[phone][0]
    return None


def to_appointment(booking, lead, *, workspace, timezone_name, status):
    start = _utc(booking.get("start_at"))
    segments = booking.get("appointment_segments") or []
    duration = sum(int(seg.get("duration_minutes") or 0) for seg in segments if isinstance(seg, dict)) or 30
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = dt.timezone.utc
    local = start.astimezone(zone)
    terminal = status in ("completed", "cancelled", "no-show")
    name = " ".join(part for part in (lead.get("first_name"), lead.get("last_name")) if part) or lead.get("name") or ""
    return {
        "id": f"square:{booking['id']}",
        "source": "square",
        "square_booking_id": booking["id"],
        "square_version": int(booking.get("version") or 0),
        "square_status": str(booking.get("status") or ""),
        "square_location_id": str(booking.get("location_id") or ""),
        "lead_id": str(lead.get("id")),
        "lead_email": str(lead.get("email") or "").strip().lower(),
        "lead_full_name": name,
        "user_email": workspace,
        "title": "Square booking",
        "appointment_time": local.strftime("%Y-%m-%dT%H:%M:%S"),
        "timezone": getattr(zone, "key", "UTC"),
        "duration": max(5, min(duration, 1440)),
        "status": status,
        "done": terminal,
        "completed": status == "completed",
        "is_done": terminal,
        "created_at": booking.get("created_at") or _iso(dt.datetime.now(dt.timezone.utc)),
        "updated_at": booking.get("updated_at") or booking.get("created_at") or "",
        "notes": "",
    }


def fetch_bookings(client, token, now):
    """All bookings from LOOKBACK_DAYS ago to LOOKAHEAD_DAYS ahead, bounded."""
    bookings, truncated = [], False
    start = now - dt.timedelta(days=LOOKBACK_DAYS)
    end = now + dt.timedelta(days=LOOKAHEAD_DAYS)
    seen = set()
    while start < end and not truncated:
        window_end = min(end, start + dt.timedelta(days=WINDOW_DAYS))
        cursor = None
        while True:
            page = client.list_bookings(token, start, window_end, cursor)
            for booking in page.get("bookings") or []:
                if isinstance(booking, dict) and booking.get("id") and booking["id"] not in seen:
                    seen.add(booking["id"])
                    bookings.append(booking)
                    if len(bookings) >= MAX_BOOKINGS:
                        truncated = True
                        break
            cursor = page.get("cursor")
            if truncated or not cursor:
                break
        start = window_end
    return bookings, truncated

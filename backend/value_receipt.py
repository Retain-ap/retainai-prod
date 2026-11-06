"""Verified revenue evidence for the Value Receipt.

The receipt only counts money a business actually received from its own
customers, and only when the record shows a RetainAI follow-up came before
a confirmed booking or an issued invoice that was then paid. That sequence is
reported as a link, never as proof the follow-up caused the payment.

Payment evidence is kept in three clearly separate kinds:

* ``provider_verified``: a paid invoice from the business's own connected
  Stripe account whose expanded charge is live, paid, succeeded, in the same
  currency and for the full amount the invoice says was paid. Never
  RetainAI's membership billing.
* ``owner_recorded``: an amount the owner typed in, or an invoice the owner
  marked as paid outside Stripe.
* ``unconfirmed``: Stripe shows the invoice as paid but no matching successful
  charge proves it (for example settled from a customer credit balance or a
  minimum-amount rule, or the charge could not be read). Shown, never counted.

Supported Stripe contract: API version 2023-10-16 (pinned on every read), where
an invoice's payment is its ``charge``. Newer versions move payments to the
``payments`` list; they are not read here and must not be assumed.

Amounts are integers in the currency's minor unit and are never added across
currencies. This module has no Flask or app imports so the rules can be tested
on their own.
"""

from __future__ import annotations

import csv
import datetime as dt
import fcntl
import io
import json
import os
import re
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

STRIPE_API_VERSION = "2023-10-16"
# Currencies RetainAI businesses invoice in, with their minor-unit exponent.
CURRENCY_EXPONENTS = {
    "cad": 2, "usd": 2, "eur": 2, "gbp": 2, "aud": 2, "nzd": 2, "chf": 2,
    "sek": 2, "nok": 2, "dkk": 2, "mxn": 2, "inr": 2, "sgd": 2, "hkd": 2,
    "zar": 2, "brl": 2, "pln": 2, "czk": 2, "jpy": 0, "krw": 0,
}
DEFAULT_WINDOW_DAYS = 30
MIN_WINDOW_DAYS, MAX_WINDOW_DAYS = 7, 90
MAX_PERIOD_DAYS = 400
MAX_AMOUNT_MINOR = 100_000_000  # 1,000,000.00 in a two-decimal currency
MAX_MANUAL_RECORDS = 5000
EARLIEST_YEAR, LATEST_YEAR = 2000, 2100
BOOKING_STATUSES = {"scheduled", "completed"}

# Notifications RetainAI writes only after an email was actually accepted for
# delivery. Used for follow-ups sent before the follow-up log existed.
LEGACY_EMAIL_SUBJECTS = {"AI email sent": "email", "Automation email sent": "email"}

VERIFIED = "provider_verified"
OWNER = "owner_recorded"
UNCONFIRMED = "unconfirmed"

SETTLEMENT_TEXT = {
    "charge": "Paid by a successful Stripe charge",
    "outside_stripe": "Marked as paid outside Stripe by the business",
    "no_charge": "Stripe shows paid with no charge (credit balance, minimum amount or other settlement)",
    "charge_unreadable": "Stripe's charge for this invoice could not be read",
    "charge_incomplete": "The charge does not prove the full paid amount was collected (not captured, partly captured, or different)",
    "disputed": "The customer disputed this charge",
    "manual": "Recorded by the owner",
}


class EvidenceError(ValueError):
    """A request that cannot be accepted as given (shown to the owner)."""


class EvidenceStoreError(RuntimeError):
    """The evidence file exists but can't be read; nothing may be written."""


# ---------------------------------------------------------------- utilities

def _valid_year(moment):
    return moment if moment and EARLIEST_YEAR <= moment.year <= LATEST_YEAR else None


def _utc(value):
    """Parse an ISO string or epoch seconds to an aware UTC datetime, or None."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            return _valid_year(dt.datetime.fromtimestamp(float(value), dt.timezone.utc))
        if isinstance(value, dt.datetime):
            return _valid_year(value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc))
        parsed = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return None
    return _valid_year(parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc))


def _iso(moment):
    return moment.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z") if moment else ""


def _email(value):
    return str(value or "").strip().lower()


def _zone(name):
    try:
        return ZoneInfo(str(name or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        return dt.timezone.utc


def normalize_currency(value):
    currency = str(value or "").strip().lower()
    if currency not in CURRENCY_EXPONENTS:
        raise EvidenceError("Choose a supported currency.")
    return currency


def to_minor(amount, currency):
    """Exact decimal -> minor units. Rejects extra precision instead of rounding money."""
    exponent = CURRENCY_EXPONENTS[normalize_currency(currency)]
    try:
        value = Decimal(str(amount).strip())
    except (InvalidOperation, AttributeError):
        raise EvidenceError("Enter the amount as a number.") from None
    if not value.is_finite():
        raise EvidenceError("Enter the amount as a number.")
    scaled = value * (Decimal(10) ** exponent)
    if scaled != scaled.to_integral_value():
        raise EvidenceError(f"Use at most {exponent} decimal places for {currency.upper()}.")
    minor = int(scaled.to_integral_value(ROUND_HALF_UP))
    if minor <= 0 or minor > MAX_AMOUNT_MINOR:
        raise EvidenceError("Enter an amount above zero and at most 1,000,000.")
    return minor


def format_minor(minor, currency):
    exponent = CURRENCY_EXPONENTS.get(currency, 2)
    return f"{Decimal(minor) / (Decimal(10) ** exponent):.{exponent}f}"


def parse_window(value):
    if value in (None, ""):
        return DEFAULT_WINDOW_DAYS
    try:
        days = int(str(value).strip())
    except ValueError:
        raise EvidenceError("The follow-up window must be a whole number of days.") from None
    if not MIN_WINDOW_DAYS <= days <= MAX_WINDOW_DAYS:
        raise EvidenceError(f"Choose a follow-up window from {MIN_WINDOW_DAYS} to {MAX_WINDOW_DAYS} days.")
    return days


@contextmanager
def _locked(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(f"{path}.lock", "a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read(path):
    """Missing file -> empty. Anything else unreadable fails closed, so a
    following write can never replace stored evidence with an empty file."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise EvidenceStoreError(f"{os.path.basename(path)} could not be read") from exc
    if not isinstance(data, dict):
        raise EvidenceStoreError(f"{os.path.basename(path)} has an unexpected format")
    return data


def _write(path, data):
    temp = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def valid_bookings_for(lead, appointments):
    """This contact's bookings that can confirm a sale (scheduled or completed)."""
    lead_id, email = str((lead or {}).get("id") or ""), _email((lead or {}).get("email"))
    rows = []
    for appt in appointments or []:
        if not isinstance(appt, dict) or not appt.get("id"):
            continue
        status = str(appt.get("status") or "scheduled").lower()
        same = (lead_id and str(appt.get("lead_id") or "") == lead_id) or (email and _email(appt.get("lead_email")) == email)
        if same and status in BOOKING_STATUSES and _utc(appt.get("created_at")):
            rows.append(appt)
    return rows


# ---------------------------------------------------------- revenue evidence

class RevenueStore:
    """Per-workspace payment evidence keyed so the same payment is stored once."""

    def __init__(self, path):
        self.path = path

    def records(self, workspace):
        bucket = _read(self.path).get(workspace) or {}
        return list((bucket.get("records") or {}).values())

    def meta(self, workspace):
        bucket = _read(self.path).get(workspace) or {}
        return {"last_sync": bucket.get("last_sync") or None}

    @contextmanager
    def _bucket(self, workspace):
        with _locked(self.path):
            data = _read(self.path)
            bucket = data.setdefault(workspace, {})
            bucket.setdefault("records", {})
            yield bucket
            _write(self.path, data)

    def upsert_stripe(self, workspace, records, synced_at, *, complete):
        """Store invoices read from the workspace's own Stripe account.

        Re-reading the same invoice updates its refund figures; nothing is
        double counted or deleted. Stored Stripe payments this read did not
        reach keep their old refund figures and are reported as not
        re-checked.
        """
        added = updated = 0
        seen = set()
        with self._bucket(workspace) as bucket:
            stored = bucket["records"]
            for record in records:
                key = record["id"]
                seen.add(key)
                record["checked_at"] = synced_at
                if key in stored:
                    previous = stored[key]
                    record["recorded_at"] = previous.get("recorded_at") or synced_at
                    compare = {k: v for k, v in previous.items() if k != "checked_at"}
                    if compare != {k: v for k, v in record.items() if k != "checked_at"}:
                        updated += 1
                else:
                    record["recorded_at"] = synced_at
                    added += 1
                stored[key] = record
            not_refreshed = sum(1 for key, item in stored.items() if item.get("source") == "stripe" and key not in seen)
            bucket["last_sync"] = {"at": synced_at, "complete": bool(complete), "read": len(records), "not_refreshed": not_refreshed}
        return {"added": added, "updated": updated, "not_refreshed": not_refreshed, "complete": bool(complete)}

    def add_manual(self, workspace, payload, *, lead, recorded_by, now, timezone_name="UTC", bookings=()):
        key = str(payload.get("idempotency_key") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise EvidenceError("A valid idempotency key is required.")
        currency = normalize_currency(payload.get("currency"))
        amount_minor = to_minor(payload.get("amount"), currency)
        zone = _zone(timezone_name)
        paid_on_text = str(payload.get("paid_at") or "").strip()[:10]
        try:
            paid_on = dt.date.fromisoformat(paid_on_text)
        except ValueError:
            raise EvidenceError("Enter the date the payment was received.") from None
        paid_time = str(payload.get("paid_time") or "").strip()
        if paid_time and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", paid_time):
            raise EvidenceError("Enter the time as HH:MM.")
        if not EARLIEST_YEAR <= paid_on.year <= LATEST_YEAR or paid_on > now.astimezone(zone).date():
            raise EvidenceError("The payment date can't be in the future.")
        if paid_time:
            hours, minutes = (int(part) for part in paid_time.split(":"))
            paid_at = dt.datetime.combine(paid_on, dt.time(hours, minutes), zone)
            if paid_at > now:
                raise EvidenceError("The payment time can't be in the future.")
        else:
            # Only the day is known: keep it as a day, never invent a time.
            paid_at = dt.datetime.combine(paid_on, dt.time(0), zone)
        reference = str(payload.get("reference") or "").strip()[:120]
        booking_id = str(payload.get("appointment_id") or "").strip()
        if booking_id and booking_id not in {str(row.get("id") or "") for row in valid_bookings_for(lead, bookings)}:
            raise EvidenceError("Choose one of this customer's bookings, or leave the booking empty.")
        record = {
            "id": f"manual:{key}",
            "source": "manual",
            "verification": OWNER,
            "settlement": "manual",
            "amount_minor": amount_minor,
            "refunded_minor": 0,
            "currency": currency,
            "paid_at": _iso(paid_at),
            "paid_precision": "time" if paid_time else "day",
            "paid_day_start": _iso(dt.datetime.combine(paid_on, dt.time(0), zone)),
            "paid_day_end": _iso(dt.datetime.combine(paid_on + dt.timedelta(days=1), dt.time(0), zone)),
            "lead_id": str(lead.get("id") or ""),
            "customer_email": _email(lead.get("email")),
            "customer_name": str(lead.get("name") or "")[:160],
            "reference": reference,
            "booking_ref": booking_id,
            "livemode": True,
            "recorded_by": recorded_by,
            "recorded_at": _iso(now),
        }
        identity = {k: record[k] for k in ("amount_minor", "currency", "paid_at", "paid_precision", "lead_id", "reference", "booking_ref")}
        with self._bucket(workspace) as bucket:
            stored = bucket["records"]
            existing = stored.get(record["id"])
            if existing:
                if {k: existing.get(k) for k in identity} != identity:
                    raise EvidenceError("This idempotency key was already used for a different payment.")
                return existing, False
            if sum(1 for item in stored.values() if item.get("source") == "manual") >= MAX_MANUAL_RECORDS:
                raise EvidenceError("Too many recorded payments; remove old ones first.")
            stored[record["id"]] = record
        return record, True

    def set_manual_refund(self, workspace, record_id, refunded, now):
        with self._bucket(workspace) as bucket:
            record = bucket["records"].get(record_id)
            if not record or record.get("source") != "manual":
                raise KeyError(record_id)
            refunded_minor = 0 if str(refunded).strip() in ("", "0", "0.0", "0.00") else to_minor(refunded, record["currency"])
            if refunded_minor > record["amount_minor"]:
                raise EvidenceError("A refund can't be larger than the payment.")
            record["refunded_minor"] = refunded_minor
            record["refund_recorded_at"] = _iso(now)
            return record

    def delete_manual(self, workspace, record_id):
        with self._bucket(workspace) as bucket:
            record = bucket["records"].get(record_id)
            if not record or record.get("source") != "manual":
                raise KeyError(record_id)
            del bucket["records"][record_id]


def _field(obj, *path):
    for key in path:
        if obj is None:
            return None
        obj = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return obj


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def stripe_invoice_record(invoice, account_id):
    """Evidence from one paid invoice, read with API version 2023-10-16.

    Provider-verified only when the expanded ``charge`` proves collected
    money: paid, succeeded, captured for exactly the amount Stripe reports as
    paid, not disputed, live like the invoice and in the same currency. Anything else is kept as unconfirmed, or
    as owner-recorded when the business marked it paid outside Stripe.
    Returns None for anything that is not a paid invoice with a valid time.
    """
    if str(_field(invoice, "status") or "") != "paid":
        return None
    currency = str(_field(invoice, "currency") or "").lower()
    if currency not in CURRENCY_EXPONENTS:
        return None
    amount_paid = _int(_field(invoice, "amount_paid"))
    paid_at = _utc(_field(invoice, "status_transitions", "paid_at"))
    if amount_paid <= 0 or not paid_at:
        return None
    livemode = bool(_field(invoice, "livemode"))
    charge = _field(invoice, "charge")
    refunded = 0
    if bool(_field(invoice, "paid_out_of_band")):
        verification, settlement = OWNER, "outside_stripe"
    elif not charge:
        verification, settlement = UNCONFIRMED, "no_charge"
    elif isinstance(charge, str):
        verification, settlement = UNCONFIRMED, "charge_unreadable"
    elif _field(charge, "disputed") is True:
        # Money under dispute may be reversed: never call it collected revenue.
        verification, settlement = UNCONFIRMED, "disputed"
    elif (
        _field(charge, "paid") is True
        and str(_field(charge, "status") or "") == "succeeded"
        # paid/succeeded can be an uncaptured authorization: require the
        # charge to be captured for exactly the amount the invoice says paid.
        and _field(charge, "captured") is True
        and _int(_field(charge, "amount_captured")) == amount_paid
        and str(_field(charge, "currency") or "").lower() == currency
        and bool(_field(charge, "livemode")) == livemode
        and _int(_field(charge, "amount")) == amount_paid
    ):
        verification, settlement = VERIFIED, "charge"
        # A credit note that refunds money also refunds the charge: take the
        # larger figure instead of adding them, so it is subtracted once.
        refunded = min(amount_paid, max(_int(_field(charge, "amount_refunded")),
                                        _int(_field(invoice, "post_payment_credit_notes_amount"))))
    else:
        verification, settlement = UNCONFIRMED, "charge_incomplete"
    if verification != VERIFIED:
        refunded = min(amount_paid, _int(_field(invoice, "post_payment_credit_notes_amount")))
    # The invoice itself is the confirmation: its own finalization time.
    issued_at = _utc(_field(invoice, "status_transitions", "finalized_at"))
    invoice_id = str(_field(invoice, "id") or "")
    booking_ref = str(_field(invoice, "metadata", "retainai_appointment_id") or "").strip()[:80]
    return {
        "id": f"stripe:{invoice_id}",
        "source": "stripe",
        "verification": verification,
        "settlement": settlement,
        "paid_outside_stripe": settlement == "outside_stripe",
        "amount_minor": amount_paid,
        "refunded_minor": refunded,
        "currency": currency,
        "paid_at": _iso(paid_at),
        "paid_precision": "time",
        "invoice_id": invoice_id,
        "invoice_number": str(_field(invoice, "number") or ""),
        "invoice_issued_at": _iso(issued_at),
        "booking_ref": booking_ref,
        "charge_id": str(_field(charge, "id") or "") if charge and not isinstance(charge, str) else "",
        "customer_email": _email(_field(invoice, "customer_email")),
        "customer_name": str(_field(invoice, "customer_name") or "")[:160],
        "stripe_account": account_id,
        "stripe_api_version": STRIPE_API_VERSION,
        "livemode": livemode,
    }


# -------------------------------------------------------------- follow-ups

class FollowupLog:
    """Outbound follow-ups RetainAI actually sent, appended at send time."""

    MAX_PER_WORKSPACE = 20000

    def __init__(self, path):
        self.path = path

    def record(self, workspace, *, lead_id="", lead_email="", channel, source, sent_at=None):
        workspace = _email(workspace)
        if not workspace or not (lead_id or lead_email):
            return None
        entry = {
            "id": uuid.uuid4().hex,
            "lead_id": str(lead_id or ""),
            "lead_email": _email(lead_email),
            "channel": str(channel),
            "source": str(source),
            "sent_at": _iso(_utc(sent_at) or dt.datetime.now(dt.timezone.utc)),
        }
        with _locked(self.path):
            data = _read(self.path)
            rows = data.get(workspace) if isinstance(data.get(workspace), list) else []
            rows.append(entry)
            data[workspace] = rows[-self.MAX_PER_WORKSPACE:]
            _write(self.path, data)
        return entry

    def entries(self, workspace):
        rows = _read(self.path).get(_email(workspace))
        return rows if isinstance(rows, list) else []


def collect_followups(workspace, *, log_entries, notifications, chats):
    """All recorded outbound follow-ups for one workspace, de-duplicated."""
    found = []
    for row in log_entries or []:
        found.append({**row, "evidence": "follow-up log"})
    for note in notifications or []:
        channel = LEGACY_EMAIL_SUBJECTS.get(str((note or {}).get("subject") or ""))
        if channel and note.get("lead_email") and note.get("timestamp"):
            found.append({
                "lead_id": "", "lead_email": _email(note["lead_email"]), "channel": channel,
                "source": "notification", "sent_at": note["timestamp"], "evidence": "sent-email notification",
            })
    for lead_id, thread in ((chats or {}).items() if isinstance(chats, dict) else []):
        for row in thread or []:
            direction = str((row or {}).get("direction") or (row or {}).get("from") or "").lower()
            when = (row or {}).get("time") or (row or {}).get("created_at")
            if direction in {"outbound", "user"} and when and str(row.get("status") or "").lower() != "failed":
                found.append({
                    "lead_id": str(lead_id), "lead_email": "", "channel": "whatsapp",
                    "source": "whatsapp", "sent_at": when, "evidence": "WhatsApp message record",
                })
    unique, seen = [], set()
    for row in found:
        moment = _utc(row.get("sent_at"))
        if not moment:
            continue
        key = (row.get("lead_id") or row.get("lead_email"), row.get("channel"), moment.replace(second=0, microsecond=0))
        if key in seen:
            continue
        seen.add(key)
        unique.append({**row, "_at": moment})
    return unique


# ---------------------------------------------------------------- receipt

def parse_period(since, until, timezone_name, now):
    """Inclusive local dates -> UTC [start, end). Defaults to the last 90 days."""
    zone = _zone(timezone_name)
    today = now.astimezone(zone).date()

    def day(value, fallback):
        if not value:
            return fallback
        try:
            parsed = dt.date.fromisoformat(str(value)[:10])
        except ValueError:
            raise EvidenceError("Use dates in YYYY-MM-DD format.") from None
        if not EARLIEST_YEAR <= parsed.year <= LATEST_YEAR:
            raise EvidenceError(f"Use dates between {EARLIEST_YEAR} and {LATEST_YEAR}.")
        return parsed

    end_day = day(until, today)
    start_day = day(since, end_day - dt.timedelta(days=89))
    if start_day > end_day:
        raise EvidenceError("The start date must be on or before the end date.")
    if (end_day - start_day).days > MAX_PERIOD_DAYS:
        raise EvidenceError(f"Choose a period of at most {MAX_PERIOD_DAYS} days.")
    start = dt.datetime.combine(start_day, dt.time(0), zone)
    end = dt.datetime.combine(end_day + dt.timedelta(days=1), dt.time(0), zone)
    return start, end, start_day.isoformat(), end_day.isoformat(), getattr(zone, "key", "UTC")


def _lead_for(record, leads_by_id, leads_by_email):
    if record.get("lead_id") and record["lead_id"] in leads_by_id:
        return leads_by_id[record["lead_id"]]
    matches = leads_by_email.get(record.get("customer_email") or "") or []
    return matches[0] if len(matches) == 1 else None


def build_receipt(*, records, leads, followups, appointments, start, end, window_days, last_sync=None, include_test=False):
    window = dt.timedelta(days=parse_window(window_days))
    last_sync_at = (last_sync or {}).get("at") or ""
    leads_by_id = {str(lead.get("id")): lead for lead in leads if isinstance(lead, dict) and lead.get("id")}
    leads_by_email = {}
    for lead in leads:
        if isinstance(lead, dict) and _email(lead.get("email")):
            leads_by_email.setdefault(_email(lead["email"]), []).append(lead)

    def followups_for(lead):
        lead_id, email = str(lead.get("id") or ""), _email(lead.get("email"))
        return sorted(
            (row for row in followups if (lead_id and row.get("lead_id") == lead_id) or (email and row.get("lead_email") == email)),
            key=lambda row: row["_at"],
        )

    items, totals = [], {}
    for record in records:
        paid_at = _utc(record.get("paid_at"))
        if not paid_at or not (start <= paid_at < end):
            continue
        day_only = record.get("paid_precision") == "day"
        # With only the payment day known, anything on that same day has an
        # unknown order relative to the payment, so it can't establish a link.
        before_payment = _utc(record.get("paid_day_start")) if day_only else paid_at
        same_day_end = _utc(record.get("paid_day_end")) if day_only else None
        currency = record.get("currency")
        net = int(record.get("amount_minor") or 0) - int(record.get("refunded_minor") or 0)
        verification = record.get("verification")
        item = {
            "id": record["id"], "source": record.get("source"), "verification": verification,
            "settlement": record.get("settlement") or ("manual" if record.get("source") == "manual" else ""),
            "settlement_text": SETTLEMENT_TEXT.get(record.get("settlement") or "", ""),
            "paid_outside_stripe": bool(record.get("paid_outside_stripe")),
            "currency": currency, "amount_minor": int(record.get("amount_minor") or 0),
            "refunded_minor": int(record.get("refunded_minor") or 0), "net_minor": max(0, net),
            "paid_at": _iso(paid_at), "paid_precision": "day" if day_only else "time",
            "invoice_number": record.get("invoice_number") or "",
            "invoice_id": record.get("invoice_id") or "", "reference": record.get("reference") or "",
            "customer_name": record.get("customer_name") or "", "lead_id": "", "linked": False,
            "reason": "", "followup": None, "confirmation": None,
            "refunds_checked_at": record.get("checked_at") or "",
            "refunds_stale": record.get("source") == "stripe" and bool(last_sync_at) and record.get("checked_at") != last_sync_at,
        }
        lead = _lead_for(record, leads_by_id, leads_by_email)
        if not record.get("livemode", True) and not include_test:
            item["reason"] = "Stripe test-mode payment (not real money)"
        elif net <= 0:
            item["reason"] = "Fully refunded"
        elif verification == UNCONFIRMED:
            item["reason"] = f"Payment not confirmed: {SETTLEMENT_TEXT.get(record.get('settlement'), 'no proof of payment')}"
        elif not lead:
            item["reason"] = "No single matching contact in RetainAI"
        else:
            item["lead_id"] = str(lead.get("id") or "")
            item["customer_name"] = lead.get("name") or item["customer_name"]
            # Only evidence tied to THIS payment can confirm it: the paid
            # invoice's own finalization, or the one booking the payment
            # explicitly references (owner-selected, or carried by the invoice).
            # Other bookings of the same customer are never used.
            confirmations = []
            if record.get("source") == "stripe" and _utc(record.get("invoice_issued_at")):
                confirmations.append({"kind": "invoice", "at": _utc(record["invoice_issued_at"]),
                                      "id": record.get("invoice_id") or "", "label": f"Invoice {record.get('invoice_number') or ''}".strip()})
            booking_ref = record.get("booking_ref") or ""
            referenced = next((appt for appt in valid_bookings_for(lead, appointments) if str(appt.get("id")) == booking_ref), None) if booking_ref else None
            if referenced:
                confirmations.append({"kind": "booking", "at": _utc(referenced.get("created_at")), "id": booking_ref,
                                      "label": f"Booking ({str(referenced.get('status') or 'scheduled').lower()})",
                                      "appointment_time": referenced.get("appointment_time") or ""})
            same_day = [c for c in confirmations if day_only and before_payment <= c["at"] < same_day_end]
            confirmations = sorted((c for c in confirmations if c["at"] <= before_payment and (not day_only or c["at"] < before_payment)),
                                   key=lambda c: c["at"], reverse=True)
            sent = followups_for(lead)
            for confirmation in confirmations:
                before = [row for row in sent if confirmation["at"] - window <= row["_at"] <= confirmation["at"]]
                if before:
                    follow = before[-1]
                    item["linked"] = True
                    item["followup"] = {"channel": follow.get("channel"), "sent_at": _iso(follow["_at"]), "evidence": follow.get("evidence")}
                    item["confirmation"] = {"kind": confirmation["kind"], "at": _iso(confirmation["at"]), "id": confirmation["id"],
                                            "label": confirmation["label"], "appointment_time": confirmation.get("appointment_time", "")}
                    break
            if not item["linked"]:
                if booking_ref and not referenced:
                    item["reason"] = "The booking selected for this payment no longer exists or was cancelled"
                elif same_day:
                    item["reason"] = "The booking was on the payment day and the payment time isn't recorded, so their order is unknown. Add the time to link it."
                elif not confirmations:
                    item["reason"] = (
                        "No booking selected for this payment" if record.get("source") == "manual"
                        else "No finalized invoice time or referenced booking for this payment"
                    )
                else:
                    item["reason"] = f"No recorded follow-up in the {window.days} days before the booking or invoice"
        bucket = totals.setdefault(currency, {"linked_verified_minor": 0, "linked_owner_recorded_minor": 0,
                                              "paid_verified_minor": 0, "paid_owner_recorded_minor": 0,
                                              "paid_unconfirmed_minor": 0, "linked_count": 0, "payment_count": 0})
        counted = record.get("livemode", True) or include_test
        if counted and net > 0:
            kind = {VERIFIED: "verified", OWNER: "owner_recorded"}.get(verification, "unconfirmed")
            bucket[f"paid_{kind}_minor"] += net
            bucket["payment_count"] += 1
            if item["linked"] and kind != "unconfirmed":
                bucket[f"linked_{kind}_minor"] += net
                bucket["linked_count"] += 1
        items.append(item)
    items.sort(key=lambda row: row["paid_at"], reverse=True)
    sync = dict(last_sync or {})
    return {
        "totals": totals,
        "items": items,
        "sync": {
            "last_synced_at": sync.get("at", ""),
            "complete": bool(sync.get("complete")) if sync else False,
            "not_refreshed": int(sync.get("not_refreshed") or 0),
            "stale_items": sum(1 for item in items if item["refunds_stale"]),
        },
        "rules": {
            "window_days": window.days,
            "linked_means": (
                "A RetainAI follow-up was sent to this customer, then within "
                f"{window.days} days the paid invoice was issued or the booking tied to "
                "this payment was made, and the customer paid after that. Other bookings "
                "of the same customer are never used."
            ),
            "not_causal": "A link shows the order of events. It does not prove the follow-up caused the payment.",
            "excluded": ("RetainAI membership charges, test-mode payments, refunded amounts and Stripe payments "
                         "without a confirmed successful charge are never counted."),
            "stripe_api_version": STRIPE_API_VERSION,
        },
    }


def _safe_cell(value):
    text = "" if value is None else str(value)
    # Stop spreadsheets from treating exported text as a formula.
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _evidence_label(item):
    if item["verification"] == VERIFIED:
        return "Provider-verified (Stripe charge)"
    if item["verification"] == UNCONFIRMED:
        return "Unconfirmed (Stripe shows paid)"
    return "Marked paid outside Stripe" if item["paid_outside_stripe"] else "Owner-recorded"


def receipt_csv(receipt):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "paid_at_utc", "paid_time_known", "customer", "currency", "amount", "refunded", "net", "evidence", "settlement",
        "source", "linked", "followup_channel", "followup_sent_at_utc", "confirmation",
        "confirmation_at_utc", "invoice_number", "reference", "refunds_checked_at_utc", "reason_not_linked",
    ])
    for item in receipt["items"]:
        currency = item["currency"]
        writer.writerow([_safe_cell(v) for v in (
            item["paid_at"], "no" if item["paid_precision"] == "day" else "yes", item["customer_name"], (currency or "").upper(),
            format_minor(item["amount_minor"], currency), format_minor(item["refunded_minor"], currency),
            format_minor(item["net_minor"], currency), _evidence_label(item), item["settlement_text"],
            item["source"], "yes" if item["linked"] else "no",
            (item["followup"] or {}).get("channel", ""), (item["followup"] or {}).get("sent_at", ""),
            (item["confirmation"] or {}).get("label", ""), (item["confirmation"] or {}).get("at", ""),
            item["invoice_number"], item["reference"], item["refunds_checked_at"], item["reason"],
        )])
    return out.getvalue()

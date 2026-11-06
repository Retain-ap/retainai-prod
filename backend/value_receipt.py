"""Verified revenue evidence for the Value Receipt.

The receipt only counts money a business actually received from its own
customers, and only when the record shows a RetainAI follow-up came before
a confirmed booking or an issued invoice that was then paid. That sequence is
reported as a link, never as proof the follow-up caused the payment.

Two kinds of payment evidence are kept apart everywhere:

* ``provider_verified``: a paid invoice read from the business's own connected
  Stripe account (never RetainAI's membership billing).
* ``owner_recorded``: an amount the owner typed in, or an invoice the owner
  marked as paid outside Stripe. Shown, but never presented as verified.

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
BOOKING_STATUSES = {"scheduled", "completed"}

# Notifications RetainAI writes only after an email was actually accepted for
# delivery. Used for follow-ups sent before the follow-up log existed.
LEGACY_EMAIL_SUBJECTS = {"AI email sent": "email", "Automation email sent": "email"}

VERIFIED = "provider_verified"
OWNER = "owner_recorded"


class EvidenceError(ValueError):
    """A request to record evidence that cannot be accepted as given."""


# ---------------------------------------------------------------- utilities

def _utc(value):
    """Parse an ISO string or epoch seconds to an aware UTC datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(float(value), dt.timezone.utc)
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    text = str(value).strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _iso(moment):
    return moment.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z") if moment else ""


def _email(value):
    return str(value or "").strip().lower()


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
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, data):
    temp = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.replace(temp, path)


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
        return {"last_synced_at": bucket.get("last_synced_at") or ""}

    @contextmanager
    def _bucket(self, workspace):
        with _locked(self.path):
            data = _read(self.path)
            bucket = data.setdefault(workspace, {})
            bucket.setdefault("records", {})
            yield bucket
            _write(self.path, data)

    def upsert_stripe(self, workspace, records, synced_at):
        """Store invoices read from the workspace's own Stripe account.

        Re-syncing the same invoice updates its refund figures; nothing is
        double counted and nothing is ever deleted by a sync.
        """
        added = updated = 0
        with self._bucket(workspace) as bucket:
            stored = bucket["records"]
            for record in records:
                key = record["id"]
                if key in stored:
                    previous = stored[key]
                    record["recorded_at"] = previous.get("recorded_at") or synced_at
                    if previous != record:
                        updated += 1
                else:
                    record["recorded_at"] = synced_at
                    added += 1
                stored[key] = record
            bucket["last_synced_at"] = synced_at
        return {"added": added, "updated": updated}

    def add_manual(self, workspace, payload, *, lead, recorded_by, now):
        key = str(payload.get("idempotency_key") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise EvidenceError("A valid idempotency key is required.")
        currency = normalize_currency(payload.get("currency"))
        amount_minor = to_minor(payload.get("amount"), currency)
        paid_at = _utc(payload.get("paid_at"))
        if not paid_at:
            raise EvidenceError("Enter the date the payment was received.")
        if paid_at > now + dt.timedelta(days=1) or paid_at.year < 2000:
            raise EvidenceError("The payment date can't be in the future.")
        reference = str(payload.get("reference") or "").strip()[:120]
        record = {
            "id": f"manual:{key}",
            "source": "manual",
            "verification": OWNER,
            "amount_minor": amount_minor,
            "refunded_minor": 0,
            "currency": currency,
            "paid_at": _iso(paid_at),
            "lead_id": str(lead.get("id") or ""),
            "customer_email": _email(lead.get("email")),
            "customer_name": str(lead.get("name") or "")[:160],
            "reference": reference,
            "livemode": True,
            "recorded_by": recorded_by,
            "recorded_at": _iso(now),
        }
        identity = {k: record[k] for k in ("amount_minor", "currency", "paid_at", "lead_id", "reference")}
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


def stripe_invoice_record(invoice, account_id):
    """Evidence from one paid invoice of the business's connected account.

    Handles the 2023-10-16 API shape this app pins (``charge``,
    ``paid_out_of_band``) and the newer one (``amount_paid_off_stripe``).
    Returns None for anything that is not a paid invoice.
    """
    if str(_field(invoice, "status") or "") != "paid":
        return None
    currency = str(_field(invoice, "currency") or "").lower()
    if currency not in CURRENCY_EXPONENTS:
        return None
    amount_paid = int(_field(invoice, "amount_paid") or 0)
    if amount_paid <= 0:
        return None
    paid_at = _utc(_field(invoice, "status_transitions", "paid_at")) or _utc(_field(invoice, "created"))
    charge = _field(invoice, "charge")
    # ``charge`` is an ID unless expanded; only an expanded charge has refunds.
    charge_refunded = 0 if not charge or isinstance(charge, str) else int(_field(charge, "amount_refunded") or 0)
    credit_notes = int(_field(invoice, "post_payment_credit_notes_amount") or 0)
    # A credit note that refunds money also refunds the charge: take the larger
    # figure instead of adding them, so a refund is never subtracted twice.
    refunded = min(amount_paid, max(charge_refunded, credit_notes))
    off_stripe = bool(_field(invoice, "paid_out_of_band")) or int(_field(invoice, "amount_paid_off_stripe") or 0) > 0
    issued_at = _utc(_field(invoice, "status_transitions", "finalized_at")) or _utc(_field(invoice, "created"))
    invoice_id = str(_field(invoice, "id") or "")
    return {
        "id": f"stripe:{invoice_id}",
        "source": "stripe",
        # Marked paid in Stripe without a Stripe payment: Stripe only records
        # the owner's statement, so it is not provider-verified money.
        "verification": OWNER if off_stripe else VERIFIED,
        "paid_outside_stripe": off_stripe,
        "amount_minor": amount_paid,
        "refunded_minor": refunded,
        "currency": currency,
        "paid_at": _iso(paid_at),
        "invoice_id": invoice_id,
        "invoice_number": str(_field(invoice, "number") or ""),
        "invoice_issued_at": _iso(issued_at),
        "customer_email": _email(_field(invoice, "customer_email")),
        "customer_name": str(_field(invoice, "customer_name") or "")[:160],
        "stripe_account": account_id,
        "livemode": bool(_field(invoice, "livemode")),
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
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        zone = ZoneInfo(str(timezone_name or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        zone = dt.timezone.utc
    today = now.astimezone(zone).date()

    def day(value, fallback):
        if not value:
            return fallback
        try:
            return dt.date.fromisoformat(str(value)[:10])
        except ValueError:
            raise EvidenceError("Use dates in YYYY-MM-DD format.") from None

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


def build_receipt(*, records, leads, followups, appointments, start, end, window_days, include_test=False):
    window = dt.timedelta(days=max(MIN_WINDOW_DAYS, min(MAX_WINDOW_DAYS, int(window_days or DEFAULT_WINDOW_DAYS))))
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

    def bookings_for(lead):
        lead_id, email = str(lead.get("id") or ""), _email(lead.get("email"))
        rows = []
        for appt in appointments or []:
            if not isinstance(appt, dict):
                continue
            status = str(appt.get("status") or "scheduled").lower()
            same = (lead_id and str(appt.get("lead_id") or "") == lead_id) or (email and _email(appt.get("lead_email")) == email)
            booked_at = _utc(appt.get("created_at"))
            if same and status in BOOKING_STATUSES and booked_at:
                rows.append({"kind": "booking", "at": booked_at, "id": str(appt.get("id") or ""),
                             "label": f"Booking ({status})", "appointment_time": appt.get("appointment_time") or ""})
        return rows

    items, totals = [], {}
    for record in records:
        paid_at = _utc(record.get("paid_at"))
        if not paid_at or not (start <= paid_at < end):
            continue
        currency = record.get("currency")
        net = int(record.get("amount_minor") or 0) - int(record.get("refunded_minor") or 0)
        item = {
            "id": record["id"], "source": record.get("source"), "verification": record.get("verification"),
            "paid_outside_stripe": bool(record.get("paid_outside_stripe")),
            "currency": currency, "amount_minor": int(record.get("amount_minor") or 0),
            "refunded_minor": int(record.get("refunded_minor") or 0), "net_minor": max(0, net),
            "paid_at": _iso(paid_at), "invoice_number": record.get("invoice_number") or "",
            "invoice_id": record.get("invoice_id") or "", "reference": record.get("reference") or "",
            "customer_name": record.get("customer_name") or "", "lead_id": "", "linked": False,
            "reason": "", "followup": None, "confirmation": None,
        }
        lead = _lead_for(record, leads_by_id, leads_by_email)
        if not record.get("livemode", True) and not include_test:
            item["reason"] = "Stripe test-mode payment (not real money)"
        elif net <= 0:
            item["reason"] = "Fully refunded"
        elif not lead:
            item["reason"] = "No single matching contact in RetainAI"
        else:
            item["lead_id"] = str(lead.get("id") or "")
            item["customer_name"] = lead.get("name") or item["customer_name"]
            confirmations = []
            if record.get("source") == "stripe" and _utc(record.get("invoice_issued_at")):
                confirmations.append({"kind": "invoice", "at": _utc(record["invoice_issued_at"]),
                                      "id": record.get("invoice_id") or "", "label": f"Invoice {record.get('invoice_number') or ''}".strip()})
            confirmations += bookings_for(lead)
            confirmations = sorted((c for c in confirmations if c["at"] <= paid_at), key=lambda c: c["at"], reverse=True)
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
                item["reason"] = (
                    "No booking or invoice before the payment" if not confirmations
                    else f"No recorded follow-up in the {window.days} days before the booking or invoice"
                )
        bucket = totals.setdefault(currency, {"linked_verified_minor": 0, "linked_owner_recorded_minor": 0,
                                              "paid_verified_minor": 0, "paid_owner_recorded_minor": 0,
                                              "linked_count": 0, "payment_count": 0})
        counted = record.get("livemode", True) or include_test
        if counted and net > 0:
            kind = "verified" if record.get("verification") == VERIFIED else "owner_recorded"
            bucket[f"paid_{kind}_minor"] += net
            bucket["payment_count"] += 1
            if item["linked"]:
                bucket[f"linked_{kind}_minor"] += net
                bucket["linked_count"] += 1
        items.append(item)
    items.sort(key=lambda row: row["paid_at"], reverse=True)
    return {
        "totals": totals,
        "items": items,
        "rules": {
            "window_days": window.days,
            "linked_means": (
                "A RetainAI follow-up was sent to this customer, then within "
                f"{window.days} days a booking was recorded or an invoice was issued, "
                "and the customer paid after that."
            ),
            "not_causal": "A link shows the order of events. It does not prove the follow-up caused the payment.",
            "excluded": "RetainAI membership charges, test-mode payments and refunded amounts are never counted.",
        },
    }


def _safe_cell(value):
    text = "" if value is None else str(value)
    # Stop spreadsheets from treating exported text as a formula.
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def receipt_csv(receipt):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "paid_at_utc", "customer", "currency", "amount", "refunded", "net", "evidence",
        "source", "linked", "followup_channel", "followup_sent_at_utc", "confirmation",
        "confirmation_at_utc", "invoice_number", "reference", "reason_not_linked",
    ])
    for item in receipt["items"]:
        currency = item["currency"]
        writer.writerow([_safe_cell(v) for v in (
            item["paid_at"], item["customer_name"], (currency or "").upper(),
            format_minor(item["amount_minor"], currency), format_minor(item["refunded_minor"], currency),
            format_minor(item["net_minor"], currency),
            "Provider-verified (Stripe)" if item["verification"] == VERIFIED
            else ("Marked paid outside Stripe" if item["paid_outside_stripe"] else "Owner-recorded"),
            item["source"], "yes" if item["linked"] else "no",
            (item["followup"] or {}).get("channel", ""), (item["followup"] or {}).get("sent_at", ""),
            (item["confirmation"] or {}).get("label", ""), (item["confirmation"] or {}).get("at", ""),
            item["invoice_number"], item["reference"], item["reason"],
        )])
    return out.getvalue()

"""Frequency policy and durable delivery guard for owner lead briefings only.

No customer automation or security mail uses this module. A pending attempt is
not a delivery receipt: it conservatively prevents repeats after a lost provider
response or a crash between sending and saving the accepted receipt.
"""

import datetime as dt
import hashlib
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = dt.timezone.utc
STATE_FILE = "lead_reminder_state.json"


def utc(value):
    try:
        parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def reminder_timezone(profile, account):
    name = str(profile.get("timezone") or account.get("timezone") or account.get("time_zone") or "UTC").strip()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def overdue_leads(leads, interval, now):
    """Keep unresolved overdue contacts eligible for the weekly reminder.

    Age is display data, not part of the material-change fingerprint. Never
    mutate contact records just to prepare an owner email.
    """
    result = []
    for lead in leads if isinstance(leads, list) else []:
        if not isinstance(lead, dict):
            continue
        last = utc(lead.get("last_contacted") or lead.get("createdAt"))
        if last is not None and (now - last).days >= interval:
            result.append({**lead, "days_since_contact": (now - last).days})
    return result


def reminder_fingerprint(leads, interval):
    entries = set()
    for lead in leads:
        identity = str(lead.get("id") or str(lead.get("email") or "").strip().lower() or lead.get("name") or "")
        last = utc(lead.get("last_contacted") or lead.get("createdAt"))
        entries.add((identity, last.isoformat() if last else ""))
    payload = json.dumps([interval, sorted(entries)], separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def daytime(now, zone):
    return 9 <= now.astimezone(zone).hour < 17


def reminder_due(record, fingerprint, now, zone):
    local_now = now.astimezone(zone)
    if not daytime(now, zone):
        return False
    if not record:
        return True
    if not isinstance(record, dict):
        raise ValueError("Lead reminder state is invalid; refusing to send.")
    # Every attempted send is a durable claim. Only accepted sends also have
    # last_sent_at, so uncertain outcomes never masquerade as successful mail.
    attempted = utc(record.get("attempted_at"))
    previous = record.get("attempted_fingerprint")
    if attempted is None or not isinstance(previous, str) or len(previous) != 64:
        raise ValueError("Lead reminder state is invalid; refusing to send.")
    if now <= attempted or local_now.date() <= attempted.astimezone(zone).date():
        return False
    return previous != fingerprint or now - attempted >= dt.timedelta(days=7)


def send_if_due(path, workspace, *, now, prepare, send):
    """Serialize claim -> provider -> receipt with the existing atomic JSON store.

    ``prepare`` rechecks the account, quiet hours and fresh contacts under the
    same cross-process lock. False/unknown provider outcomes retain the attempt
    claim; unchanged mail waits seven days before another attempt.
    """
    from value_receipt import _locked, _read, _write

    with _locked(path):
        now = now() if callable(now) else now
        prepared = prepare(now)
        if prepared is None:
            return False
        leads, interval, zone = prepared
        if not leads:
            return False
        fingerprint = reminder_fingerprint(leads, interval)
        state = _read(path)
        record = state.get(workspace, {})
        if not reminder_due(record, fingerprint, now, zone):
            return False
        record = {**record, "attempted_at": now.isoformat(), "attempted_fingerprint": fingerprint}
        state[workspace] = record
        _write(path, state)  # Failure here must stop before contacting SendGrid.
        if send(leads, interval) is not True:
            return False
        record.update(last_sent_at=now.isoformat(), last_sent_fingerprint=fingerprint)
        _write(path, state)
        return True

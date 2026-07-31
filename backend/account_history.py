"""Privacy-preserving account lifecycle history.

Only an HMAC fingerprint is retained after deletion. The original email is not
stored, but the same address cannot repeatedly claim introductory trials.
"""

import datetime
import hashlib
import hmac
import json
import os
import threading
from uuid import uuid4

from storage import DATA_ROOT


HISTORY_FILE = os.path.join(DATA_ROOT, "account_lifecycle.json")
_LOCK = threading.Lock()


def _secret():
    value = (
        os.getenv("ACCOUNT_HISTORY_SECRET")
        or os.getenv("SESSION_SECRET")
        or os.getenv("FLASK_SECRET_KEY")
        or os.getenv("APP_SECRET")
        or os.getenv("PLATFORM_OWNER_PASSWORD")
        or ""
    )
    if not value:
        raise RuntimeError("account_history_secret_missing")
    return value.encode("utf-8")


def _fingerprint(email):
    normalized = str(email or "").strip().lower().encode("utf-8")
    return hmac.new(_secret(), normalized, hashlib.sha256).hexdigest()


def _load():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as handle:
            value = json.load(handle)
            return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save(value):
    os.makedirs(DATA_ROOT, exist_ok=True)
    temporary = f"{HISTORY_FILE}.{uuid4().hex}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
    os.replace(temporary, HISTORY_FILE)


def trial_previously_used(email):
    return bool((_load().get(_fingerprint(email)) or {}).get("trial_used"))


def record_trial_start(email):
    with _LOCK:
        rows = _load()
        key = _fingerprint(email)
        row = rows.get(key) or {}
        row["trial_used"] = True
        row.setdefault(
            "first_trial_at",
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        rows[key] = row
        _save(rows)


def record_account_deletion(email):
    with _LOCK:
        rows = _load()
        key = _fingerprint(email)
        row = rows.get(key) or {}
        row["trial_used"] = True
        row["last_deleted_at"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        row["deletion_count"] = int(row.get("deletion_count") or 0) + 1
        rows[key] = row
        _save(rows)

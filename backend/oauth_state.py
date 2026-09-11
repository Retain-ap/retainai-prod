"""One-time, session-bound OAuth state helpers.

OAuth callbacks must never trust an email address supplied in the query string.
The browser receives only an opaque nonce; the signed Flask session retains the
account identity and intended return URL until the callback consumes it.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urljoin, urlparse

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app, session


_SESSION_KEY = "oauth_states"
_DEFAULT_MAX_AGE = 10 * 60
_MAX_PENDING = 8


def _state_cipher():
    """Encrypt fallback state with the same secret that signs the session."""
    secret = current_app.secret_key
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not secret:
        raise RuntimeError("Flask SECRET_KEY is required for OAuth state")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def _seal_state(record):
    payload = json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _state_cipher().encrypt(payload).decode("ascii")


def _open_state(token):
    try:
        payload = _state_cipher().decrypt(str(token or "").encode("ascii"))
        value = json.loads(payload.decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (InvalidToken, ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        return None


def _pending_states():
    value = session.get(_SESSION_KEY)
    return dict(value) if isinstance(value, dict) else {}


def issue_oauth_state(purpose, subject, redirect_url=""):
    now = int(time.time())
    pending = {
        key: value
        for key, value in _pending_states().items()
        if isinstance(value, dict)
        and now - int(value.get("created_at") or 0) <= _DEFAULT_MAX_AGE
    }
    record = {
        "purpose": str(purpose or ""),
        "subject": str(subject or "").strip().lower(),
        "redirect_url": str(redirect_url or ""),
        "created_at": now,
        "nonce": secrets.token_urlsafe(16),
    }
    # The encrypted token lets the callback recover after browsers omit or
    # replace the session cookie during an external OAuth round trip. Keeping
    # it in the session still gives us normal one-time consumption semantics.
    token = _seal_state(record)
    pending[token] = record
    newest = sorted(
        pending.items(),
        key=lambda item: int(item[1].get("created_at") or 0),
        reverse=True,
    )[:_MAX_PENDING]
    session[_SESSION_KEY] = dict(newest)
    session.modified = True
    return token


def consume_oauth_state(purpose, token, max_age=_DEFAULT_MAX_AGE):
    token = str(token or "")
    pending = _pending_states()
    record = pending.pop(token, None)
    session[_SESSION_KEY] = pending
    session.modified = True
    if not isinstance(record, dict):
        record = _open_state(token)
    if not isinstance(record, dict):
        return None
    if not secrets.compare_digest(
        str(record.get("purpose") or ""), str(purpose or "")
    ):
        return None
    created_at = int(record.get("created_at") or 0)
    if created_at <= 0 or abs(int(time.time()) - created_at) > int(max_age):
        return None
    if not str(record.get("subject") or "").strip():
        return None
    return record


def safe_same_origin_redirect(candidate, default_url):
    """Return a same-origin HTTP(S) URL, otherwise the supplied default."""
    default = str(default_url or "").strip()
    base = urlparse(default)
    if base.scheme not in {"http", "https"} or not base.netloc:
        raise ValueError("default_url must be an absolute HTTP(S) URL")

    value = str(candidate or "").strip()
    if not value:
        return default
    if value.startswith("/") and not value.startswith("//"):
        value = urljoin(f"{base.scheme}://{base.netloc}", value)
    parsed = urlparse(value)
    if (
        parsed.scheme in {"http", "https"}
        and parsed.netloc == base.netloc
        and parsed.scheme == base.scheme
    ):
        return value
    return default

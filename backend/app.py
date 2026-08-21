# app.py (CONSOLIDATED + PROD-SAFE) â€” PART 1/2
import os
import time
import re
import json
import time
import base64
import hmac
import hashlib
import datetime
import secrets
import struct
import urllib.parse
from uuid import uuid4
from typing import Any, Dict, Optional, List, Tuple
from urllib.parse import urlparse

import html
from email.utils import parseaddr
import stripe
import requests as pyrequests
from email import policy
from email.parser import BytesParser

from flask import Flask, request, jsonify, send_from_directory, redirect, current_app, Blueprint, session
from flask_cors import CORS
from dotenv import load_dotenv
from flask_apscheduler import APScheduler
from werkzeug.security import check_password_hash, generate_password_hash
from cryptography.fernet import Fernet, InvalidToken

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email

from google.oauth2 import id_token
from google.auth.transport import requests as grequests

from storage import (
    load_users, save_users, get_user, create_user,
    load_leads, save_leads, save_user_leads, migrate_json_to_sqlite_if_needed,
    DATA_ROOT, USE_SQLITE, SQLITE_PATH
)

# ----------------------------
# BOOT + CONFIG
# ----------------------------
class Config:
    SCHEDULER_API_ENABLED = True


load_dotenv()

# Ensure data root exists
try:
    os.makedirs(DATA_ROOT, exist_ok=True)
except Exception:
    pass

# Kick off one-time JSON -> SQLite migration if needed
migrate_json_to_sqlite_if_needed()
print(f"[storage] USE_SQLITE={USE_SQLITE} DATA_ROOT={DATA_ROOT} SQLITE_PATH={SQLITE_PATH}")
print(f"[BOOT] RetainAI started (PID: {os.getpid()})")

app = Flask(__name__)
app.config.from_object(Config())
app.config["BOOTSTRAP_DONE"] = False  # used to start scheduler once in prod

SESSION_SECRET = (
    os.getenv("SESSION_SECRET")
    or os.getenv("FLASK_SECRET_KEY")
    or os.getenv("APP_SECRET")
)
from account_history import record_trial_start, trial_previously_used
if not SESSION_SECRET:
    # Keep sessions stable across every production worker. The dedicated owner
    # secret is a safe deterministic recovery source until SESSION_SECRET is set.
    owner_secret = str(os.getenv("PLATFORM_OWNER_PASSWORD") or "").strip()
    if owner_secret:
        SESSION_SECRET = hashlib.sha256(
            f"retainai-session:{owner_secret}".encode("utf-8")
        ).hexdigest()
        print("[SECURITY] SESSION_SECRET is derived from the configured owner secret.")
    else:
        # Local development remains usable, but production is made deliberately
        # obvious instead of silently creating mutually incompatible workers.
        SESSION_SECRET = os.urandom(32).hex()
        print("[SECURITY] WARNING: Configure SESSION_SECRET before running multiple workers.")
app.config.update(
    SECRET_KEY=SESSION_SECRET,
    # Version the cookie name so pre-hardening Domain cookies cannot collide
    # with the current host-only production session.
    SESSION_COOKIE_NAME="retainai_v2_session",
    SESSION_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=30),
)


# ----------------------------
# CORS
# ----------------------------
ALLOWED = [o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

if not ALLOWED:
    # Safe fallback for dev if env missing
    ALLOWED = [
        "http://localhost:3000",
        "https://retainai-prod-1-frontend.onrender.com",
        "https://www.retainai.ca",
        "https://retainai.ca",
    ]

print("[CORS] Allowed origins:", ALLOWED)

CORS(
    app,
    resources={r"/api/*": {"origins": ALLOWED}},
    supports_credentials=True,
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Requested-With",
        "X-User-Email",
        "X-Owner-Email",
        "X-Auth-Email",
    ],
    expose_headers=["Content-Type"],
)

# Cookies must remain Secure in production. Allowed origins often contain
# localhost for developer convenience and must never determine cookie security.
IS_RENDER = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"))
IS_LOCAL = (
    not IS_RENDER
    and os.getenv("FLASK_ENV", "").lower() == "development"
)

app.config.update(
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=not IS_LOCAL,
    SESSION_COOKIE_DOMAIN=os.getenv("SESSION_COOKIE_DOMAIN") or None,
)

_PUBLIC_API_PATHS = {
    "/api/health",
    "/api/readiness",
    "/api/test",
    "/api/login",
    "/api/logout",
    "/api/session",
    "/api/signup",
    "/api/auth/signup",
    "/api/auth/password/forgot",
    "/api/auth/password/reset",
    "/api/auth/email/verify",
    "/api/auth/email/resend",
    "/api/oauth/google",
    "/api/auth/2fa/verify-login",
    "/api/stripe/webhook",
    "/api/stripe/oauth/callback",
    "/api/stripe/verify",
    "/api/google/oauth-callback",
    "/api/email/inbound",
    "/api/whatsapp/webhook",
    "/api/vapid-public-key",
    "/api/team/accept",
}


def _session_email() -> str:
    return str(session.get("user_email") or "").strip().lower()


def _session_org_email() -> str:
    return str(session.get("org_email") or _session_email()).strip().lower()


def _start_user_session(email: str, user_payload: dict, remember: bool = True) -> None:
    session.clear()
    session.permanent = bool(remember)
    session["user_email"] = str(email or "").strip().lower()
    session["org_email"] = str(
        (user_payload or {}).get("orgOwnerEmail")
        or (user_payload or {}).get("org_id")
        or email
        or ""
    ).strip().lower()
    session["role"] = str((user_payload or {}).get("role") or "owner").lower()
    users = load_users() or {}
    account = users.get(str(email or "").strip().lower()) if isinstance(users, dict) else {}
    session["security_version"] = int((account or {}).get("security_version") or 0)


@app.before_request
def require_authenticated_api_session():
    if request.method == "OPTIONS" or not request.path.startswith("/api/"):
        return None
    if request.path in _PUBLIC_API_PATHS:
        return None
    if request.path.startswith("/api/team/invite/"):
        return None

    # Reject browser writes from origins outside the RetainAI allowlist.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = (request.headers.get("Origin") or "").rstrip("/")
        if origin and origin not in ALLOWED:
            return jsonify({"error": "untrusted_request_origin"}), 403
        if not origin and request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify({"error": "cross_site_request_blocked"}), 403

    actor = _session_email()
    org = _session_org_email()
    if not actor:
        return jsonify({"error": "authentication_required"}), 401
    if session.get("recovery_only") and request.path not in {
        "/api/billing/checkout",
        "/api/billing/portal",
        "/api/account/deletion",
        "/api/account/export",
        "/api/logout",
    }:
        return jsonify({"error": "billing_recovery_session"}), 402

    # Legacy clients still send identity fields. Accept only the signed-in user
    # or their workspace owner, preventing email-header impersonation.
    claimed = [
        request.headers.get("X-User-Email"),
        request.headers.get("X-Owner-Email"),
        request.headers.get("X-Auth-Email"),
        request.args.get("user_email"),
        request.args.get("owner_email"),
    ]
    if request.is_json:
        body = request.get_json(silent=True) or {}
        if isinstance(body, dict):
            claimed.extend((
                body.get("user_email"),
                body.get("owner_email"),
                body.get("userEmail"),
                body.get("ownerEmail"),
            ))
    if request.endpoint in {"api_profile", "api_user"}:
        claimed.append(request.args.get("email"))
    for key, value in (request.view_args or {}).items():
        if "email" in str(key).lower():
            claimed.append(value)

    # Resolve the current account from the signed cookie on every request.
    # This also supports team members whose browser may still have old local
    # profile data from before they switched accounts.
    users = load_users() or {}
    actor_record = users.get(actor) if isinstance(users, dict) else None
    if isinstance(actor_record, dict):
        if int(session.get("security_version") or 0) != int(
            actor_record.get("security_version") or 0
        ):
            session.clear()
            return jsonify({"error": "session_revoked"}), 401
        stored_org = str(
            actor_record.get("org_id")
            or actor_record.get("orgOwnerEmail")
            or ""
        ).strip().lower()
        if stored_org:
            org = stored_org

    access_record = users.get(org) if isinstance(users, dict) else None
    if not isinstance(access_record, dict):
        access_record = actor_record
    if (
        not _is_platform_owner(actor)
        and isinstance(access_record, dict)
        and not _account_has_access(access_record)
    ):
        session.clear()
        return jsonify({"error": "account_access_inactive"}), 403

    allowed = {value for value in {actor, org} if value}
    # Customer-management routes deliberately name another account. They are
    # protected by the canonical owner check inside app_owner, while this
    # global guard still verifies the signed session and security version.
    if request.path.startswith("/api/owner/") and _is_platform_owner(actor):
        return None
    for value in claimed:
        normalized = str(value or "").strip().lower()
        if normalized and normalized not in allowed:
            return jsonify({"error": "forbidden_identity"}), 403
    return None


def _password_matches(stored: str, supplied: str) -> bool:
    stored = str(stored or "")
    if not stored or not supplied:
        return False
    if stored.startswith(("scrypt:", "pbkdf2:")):
        try:
            return check_password_hash(stored, supplied)
        except Exception:
            return False
    return hmac.compare_digest(stored, supplied)


_LOGIN_ATTEMPTS = {}
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 8


def _login_attempt_key(email: str) -> str:
    forwarded = str(request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return f"{_norm_email(email)}:{forwarded or request.remote_addr or 'unknown'}"


def _login_is_limited(email: str) -> bool:
    key = _login_attempt_key(email)
    now = time.time()
    attempts = [value for value in _LOGIN_ATTEMPTS.get(key, []) if now - value < LOGIN_WINDOW_SECONDS]
    _LOGIN_ATTEMPTS[key] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _record_login_failure(email: str) -> None:
    key = _login_attempt_key(email)
    _LOGIN_ATTEMPTS.setdefault(key, []).append(time.time())


def _clear_login_failures(email: str) -> None:
    _LOGIN_ATTEMPTS.pop(_login_attempt_key(email), None)


PASSWORD_RESET_TTL_SECONDS = 30 * 60
_PASSWORD_RESET_REQUESTS = {}


def _password_reset_rate_limited(email: str) -> bool:
    key = _login_attempt_key(email)
    now = time.time()
    attempts = [
        value
        for value in _PASSWORD_RESET_REQUESTS.get(key, [])
        if now - value < LOGIN_WINDOW_SECONDS
    ]
    _PASSWORD_RESET_REQUESTS[key] = attempts
    if len(attempts) >= 4:
        return True
    attempts.append(now)
    return False


def _password_reset_token(email: str, user: dict) -> str:
    issued_at = int(time.time())
    password_fingerprint = hashlib.sha256(
        str((user or {}).get("password") or "").encode("utf-8")
    ).hexdigest()[:20]
    payload = json.dumps(
        {"email": _norm_email(email), "iat": issued_at, "pf": password_fingerprint},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        str(SESSION_SECRET).encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def _password_reset_email(token: str, to_email: str) -> bool:
    if not SENDGRID_API_KEY:
        app.logger.error("[PASSWORD RESET] SENDGRID_API_KEY is not configured")
        return False
    reset_url = f"{FRONTEND_URL}/login?reset_token={urllib.parse.quote(token)}"
    message = Mail(
        from_email=platform_email_sender(),
        to_emails=to_email,
        subject="Reset your RetainAI password",
        html_content=(
            "<div style='font-family:Arial,sans-serif;color:#18191c;line-height:1.6'>"
            "<h2>Reset your RetainAI password</h2>"
            "<p>Use the secure link below within 30 minutes. If you did not request "
            "this change, you can safely ignore this email.</p>"
            f"<p><a href='{html.escape(reset_url, quote=True)}' "
            "style='display:inline-block;background:#d7bb66;color:#111;padding:12px 18px;"
            "border-radius:8px;text-decoration:none;font-weight:700'>Reset password</a></p>"
            "<p>For your security, this link stops working after your password changes.</p>"
            "</div>"
        ),
    )
    try:
        response = SendGridAPIClient(SENDGRID_API_KEY).send(message)
        return 200 <= int(response.status_code) < 300
    except Exception:
        app.logger.exception("[PASSWORD RESET] Email delivery failed")
        return False


def _decode_password_reset_token(token: str, users: dict) -> Tuple[str, dict]:
    encoded, supplied_signature = str(token or "").split(".", 1)
    expected_signature = hmac.new(
        str(SESSION_SECRET).encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, supplied_signature):
        raise ValueError("invalid")
    padded = encoded + ("=" * ((4 - len(encoded) % 4) % 4))
    payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    email = _norm_email(payload.get("email"))
    issued_at = int(payload.get("iat") or 0)
    if not email or issued_at <= 0 or time.time() - issued_at > PASSWORD_RESET_TTL_SECONDS:
        raise ValueError("expired")
    user = users.get(email)
    if not isinstance(user, dict):
        raise ValueError("invalid")
    current_fingerprint = hashlib.sha256(
        str(user.get("password") or "").encode("utf-8")
    ).hexdigest()[:20]
    if not hmac.compare_digest(str(payload.get("pf") or ""), current_fingerprint):
        raise ValueError("used")
    return email, user


def _email_verification_token(email: str) -> str:
    issued_at = int(time.time())
    payload = json.dumps(
        {"email": _norm_email(email), "iat": issued_at, "purpose": "verify_email"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        str(SESSION_SECRET).encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def _decode_email_verification_token(token: str) -> str:
    encoded, supplied_signature = str(token or "").split(".", 1)
    expected_signature = hmac.new(
        str(SESSION_SECRET).encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, supplied_signature):
        raise ValueError("invalid")
    padded = encoded + ("=" * ((4 - len(encoded) % 4) % 4))
    payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    if payload.get("purpose") != "verify_email":
        raise ValueError("invalid")
    issued_at = int(payload.get("iat") or 0)
    if issued_at <= 0 or time.time() - issued_at > 24 * 60 * 60:
        raise ValueError("expired")
    return _norm_email(payload.get("email"))


def _send_verification_email(email: str) -> bool:
    if not SENDGRID_API_KEY:
        return False
    token = _email_verification_token(email)
    verify_url = f"{API_PUBLIC_URL}/api/auth/email/verify?token={urllib.parse.quote(token)}"
    message = Mail(
        from_email=platform_email_sender(),
        to_emails=email,
        subject="Verify your RetainAI email",
        html_content=(
            "<div style='font-family:Arial,sans-serif;color:#18191c;line-height:1.6'>"
            "<h2>Verify your email</h2><p>Confirm this email belongs to you to secure "
            "your RetainAI account.</p>"
            f"<p><a href='{html.escape(verify_url, quote=True)}' "
            "style='display:inline-block;background:#d7bb66;color:#111;padding:12px 18px;"
            "border-radius:8px;text-decoration:none;font-weight:700'>Verify email</a></p>"
            "<p>This link expires in 24 hours.</p></div>"
        ),
    )
    try:
        response = SendGridAPIClient(SENDGRID_API_KEY).send(message)
        return 200 <= int(response.status_code) < 300
    except Exception:
        app.logger.exception("[EMAIL VERIFY] Delivery failed")
        return False


def _mfa_cipher() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(str(SESSION_SECRET).encode("utf-8")).digest())
    return Fernet(key)


def _encrypt_mfa_secret(secret: str) -> str:
    return _mfa_cipher().encrypt(str(secret).encode("utf-8")).decode("utf-8")


def _decrypt_mfa_secret(value: str) -> str:
    try:
        return _mfa_cipher().decrypt(str(value).encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return ""


def _new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_at(secret: str, timestamp: float) -> str:
    padding = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode((secret + padding).upper())
    counter = int(timestamp // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _verify_totp_secret(secret: str, code: str) -> bool:
    normalized = re.sub(r"\s+", "", str(code or ""))
    if not re.fullmatch(r"\d{6}", normalized):
        return False
    now = time.time()
    return any(
        hmac.compare_digest(_totp_at(secret, now + window * 30), normalized)
        for window in (-1, 0, 1)
    )


def _verify_mfa_code(user: dict, code: str) -> bool:
    normalized = re.sub(r"\s+", "", str(code or ""))
    if not normalized:
        return False
    secret = _decrypt_mfa_secret((user or {}).get("totp_secret", ""))
    if secret and _verify_totp_secret(secret, normalized):
        return True
    for index, stored_hash in enumerate(list((user or {}).get("backup_code_hashes") or [])):
        if check_password_hash(stored_hash, normalized.upper()):
            remaining = list(user.get("backup_code_hashes") or [])
            remaining.pop(index)
            user["backup_code_hashes"] = remaining
            return True
    return False

def _cors_preflight_response():
    resp = current_app.make_response(("", 204))
    origin = (request.headers.get("Origin") or "").rstrip("/")

    if origin in ALLOWED:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, X-Requested-With, "
            "X-User-Email, X-Owner-Email, X-Auth-Email"
        )

    return resp

@app.after_request
def add_cors_headers(resp):
    origin = (request.headers.get("Origin") or "").rstrip("/")

    if origin in ALLOWED:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, X-Requested-With, "
            "X-User-Email, X-Owner-Email, X-Auth-Email"
        )

    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(self)"
    )
    if not IS_LOCAL:
        resp.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains"
        )

    return resp

@app.route("/api/<path:_any>", methods=["OPTIONS"])
def api_options(_any):
    return _cors_preflight_response()

@app.route("/api/oauth/google", methods=["OPTIONS"])
def google_oauth_options():
    return _cors_preflight_response()

# ----------------------------
# HEALTH / TEST
# ----------------------------
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True), 200

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify(ok=True, ts=int(time.time())), 200


@app.route("/api/readiness", methods=["GET"])
def api_readiness():
    """Report production dependencies without exposing secret values."""
    storage_ready = False
    storage_error = ""
    try:
        users = load_users()
        storage_ready = isinstance(users, dict)
    except Exception as exc:
        storage_error = type(exc).__name__

    checks = {
        "storage": storage_ready,
        "stable_session_secret": bool(
            os.getenv("SESSION_SECRET")
            or os.getenv("FLASK_SECRET_KEY")
            or os.getenv("APP_SECRET")
            or os.getenv("PLATFORM_OWNER_PASSWORD")
        ),
        "stable_account_history_secret": bool(
            os.getenv("ACCOUNT_HISTORY_SECRET")
            or os.getenv("SESSION_SECRET")
            or os.getenv("FLASK_SECRET_KEY")
            or os.getenv("APP_SECRET")
            or os.getenv("PLATFORM_OWNER_PASSWORD")
        ),
        "stripe_billing": bool(
            os.getenv("STRIPE_SECRET_KEY")
            and os.getenv("STRIPE_PRICE_ID")
            and os.getenv("STRIPE_WEBHOOK_SECRET")
        ),
        "transactional_email": bool(os.getenv("SENDGRID_API_KEY")),
        "google_sign_in": bool(os.getenv("GOOGLE_CLIENT_ID")),
        "whatsapp": bool(
            (os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN"))
            and (os.getenv("WHATSAPP_PHONE_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID"))
            and (os.getenv("APP_SECRET") or os.getenv("META_APP_SECRET"))
        ),
        "persistent_storage": bool(
            (os.getenv("USE_SQLITE") or "").strip().lower() == "true"
            and os.getenv("SQLITE_PATH")
        ),
    }
    required = ("storage", "stable_session_secret", "stripe_billing", "transactional_email")
    ready = all(checks[name] for name in required)
    payload = {
        "ok": ready,
        "status": "ready" if ready else "degraded",
        "checks": checks,
        "ts": int(time.time()),
    }
    if storage_error:
        payload["storage_error"] = storage_error
    return jsonify(payload), 200 if ready else 503

@app.route("/test", methods=["GET"])
def test_root():
    return jsonify(ok=True, route="/test"), 200

@app.route("/api/test", methods=["GET"])
def test_api():
    return jsonify(ok=True, route="/api/test"), 200


# ----------------------------
# ENV & third-party keys
# ----------------------------
OPENROUTER_API_KEY = (os.getenv("OPENROUTER_API_KEY") or "").strip()
SENDGRID_API_KEY = (os.getenv("SENDGRID_API_KEY") or "").strip()

VAPID_PUBLIC_KEY = (os.getenv("VAPID_PUBLIC_KEY") or "").strip()
VAPID_PRIVATE_KEY = (os.getenv("VAPID_PRIVATE_KEY") or "").strip()

SENDER_EMAIL = os.getenv("SENDER_EMAIL", "noreply@retainai.ca")
PLATFORM_EMAIL = os.getenv("PLATFORM_EMAIL", "welcome@retainai.ca")
PLATFORM_EMAIL_NAME = os.getenv("PLATFORM_EMAIL_NAME", "RetainAI")


def platform_email_sender():
    """Sender identity for emails RetainAI sends to its own users."""
    return Email(PLATFORM_EMAIL, PLATFORM_EMAIL_NAME)
INBOUND_REPLY_DOMAIN = (os.getenv("INBOUND_REPLY_DOMAIN") or "reply.retainai.ca").strip().lower()
STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
STRIPE_PRICE_ID = (os.getenv("STRIPE_PRICE_ID") or "").strip()
STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
STRIPE_CONNECT_CLIENT_ID = (os.getenv("STRIPE_CONNECT_CLIENT_ID") or "").strip()
STRIPE_REDIRECT_URI = (os.getenv("STRIPE_REDIRECT_URI") or "").strip()

FRONTEND_URL = (
    os.getenv("PUBLIC_FRONTEND_URL")
    or os.getenv("FRONTEND_URL")
    or "http://localhost:3000"
).rstrip("/")
if FRONTEND_URL == "https://retainai-prod-1-frontend.onrender.com":
    # Stripe and OAuth must return to the canonical site. On the temporary
    # Render hostname the api.retainai.ca session cookie becomes cross-site.
    FRONTEND_URL = "https://www.retainai.ca"
API_PUBLIC_URL = (
    os.getenv("PUBLIC_API_URL")
    or os.getenv("BACKEND_URL")
    or "https://api.retainai.ca"
).rstrip("/")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

ZERO_DECIMAL = {"bif","clp","djf","gnf","jpy","kmf","krw","mga","pyg","rwf","ugx","vnd","vuv","xaf","xof","xpf"}

# --- WhatsApp Cloud API ---
WHATSAPP_TOKEN    = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "retainai-verify")
WHATSAPP_WABA_ID = os.getenv("WHATSAPP_WABA_ID") or os.getenv("WHATSAPP_BUSINESS_ID")
WHATSAPP_TEMPLATE_DEFAULT = os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "retainai_outreach")
WHATSAPP_TEMPLATE_LANG = os.getenv("WHATSAPP_TEMPLATE_LANG", "en_US")
APP_SECRET = os.getenv("APP_SECRET") or os.getenv("META_APP_SECRET")
DEFAULT_COUNTRY_CODE = (os.getenv("DEFAULT_COUNTRY_CODE") or "1").strip()

# --- Google OAuth ---
GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
GOOGLE_CLIENT_SECRET = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
GOOGLE_REDIRECT_URI = (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
]


# ----------------------------
# Legacy JSON helpers (non-core files)
# ----------------------------
SUBSCRIPTIONS: Dict[str, Any] = {}

NOTIFICATIONS_FILE = os.path.join(DATA_ROOT, "notifications.json")
APPOINTMENTS_FILE  = os.path.join(DATA_ROOT, "appointments.json")
CHAT_FILE          = os.path.join(DATA_ROOT, "whatsapp_chats.json")
STATUS_FILE        = os.path.join(DATA_ROOT, "whatsapp_status.json")
WA_WEBHOOK_EVENTS_FILE = os.path.join(DATA_ROOT, "whatsapp_webhook_events.json")
WA_UNMATCHED_FILE      = os.path.join(DATA_ROOT, "whatsapp_unmatched.json")

ICS_DIR = os.path.join(DATA_ROOT, "ics_files")
os.makedirs(ICS_DIR, exist_ok=True)

def _legacy_load_json(file_path: str):
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _legacy_save_json(file_path: str, data: Any):
    # A unique temporary name prevents concurrent webhook workers from
    # replacing one another's in-flight files.
    tmp = f"{file_path}.{os.getpid()}.{uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, file_path)

def load_notifications():
    return _legacy_load_json(NOTIFICATIONS_FILE)

def save_notifications(data):
    _legacy_save_json(NOTIFICATIONS_FILE, data)

def load_appointments():
    return _legacy_load_json(APPOINTMENTS_FILE)

def save_appointments(data):
    _legacy_save_json(APPOINTMENTS_FILE, data)

def load_chats():
    return _legacy_load_json(CHAT_FILE)

def save_chats(data):
    _legacy_save_json(CHAT_FILE, data)


def append_chat_message(user_email: str, lead_id: str, row: dict):
    """Cross-worker atomic append for the webhook/send hot path."""
    lock_path = CHAT_FILE + ".lock"
    lock_fd = None
    for _ in range(200):
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            time.sleep(0.01)
    if lock_fd is None:
        raise RuntimeError("WhatsApp chat store is busy")
    try:
        chats = load_chats() or {}
        user_chats = chats.get(user_email, {}) or {}
        thread = user_chats.get(str(lead_id), []) or []
        row_id = str((row or {}).get("id") or (row or {}).get("message_id") or "")
        if row_id and any(
            str((item or {}).get("id") or (item or {}).get("message_id") or "") == row_id
            for item in thread
        ):
            return thread
        thread.append(row)
        user_chats[str(lead_id)] = thread
        chats[user_email] = user_chats
        save_chats(chats)
        return thread
    finally:
        os.close(lock_fd)
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass

def load_statuses():
    return _legacy_load_json(STATUS_FILE)

def save_statuses(data):
    _legacy_save_json(STATUS_FILE, data)


def load_wa_webhook_events():
    data = _legacy_load_json(WA_WEBHOOK_EVENTS_FILE)
    return data if isinstance(data, list) else []


def save_wa_webhook_events(data):
    _legacy_save_json(WA_WEBHOOK_EVENTS_FILE, data if isinstance(data, list) else [])


def load_wa_unmatched():
    data = _legacy_load_json(WA_UNMATCHED_FILE)
    return data if isinstance(data, list) else []


def save_wa_unmatched(data):
    _legacy_save_json(WA_UNMATCHED_FILE, data if isinstance(data, list) else [])


# ----------------------------
# Utilities
# ----------------------------
_BAD_KEYS = {
    "_sa_instance_state", "headers", "request", "cookies", "environ",
    "wsgi", "response", "session", "files", "form", "args", "json",
}

def _to_dict(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, tuple) and obj:
        for part in obj:
            d = _to_dict(part)
            if d:
                return d
        return {}
    if hasattr(obj, "get_json") and callable(getattr(obj, "get_json")):
        try:
            j = obj.get_json(silent=True)
            if isinstance(j, dict):
                return j
        except Exception:
            pass
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    try:
        return dict(obj)
    except Exception:
        pass
    if hasattr(obj, "_asdict") and callable(getattr(obj, "_asdict")):
        try:
            return dict(obj._asdict())
        except Exception:
            return {}
    if hasattr(obj, "__dict__"):
        try:
            return {k: v for k, v in vars(obj).items()}
        except Exception:
            return {}
    return {}

def _json_sanitize(val: Any):
    import datetime as _dt
    import base64 as _b64
    if val is None or isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, (_dt.datetime, _dt.date)):
        try:
            return val.isoformat()
        except Exception:
            return str(val)
    if isinstance(val, (bytes, bytearray, memoryview)):
        try:
            return _b64.b64encode(bytes(val)).decode("ascii")
        except Exception:
            return str(val)
    if isinstance(val, dict):
        out = {}
        for k, v in val.items():
            if str(k) in _BAD_KEYS:
                continue
            try:
                out[str(k)] = _json_sanitize(v)
            except Exception:
                continue
        return out
    if isinstance(val, (list, tuple, set)):
        out = []
        for x in val:
            try:
                out.append(_json_sanitize(x))
            except Exception:
                continue
        return out
    try:
        return str(val)
    except Exception:
        return None

def _normalize_profile(email: str, raw: Optional[dict]) -> dict:
    r = _to_dict(raw) if raw is not None else {}
    email = (email or r.get("email") or "").strip()

    def _int(v, default=0):
        try:
            return int(v)
        except Exception:
            return default

    business = (r.get("business") or r.get("businessName") or "").strip()
    people = _int(r.get("people"), 0)
    teamSize = _int(r.get("teamSize"), people)

    return {
        "name": (r.get("name") or "").strip(),
        "email": email,
        "logo": (r.get("logo") or r.get("picture") or "").strip(),
        "business": business,
        "businessName": business,
        "businessType": (r.get("businessType") or r.get("type") or "").strip(),
        "location": (r.get("location") or "").strip(),
        "people": people,
        "teamSize": teamSize,
    }

def _upsert_user(email: str, patch: dict) -> dict:
    """
    Safe upsert via storage adapter map (works for JSON or SQLite adapter patterns).
    We avoid calling create_user(dict) because signature can differ.
    """
    email = _norm_email(email)
    users = load_users()
    existing = _to_dict(users.get(email)) if isinstance(users, dict) else _to_dict(get_user(email))
    merged = dict(existing or {})
    merged.update({k: v for k, v in (patch or {}).items() if v is not None})
    merged["email"] = email

    if isinstance(users, dict):
        users[email] = merged
        save_users(users)
    else:
        try:
            create_user(**merged)
        except Exception:
            pass
    return merged

def add_notification(
    user_email: str,
    subject: str,
    message: str = "",
    channel: str = "app",
    lead_email: str = "",
    extra: dict | None = None,
):
    user_email = (user_email or "").strip().lower()
    if not user_email:
        return None

    all_notes = load_notifications() or {}
    if not isinstance(all_notes, dict):
        all_notes = {}

    user_notes = all_notes.get(user_email, []) or []
    if not isinstance(user_notes, list):
        user_notes = []

    note = {
        "id": f"note_{uuid4().hex[:12]}",
        "subject": str(subject or "Notification"),
        "message": str(message or ""),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "read": False,
        "channel": str(channel or "app"),
        "lead_email": str(lead_email or "").strip().lower(),
    }

    if isinstance(extra, dict):
        for k, v in extra.items():
            note[k] = v

    user_notes.insert(0, note)
    all_notes[user_email] = user_notes
    save_notifications(all_notes)
    return note


def log_notification(user_email, subject, message, lead_email=None):
    return add_notification(
        user_email=user_email,
        subject=subject,
        message=message,
        channel="app",
        lead_email=lead_email or "",
    )


def _notification_sort_ts(n: dict) -> float:
    raw = n.get("timestamp") or n.get("created_at") or n.get("time") or ""
    try:
        return datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _normalize_notification_item(n: dict, idx: int = 0) -> dict:
    item = dict(n or {})
    item.setdefault("id", item.get("_id") or item.get("uuid") or f"note_{idx}")
    item.setdefault("read", False)
    item.setdefault("timestamp", item.get("created_at") or item.get("time") or item.get("timestamp") or "")
    item.setdefault("subject", item.get("title") or item.get("type") or item.get("subject") or "Notification")
    item.setdefault("message", item.get("body") or item.get("text") or item.get("message") or "")
    item.setdefault("channel", item.get("channel") or "app")
    item.setdefault("lead_email", item.get("lead_email") or item.get("email") or "")
    item.setdefault("lead_name", item.get("lead_name") or item.get("leadName") or "")
    return item

def _trim_email_reply_text(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""

    # Normalize line endings
    s = s.replace("\r\n", "\n").replace("\r", "\n")

    # Common reply separators
    patterns = [
        r"\nOn .+?wrote:\n",
        r"\nFrom:\s.+",
        r"\nSent:\s.+",
        r"\n---+\s*Original Message\s*---+",
        r"\n_{5,}\n",
    ]

    for pat in patterns:
        m = re.search(pat, s, flags=re.IGNORECASE | re.DOTALL)
        if m:
            s = s[:m.start()].strip()
            break

    # Remove quoted lines that start with >
    lines = s.split("\n")
    cleaned = []
    for line in lines:
        if line.strip().startswith(">"):
            break
        cleaned.append(line)

    s = "\n".join(cleaned).strip()

    # Collapse extra blank lines
    s = re.sub(r"\n{3,}", "\n\n", s).strip()

    return s

def _extract_inbound_email_bodies(raw_email: str):
    """
    Returns (plain_text, html_text) extracted from raw MIME email.
    """
    try:
        if not raw_email:
            return "", ""

        msg = BytesParser(policy=policy.default).parsebytes(
            raw_email.encode("utf-8", errors="ignore")
        )

        plain_parts = []
        html_parts = []

        if msg.is_multipart():
            for part in msg.walk():
                ctype = (part.get_content_type() or "").lower()
                disp = str(part.get("Content-Disposition") or "").lower()

                # skip attachments
                if "attachment" in disp:
                    continue

                try:
                    content = part.get_content()
                except Exception:
                    try:
                        payload = part.get_payload(decode=True) or b""
                        charset = part.get_content_charset() or "utf-8"
                        content = payload.decode(charset, errors="ignore")
                    except Exception:
                        content = ""

                if ctype == "text/plain" and content:
                    plain_parts.append(str(content))
                elif ctype == "text/html" and content:
                    html_parts.append(str(content))
        else:
            ctype = (msg.get_content_type() or "").lower()
            try:
                content = msg.get_content()
            except Exception:
                try:
                    payload = msg.get_payload(decode=True) or b""
                    charset = msg.get_content_charset() or "utf-8"
                    content = payload.decode(charset, errors="ignore")
                except Exception:
                    content = ""

            if ctype == "text/plain" and content:
                plain_parts.append(str(content))
            elif ctype == "text/html" and content:
                html_parts.append(str(content))

        plain_text = "\n\n".join([p.strip() for p in plain_parts if str(p).strip()]).strip()
        html_text = "\n\n".join([p.strip() for p in html_parts if str(p).strip()]).strip()

        return plain_text, html_text

    except Exception as e:
        try:
            app.logger.warning("[EMAIL MIME PARSE ERROR] %s", e)
        except Exception:
            pass
        return "", ""

def _reply_encode(s: str) -> str:
    return ((s or "").strip().lower().encode("utf-8")).hex()

def _reply_decode(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return ""
    return bytes.fromhex(s).decode("utf-8")

def make_inbound_reply_address(owner_email: str, lead_email: str) -> str:
    owner_tok = _reply_encode(owner_email)
    lead_tok = _reply_encode(lead_email)
    return f"r.{owner_tok}.{lead_tok}@{INBOUND_REPLY_DOMAIN}"

def parse_inbound_reply_address(addr: str):
    try:
        raw = (addr or "").strip()
        expected_domain = INBOUND_REPLY_DOMAIN.rstrip(".").lower()

        # extract first email-like token
        email_addr = raw
        if any(ch in raw for ch in [" ", "<", ">", ","]):
            m = re.search(r'([^\s<>,]+@[^\s<>,]+)', raw)
            if not m:
                return "", ""
            email_addr = m.group(1).strip()

        if "@" not in email_addr:
            return "", ""

        local, domain = email_addr.rsplit("@", 1)
        domain = domain.strip().lower().rstrip(".")

        if domain != expected_domain:
            return "", ""

        if not local.startswith("r."):
            return "", ""

        rest = local[2:]
        if "." not in rest:
            return "", ""

        owner_tok, lead_tok = rest.split(".", 1)
        owner_tok = owner_tok.strip()
        lead_tok = lead_tok.strip()

        if not owner_tok or not lead_tok:
            return "", ""

        owner_email = _reply_decode(owner_tok).strip().lower()
        lead_email = _reply_decode(lead_tok).strip().lower()

        if "@" not in owner_email or "@" not in lead_email:
            return "", ""

        return owner_email, lead_email

    except Exception as e:
        try:
            app.logger.warning("[EMAIL INBOUND PARSE ERROR] %s", e)
        except Exception:
            pass
        return "", ""

def _strip_html_to_text(s: str) -> str:
    if not s:
        return ""
    txt = str(s)
    txt = re.sub(r"(?i)<br\s*/?>", "\n", txt)
    txt = re.sub(r"(?i)</p\s*>", "\n\n", txt)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = html.unescape(txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()

def _find_lead_by_email_for_owner(owner_email: str, lead_email: str):
    leads_by_user = load_leads() or {}
    arr = (leads_by_user.get((owner_email or "").strip().lower(), []) or [])
    target = (lead_email or "").strip().lower()
    for ld in arr:
        if str(ld.get("email") or "").strip().lower() == target:
            return ld
    return None

def _build_upcoming_appointment_notifications(user_email: str) -> list:
    out = []
    appointments = load_appointments() or {}
    user_appts = appointments.get((user_email or "").strip().lower(), []) or []
    now = datetime.datetime.utcnow()
    soon_cutoff = now + datetime.timedelta(days=7)

    for appt in user_appts:
        if not isinstance(appt, dict):
            continue

        raw_ts = appt.get("appointment_time")
        if not raw_ts:
            continue

        try:
            appt_dt = datetime.datetime.strptime(raw_ts, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            continue

        if now <= appt_dt <= soon_cutoff:
            out.append({
                "id": f"appt_upcoming_{appt.get('id')}",
                "subject": "Upcoming appointment",
                "message": f"{appt.get('lead_first_name') or appt.get('lead_email') or 'Lead'} has an appointment scheduled.",
                "timestamp": appt_dt.isoformat() + "Z",
                "read": False,
                "channel": "appointment",
                "lead_email": appt.get("lead_email") or "",
                "lead_name": appt.get("lead_first_name") or "",
                "appointment_id": appt.get("id"),
                "derived": True,
            })

        status = str(appt.get("status") or "").strip().lower().replace("_", "-")
        if status == "no-show":
            out.append({
                "id": f"appt_noshow_{appt.get('id')}",
                "subject": "Appointment no-show",
                "message": f"{appt.get('lead_first_name') or appt.get('lead_email') or 'Lead'} missed an appointment.",
                "timestamp": appt.get("updated_at") or appt_dt.isoformat() + "Z",
                "read": False,
                "channel": "appointment",
                "lead_email": appt.get("lead_email") or "",
                "lead_name": appt.get("lead_first_name") or "",
                "appointment_id": appt.get("id"),
                "derived": True,
            })

    return out
# ----------------------------
# /api/profile (SINGLE SOURCE OF TRUTH) â€” FIXED (no duplicates)
# ----------------------------
@app.route('/api/user/<path:email>', methods=['GET'])
def api_get_user(email):
    email = _norm_email(email)
    users = load_users() or {}

    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    role, org_email, org_owner, subject = _resolve_org_and_role(email, users)
    if not role:
        return jsonify({"error": "User not found"}), 404

    if not org_owner:
        return jsonify({"error": "Org owner not found"}), 404

    if not _org_is_active(org_owner):
        return jsonify({"error": "account_inactive"}), 403

    subject = subject or {}
    org_owner = org_owner or {}

    # Owner sees own record.
    # Member sees own display identity, but org-level business/billing fields from owner.
    if role == "owner":
        display_name = org_owner.get("name", "")
        base = org_owner
    else:
        display_name = subject.get("name", "") or org_owner.get("name", "")
        base = org_owner

    out = {
        "email": email,

        "name": display_name,
        "logo": base.get("logo") or base.get("picture", ""),

        "business": base.get("business", ""),
        "businessName": base.get("business", ""),
        "businessType": base.get("businessType", ""),
        "lineOfBusiness": base.get("businessType", ""),
        "location": base.get("location", ""),
        "people": base.get("people") or base.get("teamSize", ""),
        "teamSize": base.get("teamSize") or base.get("people", ""),

        "stripe_account_id": base.get("stripe_account_id"),
        "stripe_connected": bool(base.get("stripe_connected", False)),

        "whatsapp": base.get("whatsapp", ""),
        "gcal_connected": bool(base.get("gcal_connected", False)),
        "gcal_calendars": base.get("gcal_calendars", []),

        "status": base.get("status", ""),
        "deletion_requested_at": base.get("deletion_requested_at", ""),
        "deletion_scheduled_for": base.get("deletion_scheduled_for", ""),
        "role": role,
        "orgOwnerEmail": org_email,

        "canInviteTeam": role == "owner",
        "canEditBusiness": role == "owner",
        "canManageBilling": role == "owner",
        "platformOwner": _is_platform_owner(email),
    }

    return jsonify(out), 200
    
@app.route("/api/profile", methods=["GET", "POST", "OPTIONS"])
def api_profile():
    if request.method == "OPTIONS":
        return ("", 204)

    if request.method == "GET":
        email = _norm_email(request.args.get("email") or request.headers.get("X-User-Email"))
        if not email:
            return jsonify({"error": "Missing email"}), 400

        users = load_users() or {}
        if not isinstance(users, dict):
            return jsonify({"error": "storage_not_ready"}), 500

        role, org_email, org_owner, subject = _resolve_org_and_role(email, users)
        if not role:
            return jsonify({"error": "User not found"}), 404

        if not org_owner:
            return jsonify({"error": "Org owner not found"}), 404

        if not _org_is_active(org_owner):
            return jsonify({"error": "account_inactive"}), 403

        subject = subject or {}
        org_owner = org_owner or {}

        if role == "owner":
            display_name = org_owner.get("name", "")
            base = org_owner
        else:
            display_name = subject.get("name", "") or org_owner.get("name", "")
            base = org_owner

        return jsonify({
            "email": email,

            "name": display_name,
            "logo": base.get("logo") or base.get("picture", ""),

            "business": base.get("business", ""),
            "businessName": base.get("business", ""),
            "businessType": base.get("businessType", ""),
            "lineOfBusiness": base.get("businessType", ""),
            "location": base.get("location", ""),
            "people": base.get("people") or base.get("teamSize", ""),
            "teamSize": base.get("teamSize") or base.get("people", ""),

            "stripe_connected": bool(base.get("stripe_connected", False)),
            "stripe_account_id": base.get("stripe_account_id"),

            "whatsapp": base.get("whatsapp", ""),
            "gcal_connected": bool(base.get("gcal_connected", False)),
            "gcal_calendars": base.get("gcal_calendars", []),

            "status": base.get("status", ""),
            "deletion_requested_at": base.get("deletion_requested_at", ""),
            "deletion_scheduled_for": base.get("deletion_scheduled_for", ""),
            "role": role,
            "orgOwnerEmail": org_email,
            "canInviteTeam": role == "owner",
            "canEditBusiness": role == "owner",
            "canManageBilling": role == "owner",
            "platformOwner": _is_platform_owner(email),
        }), 200

    # POST
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email") or request.headers.get("X-User-Email"))
    if not email:
        return jsonify({"error": "Missing email"}), 400

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    role, org_email, org_owner, subject = _resolve_org_and_role(email, users)
    if not role:
        return jsonify({"error": "User not found"}), 404

    # Only owners can update org business fields.
    # Members can only update their own display name.
    def _to_int(v, fallback=""):
        try:
            if v in (None, ""):
                return fallback
            return int(v)
        except Exception:
            return fallback

    if role == "owner":
        target_email = org_email
        target = users.get(target_email, {}) or {}

        if "name" in data:
            target["name"] = (data.get("name") or "").strip()
        if "logo" in data:
            target["logo"] = (data.get("logo") or "").strip()

        target["business"] = (
            data.get("business")
            or data.get("businessName")
            or target.get("business")
            or ""
        ).strip()

        target["businessName"] = target.get("business", "")

        target["businessType"] = (
            data.get("businessType")
            or data.get("lineOfBusiness")
            or target.get("businessType")
            or ""
        ).strip()

        target["location"] = (
            data.get("location")
            or target.get("location")
            or ""
        ).strip()

        people_val = data.get("people", data.get("teamSize"))
        if people_val is not None:
            iv = _to_int(people_val, "")
            target["people"] = iv
            target["teamSize"] = iv

        users[target_email] = target
        save_users(users)

        return jsonify({
            "ok": True,
            "email": email,
            "name": target.get("name", ""),
            "logo": target.get("logo") or target.get("picture", ""),
            "business": target.get("business", ""),
            "businessName": target.get("business", ""),
            "businessType": target.get("businessType", ""),
            "lineOfBusiness": target.get("businessType", ""),
            "location": target.get("location", ""),
            "people": target.get("people") or target.get("teamSize", ""),
            "teamSize": target.get("teamSize") or target.get("people", ""),
            "stripe_connected": bool(target.get("stripe_connected", False)),
            "stripe_account_id": target.get("stripe_account_id"),
            "role": role,
            "orgOwnerEmail": org_email,
        }), 200

    # member update: only their own display name
    member_key = f"user::{email}"
    member = users.get(member_key, {}) or {}
    if "name" in data:
        member["name"] = (data.get("name") or "").strip()
    users[member_key] = member
    save_users(users)

    return jsonify({
        "ok": True,
        "email": email,
        "name": member.get("name", "") or (subject or {}).get("name", ""),
        "role": role,
        "orgOwnerEmail": org_email,
    }), 200

# ----------------------------
# OpenRouter helpers
# ----------------------------
AI_MODEL_ORDER_PROMPT = [
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-1.5-pro",
    "meta-llama/llama-3.1-70b-instruct",
    "meta-llama/llama-3.1-8b-instruct",
]

def _clean_ai_text(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"^(Subject|Lead Name|Recipient)\s*:\s*.*\n?", "", s, flags=re.I | re.M)
    s = re.sub(r"^\s*[\w \-]+:\s*$", "", s, flags=re.M)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _complete_openrouter_prompt(messages, *, max_tokens=150, temperature=0.7, timeout=30):
    key = OPENROUTER_API_KEY
    if not key:
        return False, "", {"error": "OPENROUTER_API_KEY missing"}

    last_err = None
    for model in AI_MODEL_ORDER_PROMPT:
        attempt_tokens = int(max_tokens)
        for attempt in range(3):
            try:
                r = pyrequests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": attempt_tokens,
                        "temperature": float(temperature),
                    },
                    timeout=timeout,
                )
                ct = r.headers.get("content-type", "")
                j = r.json() if "application/json" in ct.lower() else {}

                if r.ok and j.get("choices"):
                    txt = j["choices"][0]["message"]["content"]
                    return True, _clean_ai_text(txt), {"model": model, "status": r.status_code, "tokens": attempt_tokens}

                if r.status_code in (429,) or (500 <= r.status_code < 600):
                    time.sleep(0.7 + attempt * 0.4)
                    attempt_tokens = max(60, int(attempt_tokens * 0.9))
                    continue

                last_err = {"status": r.status_code, "body": j or r.text}
                break

            except Exception as e:
                last_err = {"exception": str(e)}
                time.sleep(0.4 + attempt * 0.3)
                continue

    return False, "", {"error": "all_models_failed", "last": last_err}


# ----------------------------
# SendGrid email helpers
# ----------------------------
def send_email_with_template(to_email, template_id, dynamic_data, subject=None, from_email=None, reply_to_email=None):
    if not SENDGRID_API_KEY:
        print("[SENDGRID] SENDGRID_API_KEY missing; skipping email send.")
        return False

    from_email = from_email or SENDER_EMAIL
    subject = subject or "Message from RetainAI"
    dynamic_data = dynamic_data or {}
    dynamic_data["subject"] = subject

    message = Mail(from_email=from_email, to_emails=to_email, subject=subject)
    message.template_id = template_id
    message.dynamic_template_data = dynamic_data
    if reply_to_email:
        message.reply_to = Email(reply_to_email)

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"[SENDGRID] Status: {response.status_code} | To: {to_email} | Subject: {subject}")
        return response.status_code == 202
    except Exception as e:
        print(f"[SENDGRID ERROR] Failed to send to {to_email}: {e}")
        return False


# ----------------------------
# ICS helpers
# ----------------------------
def _ics_escape(value):
    """Escape user-controlled text before placing it in an RFC 5545 field."""
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("\r", "")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def create_ics_file(appt):
    dt_start = datetime.datetime.strptime(appt["appointment_time"], "%Y-%m-%dT%H:%M:%S")
    dt_end = dt_start + datetime.timedelta(minutes=int(appt.get("duration", 30)))
    dt_stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_uid = _ics_escape(appt.get("id"))
    summary = _ics_escape(f"Appointment with {appt.get('user_name', '')} at {appt.get('business_name', '')}")
    description = _ics_escape(f"Appointment at {appt.get('appointment_location', '')} with {appt.get('user_name', '')}")
    location = _ics_escape(appt.get("appointment_location", ""))
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//RetainAI//EN
BEGIN:VEVENT
UID:{safe_uid}
DTSTAMP:{dt_stamp}
DTSTART:{dt_start.strftime("%Y%m%dT%H%M%S")}
DTEND:{dt_end.strftime("%Y%m%dT%H%M%S")}
SUMMARY:{summary}
DESCRIPTION:{description}
LOCATION:{location}
END:VEVENT
END:VCALENDAR
"""
    fname = f"{uid}.ics"
    with open(os.path.join(ICS_DIR, fname), "w", encoding="utf-8") as f:
        f.write(ics_content)
    return fname

@app.route("/ics/<filename>")
def serve_ics(filename):
    return send_from_directory(ICS_DIR, filename, as_attachment=True)

def make_google_calendar_link(appt):
    dt_start = datetime.datetime.strptime(appt["appointment_time"], "%Y-%m-%dT%H:%M:%S")
    dt_end = dt_start + datetime.timedelta(minutes=int(appt.get("duration", 30)))
    # Appointment input is business-local time. Keep the calendar event
    # floating instead of incorrectly labeling it as UTC and shifting it.
    start_str = dt_start.strftime("%Y%m%dT%H%M%S")
    end_str = dt_end.strftime("%Y%m%dT%H%M%S")
    title = f"Appointment with {appt.get('user_name', '')} at {appt.get('business_name', '')}"
    details = f"Appointment with {appt.get('user_name', '')} at {appt.get('business_name', '')}."
    query = urllib.parse.urlencode({
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start_str}/{end_str}",
        "details": details,
        "location": appt.get("appointment_location") or "",
    })
    return f"https://calendar.google.com/calendar/render?{query}"


# ----------------------------
# Notifications & scheduler jobs
# ----------------------------
SG_TEMPLATE_APPT_CONFIRM       = "d-8101601827b94125b6a6a167c4455719"
SG_TEMPLATE_FOLLOWUP_USER      = "d-f239cca5f5634b01ac376a8b8690ef10"
SG_TEMPLATE_WELCOME            = "d-d4051648842b44098e601a3b16190cf9"
SG_TEMPLATE_BIRTHDAY           = "d-94133232d9bd48e0864e21dce34158d3"
SG_TEMPLATE_TRIAL_ENDING       = "d-b7329a138d5b40b096da3ff965407845"
SG_TEMPLATE_FOLLOWUP_LEAD      = "d-b40c227ed00e4cd29fdeb10dcc71a268"
SG_TEMPLATE_REENGAGE_LEAD      = "d-9c6ac36680c8473a84dda817fb58e7b7"
SG_TEMPLATE_APOLOGY_LEAD       = "d-64abfc217ce443d59c2cb411fc85cc74"
SG_TEMPLATE_UPSELL_LEAD        = "d-a7a2c04c57e344aebd6a94559ae71ea9"
SG_TEMPLATE_BDAY_REMINDER_USER = "d-599937685fc544ecb756d9fdb8275a9b"
SG_TEMPLATE_POST_APPT_UPDATE   = "d-bac1ee34ec724a41addf59d54ffdad07"

BUSINESS_TYPE_INTERVALS = {
    "nail salon": 5,
    "real estate": 14,
    "law firm": 30,
    "dentist": 7,
    "coaching": 30,
    "consulting": 21,
    "spa": 10,
    "accounting": 30,
}

def send_warning_summary_email(user_email, warning_leads, interval):
    if not warning_leads:
        return
    users = load_users()
    user = users.get(user_email, {}) if isinstance(users, dict) else {}
    user_name = user.get("name") or user_email.split("@")[0].capitalize()

    def format_date(dtstr):
        if not dtstr:
            return "-"
        try:
            return dtstr.split("T")[0]
        except Exception:
            return dtstr

    lead_list_html = "<ul style='padding-left:24px;margin:0;'>"
    for lead in warning_leads:
        safe_name = html.escape(str(lead.get("name") or "-"))
        safe_email = html.escape(str(lead.get("email") or "-"))
        safe_last_contacted = html.escape(str(format_date(lead.get("last_contacted") or lead.get("createdAt") or "-")))
        safe_days = html.escape(str(lead.get("days_since_contact") or "?"))
        safe_notes = html.escape(str(lead.get("notes") or "No notes recorded"))
        lead_list_html += (
            f"<li style='margin:0 0 16px;color:#f7cb53;'>"
            f"<span style='font-weight:800;font-size:16px;'>{safe_name}</span><br>"
            f"<span style='color:#aeb3bd;'>Email:</span> <span style='color:#ffffff;'>{safe_email}</span><br>"
            f"<span style='color:#aeb3bd;'>Last contacted:</span> <span style='color:#ffffff;'>{safe_last_contacted}</span> "
            f"<span style='color:#8d949f;'>&nbsp;({safe_days} days ago)</span><br>"
            f"<span style='color:#aeb3bd;'>Notes:</span> <span style='color:#d7dae0;'>{safe_notes}</span>"
            "</li>"
        )
    lead_list_html += "</ul>"

    dynamic_data = {
        "user_name": user_name,
        "lead_list": lead_list_html,
        "crm_link": f"{FRONTEND_URL}/app?section=dashboard",
        "year": datetime.datetime.now().year,
        "interval": interval,
        "count": len(warning_leads)
    }
    send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_FOLLOWUP_USER,
        dynamic_data=dynamic_data,
        subject="Leads need your attention",
        from_email=platform_email_sender()
    )

def send_post_appointment_update_email(user_email, user_name, lead_name, business_name, appointment_time):
    display_time = appointment_time
    try:
        dt = datetime.datetime.strptime(appointment_time, "%Y-%m-%dT%H:%M:%S")
        display_time = dt.strftime("%B %d, %Y at %I:%M %p")
    except Exception:
        pass

    crm_link = f"{FRONTEND_URL}/app?section=calendar&view=appointments&capture=1"

    return send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_POST_APPT_UPDATE,
        dynamic_data={
            "user_name": user_name or "",
            "lead_name": lead_name or "your lead",
            "business_name": business_name or "your business",
            "appointment_time": display_time,
            "crm_link": crm_link,
            "current_year": datetime.datetime.now().year,
        },
        subject=f"Update your notes for {lead_name or 'your lead'}",
        from_email=platform_email_sender(),
    )

def send_post_appointment_update_prompts():
    print("[Scheduler] Checking for completed appointments needing note updates...")

    appointments = load_appointments() or {}
    users = load_users() or {}
    now = datetime.datetime.utcnow()

    changed = False

    for user_email, user_appts in (appointments.items() if isinstance(appointments, dict) else []):
        user = users.get(user_email, {}) if isinstance(users, dict) else {}
        user_name = user.get("name", "") or user_email.split("@")[0]
        business_name = user.get("business", "") or user.get("businessName", "") or "RetainAI"

        for appt in (user_appts or []):
            if appt.get("post_appt_update_sent"):
                continue

            appointment_time = appt.get("appointment_time")
            if not appointment_time:
                continue

            try:
                appt_dt = datetime.datetime.strptime(appointment_time, "%Y-%m-%dT%H:%M:%S")
            except Exception:
                continue

            # Wait 60 minutes after the appointment start time
            if now < (appt_dt + datetime.timedelta(minutes=60)):
                continue

            lead_name = appt.get("lead_first_name") or appt.get("lead_name") or appt.get("lead_email") or "Lead"

            try:
                ok = send_post_appointment_update_email(
                    user_email=user_email,
                    user_name=user_name,
                    lead_name=lead_name,
                    business_name=business_name,
                    appointment_time=appointment_time,
                )

                if ok:
                    appt["post_appt_update_sent"] = True
                    appt["post_appt_update_sent_at"] = now.isoformat() + "Z"
                    changed = True

                    log_notification(
                        user_email,
                        f"Post-appointment update reminder sent for {lead_name}",
                        f"We emailed you to update notes for your appointment with {lead_name}.",
                        appt.get("lead_email")
                    )

            except Exception as e:
                print(f"[Scheduler] post-appointment update email error for {user_email}: {e}")

        appointments[user_email] = user_appts

    if changed:
        save_appointments(appointments)

def check_for_lead_reminders():
    print("[Scheduler] Checking for leads needing follow-up...")
    leads_by_user = load_leads() or {}
    users_by_email = load_users() or {}
    now = datetime.datetime.utcnow()

    for user_email, leads in (leads_by_user.items() if isinstance(leads_by_user, dict) else []):
        user = users_by_email.get(user_email, {}) if isinstance(users_by_email, dict) else {}
        business_type = (user.get("businessType") or user.get("business") or "").lower().strip()
        interval = BUSINESS_TYPE_INTERVALS.get(business_type, 14)

        warning_leads = []
        for lead in (leads or []):
            last_contacted = lead.get("last_contacted") or lead.get("createdAt")
            if not last_contacted:
                continue
            try:
                last_dt = datetime.datetime.fromisoformat(last_contacted.replace("Z", ""))
                days_since = (now - last_dt).days
            except Exception:
                days_since = 0

            if interval <= days_since <= interval + 2:
                lead["days_since_contact"] = days_since
                warning_leads.append(lead)

        if warning_leads:
            try:
                send_warning_summary_email(user_email, warning_leads, interval)
                log_notification(
                    user_email,
                    "Leads needing follow-up",
                    f"{len(warning_leads)} leads require follow-up: " + ", ".join(l.get("name","") for l in warning_leads)
                )
            except Exception as e:
                print("[WARN] lead reminder email/log error:", e)

def send_birthday_email(lead_email, lead_name, business_name):
    send_email_with_template(
        to_email=lead_email,
        template_id=SG_TEMPLATE_BIRTHDAY,
        dynamic_data={"lead_name": lead_name, "business_name": business_name},
    )

def send_birthday_reminder_to_user(user_email, user_name, lead_name, business_name, birthday, lead=None):
    lead = lead or {}
    send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_BDAY_REMINDER_USER,
        dynamic_data={
            "user_name": user_name,
            "lead_name": lead_name,
            "business_name": business_name,
            "birthday": birthday,
            "birthday_timing": "tomorrow",
            "days_until": 1,
            "lead_email": lead.get("email") or "Not provided",
            "notes": lead.get("notes") or "No notes recorded yet",
            "last_contacted": lead.get("last_contacted") or "No recent contact recorded",
            "crm_link": f"{FRONTEND_URL}/app?section=contacts",
            "current_year": datetime.datetime.now().year,
        },
        subject=f"Birthday Reminder: {lead_name}'s birthday is tomorrow!",
        from_email=platform_email_sender()
    )

def send_birthday_greetings():
    leads_by_user = load_leads() or {}
    users_by_email = load_users() or {}
    today = datetime.datetime.utcnow().strftime("%m-%d")
    tomorrow = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).strftime("%m-%d")

    for user_email, leads in (leads_by_user.items() if isinstance(leads_by_user, dict) else []):
        user = users_by_email.get(user_email, {}) if isinstance(users_by_email, dict) else {}
        business = user.get("business", "")
        user_name = user.get("name", "")

        for lead in (leads or []):
            bday = (lead.get("birthday") or "").strip()
            if bday and len(bday.split("-")) >= 3:
                mmdd = "-".join(bday.split("-")[1:3])
                if mmdd == today:
                    send_birthday_email(lead.get("email", ""), lead.get("name", ""), business)
                    log_notification(user_email, f"Happy Birthday, {lead.get('name','')}!", "Automated birthday email", lead.get("email"))
                if mmdd == tomorrow:
                    send_birthday_reminder_to_user(
                        user_email=user_email,
                        user_name=user_name,
                        lead_name=lead.get("name", ""),
                        business_name=business,
                        birthday=bday,
                        lead=lead,
                    )
                    log_notification(user_email, f"Reminder: {lead.get('name','')}'s birthday is tomorrow!", "Birthday reminder sent", lead.get("email"))

TRIAL_DAYS = 14

def _within_trial(user: dict, days: int = TRIAL_DAYS) -> bool:
    return _trial_details(user, days)["active"]

def _complimentary_access_active(user: dict) -> bool:
    if not isinstance(user, dict):
        return False
    if not (user.get("billing_exempt") and user.get("complimentary_access")):
        return False
    if str(user.get("status") or "").lower() != "active":
        return False
    expires_at = str(user.get("complimentary_expires_at") or "").strip()
    if not expires_at:
        return True
    try:
        expiry = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.now(datetime.timezone.utc) <= expiry
    except Exception:
        return False

def _account_has_access(user: dict) -> bool:
    if not isinstance(user, dict):
        return False
    if user.get("billing_exempt"):
        return _complimentary_access_active(user)
    return user.get("status") == "active" or _within_trial(user, TRIAL_DAYS)

def _trial_details(user: dict, days: int = TRIAL_DAYS) -> dict:
    if (user or {}).get("trial_eligible") is False:
        return {"active": False, "daysRemaining": 0, "endsAt": None}
    ts = str((user or {}).get("trial_start") or "")
    if not ts:
        return {"active": False, "daysRemaining": 0, "endsAt": None}
    try:
        started = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=datetime.timezone.utc)
        ends = started + datetime.timedelta(days=days)
        remaining_seconds = (
            ends - datetime.datetime.now(datetime.timezone.utc)
        ).total_seconds()
        days_remaining = max(0, int((remaining_seconds + 86399) // 86400))
        return {
            "active": remaining_seconds > 0,
            "daysRemaining": days_remaining,
            "endsAt": ends.isoformat().replace("+00:00", "Z"),
        }
    except Exception:
        return {"active": False, "daysRemaining": 0, "endsAt": None}

def send_trial_ending_email(user_email, user_name, business_name, trial_end_date):
    send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_TRIAL_ENDING,
        dynamic_data={"user_name": user_name, "business_name": business_name, "trial_end_date": trial_end_date},
        subject="Your RetainAI trial ends soon",
        from_email=platform_email_sender(),
    )

def send_trial_ending_soon():
    users = load_users() or {}
    if not isinstance(users, dict):
        return

    now = datetime.datetime.utcnow()
    changed = False
    for email, user in users.items():
        trial_start = user.get("trial_start")
        if (
            not trial_start
            or user.get("trial_eligible") is False
            or user.get("status") not in ["pending_payment", "active"]
        ):
            continue
        try:
            trial_start_dt = datetime.datetime.fromisoformat(trial_start)
        except Exception:
            continue

        trial_end = trial_start_dt + datetime.timedelta(days=TRIAL_DAYS)
        days_left = (trial_end - now).days

        if days_left == 2 and not user.get("trial_ending_notice_sent"):
            send_trial_ending_email(
                user_email=email,
                user_name=user.get("name", ""),
                business_name=user.get("business", ""),
                trial_end_date=trial_end.strftime("%B %d, %Y"),
            )
            user["trial_ending_notice_sent"] = True
            changed = True

    if changed:
        save_users(users)

# ----------------------------
# LEADS API (PERSISTENT) â€” KEEP ONLY THIS
# - Frontend uses:
#   GET  /api/leads   (with header X-User-Email)
#   POST /api/leads   (with header X-User-Email, body {leads:[...]})
# - Storage uses load_leads()/save_leads() from storage.py (JSON or SQLite)
# ----------------------------

from flask import request, jsonify

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()

def _platform_owner_emails() -> set:
    # Platform control is restricted to the dedicated RetainAI identity.
    # Customer accounts can still own and manage their own workspaces.
    return {"owner@retainai.ca"}

def _is_platform_owner(email: str) -> bool:
    return _norm_email(email) in _platform_owner_emails()

def _req_user_email() -> str:
    return _norm_email(_session_org_email())

def _org_is_active(owner_record: dict) -> bool:
    if not owner_record or not isinstance(owner_record, dict):
        return False
    return _account_has_access(owner_record)

def _lead_status_from_dates(lead: dict) -> str:
    now = datetime.datetime.utcnow()

    def parse_dt(val):
        if not val:
            return None
        try:
            return datetime.datetime.fromisoformat(str(val).replace("Z", ""))
        except Exception:
            return None

    last_contacted = (
        parse_dt(lead.get("last_contacted"))
        or parse_dt(lead.get("last_activity_at"))
        or parse_dt(lead.get("last_inbound_at"))
        or parse_dt(lead.get("last_outbound_at"))
        or parse_dt(lead.get("updated_at"))
        or parse_dt(lead.get("createdAt"))
        or parse_dt(lead.get("created_at"))
    )

    if not last_contacted:
        return "cold"

    days_since = (now - last_contacted).days

    if days_since >= 14:
        return "cold"
    if days_since >= 7:
        return "warning"
    return "active"


@app.route("/api/leads", methods=["GET", "OPTIONS"])
def api_get_leads():
    if request.method == "OPTIONS":
        return ("", 204)

    email = _req_user_email()
    if not email:
        return jsonify({"ok": False, "error": "missing_user_email"}), 400

    try:
        all_leads = load_leads() or {}
        if not isinstance(all_leads, dict):
            all_leads = {}

        leads = all_leads.get(email, [])
        if not isinstance(leads, list):
            leads = []

        normalized = []
        changed = False

        for lead in leads:
            if not isinstance(lead, dict):
                continue

            item = dict(lead)
            computed_status = _lead_status_from_dates(item)

            if item.get("status") != computed_status:
                item["status"] = computed_status
                changed = True

            normalized.append(item)

        if changed:
            save_user_leads(email, normalized)

        return jsonify({
            "ok": True,
            "email": email,
            "leads": normalized
        }), 200

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


@app.route("/api/leads", methods=["POST", "OPTIONS"])
def api_save_leads():
    if request.method == "OPTIONS":
        return ("", 204)

    email = _req_user_email()
    if not email:
        return jsonify({"ok": False, "error": "missing_user_email"}), 400

    payload = request.get_json(silent=True) or {}
    leads = payload.get("leads", None)

    if not isinstance(leads, list):
        return jsonify({"ok": False, "error": "body_must_include_leads_array"}), 400

    try:
        save_user_leads(email, leads)

        return jsonify({"ok": True, "email": email, "count": len(leads)}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


@app.post("/api/leads/contacted")
def api_mark_lead_contacted():
    email = _req_user_email()
    payload = request.get_json(silent=True) or {}
    lead_id = str(payload.get("leadId") or payload.get("lead_id") or "").strip()
    contacted_at = str(payload.get("at") or "").strip() or (
        datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    )
    if not email or not lead_id:
        return jsonify({"ok": False, "error": "user and leadId are required"}), 400

    leads_by_user = load_leads() or {}
    leads = leads_by_user.get(email, []) if isinstance(leads_by_user, dict) else []
    updated = None
    for lead in leads:
        if isinstance(lead, dict) and str(lead.get("id") or "") == lead_id:
            lead["last_contacted"] = contacted_at
            lead["last_activity_at"] = contacted_at
            lead["updated_at"] = contacted_at
            lead["status"] = "active"
            updated = lead
            break
    if updated is None:
        return jsonify({"ok": False, "error": "lead_not_found"}), 404
    save_user_leads(email, leads)
    return jsonify({"ok": True, "lead": updated}), 200

# Notifications

@app.route("/api/notifications/<path:user_email>", methods=["GET"])
def get_notifications(user_email):
    user_email = (user_email or "").strip().lower()

    try:
        all_notes = load_notifications() or {}
        if not isinstance(all_notes, dict):
            all_notes = {}
    except Exception as e:
        try:
            app.logger.warning("[NOTIFICATIONS] load failed for %s: %s", user_email, e)
        except Exception:
            pass
        all_notes = {}

    notes = all_notes.get(user_email, []) or []
    if not isinstance(notes, list):
        notes = []

    normalized = []
    for idx, n in enumerate(notes):
        if not isinstance(n, dict):
            continue
        normalized.append(_normalize_notification_item(n, idx))

    # Merge in derived appointment notifications
    derived = _build_upcoming_appointment_notifications(user_email)

    # Deduplicate by id
    seen = set()
    merged = []
    for item in normalized + derived:
        nid = str(item.get("id") or "")
        if nid in seen:
            continue
        seen.add(nid)
        merged.append(item)

    merged.sort(key=_notification_sort_ts, reverse=True)
    return jsonify({"notifications": merged}), 200


@app.route("/api/notifications/<path:user_email>/<notif_id>/mark_read", methods=["POST"])
def mark_notification_read(user_email, notif_id):
    user_email = (user_email or "").strip().lower()
    notif_id = str(notif_id or "").strip()

    try:
        all_notes = load_notifications() or {}
        if not isinstance(all_notes, dict):
            all_notes = {}
    except Exception as e:
        try:
            app.logger.warning("[NOTIFICATIONS] load failed for mark_read %s: %s", user_email, e)
        except Exception:
            pass
        return jsonify({"error": "Failed to load notifications"}), 500

    user_notes = all_notes.get(user_email, []) or []
    if not isinstance(user_notes, list):
        user_notes = []

    found = False

    # prefer stable id match
    for idx, n in enumerate(user_notes):
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or n.get("_id") or n.get("uuid") or idx)
        if nid == notif_id:
            n["read"] = True
            found = True
            break

    # backward-compatible numeric fallback
    if not found and notif_id.isdigit():
        idx = int(notif_id)
        if 0 <= idx < len(user_notes) and isinstance(user_notes[idx], dict):
            user_notes[idx]["read"] = True
            found = True

    if not found:
        return jsonify({"error": "Notification not found"}), 404

    all_notes[user_email] = user_notes

    try:
        save_notifications(all_notes)
    except Exception as e:
        try:
            app.logger.warning("[NOTIFICATIONS] save failed for %s: %s", user_email, e)
        except Exception:
            pass
        return jsonify({"error": "Failed to save notification state"}), 500

    return jsonify({"ok": True}), 200


@app.post("/api/notifications/<path:user_email>/read")
def mark_notification_read_legacy(user_email):
    """Compatibility endpoint for older clients that send the ID in JSON."""
    payload = request.get_json(silent=True) or {}
    notif_id = str(payload.get("id") or payload.get("notification_id") or "").strip()
    if not notif_id:
        return jsonify({"error": "Notification id is required"}), 400
    return mark_notification_read(user_email, notif_id)

@app.route("/api/email/inbound", methods=["POST"])
def inbound_email_webhook():
    try:
        form = request.form or {}

        to_addr = (form.get("to") or "").strip()
        from_addr = (form.get("from") or "").strip()
        subject = (form.get("subject") or "").strip()

        text_body = (form.get("text") or "").strip()
        html_body = (form.get("html") or "").strip()
        raw_email = form.get("email") or ""

        if not text_body and not html_body and raw_email:
            parsed_text, parsed_html = _extract_inbound_email_bodies(raw_email)
            text_body = text_body or parsed_text
            html_body = html_body or parsed_html

        spam_score = form.get("spam_score")
        spam_report = form.get("spam_report")

        try:
            app.logger.warning(
                "[EMAIL INBOUND] to=%r from=%r subject=%r keys=%s",
                to_addr,
                from_addr,
                subject,
                list(form.keys())
            )
        except Exception:
            pass

        owner_email, routed_lead_email = parse_inbound_reply_address(to_addr)

        try:
            app.logger.warning(
                "[EMAIL INBOUND] parsed owner=%r lead=%r from to=%r",
                owner_email,
                routed_lead_email,
                to_addr,
            )
        except Exception:
            pass

        if not owner_email:
            return jsonify({
                "ok": False,
                "error": "reply address could not be parsed",
                "to": to_addr,
            }), 400

        sender_email = parseaddr(from_addr)[1].strip().lower()
        if not sender_email:
            return jsonify({
                "ok": False,
                "error": "sender email missing",
                "from": from_addr,
            }), 400

        lead = _find_lead_by_email_for_owner(owner_email, sender_email)
        if not lead and routed_lead_email:
            lead = _find_lead_by_email_for_owner(owner_email, routed_lead_email)

        if not lead:
            add_notification(
                user_email=owner_email,
                subject="Email received (unmatched)",
                message=f"Received an email reply from {sender_email}, but no matching lead was found.",
                channel="email",
                lead_email=sender_email,
                extra={
                    "type": "inbound",
                    "email_subject": subject,
                },
            )
            return jsonify({"ok": True, "matched": False}), 200

        lead_id = str(lead.get("id") or "")
        lead_name = lead.get("name") or lead.get("first_name") or ""

        clean_text = _trim_email_reply_text(
            (
                text_body
                or _strip_html_to_text(html_body)
                or "(no body)"
            ).strip()
        )

        # IMPORTANT:
        # Do NOT save email replies into WhatsApp chat storage.
        # Notifications handle email activity separately.

        try:
            leads_by_user = load_leads() or {}
            arr = (leads_by_user.get(owner_email, []) or [])
            for i, ld in enumerate(arr):
                if str(ld.get("id") or "") == lead_id:
                    arr[i]["last_inbound_at"] = datetime.datetime.utcnow().isoformat()
                    arr[i]["last_activity_at"] = datetime.datetime.utcnow().isoformat()
                    break
            save_user_leads(owner_email, arr)
        except Exception:
            pass

        preview_text = clean_text[:180].strip()
        if len(clean_text) > 180:
            preview_text += "..."

        add_notification(
            user_email=owner_email,
            subject="Email received",
            message=preview_text or "(no body)",
            channel="email",
            lead_email=sender_email,
            extra={
                "lead_name": lead_name,
                "type": "inbound",
                "email_subject": subject,
                "spam_score": spam_score,
                "spam_report": spam_report,
            },
        )

        return jsonify({
            "ok": True,
            "matched": True,
            "owner_email": owner_email,
            "lead_email": sender_email,
            "lead_id": lead_id,
        }), 200

    except Exception as e:
        try:
            app.logger.exception("[EMAIL INBOUND] failed: %s", e)
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(e)}), 500

# ----------------------------
# Appointments
# ----------------------------
@app.route("/api/appointments/<user_email>", methods=["GET"])
def get_appointments(user_email):
    data = load_appointments()
    return jsonify({"appointments": data.get(user_email, [])}), 200

def send_appointment_confirmation_email(appt):
    try:
        create_ics_file(appt)

        display_time = datetime.datetime.strptime(
            appt["appointment_time"], "%Y-%m-%dT%H:%M:%S"
        ).strftime("%B %d, %Y, %I:%M %p")

        ics_file_url = f"{request.host_url.rstrip('/')}/ics/{appt['id']}.ics"
        google_calendar_link = make_google_calendar_link(appt)

        sent = send_email_with_template(
            to_email=appt["lead_email"],
            template_id=SG_TEMPLATE_APPT_CONFIRM,
            dynamic_data={
                "lead_first_name": appt.get("lead_first_name", ""),
                "user_name": appt.get("user_name", ""),
                "business_name": appt.get("business_name", ""),
                "display_time": display_time,
                "appointment_location": appt.get("appointment_location", ""),
                "google_calendar_link": google_calendar_link,
                "ics_file_url": ics_file_url,
                "user_email": appt.get("user_email", ""),
            },
            subject=f"Your appointment with {appt.get('business_name') or 'us'} is confirmed",
            from_email=Email(SENDER_EMAIL, appt.get("business_name") or "Your Business"),
            reply_to_email=(
                make_inbound_reply_address(appt.get("user_email", ""), appt.get("lead_email", ""))
                if appt.get("user_email") and appt.get("lead_email") else None
            ),
        )

        if sent:
            add_notification(
                appt.get("user_email", ""),
                "Appointment confirmation sent",
                f"Confirmation email sent to {appt.get('lead_first_name','Client')} for {display_time}.",
                channel="appointment",
                lead_email=appt.get("lead_email", ""),
                extra={"appointment_id": appt.get("id")}
            )

        return bool(sent)
    except Exception as e:
        try:
            app.logger.warning("[APPOINTMENT CONFIRM EMAIL ERROR] %s", e)
        except Exception:
            pass
        return False

@app.route("/api/appointments/<user_email>", methods=["POST"])
def create_appointment(user_email):
    data = request.get_json(silent=True) or {}
    user_email = (user_email or "").strip().lower()

    lead_email = (data.get("lead_email") or "").strip()
    lead_first_name = (data.get("lead_first_name") or "").strip()
    lead_last_name = (data.get("lead_last_name") or "").strip()
    lead_full_name = (data.get("lead_full_name") or "").strip()

    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", lead_email):
        return jsonify({"error": "A valid lead_email is required"}), 400

    raw_appointment_time = str(data.get("appointment_time") or "").strip()
    try:
        parsed_appointment_time = datetime.datetime.strptime(
            raw_appointment_time, "%Y-%m-%dT%H:%M:%S"
        )
    except (TypeError, ValueError):
        return jsonify({"error": "appointment_time must use YYYY-MM-DDTHH:MM:SS"}), 400

    try:
        duration = int(data.get("duration", 30))
    except (TypeError, ValueError):
        return jsonify({"error": "duration must be a number of minutes"}), 400
    if duration < 5 or duration > 1440:
        return jsonify({"error": "duration must be between 5 and 1440 minutes"}), 400

    # Fallback parsing if only full name was sent
    if not lead_first_name and lead_full_name:
        parts = lead_full_name.split()
        if parts:
            lead_first_name = parts[0].strip()
            if len(parts) > 1:
                lead_last_name = " ".join(parts[1:]).strip()

    appt = {
        "id": str(uuid4()),
        "lead_email": lead_email,
        "lead_first_name": lead_first_name,
        "lead_last_name": lead_last_name,
        "lead_full_name": lead_full_name or " ".join(
            [p for p in [lead_first_name, lead_last_name] if p]
        ).strip(),
        "user_name": data.get("user_name", ""),
        "user_email": user_email,
        "business_name": data.get("business_name", ""),
        "appointment_time": raw_appointment_time,
        "appointment_location": data.get("appointment_location", ""),
        "duration": duration,
        "notes": data.get("notes", ""),
        "status": data.get("status", "scheduled"),
        "lead_id": data.get("lead_id", ""),
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    appointments = load_appointments() or {}
    appointments.setdefault(user_email, []).append(appt)
    save_appointments(appointments)

    create_ics_file(appt)

    display_time = parsed_appointment_time.strftime("%B %d, %Y, %I:%M %p")

    ics_file_url = f"{request.host_url.rstrip('/')}/ics/{appt['id']}.ics"
    google_calendar_link = make_google_calendar_link(appt)

    confirmation_sent = send_email_with_template(
        to_email=appt["lead_email"],
        template_id=SG_TEMPLATE_APPT_CONFIRM,
        dynamic_data={
            "lead_first_name": appt["lead_first_name"],
            "lead_last_name": appt["lead_last_name"],
            "lead_full_name": appt["lead_full_name"],
            "user_name": appt["user_name"],
            "business_name": appt["business_name"],
            "display_time": display_time,
            "appointment_location": appt["appointment_location"],
            "google_calendar_link": google_calendar_link,
            "ics_file_url": ics_file_url,
            "user_email": appt["user_email"],
        },
        subject=f"Your appointment with {appt.get('business_name') or 'us'} is confirmed",
        from_email=Email(SENDER_EMAIL, appt.get("business_name") or "Your Business"),
        reply_to_email=(
            make_inbound_reply_address(appt.get("user_email", ""), appt.get("lead_email", ""))
            if appt.get("user_email") and appt.get("lead_email") else None
        ),
    )

    add_notification(
        user_email=user_email,
        subject=("Appointment created" if confirmation_sent else "Appointment created - email needs attention"),
        message=(
            f"Appointment booked with {appt.get('lead_full_name') or appt.get('lead_email') or 'lead'} for {display_time}."
            + ("" if confirmation_sent else " The confirmation email could not be sent.")
        ),
        channel="appointment",
        lead_email=appt.get("lead_email") or "",
        extra={
            "lead_name": appt.get("lead_full_name") or appt.get("lead_first_name") or "",
            "appointment_id": appt.get("id"),
        },
    )

    return jsonify({
        "message": (
            "Appointment created and confirmation sent."
            if confirmation_sent else
            "Appointment created, but the confirmation email could not be sent."
        ),
        "appointment": appt,
        "confirmation_sent": bool(confirmation_sent),
    }), 201


@app.route("/api/appointments/<user_email>/<appt_id>", methods=["PUT"])
def update_appointment(user_email, appt_id):
    data = request.get_json(silent=True) or {}
    user_email = (user_email or "").strip().lower()

    appointments = load_appointments() or {}
    user_appts = appointments.get(user_email, [])
    updated = False
    updated_obj = None

    for i, appt in enumerate(user_appts):
        if appt["id"] == appt_id:
            for k, v in data.items():
                user_appts[i][k] = v
            user_appts[i]["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            updated = True
            updated_obj = user_appts[i]
            create_ics_file(updated_obj)
            break

    appointments[user_email] = user_appts
    save_appointments(appointments)

    if updated and updated_obj:
        add_notification(
            user_email=user_email,
            subject="Appointment updated",
            message=f"Appointment updated for {updated_obj.get('lead_first_name') or updated_obj.get('lead_email') or 'lead'}.",
            channel="appointment",
            lead_email=updated_obj.get("lead_email") or "",
            extra={
                "lead_name": updated_obj.get("lead_first_name") or "",
                "appointment_id": updated_obj.get("id"),
            },
        )

        if str(updated_obj.get("status") or "").strip().lower().replace("_", "-") == "no-show":
            add_notification(
                user_email=user_email,
                subject="Appointment no-show",
                message=f"{updated_obj.get('lead_first_name') or updated_obj.get('lead_email') or 'Lead'} was marked as a no-show.",
                channel="appointment",
                lead_email=updated_obj.get("lead_email") or "",
                extra={
                    "lead_name": updated_obj.get("lead_first_name") or "",
                    "appointment_id": updated_obj.get("id"),
                },
            )

    return jsonify({"updated": updated, "appointment": updated_obj}), 200

@app.route("/api/appointments/<user_email>/<appt_id>", methods=["DELETE"])
def delete_appointment(user_email, appt_id):
    user_email = (user_email or "").strip().lower()

    appointments = load_appointments() or {}
    user_appts = appointments.get(user_email, []) or []

    removed = None
    kept = []
    for a in user_appts:
        if a.get("id") == appt_id and removed is None:
            removed = a
        else:
            kept.append(a)

    appointments[user_email] = kept
    save_appointments(appointments)

    fname = os.path.join(ICS_DIR, f"{appt_id}.ics")
    if os.path.exists(fname):
        os.remove(fname)

    if removed:
        add_notification(
            user_email=user_email,
            subject="Appointment canceled",
            message=f"Appointment removed for {removed.get('lead_first_name') or removed.get('lead_email') or 'lead'}.",
            channel="appointment",
            lead_email=removed.get("lead_email") or "",
            extra={
                "lead_name": removed.get("lead_first_name") or "",
                "appointment_id": removed.get("id"),
            },
        )

    return jsonify({"deleted": 1 if removed else 0}), 200

# ----------------------------
# Stripe Connect / Billing (ORG-AWARE + MEMBER SAFE)
# ----------------------------
def _resolve_org_and_role(email: str, users: dict):
    """
    Return (role, org_owner_email, org_owner_record, subject_record).

    Team records live under ``user::<email>``. A teammate may also have a
    top-level login record, but that must never make them an organization owner.
    Roles currently returned are: owner, manager, or member.
    """
    email = _norm_email(email)
    if not email or not isinstance(users, dict):
        return (None, None, None, None)

    team_rec = users.get(f"user::{email}")
    if isinstance(team_rec, dict):
        role = str(team_rec.get("role") or "member").strip().lower()
        org_email = _norm_email(team_rec.get("org_id") or email)

        # Older team code may have created a user::<owner> mirror record.
        if role == "owner" or org_email == email:
            org_owner = users.get(org_email) or users.get(email)
            if isinstance(org_owner, dict):
                return ("owner", org_email, org_owner, team_rec)
        else:
            org_owner = users.get(org_email)
            if isinstance(org_owner, dict):
                if role not in ("manager", "member"):
                    role = "member"
                return (role, org_email, org_owner, team_rec)

    top_level = users.get(email)
    if isinstance(top_level, dict):
        top_role = str(top_level.get("role") or "").strip().lower()
        top_org = _norm_email(top_level.get("org_id") or "")

        # A member's own login record is still a member record, not an owner.
        if top_org and top_org != email and top_role in ("manager", "member"):
            org_owner = users.get(top_org)
            if isinstance(org_owner, dict):
                return (top_role, top_org, org_owner, top_level)

        return ("owner", email, top_level, top_level)

    return (None, None, None, None)

def _require_user_email_arg():
    ue = request.args.get("user_email")
    return _norm_email(ue) if ue else None

def to_minor(amount, currency):
    c = (currency or "usd").lower()
    return int(round(float(amount) * (1 if c in ZERO_DECIMAL else 100)))

def from_minor(value, currency):
    c = (currency or "usd").lower()
    denom = 1 if c in ZERO_DECIMAL else 100.0
    return (value or 0) / denom

def _safe_get(obj, *path, default=None):
    cur = obj
    for p in path:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = getattr(cur, p, None)
    return cur if cur is not None else default

def _connected_acct_for(email: str):
    users = load_users() or {}
    if not isinstance(users, dict):
        return (None, None, None, None)
    role, org_email, org_owner, _subject = _resolve_org_and_role(email, users)
    if not role:
        return (None, None, None, None)
    return (role, org_email, org_owner, org_owner.get("stripe_account_id"))

def serialize_invoice(inv):
    currency = inv.currency
    cust_name = (
        _safe_get(inv, "customer", "name")
        or _safe_get(inv, "metadata", "customer_name")
        or _safe_get(inv, "customer_email")
    )

    amount_total = from_minor(getattr(inv, "total", None) or inv.amount_due, currency)
    amount_due   = from_minor(inv.amount_due, currency)
    amount_paid  = from_minor(getattr(inv, "amount_paid", 0), currency)

    display = amount_total if str(inv.status).lower() == "paid" else amount_due

    return {
        "id": inv.id,
        "customer_name": cust_name,
        "customer_email": inv.customer_email,
        "amount_total": round(amount_total, 2),
        "amount_due": round(amount_due, 2),
        "amount_paid": round(amount_paid, 2),
        "amount_display": round(display, 2),
        "currency": currency,
        "due_date": inv.due_date,
        "status": inv.status,
        "invoice_url": inv.hosted_invoice_url,
        "number": getattr(inv, "number", None),
    }

# app.py (CONSOLIDATED + PROD-SAFE) â€” PART 2/2 (CONTINUATION)

@app.route("/api/stripe/connect-url", methods=["GET"])
def get_stripe_connect_url():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "STRIPE_SECRET_KEY is missing"}), 500

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    role, org_email, org_owner, _ = _resolve_org_and_role(user_email, users)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403

    try:
        acct_id = org_owner.get("stripe_account_id")
        acct = None

        if acct_id:
            try:
                acct = stripe.Account.retrieve(acct_id)
            except Exception:
                acct = None

        if not acct:
            acct = stripe.Account.create(type="express", email=org_email)
            org_owner["stripe_account_id"] = acct.id
            org_owner["stripe_connected"] = True
            users[org_email] = org_owner
            save_users(users)

        return_url = f"{FRONTEND_URL}/app/settings?stripe_connected=1"
        refresh_url = f"{FRONTEND_URL}/app/settings?stripe_refresh=1"

        link = stripe.AccountLink.create(
            account=acct.id,
            refresh_url=refresh_url,
            return_url=return_url,
            type="account_onboarding",
        )

        return jsonify({"url": link.url}), 200

    except Exception as e:
        try:
            app.logger.exception("[STRIPE CONNECT URL] %s", e)
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

@app.route("/api/stripe/oauth/connect", methods=["GET"])
def stripe_oauth_connect():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    if not STRIPE_CONNECT_CLIENT_ID or not STRIPE_REDIRECT_URI:
        return jsonify({"error": "Stripe Connect not configured"}), 500

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    role, org_email, org_owner, _ = _resolve_org_and_role(user_email, users)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403

    oauth_url = (
        "https://connect.stripe.com/oauth/authorize"
        f"?response_type=code"
        f"&client_id={STRIPE_CONNECT_CLIENT_ID}"
        f"&scope=read_write"
        f"&redirect_uri={urllib.parse.quote_plus(STRIPE_REDIRECT_URI)}"
        f"&state={org_email}"
    )

    return jsonify({"url": oauth_url}), 200

@app.route("/api/stripe/oauth/callback", methods=["GET"])
def stripe_oauth_callback():
    error = request.args.get("error")
    error_desc = request.args.get("error_description", "")
    state_email = _norm_email(request.args.get("state"))
    code = request.args.get("code")

    if error:
        msg = urllib.parse.quote_plus(error_desc or error)
        return redirect(f"{FRONTEND_URL}/app/settings?stripe_error=1&stripe_error_desc={msg}")

    if not code or not state_email:
        return redirect(f"{FRONTEND_URL}/app/settings?stripe_error=1&stripe_error_desc=missing_code_or_state")

    try:
        resp = stripe.OAuth.token(
            grant_type="authorization_code",
            code=code,
        )
        stripe_user_id = resp["stripe_user_id"]
    except Exception as e:
        msg = urllib.parse.quote_plus(str(e))
        return redirect(f"{FRONTEND_URL}/app/settings?stripe_error=1&stripe_error_desc={msg}")

    users = load_users() or {}
    if not isinstance(users, dict):
        return redirect(f"{FRONTEND_URL}/app/settings?stripe_error=1&stripe_error_desc=storage_not_ready")

    role, org_email, org_owner, _subject = _resolve_org_and_role(state_email, users)
    if not role:
        return redirect(f"{FRONTEND_URL}/app/settings?stripe_error=1&stripe_error_desc=user_not_found")

    org_owner = org_owner or {}
    org_owner["stripe_account_id"] = stripe_user_id
    org_owner["stripe_connected"] = True
    users[org_email] = org_owner
    save_users(users)

    return redirect(f"{FRONTEND_URL}/app/settings?stripe_connected=1")

@app.route("/api/stripe/dashboard-link", methods=["GET"])
def stripe_dashboard_link():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    role, org_email, org_owner, acct_id = _connected_acct_for(user_email)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 400

    try:
        acct = stripe.Account.retrieve(acct_id)
        if getattr(acct, "type", None) in ("express", "custom"):
            link = stripe.Account.create_login_link(acct_id)
            return jsonify({"url": link.url}), 200

        return jsonify({"url": f"https://dashboard.stripe.com/{acct_id}"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stripe/account", methods=["GET"])
def get_stripe_account():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    role, org_email, org_owner, acct_id = _connected_acct_for(user_email)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 404

    acct = stripe.Account.retrieve(acct_id)
    email = getattr(acct, "email", None) or _safe_get(acct, "business_profile", "support_email")

    return jsonify({
        "account": {
            "id": acct.id,
            "type": getattr(acct, "type", None),
            "default_currency": getattr(acct, "default_currency", None),
            "details_submitted": getattr(acct, "details_submitted", None),
            "email": email
        }
    }), 200

@app.route("/api/stripe/invoice", methods=["POST"])
def create_stripe_invoice():
    data = request.get_json(silent=True) or {}

    user_email = _norm_email(data.get("user_email"))
    customer_name = data.get("customer_name")
    customer_email = data.get("customer_email")
    description = data.get("description")
    amount = data.get("amount")
    unit_amount = data.get("unit_amount")
    quantity = int(data.get("quantity") or 1)
    currency = (data.get("currency") or "").lower().strip() or None

    if not all([user_email, customer_name, customer_email, description]):
        return jsonify({"error": "Missing required fields"}), 400

    try:
        if amount is not None:
            total_float = float(amount)
        else:
            total_float = float(unit_amount) * quantity
        if total_float <= 0:
            raise ValueError("amount<=0")
    except Exception:
        return jsonify({"error": "Amount must be a number greater than 0"}), 400

    role, org_email, org_owner, acct_id = _connected_acct_for(user_email)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 400

    try:
        if not currency:
            acct = stripe.Account.retrieve(acct_id)
            currency = (getattr(acct, "default_currency", None) or "usd").lower()

        existing = stripe.Customer.list(email=customer_email, limit=1, stripe_account=acct_id).data
        if existing:
            cust = existing[0]
            stripe.Customer.modify(cust.id, name=customer_name, stripe_account=acct_id)
        else:
            cust = stripe.Customer.create(email=customer_email, name=customer_name, stripe_account=acct_id)
        cust_id = cust.id

        inv = stripe.Invoice.create(
            customer=cust_id,
            collection_method="send_invoice",
            days_until_due=7,
            auto_advance=False,
            metadata={"user_email": user_email, "customer_name": customer_name},
            stripe_account=acct_id,
        )

        total_minor = to_minor(total_float, currency)
        stripe.InvoiceItem.create(
            customer=cust_id,
            invoice=inv.id,
            amount=total_minor,
            currency=currency,
            description=description,
            metadata={"user_email": user_email, "customer_name": customer_name, "quantity": quantity},
            stripe_account=acct_id,
        )

        inv = stripe.Invoice.finalize_invoice(inv.id, stripe_account=acct_id)

        latest = stripe.Invoice.list(limit=100, expand=["data.customer"], stripe_account=acct_id).data
        invoices = [serialize_invoice(x) for x in latest]

        return jsonify({
            "success": True,
            "account_id": acct_id,
            "invoice_id": inv.id,
            "invoice_url": inv.hosted_invoice_url,
            "amount_due": from_minor(inv.amount_due, inv.currency),
            "amount_total": from_minor(getattr(inv, "total", None) or inv.amount_due, inv.currency),
            "currency": inv.currency,
            "invoice": serialize_invoice(inv),
            "invoices": invoices
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stripe/invoices", methods=["GET"])
def list_stripe_invoices():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    role, org_email, org_owner, acct_id = _connected_acct_for(user_email)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 400

    invs = stripe.Invoice.list(limit=100, expand=["data.customer"], stripe_account=acct_id).data
    out = [serialize_invoice(inv) for inv in invs]
    return jsonify({"invoices": out, "account_id": acct_id}), 200

@app.route("/api/stripe/invoice/send", methods=["POST"])
def resend_invoice_email():
    data = request.get_json(silent=True) or {}
    invoice_id = data.get("invoice_id")
    user_email = _norm_email(data.get("user_email"))
    if not invoice_id or not user_email:
        return jsonify({"error": "Missing invoice_id or user_email"}), 400

    role, org_email, org_owner, acct_id = _connected_acct_for(user_email)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 400
    if not SENDGRID_API_KEY:
        return jsonify({"error": "SendGrid not configured"}), 500

    user_name = org_owner.get("name", "")
    business = org_owner.get("business", "")

    try:
        inv = stripe.Invoice.retrieve(invoice_id, expand=["customer"], stripe_account=acct_id)
        total = from_minor(getattr(inv, "total", None) or inv.amount_due, inv.currency)
        cust = inv.customer

        html = f"""
          <p>Hi {inv.metadata.get("customer_name","")},</p>
          <p>Your invoice <strong>#{getattr(inv, "number", inv.id)}</strong> from <strong>{business}</strong> is now available.</p>
          <p><strong>Amount:</strong> {total:.2f} {inv.currency.upper()}</p>
          <p><a href="{inv.hosted_invoice_url}">View &amp; pay your invoice â†’</a></p>
          <br/>
          <p>Thanks for working with {business}!</p>
        """

        msg = Mail(
            from_email=Email("billing@retainai.ca", name=f"{user_name} at {business}"),
            to_emails=_safe_get(cust, "email", default=None) or inv.customer_email,
            subject=f"Invoice #{getattr(inv, 'number', inv.id)} from {business}",
            html_content=html
        )
        SendGridAPIClient(SENDGRID_API_KEY).send(msg)
        return jsonify({"success": True}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception:
        return "", 400

    event_type = str(event.get("type") or "")
    event_object = (event.get("data") or {}).get("object") or {}
    users = load_users() or {}
    if not isinstance(users, dict):
        return "", 503

    def find_billing_user() -> Tuple[str, Optional[dict]]:
        metadata = event_object.get("metadata") or {}
        candidate_email = _norm_email(
            event_object.get("customer_email")
            or (event_object.get("customer_details") or {}).get("email")
            or metadata.get("user_email")
        )
        if candidate_email and isinstance(users.get(candidate_email), dict):
            return candidate_email, users[candidate_email]
        customer_id = str(event_object.get("customer") or "")
        subscription_id = str(
            event_object.get("subscription")
            or (event_object.get("id") if event_type.startswith("customer.subscription.") else "")
            or ""
        )
        for stored_email, stored_user in users.items():
            if not isinstance(stored_user, dict):
                continue
            if customer_id and str(stored_user.get("stripe_customer_id") or "") == customer_id:
                return stored_email, stored_user
            if subscription_id and str(stored_user.get("stripe_subscription_id") or "") == subscription_id:
                return stored_email, stored_user
        return "", None

    email, user = find_billing_user()
    if email and user:
        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        customer_id = event_object.get("customer")
        if customer_id:
            user["stripe_customer_id"] = customer_id

        if event_type == "checkout.session.completed":
            user["stripe_checkout_session_id"] = str(event_object.get("id") or "")
            subscription = event_object.get("subscription")
            if subscription:
                user["stripe_subscription_id"] = (
                    subscription.get("id") if isinstance(subscription, dict) else subscription
                )
            user["status"] = "active"
            user["billing_status"] = "active"
            user["billing_issue_at"] = ""
        elif event_type in {"invoice.paid", "invoice.payment_succeeded"}:
            user["status"] = "active"
            user["billing_status"] = "active"
            user["billing_issue_at"] = ""
        elif event_type in {"invoice.payment_failed", "invoice.payment_action_required"}:
            # Keep the workspace available while Stripe retries the payment.
            user["billing_status"] = "past_due"
            user["billing_issue_at"] = now_iso
        elif event_type == "customer.subscription.updated":
            subscription_status = str(event_object.get("status") or "")
            user["stripe_subscription_id"] = event_object.get("id")
            user["billing_status"] = subscription_status
            items = ((event_object.get("items") or {}).get("data") or [])
            monthly_value = 0.0
            currency = ""
            for item in items:
                price = (item or {}).get("price") or {}
                unit_amount = price.get("unit_amount")
                recurring = price.get("recurring") or {}
                interval = str(recurring.get("interval") or "month")
                interval_count = max(1, int(recurring.get("interval_count") or 1))
                quantity = max(1, int((item or {}).get("quantity") or 1))
                if unit_amount is None:
                    continue
                amount = (float(unit_amount) / 100.0) * quantity
                if interval == "year":
                    amount /= 12 * interval_count
                elif interval == "week":
                    amount *= 52 / (12 * interval_count)
                elif interval == "day":
                    amount *= 365 / (12 * interval_count)
                else:
                    amount /= interval_count
                monthly_value += amount
                currency = str(price.get("currency") or currency).upper()
            user["subscription_mrr"] = round(monthly_value, 2)
            user["subscription_currency"] = currency
            if subscription_status in {"active", "trialing", "past_due"}:
                user["status"] = "active"
            elif subscription_status in {"unpaid", "incomplete_expired", "canceled"}:
                user["status"] = "inactive"
        elif event_type == "customer.subscription.deleted":
            user["billing_status"] = "canceled"
            user["status"] = "inactive"
            user["stripe_subscription_id"] = ""

        user["stripe_event_type"] = event_type
        user["stripe_event_at"] = now_iso
        users[email] = user
        save_users(users)
    return "", 200

@app.route("/api/stripe/disconnect", methods=["POST"])
def stripe_disconnect():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    role, org_email, org_owner, acct_id = _connected_acct_for(user_email)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403
    if not acct_id:
        return jsonify({"error": "No Stripe account to disconnect"}), 400

    try:
        if STRIPE_CONNECT_CLIENT_ID:
            try:
                stripe.OAuth.deauthorize(
                    client_id=STRIPE_CONNECT_CLIENT_ID,
                    stripe_user_id=acct_id
                )
            except Exception as e:
                app.logger.warning("[STRIPE DISCONNECT] deauth warning: %s", e)

        org_owner = users.get(org_email, {}) or {}
        org_owner.pop("stripe_account_id", None)
        org_owner["stripe_connected"] = False
        users[org_email] = org_owner
        save_users(users)

        return jsonify({"ok": True}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------------------
# Auth & Google OAuth (trial gated)
# ----------------------------
def _user_payload(email: str, user: dict) -> dict:
    email = _norm_email(email)
    users = load_users() or {}

    role, org_email, org_owner, subject = _resolve_org_and_role(email, users if isinstance(users, dict) else {})
    org_owner = org_owner or {}
    subject = subject or user or {}

    if role and role != "owner":
        base = org_owner
        display_name = subject.get("name", "") or base.get("name", "")
    else:
        base = subject
        display_name = base.get("name", "")

    logo = base.get("logo") or base.get("picture") or ""
    trial = _trial_details(base)

    return {
        "email": email,
        "name": display_name,
        "logo": logo,

        "businessType": base.get("businessType", ""),
        "business": base.get("business", ""),
        "people": base.get("people") or base.get("teamSize", ""),
        "location": base.get("location", ""),

        "stripe_account_id": base.get("stripe_account_id"),
        "stripe_connected": bool(base.get("stripe_connected", False)),

        "gcal_connected": bool(base.get("gcal_connected", False)),
        "gcal_calendars": base.get("gcal_calendars", []),

        "status": base.get("status", ""),
        "trialActive": trial["active"],
        "trialDaysRemaining": trial["daysRemaining"],
        "trialEndsAt": trial["endsAt"],
        "billingRequired": not _is_platform_owner(email) and not _account_has_access(base),
        "complimentaryAccess": _complimentary_access_active(base),
        "complimentaryExpiresAt": base.get("complimentary_expires_at", ""),
        "hasBillingProfile": bool(
            base.get("stripe_customer_id") or base.get("stripe_subscription_id")
        ),
        "deletion_requested_at": base.get("deletion_requested_at", ""),
        "deletion_scheduled_for": base.get("deletion_scheduled_for", ""),
        "role": role or user.get("role"),
        "org_id": org_email or user.get("org_id"),
        "orgOwnerEmail": org_email,

        "canInviteTeam": role == "owner",
        "canEditBusiness": role == "owner",
        "canManageBilling": role == "owner",
        "platformOwner": _is_platform_owner(email),
        "emailVerified": bool(base.get("email_verified") or _is_platform_owner(email)),
    }

def _bootstrap_platform_owner() -> None:
    """
    Provision or recover the dedicated platform-owner login from Render secrets.
    No password is embedded in source control. When PLATFORM_OWNER_PASSWORD is
    configured, it becomes the authoritative password after every safe restart.
    """
    password = str(os.getenv("PLATFORM_OWNER_PASSWORD") or "").strip()
    email = "owner@retainai.ca"
    if not password or not email:
        return
    if len(password) < 12:
        print("[SECURITY] PLATFORM_OWNER_PASSWORD must contain at least 12 characters.")
        return

    users = load_users() or {}
    if not isinstance(users, dict):
        print("[SECURITY] Could not bootstrap the platform owner: storage is unavailable.")
        return

    account = users.get(email)
    if not isinstance(account, dict):
        account = {}
    account.update(
        {
            "email": email,
            "name": account.get("name") or "RetainAI Owner",
            "business": account.get("business") or "RetainAI",
            "businessName": account.get("businessName") or "RetainAI",
            "role": "owner",
            "org_id": email,
            "status": "active",
            "email_verified": True,
            "password": generate_password_hash(password),
        }
    )
    users[email] = account
    save_users(users)
    print(f"[SECURITY] Platform owner account ready: {email}")


_bootstrap_platform_owner()


@app.post("/api/auth/password/forgot")
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    generic = {
        "ok": True,
        "message": "If an account exists for that email, a secure reset link is on its way.",
    }
    if not email or _password_reset_rate_limited(email):
        return jsonify(generic), 200

    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if (
        isinstance(user, dict)
        and user.get("password")
        and not _is_platform_owner(email)
    ):
        _password_reset_email(_password_reset_token(email, user), email)
    return jsonify(generic), 200


@app.post("/api/auth/password/reset")
def reset_password():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "").strip()
    password = str(data.get("password") or "")
    if len(password) < 12:
        return jsonify({"error": "Use at least 12 characters for your new password."}), 400
    if len(password) > 256:
        return jsonify({"error": "Password is too long."}), 400

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 503
    try:
        email, user = _decode_password_reset_token(token, users)
    except Exception:
        return jsonify({
            "error": "This reset link is invalid or expired. Request a new one."
        }), 400

    user["password"] = generate_password_hash(password)
    user["password_changed_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    user["security_version"] = int(user.get("security_version") or 0) + 1
    users[email] = user
    save_users(users)
    session.clear()
    _clear_login_failures(email)
    return jsonify({
        "ok": True,
        "message": "Password updated. Sign in with your new password.",
    }), 200


@app.get("/api/auth/email/verify")
def verify_email():
    token = str(request.args.get("token") or "")
    try:
        email = _decode_email_verification_token(token)
    except Exception:
        return redirect(f"{FRONTEND_URL}/login?email_verified=invalid")
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not isinstance(user, dict):
        return redirect(f"{FRONTEND_URL}/login?email_verified=invalid")
    user["email_verified"] = True
    user["email_verified_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    users[email] = user
    save_users(users)
    return redirect(f"{FRONTEND_URL}/login?email_verified=success")


@app.post("/api/auth/email/resend")
def resend_verification_email():
    data = request.get_json(silent=True) or {}
    email = _session_email() or _norm_email(data.get("email"))
    generic = {"ok": True, "message": "If verification is required, a new email is on its way."}
    if not email or _password_reset_rate_limited(f"verify:{email}"):
        return jsonify(generic), 200
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not isinstance(user, dict):
        return jsonify(generic), 200
    if user.get("email_verified"):
        return jsonify(generic), 200
    if not _send_verification_email(email):
        return jsonify({"error": "verification_email_unavailable"}), 503
    return jsonify(generic), 200


def _complete_login_response(email: str, user: dict, payload: dict, remember: bool, message: str):
    _clear_login_failures(email)
    if bool((user or {}).get("totp_enabled")):
        session.clear()
        session.permanent = False
        session["mfa_pending_email"] = _norm_email(email)
        session["mfa_pending_remember"] = bool(remember)
        session["mfa_pending_at"] = int(time.time())
        return jsonify({
            "message": "Two-factor verification required",
            "mfaRequired": True,
            "emailHint": _norm_email(email),
        }), 202
    _start_user_session(email, payload, remember)
    return jsonify({"message": message, "user": payload}), 200


@app.route("/api/signup", methods=["POST", "OPTIONS"])
@app.route("/api/auth/signup", methods=["POST", "OPTIONS"])
def signup():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}

    email = _norm_email(data.get("email"))
    password = (data.get("password") or "").strip()
    name = (data.get("name") or "").strip()

    businessType = (data.get("businessType") or "").strip()
    businessName = (data.get("businessName") or businessType or "").strip()
    teamSize = (data.get("teamSize") or "").strip()
    logo = (data.get("logo") or "").strip()

    phone = (data.get("phone") or "").strip()
    website = (data.get("website") or "").strip()
    instagram = (data.get("instagram") or "").strip()
    location = (data.get("location") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    if email in users:
        return jsonify({"error": "User already exists"}), 409

    trial_start = datetime.datetime.utcnow().isoformat()
    repeat_customer = trial_previously_used(email)
    trial_days = 0 if repeat_customer else int(TRIAL_DAYS)

    users[email] = {
        "email": email,
        "password": generate_password_hash(password),
        "name": name,
        "businessType": businessType,
        "business": businessName,
        "businessName": businessName,
        "teamSize": teamSize,
        "logo": logo,
        "phone": phone,
        "website": website,
        "instagram": instagram,
        "location": location,
        "status": "pending_payment",
        "email_verified": False,
        "trial_start": trial_start,
        "trial_eligible": not repeat_customer,
        "trial_ending_notice_sent": False,
    }
    save_users(users)
    record_trial_start(email)
    _send_verification_email(email)

    try:
        send_email_with_template(
            to_email=email,
            template_id=SG_TEMPLATE_WELCOME,
            dynamic_data={"user_name": name or "", "business_type": businessName or ""},
            from_email=platform_email_sender(),
            subject="Welcome to RetainAI"
        )
    except Exception as e:
        print(f"[WARN] Couldn't send welcome email: {e}")

    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        return jsonify({"error": "Billing not configured. Missing STRIPE_SECRET_KEY or STRIPE_PRICE_ID."}), 500

    try:
        checkout = _create_or_reuse_billing_checkout(
            email,
            users[email],
            cancel_url=f"{FRONTEND_URL}/login?canceled=1",
            trial_days=trial_days,
        )
        return jsonify({
            "checkoutUrl": checkout["url"],
            "billingState": checkout["state"],
        }), 200

    except stripe.error.StripeError as e:
        print(f"[STRIPE ERROR] {getattr(e, 'user_message', str(e))}")
        return jsonify({"error": "Could not start payment process."}), 500
    except Exception as e:
        print(f"[STRIPE ERROR] {e}")
        return jsonify({"error": "Could not start payment process."}), 500


def _reconcile_paid_subscription(email: str, user: dict) -> bool:
    """Recover access when Stripe is active but a webhook was delayed."""
    if not STRIPE_SECRET_KEY or not isinstance(user, dict):
        return False
    customer_ids = []
    stored_customer = str(user.get("stripe_customer_id") or "").strip()
    if stored_customer:
        customer_ids.append(stored_customer)
    try:
        for customer in stripe.Customer.list(email=email, limit=10).data:
            customer_id = str(customer.get("id") or "").strip()
            if customer_id and customer_id not in customer_ids:
                customer_ids.append(customer_id)
    except Exception:
        return False

    for customer_id in customer_ids:
        try:
            subscriptions = stripe.Subscription.list(
                customer=customer_id,
                status="all",
                limit=10,
            ).data
        except Exception:
            continue
        for subscription in subscriptions:
            subscription_status = str(subscription.get("status") or "")
            if subscription_status not in {"active", "trialing"}:
                continue
            user["status"] = "active"
            user["billing_status"] = subscription_status
            user["stripe_customer_id"] = customer_id
            user["stripe_subscription_id"] = subscription.get("id")
            user["stripe_event_type"] = "login.subscription_reconciled"
            user["stripe_event_at"] = datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat().replace("+00:00", "Z")
            return True
    return False


_BLOCKING_SUBSCRIPTION_STATUSES = {
    "active",
    "trialing",
    "past_due",
    "unpaid",
    "incomplete",
    "paused",
}


def _find_existing_billing_subscription(email: str, user: dict):
    """Return an existing live/recoverable subscription before creating another."""
    customer_ids = []
    stored_customer = str((user or {}).get("stripe_customer_id") or "").strip()
    if stored_customer:
        customer_ids.append(stored_customer)
    try:
        for customer in stripe.Customer.list(email=email, limit=10).data:
            customer_id = str(customer.get("id") or "").strip()
            if customer_id and customer_id not in customer_ids:
                customer_ids.append(customer_id)
    except Exception:
        # A Stripe lookup failure must fail closed later; it must never be
        # interpreted as permission to create another subscription.
        raise

    matches = []
    for customer_id in customer_ids:
        subscriptions = stripe.Subscription.list(
            customer=customer_id,
            status="all",
            limit=100,
        ).data
        for subscription in subscriptions:
            status = str(subscription.get("status") or "").lower()
            if status in _BLOCKING_SUBSCRIPTION_STATUSES:
                matches.append((customer_id, subscription))

    if not matches:
        return None

    # Prefer the oldest subscription. A customer needs only one RetainAI plan;
    # retaining all matches in the record makes accidental duplicates visible
    # to support without silently charging for yet another one.
    matches.sort(key=lambda item: int(item[1].get("created") or 0))
    customer_id, subscription = matches[0]
    user["stripe_customer_id"] = customer_id
    user["stripe_subscription_id"] = str(subscription.get("id") or "")
    user["billing_status"] = str(subscription.get("status") or "")
    user["stripe_duplicate_subscription_count"] = max(0, len(matches) - 1)
    if user["billing_status"] in {"active", "trialing"}:
        user["status"] = "active"
    return subscription


def _create_or_reuse_billing_checkout(
    email: str,
    user: dict,
    *,
    cancel_url: str,
    trial_days: int = 0,
    recovery: bool = False,
):
    """Create at most one Stripe subscription checkout for an account.

    Every entry point uses this function. It first checks Stripe for an
    existing subscription, reuses an open Checkout Session, and supplies a
    deterministic idempotency key so concurrent clicks cannot create multiple
    sessions or subscriptions.
    """
    if _complimentary_access_active(user):
        return {
            "state": "complimentary_access",
            "url": f"{FRONTEND_URL}/app",
            "subscriptionStatus": "complimentary",
        }
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        raise RuntimeError("Billing is not configured.")

    price = stripe.Price.retrieve(STRIPE_PRICE_ID)
    recurring = (price or {}).get("recurring") or {}
    if not bool((price or {}).get("active", True)):
        raise RuntimeError("The configured RetainAI price is inactive.")
    if str(recurring.get("interval") or "").lower() != "month":
        raise RuntimeError("The configured RetainAI price must renew monthly.")

    users = load_users() or {}
    stored = users.get(email) if isinstance(users, dict) else None
    if isinstance(stored, dict):
        user = stored

    existing = _find_existing_billing_subscription(email, user)
    if existing is not None:
        if isinstance(users, dict):
            users[email] = user
            save_users(users)
        return {
            "state": "existing_subscription",
            "url": f"{FRONTEND_URL}/login?billing=already_active",
            "subscriptionStatus": str(existing.get("status") or ""),
        }

    previous_session_id = str(user.get("stripe_checkout_session_id") or "").strip()
    if previous_session_id:
        try:
            previous = stripe.checkout.Session.retrieve(
                previous_session_id,
                expand=["subscription"],
            )
            if str(previous.get("status") or "") == "open" and previous.get("url"):
                return {"state": "open_checkout", "url": previous.url}
            subscription = previous.get("subscription")
            subscription_status = (
                str(subscription.get("status") or "")
                if isinstance(subscription, dict)
                else ""
            )
            if subscription_status in _BLOCKING_SUBSCRIPTION_STATUSES:
                user["stripe_subscription_id"] = str(
                    subscription.get("id") if isinstance(subscription, dict) else subscription
                )
                user["billing_status"] = subscription_status
                if subscription_status in {"active", "trialing"}:
                    user["status"] = "active"
                if isinstance(users, dict):
                    users[email] = user
                    save_users(users)
                return {
                    "state": "existing_subscription",
                    "url": f"{FRONTEND_URL}/login?billing=already_active",
                    "subscriptionStatus": subscription_status,
                }
        except stripe.error.InvalidRequestError:
            # The old session expired or was removed. A new generation is safe
            # only after the subscription lookup above confirmed none exists.
            pass

    generation = int(user.get("stripe_checkout_generation") or 0)
    if previous_session_id:
        generation += 1
    user["stripe_checkout_generation"] = generation
    idempotency_key = hashlib.sha256(
        f"retainai-subscription-checkout:{email}:{generation}".encode("utf-8")
    ).hexdigest()

    checkout_args = {
        "payment_method_types": ["card"],
        "mode": "subscription",
        "line_items": [{"price": STRIPE_PRICE_ID, "quantity": 1}],
        "success_url": f"{FRONTEND_URL}/login?paid=1&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": cancel_url,
        "metadata": {
            "user_email": email,
            "recovery": "true" if recovery else "false",
            "checkout_generation": str(generation),
        },
        "subscription_data": {
            "metadata": {
                "user_email": email,
                "checkout_generation": str(generation),
            }
        },
    }
    if user.get("stripe_customer_id"):
        checkout_args["customer"] = user["stripe_customer_id"]
    else:
        checkout_args["customer_email"] = email
    if int(trial_days or 0) > 0:
        checkout_args["subscription_data"]["trial_period_days"] = int(trial_days)

    checkout = stripe.checkout.Session.create(
        **checkout_args,
        idempotency_key=idempotency_key,
    )
    user["stripe_checkout_session_id"] = checkout.id
    user["stripe_checkout_created_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat().replace("+00:00", "Z")
    if isinstance(users, dict):
        users[email] = user
        save_users(users)
    return {"state": "new_checkout", "url": checkout.url}


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    password = (data.get("password") or "").strip()
    remember = bool(data.get("remember", True))

    if not email or not password:
        return jsonify({"error": "Invalid credentials or account not active"}), 401
    if _login_is_limited(email):
        return jsonify({
            "error": "Too many login attempts. Please wait 15 minutes and try again.",
            "code": "rate_limited",
        }), 429

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    # The dedicated platform-owner login can repair itself from Render secrets.
    # This makes owner recovery reliable even when storage was unavailable during
    # application startup. The secret itself is never returned or logged.
    configured_owner_email = "owner@retainai.ca"
    if email == configured_owner_email and _is_platform_owner(email):
        configured_owner_password = str(
            os.getenv("PLATFORM_OWNER_PASSWORD") or ""
        ).strip()
        if not configured_owner_password:
            return jsonify({
                "error": "Owner login is not configured. Add PLATFORM_OWNER_PASSWORD to the backend service in Render."
            }), 503
        if not hmac.compare_digest(configured_owner_password, password):
            _record_login_failure(email)
            return jsonify({"error": "Incorrect owner password"}), 401

        owner = users.get(email)
        if not isinstance(owner, dict):
            owner = {}
        owner.update(
            {
                "email": email,
                "name": owner.get("name") or "RetainAI Owner",
                "business": owner.get("business") or "RetainAI",
                "businessName": owner.get("businessName") or "RetainAI",
                "role": "owner",
                "org_id": email,
                "status": "active",
                "password": generate_password_hash(configured_owner_password),
                "last_login": datetime.datetime.now(datetime.timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
        users[email] = owner
        save_users(users)
        payload = _user_payload(email, owner)
        return _complete_login_response(
            email, owner, payload, remember, "Owner login successful"
        )

    # Team membership takes priority over a teammate's top-level login record.
    # This prevents a teammate from being mistaken for an organization owner.
    team_key = f"user::{email}"
    team_rec = users.get(team_key)
    if isinstance(team_rec, dict):
        owner_email = _norm_email(team_rec.get("org_id") or "")
        owner_acct = users.get(owner_email) or {}
        member_login = users.get(email) or {}

        owner_ok = bool(owner_acct) and (
            _is_platform_owner(owner_email)
            or _account_has_access(owner_acct)
        )
        member_active = str(team_rec.get("team_status") or "active").lower() == "active"

        own_password = member_login.get("password", "")
        password_ok = _password_matches(own_password, password)

        if owner_ok and member_active and password_ok:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            team_rec["last_login"] = now_iso
            users[team_key] = team_rec

            if not isinstance(member_login, dict) or not member_login:
                member_login = {
                    "email": email,
                    "name": team_rec.get("name") or email.split("@")[0].title(),
                    "role": team_rec.get("role", "member"),
                    "org_id": owner_email,
                    "status": "active",
                }
            member_login["last_login"] = now_iso
            if own_password and not str(own_password).startswith(("scrypt:", "pbkdf2:")):
                member_login["password"] = generate_password_hash(password)
            users[email] = member_login
            save_users(users)

            member_user = {
                "email": email,
                "name": team_rec.get("name") or member_login.get("name") or email.split("@")[0].title(),
                "business": owner_acct.get("business", ""),
                "businessType": owner_acct.get("businessType", ""),
                "teamSize": owner_acct.get("teamSize", ""),
                "logo": owner_acct.get("logo") or owner_acct.get("picture") or "",
                "status": "active",
                "role": team_rec.get("role", "member"),
                "org_id": owner_email,
            }
            payload = _user_payload(email, member_user)
            return _complete_login_response(
                email, member_login, payload, remember, "Login successful"
            )

        _record_login_failure(email)
        return jsonify({"error": "Invalid credentials or account not active"}), 401

    # Organization owner login.
    user = users.get(email)
    if isinstance(user, dict):
        password_valid = _password_matches(user.get("password", ""), password)
        if password_valid and user.get("email_verified") is False:
            return jsonify({
                "error": "Verify your email before signing in.",
                "code": "email_verification_required",
            }), 403
        if password_valid and user.get("status") != "active":
            # Webhooks remain authoritative, but a delayed/missed delivery must
            # not trap a customer who already has an active Stripe subscription.
            _reconcile_paid_subscription(email, user)
        allowed = password_valid and (
            _is_platform_owner(email)
            or _account_has_access(user)
        )
        if allowed:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            user["last_login"] = now_iso
            if not str(user.get("password") or "").startswith(("scrypt:", "pbkdf2:")):
                user["password"] = generate_password_hash(password)
            users[email] = user

            # Keep an older user::<owner> mirror in sync when it exists.
            owner_team_key = f"user::{email}"
            owner_team_rec = users.get(owner_team_key)
            if isinstance(owner_team_rec, dict) and str(owner_team_rec.get("role") or "").lower() == "owner":
                owner_team_rec["last_login"] = now_iso
                users[owner_team_key] = owner_team_rec

            save_users(users)
            payload = _user_payload(email, user)
            return _complete_login_response(
                email, user, payload, remember, "Login successful"
            )
        if password_valid:
            _start_user_session(email, _user_payload(email, user), remember)
            session["recovery_only"] = True
            checkout_url = None
            checkout_error = None
            try:
                checkout = _create_or_reuse_billing_checkout(
                    email,
                    user,
                    cancel_url=f"{FRONTEND_URL}/login?billing=canceled",
                    recovery=True,
                )
                checkout_url = checkout["url"]
            except Exception:
                checkout_error = "Billing is temporarily unavailable. Please contact support."
            trial = _trial_details(user)
            return jsonify({
                "error": "Your trial has ended. Choose a plan to continue.",
                "code": "billing_required",
                "account": {
                    "email": email,
                    "trialDaysRemaining": trial["daysRemaining"],
                    "trialEndsAt": trial["endsAt"],
                    "checkoutUrl": checkout_url,
                    "billingError": checkout_error,
                },
            }), 402

    _record_login_failure(email)
    return jsonify({"error": "Invalid credentials or account not active"}), 401


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True}), 200


@app.post("/api/auth/2fa/verify-login")
def verify_two_factor_login():
    email = _norm_email(session.get("mfa_pending_email"))
    pending_at = int(session.get("mfa_pending_at") or 0)
    if not email or not pending_at or time.time() - pending_at > 10 * 60:
        session.clear()
        return jsonify({"error": "Your verification session expired. Please sign in again."}), 401
    if _login_is_limited(email):
        return jsonify({"error": "Too many verification attempts. Please try again later."}), 429

    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not isinstance(user, dict) or not bool(user.get("totp_enabled")):
        session.clear()
        return jsonify({"error": "Two-factor verification is unavailable."}), 401

    code = str((request.get_json(silent=True) or {}).get("code") or "")
    if not _verify_mfa_code(user, code):
        _record_login_failure(email)
        return jsonify({"error": "That verification code is not valid."}), 401

    remember = bool(session.get("mfa_pending_remember", True))
    users[email] = user
    save_users(users)
    payload = _user_payload(email, user)
    _start_user_session(email, payload, remember)
    _clear_login_failures(email)
    return jsonify({"message": "Login successful", "user": payload}), 200


@app.get("/api/auth/2fa/status")
def two_factor_status():
    email = _session_email()
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else {}
    return jsonify({
        "enabled": bool((user or {}).get("totp_enabled")),
        "backupCodesRemaining": len((user or {}).get("backup_code_hashes") or []),
        "required": _is_platform_owner(email),
    }), 200


@app.post("/api/auth/2fa/setup")
def two_factor_setup():
    email = _session_email()
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not isinstance(user, dict):
        return jsonify({"error": "Account not found"}), 404

    secret = _new_totp_secret()
    user["totp_pending_secret"] = _encrypt_mfa_secret(secret)
    users[email] = user
    save_users(users)
    uri = (
        "otpauth://totp/"
        + urllib.parse.quote(f"RetainAI:{email}", safe="")
        + "?"
        + urllib.parse.urlencode(
            {
                "secret": secret,
                "issuer": "RetainAI",
                "algorithm": "SHA1",
                "digits": 6,
                "period": 30,
            }
        )
    )
    return jsonify({"secret": secret, "uri": uri}), 200


@app.post("/api/auth/2fa/confirm")
def two_factor_confirm():
    email = _session_email()
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not isinstance(user, dict):
        return jsonify({"error": "Account not found"}), 404
    encrypted_secret = user.get("totp_pending_secret", "")
    secret = _decrypt_mfa_secret(encrypted_secret)
    code = str((request.get_json(silent=True) or {}).get("code") or "")
    if not secret or not _verify_totp_secret(secret, code):
        return jsonify({"error": "That verification code is not valid."}), 400

    backup_codes = [
        f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        for _ in range(10)
    ]
    user["totp_secret"] = encrypted_secret
    user["totp_enabled"] = True
    user["backup_code_hashes"] = [
        generate_password_hash(value) for value in backup_codes
    ]
    user.pop("totp_pending_secret", None)
    users[email] = user
    save_users(users)
    return jsonify({"enabled": True, "backupCodes": backup_codes}), 200


@app.post("/api/auth/2fa/disable")
def two_factor_disable():
    email = _session_email()
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not isinstance(user, dict):
        return jsonify({"error": "Account not found"}), 404
    code = str((request.get_json(silent=True) or {}).get("code") or "")
    if not _verify_mfa_code(user, code):
        return jsonify({"error": "Enter a valid authenticator or recovery code."}), 400
    user["totp_enabled"] = False
    user.pop("totp_secret", None)
    user.pop("totp_pending_secret", None)
    user.pop("backup_code_hashes", None)
    users[email] = user
    save_users(users)
    return jsonify({"enabled": False}), 200


@app.post("/api/billing/checkout")
def billing_checkout():
    email = _session_org_email()
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not isinstance(user, dict):
        return jsonify({"error": "Account not found"}), 404
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        return jsonify({"error": "Billing is not configured."}), 503

    trial = _trial_details(user)
    try:
        checkout = _create_or_reuse_billing_checkout(
            email,
            user,
            cancel_url=f"{FRONTEND_URL}/app?billing=canceled",
            trial_days=trial["daysRemaining"] if trial["active"] else 0,
        )
        return jsonify({
            "url": checkout["url"],
            "billingState": checkout["state"],
        }), 200
    except Exception as checkout_error:
        app.logger.exception("[BILLING CHECKOUT] %s", checkout_error)
        return jsonify({"error": "Could not open secure checkout."}), 502


@app.post("/api/billing/portal")
def billing_portal():
    email = _session_org_email()
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    customer_id = (user or {}).get("stripe_customer_id")
    if not customer_id:
        return jsonify({"error": "No billing profile exists yet. Choose a plan first."}), 409
    try:
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{FRONTEND_URL}/app/settings?tab=billing",
        )
        return jsonify({"url": portal.url}), 200
    except Exception:
        return jsonify({"error": "Could not open the billing portal."}), 502


@app.route("/api/session", methods=["GET"])
def session_status():
    email = _session_email()
    if not email:
        return jsonify({"authenticated": False, "user": None}), 200
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not isinstance(user, dict):
        return jsonify({"authenticated": False}), 401
    if int(session.get("security_version") or 0) != int(user.get("security_version") or 0):
        session.clear()
        return jsonify({"authenticated": False, "error": "session_revoked"}), 401
    role, org_email, org_owner, _subject = _resolve_org_and_role(email, users)
    access_record = org_owner if role and role != "owner" else user
    if not (_is_platform_owner(email) or _account_has_access(access_record)):
        session.clear()
        return jsonify({"authenticated": False, "error": "account_access_inactive"}), 403
    if session.get("recovery_only"):
        return jsonify({
            "authenticated": False,
            "recoveryOnly": True,
            "message": "Payment or account recovery is required.",
        }), 200
    return jsonify({"authenticated": True, "user": _user_payload(email, user)}), 200

@app.route("/api/oauth/google", methods=["POST"])
def google_oauth():
    if request.method == "OPTIONS":
        return _cors_preflight_response()
    data = request.get_json(silent=True) or {}
    token = data.get("credential")
    if not token:
        return jsonify({"error": "No Google token provided"}), 400

    try:
        idinfo = id_token.verify_oauth2_token(token, grequests.Request(), GOOGLE_CLIENT_ID)
        email = _norm_email(idinfo["email"])
        name = (idinfo.get("name") or "").strip()
        picture = (idinfo.get("picture") or "").strip()

        users = load_users() or {}
        if not isinstance(users, dict):
            return jsonify({"error": "storage_not_ready"}), 500

        user = users.get(email)
        if not user:
            return jsonify({"error": "No account found for this Google email. Please sign up first."}), 404

        changed = False
        if not user.get("name") and name:
            user["name"] = name
            changed = True
        if not user.get("logo") and picture:
            user["logo"] = picture
            changed = True
        if user.get("picture") and not user.get("logo"):
            user["logo"] = user["picture"]
            changed = True
        if idinfo.get("email_verified") and not user.get("email_verified"):
            user["email_verified"] = True
            user["email_verified_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            changed = True

        if changed:
            users[email] = user
            save_users(users)

        if not (
            _is_platform_owner(email)
            or _account_has_access(user)
        ):
            _start_user_session(email, _user_payload(email, user), bool(data.get("remember", True)))
            session["recovery_only"] = True
            checkout_url = None
            checkout_error = None
            try:
                checkout = _create_or_reuse_billing_checkout(
                    email,
                    user,
                    cancel_url=f"{FRONTEND_URL}/login?billing=canceled",
                    recovery=True,
                )
                checkout_url = checkout["url"]
            except Exception:
                checkout_error = "Billing is temporarily unavailable. Please try again or contact support."
            trial = _trial_details(user)
            return jsonify({
                "error": "Your trial has ended. Choose a plan to continue.",
                "code": "billing_required",
                "account": {
                    "email": email,
                    "trialDaysRemaining": trial["daysRemaining"],
                    "trialEndsAt": trial["endsAt"],
                    "checkoutUrl": checkout_url,
                    "billingError": checkout_error,
                },
            }), 402

        payload = _user_payload(email, user)
        return _complete_login_response(
            email,
            user,
            payload,
            bool(data.get("remember", True)),
            "Google login successful",
        )

    except Exception as e:
        print("[GOOGLE OAUTH ERROR]", e)
        return jsonify({"error": "Invalid Google token"}), 401

@app.route("/api/oauth/google/complete", methods=["POST"])
def google_oauth_complete():
    """
    Unified 'complete' endpoint:
    - If called with no email, no-op success.
    - If profile fields exist, updates user profile without changing status.
    """
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    if not email:
        return jsonify({"ok": True}), 200

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    if email not in users:
        return jsonify({"error": "User not found"}), 404

    user = users[email]

    businessType = (data.get("businessType") or "").strip()
    businessName = (data.get("businessName") or data.get("business") or businessType).strip()
    name = (data.get("name") or "").strip()
    logo = (data.get("logo") or "").strip()
    people = data.get("people", data.get("teamSize"))

    if businessType:
        user["businessType"] = businessType
    if businessName:
        user["business"] = businessName
        user["businessName"] = businessName
    if name:
        user["name"] = name
    if logo:
        user["logo"] = logo
    if people is not None:
        try:
            user["people"] = int(people)
            user["teamSize"] = int(people)
        except Exception:
            pass

    users[email] = user
    save_users(users)
    return jsonify({"message": "Profile updated", "user": _user_payload(email, user)}), 200

@app.route("/api/stripe/verify", methods=["GET"])
def stripe_verify():
    sid = request.args.get("session_id")
    if not sid:
        return jsonify({"ok": False, "error": "missing session_id"}), 400

    try:
        session_obj = stripe.checkout.Session.retrieve(sid, expand=["subscription", "customer"])
        email = (
            (session_obj.get("customer_details") or {}).get("email")
            or session_obj.get("customer_email")
            or (session_obj.get("metadata") or {}).get("user_email")
            or ""
        )
        email = _norm_email(email)
        if not email:
            return jsonify({"ok": False, "error": "no email on session"}), 400

        users = load_users() or {}
        if not isinstance(users, dict):
            return jsonify({"ok": False, "error": "storage_not_ready"}), 500

        if email not in users:
            return jsonify({"ok": False, "error": "user not found"}), 404

        user = users[email]
        sub = session_obj.get("subscription")
        sub_status = (sub.get("status") if isinstance(sub, dict) else None) or ""
        payment_status = str(session_obj.get("payment_status") or "")
        customer_value = session_obj.get("customer")
        customer_id = (
            customer_value.get("id")
            if isinstance(customer_value, dict)
            else customer_value
        )
        subscription_id = sub.get("id") if isinstance(sub, dict) else sub

        if (
            payment_status in {"paid", "no_payment_required"}
            and sub_status in {"active", "trialing"}
        ):
            user["status"] = "active"
            user["billing_status"] = sub_status
            user["stripe_customer_id"] = str(customer_id or "")
            user["stripe_subscription_id"] = str(subscription_id or "")
            user["stripe_event_type"] = "checkout.return_verified"
            user["stripe_event_at"] = datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat().replace("+00:00", "Z")
        else:
            return jsonify({
                "ok": False,
                "error": "payment_not_complete",
                "paymentStatus": payment_status,
                "subscriptionStatus": sub_status,
            }), 402

        users[email] = user
        save_users(users)

        return jsonify({"ok": True, "user": _user_payload(email, user)}), 200

    except Exception as e:
        print("[STRIPE VERIFY ERROR]", e)
        return jsonify({"ok": False, "error": str(e)}), 500


# ----------------------------
# Google Calendar token handling
# ----------------------------
def _google_refresh_access_token(refresh_token: str):
    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    r = pyrequests.post("https://oauth2.googleapis.com/token", data=data)
    if r.status_code != 200:
        raise RuntimeError(f"Refresh failed: {r.text}")
    return r.json()

def _save_user_tokens(email: str, *, access_token=None, refresh_token=None, scope=None, extra: dict=None):
    email = _norm_email(email)
    users = load_users() or {}
    if not isinstance(users, dict):
        raise RuntimeError("storage_not_ready")

    user = users.get(email, {}) or {}
    if access_token:
        user["gcal_access_token"] = access_token
    if refresh_token or ("gcal_refresh_token" not in user):
        user["gcal_refresh_token"] = refresh_token or user.get("gcal_refresh_token")
    if scope:
        user["gcal_scope"] = scope
    user["gcal_connected"] = True
    if extra:
        user.update(extra)
    users[email] = user
    save_users(users)
    return user

@app.route("/api/google/auth-url", methods=["GET"])
def google_auth_url():
    email = _norm_email(request.args.get("user_email"))
    if not email:
        return jsonify({"error": "Missing user_email"}), 400

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "access_type": "offline",
        "prompt": "consent",
        "scope": " ".join(GOOGLE_SCOPES),
        "state": email,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return jsonify({"url": url})

@app.route("/api/google/oauth-callback")
def google_oauth_cb():
    code = request.args.get("code")
    error = request.args.get("error")
    state = _norm_email(request.args.get("state"))

    if error:
        return f"Google OAuth error: {error}", 400
    if not code or not state:
        return "Missing code or state", 400

    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    token_resp = pyrequests.post("https://oauth2.googleapis.com/token", data=data)
    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    scope = tokens.get("scope")

    if not access_token:
        return "Failed to obtain tokens", 400

    users = load_users() or {}
    user = users.get(state, {}) if isinstance(users, dict) else {}
    if not refresh_token:
        refresh_token = user.get("gcal_refresh_token")

    cal_resp = pyrequests.get(
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    calendars = []
    if cal_resp.status_code == 200:
        calendars = [
            {"id": c["id"], "summary": c.get("summary"), "primary": c.get("primary", False)}
            for c in cal_resp.json().get("items", [])
        ]
    else:
        print("[GOOGLE OAUTH] calendarList call failed:", cal_resp.text)

    _save_user_tokens(
        state,
        access_token=access_token,
        refresh_token=refresh_token,
        scope=scope,
        extra={"gcal_calendars": calendars}
    )
    return "Google Calendar connected! You may close this tab and return to the app."

@app.route("/api/google/status/<path:email>")
def google_status(email):
    email = _session_org_email()
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not user or not user.get("gcal_connected"):
        return jsonify({"connected": False})
    return jsonify({
        "connected": True,
        "calendars": user.get("gcal_calendars", []),
        "has_refresh_token": bool(user.get("gcal_refresh_token"))
    })

@app.route("/api/google/disconnect/<path:email>", methods=["POST"])
def google_disconnect(email):
    if _session_email() != _session_org_email() and not _is_platform_owner(_session_email()):
        return jsonify({"disconnected": False, "error": "owner_required"}), 403
    email = _session_org_email()
    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"disconnected": False, "error": "storage_not_ready"}), 500

    user = users.get(email)
    if user:
        user.pop("gcal_access_token", None)
        user.pop("gcal_refresh_token", None)
        user["gcal_connected"] = False
        user.pop("gcal_calendars", None)
        users[email] = user
        save_users(users)
        return jsonify({"disconnected": True})
    return jsonify({"disconnected": False})

@app.route("/api/google/calendars/<path:email>")
def google_calendars(email):
    email = _session_org_email()
    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not user or not user.get("gcal_access_token"):
        return jsonify({"error": "Not connected"}), 401

    access_token = user.get("gcal_access_token")
    refresh_token = user.get("gcal_refresh_token")

    def fetch_cal_list(atok):
        return pyrequests.get(
            "https://www.googleapis.com/calendar/v3/users/me/calendarList",
            headers={"Authorization": f"Bearer {atok}"}
        )

    resp = fetch_cal_list(access_token)
    if resp.status_code == 401 and refresh_token:
        try:
            new_tok = _google_refresh_access_token(refresh_token)
            access_token = new_tok.get("access_token") or access_token
            _save_user_tokens(email, access_token=access_token)
            resp = fetch_cal_list(access_token)
        except Exception as e:
            print("[GOOGLE CAL LIST] refresh failed:", e)
            return jsonify({"error": "Unauthorized"}), 401

    if resp.status_code != 200:
        return jsonify({"error": resp.text}), resp.status_code

    items = resp.json().get("items", [])
    out = [{"id": c["id"], "summary": c.get("summary"), "primary": c.get("primary", False)} for c in items]
    return jsonify({"calendars": out})

@app.route("/api/google/events/<path:email>")
def google_events(email):
    email = _session_org_email()
    calendar_id = request.args.get("calendarId")

    users = load_users() or {}
    user = users.get(email) if isinstance(users, dict) else None
    if not user or not user.get("gcal_connected"):
        return jsonify({"error": "Not connected"}), 401

    access_token = user.get("gcal_access_token")
    refresh_token = user.get("gcal_refresh_token")
    if not access_token:
        return jsonify({"error": "No access token"}), 401

    if not calendar_id:
        cals = user.get("gcal_calendars", []) or []
        calendar_id = "primary"
        for c in cals:
            if c.get("primary"):
                calendar_id = c["id"]
                break

    now = datetime.datetime.utcnow().isoformat() + "Z"
    max_time = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat() + "Z"

    def fetch_events(atok):
        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/"
            f"{urllib.parse.quote(calendar_id)}/events"
            f"?timeMin={now}&timeMax={max_time}&singleEvents=true&orderBy=startTime"
        )
        return pyrequests.get(url, headers={"Authorization": f"Bearer {atok}"})

    resp = fetch_events(access_token)

    if resp.status_code == 401 and refresh_token:
        try:
            new_tok = _google_refresh_access_token(refresh_token)
            access_token = new_tok.get("access_token") or access_token
            _save_user_tokens(email, access_token=access_token)
            resp = fetch_events(access_token)
        except Exception as e:
            print("[GOOGLE EVENTS] refresh failed:", e)
            return jsonify({"error": "Unauthorized"}), 401

    if resp.status_code != 200:
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return jsonify({"error": resp.text}), resp.status_code

    return jsonify(resp.json())


# ============================================================
# WhatsApp Cloud API â€” 24h gate, templates, webhook, etc.
# ============================================================

_TEMPLATE_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_TEMPLATE_TTL_SECONDS = 300

_MSG_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_MSG_CACHE_TTL_SECONDS = 2

_WABA_RES: Dict[str, Dict[str, Any]] = {}
_WABA_TTL_SECONDS = 300


def wa_normalize_lang(code: str) -> str:
    default = (os.getenv("WHATSAPP_TEMPLATE_LANG") or "en").strip()
    if not code:
        return default
    c = str(code).replace("-", "_").strip()
    parts = c.split("_")
    if len(parts) == 1:
        return parts[0].lower()
    if len(parts) >= 2 and parts[0] and parts[1]:
        return parts[0].lower() + "_" + parts[1].upper()
    return c.lower()


def wa_primary_lang(code: str) -> str:
    if not code:
        return ""
    return code.replace("-", "_").split("_", 1)[0].lower()


def wa_norm_number(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    dcc = os.getenv("DEFAULT_COUNTRY_CODE", "1")
    if len(d) == 10 and dcc.isdigit():
        d = dcc + d
    return d


def _wa_numbers_equal(a: str, b: str) -> bool:
    """Compare WhatsApp/phone numbers without losing valid country-code matches."""
    left = wa_norm_number(a)
    right = wa_norm_number(b)
    if not left or not right:
        return False
    if left == right:
        return True
    # Tolerate one side being stored without a country code.
    if len(left) >= 10 and len(right) >= 10 and left[-10:] == right[-10:]:
        return True
    return False


def _lead_phone_values(lead: dict) -> list:
    if not isinstance(lead, dict):
        return []
    keys = (
        "whatsapp", "phone", "mobile", "phone_number", "phoneNumber",
        "mobile_phone", "mobilePhone", "telephone", "tel"
    )
    values = []
    for key in keys:
        value = lead.get(key)
        if value not in (None, ""):
            values.append(str(value))
    return values


def lead_matches_wa(lead: dict, wa_digits: str) -> bool:
    return any(_wa_numbers_equal(value, wa_digits) for value in _lead_phone_values(lead))


def resolve_whatsapp_lead(wa_id: str, workspace_email: str = ""):
    """Return one atomic owner/lead match so owner and lead can never come from different records."""
    wa = wa_norm_number(wa_id)
    if not wa:
        return None, None, None

    leads_by_user = load_leads() or {}
    workspace = _norm_email(workspace_email)
    if workspace:
        leads_by_user = {workspace: leads_by_user.get(workspace, [])}

    candidates = []
    for user_email, leads in (leads_by_user.items() if isinstance(leads_by_user, dict) else []):
        for lead in (leads or []):
            if lead_matches_wa(lead, wa):
                lead_id = str(lead.get("id") or "").strip()
                if lead_id:
                    candidates.append((
                        str(user_email or "").strip().lower(),
                        lead_id,
                        lead,
                    ))

    if not candidates:
        return None, None, None
    if len(candidates) == 1:
        return candidates[0]

    # A platform-default number can serve more than one workspace during
    # migration. Route a reply to the workspace/lead that most recently sent
    # to this exact customer number rather than choosing an arbitrary duplicate.
    candidate_keys = {(email, lead_id) for email, lead_id, _ in candidates}
    recent_routes = []
    statuses = load_statuses() or {}
    for status in (statuses.values() if isinstance(statuses, dict) else []):
        if not isinstance(status, dict) or not _wa_numbers_equal(status.get("to") or "", wa):
            continue
        key = (
            _norm_email(status.get("user_email") or ""),
            str(status.get("lead_id") or "").strip(),
        )
        if key in candidate_keys:
            recent_routes.append((
                str(status.get("updated_at") or status.get("time") or ""),
                key,
            ))

    if recent_routes:
        _, selected_key = max(recent_routes, key=lambda item: item[0])
        for candidate in candidates:
            if (candidate[0], candidate[1]) == selected_key:
                return candidate

    return candidates[0]


def find_user_by_whatsapp(wa_id: str) -> Optional[str]:
    user_email, _, _ = resolve_whatsapp_lead(wa_id)
    return user_email


def find_lead_by_whatsapp(wa_id: str) -> Optional[str]:
    _, lead_id, _ = resolve_whatsapp_lead(wa_id)
    return lead_id


def _wa_event(kind: str, **data):
    """Keep a small durable webhook trail for production diagnostics."""
    try:
        events = load_wa_webhook_events()
        event = {
            "id": f"waevt_{uuid4().hex[:12]}",
            "kind": str(kind or "event"),
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
        event.update(_json_sanitize(data or {}))
        events.insert(0, event)
        save_wa_webhook_events(events[:250])
        return event
    except Exception:
        return None


def _wa_mask_number(value: str) -> str:
    digits = wa_norm_number(value)
    if len(digits) <= 4:
        return digits
    return ("*" * max(0, len(digits) - 4)) + digits[-4:]


def _wa_message_text(message: dict) -> str:
    """Convert all common WhatsApp inbound message types into readable CRM text."""
    if not isinstance(message, dict):
        return "[unknown message]"

    message_type = str(message.get("type") or "unknown").strip().lower()
    if message_type == "text":
        return str((message.get("text") or {}).get("body") or "").strip()

    if message_type == "button":
        button = message.get("button") or {}
        return str(button.get("text") or button.get("payload") or "[button reply]").strip()

    if message_type == "interactive":
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return str(reply.get("title") or reply.get("description") or reply.get("id") or "[interactive reply]").strip()

    if message_type == "image":
        caption = str((message.get("image") or {}).get("caption") or "").strip()
        return caption or "[image received]"
    if message_type == "video":
        caption = str((message.get("video") or {}).get("caption") or "").strip()
        return caption or "[video received]"
    if message_type == "document":
        document = message.get("document") or {}
        return str(document.get("caption") or document.get("filename") or "[document received]").strip()
    if message_type == "audio":
        return "[audio message received]"
    if message_type == "sticker":
        return "[sticker received]"
    if message_type == "location":
        location = message.get("location") or {}
        name = str(location.get("name") or location.get("address") or "").strip()
        lat = location.get("latitude")
        lng = location.get("longitude")
        if name:
            return f"[location: {name}]"
        if lat is not None and lng is not None:
            return f"[location: {lat}, {lng}]"
        return "[location received]"
    if message_type == "contacts":
        return "[contact received]"
    if message_type == "reaction":
        emoji = str((message.get("reaction") or {}).get("emoji") or "").strip()
        return f"[reaction {emoji}]" if emoji else "[reaction received]"

    return f"[{message_type} message received]"


def _wa_readable_text(value: Any) -> str:
    """Normalize legacy/object-shaped message values without leaking Python dicts to the UI."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("body", "text", "message", "title", "description", "caption", "value"):
            candidate = value.get(key)
            if candidate is not None:
                text = _wa_readable_text(candidate)
                if text:
                    return text
        return ""
    if isinstance(value, list):
        return " ".join(filter(None, (_wa_readable_text(item) for item in value))).strip()
    return str(value).strip()


def _wa_render_template(body_text: str, values: List[Any], param_keys: Optional[List[str]] = None) -> str:
    rendered = str(body_text or "")
    clean_values = [_wa_readable_text(value) for value in (values or [])]
    keys = [str(key or "").strip() for key in (param_keys or [])]
    for index, value in enumerate(clean_values, start=1):
        rendered = re.sub(r"\{\{\s*" + str(index) + r"\s*\}\}", value, rendered)
        if index - 1 < len(keys) and keys[index - 1]:
            rendered = re.sub(
                r"\{\{\s*" + re.escape(keys[index - 1]) + r"\s*\}\}",
                value,
                rendered,
            )
    return rendered.strip()


def _normalize_stored_chat_row(value: Any) -> dict:
    if isinstance(value, dict):
        row = dict(value)
        row["text"] = _wa_readable_text(row.get("text") or row.get("message") or row.get("body"))
        row["from"] = row.get("from") or ("user" if row.get("direction") == "outbound" else "lead")
        row["direction"] = row.get("direction") or ("outbound" if row.get("from") == "user" else "inbound")
        return row
    return {
        "id": f"legacy_{uuid4().hex[:12]}",
        "from": "user",
        "direction": "outbound",
        "text": _wa_readable_text(value) or "Legacy message details were not stored correctly.",
        "time": None,
    }


def _wa_store_unmatched(sender_waid: str, message: dict, text_value: str, phone_number_id: str = "", profile_name: str = ""):
    try:
        unmatched = load_wa_unmatched()
        message_id = str((message or {}).get("id") or "").strip()
        if message_id and any(str(row.get("message_id") or "") == message_id for row in unmatched):
            return
        unmatched.insert(0, {
            "id": f"waun_{uuid4().hex[:12]}",
            "message_id": message_id,
            "sender": wa_norm_number(sender_waid),
            "sender_masked": _wa_mask_number(sender_waid),
            "profile_name": str(profile_name or "").strip()[:120],
            "phone_number_id": str(phone_number_id or ""),
            "type": str((message or {}).get("type") or "unknown"),
            "text": str(text_value or "")[:500],
            "received_at": datetime.datetime.utcnow().isoformat() + "Z",
        })
        save_wa_unmatched(unmatched[:100])
    except Exception:
        pass


def _wa_append_inbound(user_email: str, lead_id: str, lead: dict, sender_waid: str, message: dict, text_value: str):
    """Persist one inbound message exactly once and update lead activity."""
    message_id = str((message or {}).get("id") or "").strip()
    timestamp = str((message or {}).get("timestamp") or "").strip()
    try:
        received_at = datetime.datetime.utcfromtimestamp(int(timestamp)).isoformat() + "Z" if timestamp else datetime.datetime.utcnow().isoformat() + "Z"
    except Exception:
        received_at = datetime.datetime.utcnow().isoformat() + "Z"

    chats = load_chats() or {}
    user_chats = chats.get(user_email, {}) or {}
    thread = user_chats.get(str(lead_id), []) or []

    if message_id and any(str(item.get("id") or item.get("message_id") or "") == message_id for item in thread):
        return thread, False

    row = {
        "id": message_id or f"wain_{uuid4().hex[:16]}",
        "message_id": message_id,
        "from": "lead",
        "direction": "inbound",
        "text": str(text_value or "").strip() or "[message received]",
        "type": str((message or {}).get("type") or "unknown"),
        "phone": wa_norm_number(sender_waid),
        "time": received_at,
        "context": _json_sanitize((message or {}).get("context") or {}),
    }
    thread = append_chat_message(user_email, str(lead_id), row)

    _MSG_CACHE[(str(user_email or ""), str(lead_id or ""))] = {
        "at": datetime.datetime.utcnow(),
        "data": thread,
    }

    # Update lead activity so no-reply logic and CRM previews immediately see the response.
    try:
        leads_by_user = load_leads() or {}
        owner_leads = leads_by_user.get(user_email, []) or []
        for item in owner_leads:
            if str(item.get("id") or "") == str(lead_id):
                item["last_reply_at"] = received_at
                item["last_inbound_at"] = received_at
                item["last_contact"] = received_at
                item["last_message"] = row["text"]
                item["last_message_direction"] = "inbound"
                item["wa_last_inbound_id"] = row["id"]
                if "wa_opt_out" in lead:
                    item["wa_opt_out"] = bool(lead.get("wa_opt_out"))
                break
        save_user_leads(user_email, owner_leads)
    except Exception as exc:
        try:
            app.logger.warning("[WA WEBHOOK] lead activity update failed: %s", exc)
        except Exception:
            pass

    return thread, True


def _wa_workspace_email(explicit: str = "") -> str:
    if explicit:
        return _norm_email(explicit)
    try:
        return _session_org_email()
    except RuntimeError:
        return ""


def _wa_workspace_record(workspace_email: str = "") -> dict:
    workspace = _wa_workspace_email(workspace_email)
    users = load_users() or {}
    record = users.get(workspace) if workspace and isinstance(users, dict) else None
    return record if isinstance(record, dict) else {}


def wa_credentials(workspace_email: str = "") -> dict:
    record = _wa_workspace_record(workspace_email)
    encrypted = str(record.get("wa_access_token_encrypted") or "")
    workspace_token = _decrypt_mfa_secret(encrypted) if encrypted else ""
    return {
        "workspace_email": _wa_workspace_email(workspace_email),
        "token": workspace_token or WHATSAPP_TOKEN or "",
        "phone_id": str(record.get("wa_phone_id") or WHATSAPP_PHONE_ID or ""),
        "waba_id": str(record.get("wa_waba_id") or WHATSAPP_WABA_ID or ""),
        "business_number": str(record.get("wa_business_number") or record.get("whatsapp") or ""),
        "source": "workspace" if workspace_token and record.get("wa_phone_id") else "platform_default",
    }


def _wa_workspace_for_phone_id(phone_id: str) -> str:
    target = str(phone_id or "").strip()
    users = load_users() or {}
    for email, record in (users.items() if isinstance(users, dict) else []):
        if target and isinstance(record, dict) and str(record.get("wa_phone_id") or "").strip() == target:
            return _norm_email(email)
    return ""


def wa_env(workspace_email: str = "") -> Tuple[str, str]:
    config = wa_credentials(workspace_email)
    token = config["token"]
    phone_id = config["phone_id"]
    if not token or not phone_id:
        raise RuntimeError("WhatsApp credentials missing (WHATSAPP_TOKEN / WHATSAPP_PHONE_ID)")
    return token, phone_id


def wa_resolve_waba_id(force: bool = False, workspace_email: str = "") -> str:
    config = wa_credentials(workspace_email)
    cache_key = config["phone_id"] or config["workspace_email"] or "platform"
    now = datetime.datetime.utcnow()
    cached = _WABA_RES.get(cache_key) or {}
    if (
        not force
        and cached.get("id")
        and cached.get("checked_at")
        and (now - cached["checked_at"]).total_seconds() < _WABA_TTL_SECONDS
    ):
        return cached["id"]

    # The Cloud API phone-number object no longer exposes a
    # `whatsapp_business_account` field. Use the WABA ID supplied by Meta's
    # API Setup screen instead of requesting that invalid Graph field.
    if config["waba_id"]:
        _WABA_RES[cache_key] = {"id": config["waba_id"], "checked_at": now}
        return config["waba_id"]

    try:
        wa_env(workspace_email)
        _WABA_RES[cache_key] = {"id": "", "checked_at": now}
        return ""

    except Exception as e:
        try:
            app.logger.warning("[WA WABA] resolve error: %s", e)
        except Exception:
            pass
        return config["waba_id"]


def wa_fetch_templates_for_waba(waba_id: str, workspace_email: str = ""):
    if not waba_id:
        raise RuntimeError("WhatsApp WABA ID could not be resolved")
    token, _ = wa_env(workspace_email)
    headers = {"Authorization": f"Bearer {token}"}
    params = {"fields": "name,language,status,category,components", "limit": 200}
    url = f"https://graph.facebook.com/{os.getenv('WHATSAPP_API_VERSION', 'v24.0')}/{waba_id}/message_templates"
    return pyrequests.get(url, headers=headers, params=params, timeout=30)


def wa_fetch_templates_raw(workspace_email: str = ""):
    waba_id = wa_resolve_waba_id(workspace_email=workspace_email)
    return wa_fetch_templates_for_waba(waba_id, workspace_email)


def wa_lookup_template_status(name: str, lang_api: str, force: bool = False) -> str:
    config = wa_credentials()
    if not (config["token"] and (config["waba_id"] or config["phone_id"])):
        return "UNKNOWN"

    normalized_name = (name or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "") or "").strip()
    lang_norm = wa_normalize_lang(lang_api or os.getenv("WHATSAPP_TEMPLATE_LANG", "en") or "")
    key = (config["workspace_email"] or config["phone_id"] or "platform", normalized_name, lang_norm)

    now = datetime.datetime.utcnow()
    if not force:
        cached = _TEMPLATE_CACHE.get(key)
        if cached and (now - cached["checked_at"]) < datetime.timedelta(seconds=_TEMPLATE_TTL_SECONDS):
            return cached["status"]

    try:
        r = wa_fetch_templates_raw()
        items = (r.json() or {}).get("data", []) if r.ok else []
        primary = wa_primary_lang(lang_norm)
        exact_status = None
        fallback_status = None

        for t in items:
            if (t.get("name") or "") != normalized_name:
                continue
            tl_norm = wa_normalize_lang(t.get("language") or "")
            if tl_norm == lang_norm:
                exact_status = (t.get("status") or "UNKNOWN")
            if wa_primary_lang(tl_norm) == primary:
                st = (t.get("status") or "UNKNOWN")
                if (fallback_status or "").upper() != "APPROVED":
                    fallback_status = st

        status = exact_status or fallback_status or "PENDING"
        _TEMPLATE_CACHE[key] = {"status": status, "checked_at": now}
        return status

    except Exception as e:
        try:
            app.logger.warning("[WA TPL CHECK ERROR] %s", e)
        except Exception:
            pass
        _TEMPLATE_CACHE[key] = {"status": "UNKNOWN", "checked_at": now}
        return "UNKNOWN"


def wa_is_template_approved(name: str, lang: str, force: bool = False) -> bool:
    return wa_lookup_template_status(name, lang, force).upper() == "APPROVED"


def get_last_inbound_ts(user_email: str, lead_id: str) -> Optional[str]:
    chats = load_chats()
    msgs = (chats.get(user_email, {}) or {}).get(str(lead_id), []) or []
    for m in reversed(msgs):
        if m.get("from") == "lead":
            return m.get("time")
    return None


def within_24h(user_email: str, lead_id: str) -> bool:
    ts = get_last_inbound_ts(user_email, lead_id)
    if not ts:
        return False
    try:
        last_dt = datetime.datetime.fromisoformat(ts.replace("Z", ""))
    except Exception:
        return False
    return (datetime.datetime.utcnow() - last_dt) <= datetime.timedelta(hours=24)

@app.route("/api/generate-message", methods=["POST"])
def generate_message():
    data = request.get_json(silent=True) or {}

    lead = data.get("lead") or {}
    last_message = str(data.get("last_message") or "").strip()
    user_business = str(data.get("user_business") or "business").strip()
    user_name = str(data.get("user_name") or "").strip()

    lead_name = str(lead.get("name") or "").strip()
    lead_tags = lead.get("tags") or []
    if not isinstance(lead_tags, list):
        lead_tags = []
    lead_notes = str(lead.get("notes") or "-").strip()

    if not OPENROUTER_API_KEY:
        return jsonify({"error": "OPENROUTER_API_KEY is missing on the backend."}), 500

    prompt = (
        f"You are a professional, emotionally intelligent assistant for a {user_business} business. "
        f"Given the context below, write ONLY a direct, warm, natural message that could be sent in chat or email, "
        f"with no greeting lines, subjects, or sign-offs. Only output the message body.\n\n"
        f"Lead Name: {lead_name or 'Client'}\n"
        f"User Name: {user_name or 'Business Owner'}\n"
        f"Tags: {', '.join([str(t) for t in lead_tags]) or '-'}\n"
        f"Notes: {lead_notes or '-'}\n"
        f"Most recent message from the lead: \"{last_message or '-'}\"\n\n"
        "Your reply should be concise, helpful, and conversational. "
        "Do NOT include subject lines, greetings, or closings. "
        "Reply as if you were the business owner responding to the client."
    )

    try:
        resp = pyrequests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-4o",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a CRM messaging assistant. Output only the message body."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": 200,
                "temperature": 0.7
            },
            timeout=30
        )

        # Handle non-200 upstream cleanly
        if not resp.ok:
            try:
                err_json = resp.json()
            except Exception:
                err_json = {"raw": resp.text}

            try:
                app.logger.error("[AI GENERATE] OpenRouter error %s %s", resp.status_code, err_json)
            except Exception:
                pass

            return jsonify({
                "error": "OpenRouter request failed.",
                "status": resp.status_code,
                "details": err_json
            }), 502

        try:
            result = resp.json()
        except Exception:
            try:
                app.logger.error("[AI GENERATE] Non-JSON response: %s", resp.text[:500])
            except Exception:
                pass
            return jsonify({"error": "AI provider returned invalid JSON."}), 502

        choices = result.get("choices") or []
        if choices and choices[0].get("message", {}).get("content"):
            reply = choices[0]["message"]["content"].strip()
            return jsonify({"reply": reply}), 200

        return jsonify({
            "error": (result.get("error") or {}).get("message") or "AI response was incomplete."
        }), 500

    except pyrequests.RequestException as ex:
        try:
            app.logger.error("[AI GENERATE] Request exception: %s", str(ex))
        except Exception:
            pass
        return jsonify({"error": f"Failed to contact AI provider: {str(ex)}"}), 502

    except Exception as ex:
        try:
            app.logger.exception("[AI GENERATE] Unexpected error: %s", str(ex))
        except Exception:
            pass
        return jsonify({"error": "Failed to get AI response"}), 500
        
def wa_send_text(to_number: str, body: str, workspace_email: str = ""):
    to = wa_norm_number(to_number)
    token, phone_id = wa_env(workspace_email)
    ver = os.getenv("WHATSAPP_API_VERSION", "v20.0")
    url = f"https://graph.facebook.com/{ver}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body}
    }
    resp = pyrequests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        try:
            app.logger.error("[WA SEND ERROR] %s %s", resp.status_code, resp.text)
        except Exception:
            pass
    return resp


def wa_extract_template_metadata(template: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return normalized template metadata used by both the UI and send preflight."""
    template = template if isinstance(template, dict) else {}
    components = template.get("components") or []
    if not isinstance(components, list):
        components = []

    body = next(
        (c for c in components if isinstance(c, dict) and str(c.get("type") or "").upper() == "BODY"),
        {},
    ) or {}
    body_text = str(body.get("text") or "")
    body_tokens = re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", body_text)

    numeric_indexes = []
    named_tokens = []
    for token in body_tokens:
        token = str(token or "").strip()
        if token.isdigit():
            numeric_indexes.append(int(token))
        elif token and token not in named_tokens:
            named_tokens.append(token)

    if numeric_indexes:
        body_param_count = max(numeric_indexes)
        body_param_keys = [str(i) for i in range(1, body_param_count + 1)]
        parameter_format = "POSITIONAL"
    else:
        body_param_keys = named_tokens
        body_param_count = len(body_param_keys)
        parameter_format = "NAMED" if body_param_keys else str(template.get("parameter_format") or "POSITIONAL").upper()

    body_example = body.get("example") or {}
    sample_values: List[str] = []
    raw_examples = body_example.get("body_text") if isinstance(body_example, dict) else None
    if isinstance(raw_examples, list) and raw_examples:
        first_example = raw_examples[0]
        if isinstance(first_example, list):
            sample_values = [str(v) for v in first_example]
        else:
            sample_values = [str(v) for v in raw_examples]

    header = next(
        (c for c in components if isinstance(c, dict) and str(c.get("type") or "").upper() == "HEADER"),
        {},
    ) or {}
    header_format = str(header.get("format") or "TEXT").upper()
    header_text = str(header.get("text") or "")
    header_param_count = len(set(re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", header_text)))
    media_header_required = header_format in {"IMAGE", "VIDEO", "DOCUMENT", "LOCATION"}

    button_param_count = 0
    buttons_component = next(
        (c for c in components if isinstance(c, dict) and str(c.get("type") or "").upper() == "BUTTONS"),
        {},
    ) or {}
    buttons = buttons_component.get("buttons") or []
    if isinstance(buttons, list):
        for button in buttons:
            if not isinstance(button, dict):
                continue
            url = str(button.get("url") or "")
            button_param_count += len(set(re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", url)))

    unsupported_reasons = []
    if media_header_required:
        unsupported_reasons.append(f"dynamic {header_format.lower()} header")
    if header_param_count:
        unsupported_reasons.append(f"{header_param_count} header parameter(s)")
    if button_param_count:
        unsupported_reasons.append(f"{button_param_count} dynamic button parameter(s)")

    return {
        "name": template.get("name"),
        "language": template.get("language"),
        "normalized_language": wa_normalize_lang(template.get("language") or ""),
        "status": str(template.get("status") or "").upper(),
        "category": template.get("category"),
        "parameter_format": parameter_format,
        "components": components,
        "body_text": body_text,
        "body_param_count": int(body_param_count or 0),
        "body_param_keys": body_param_keys,
        "body_example_params": sample_values,
        "header_param_count": int(header_param_count or 0),
        "button_param_count": int(button_param_count or 0),
        "media_header_required": bool(media_header_required),
        "supported_by_automations": not unsupported_reasons,
        "unsupported_reason": ", ".join(unsupported_reasons),
    }


def wa_send_template(
    to_number: str,
    template_name: str,
    lang_code: str,
    parameters: Optional[List[Any]] = None,
    expected_body_param_count: Optional[int] = None,
    workspace_email: str = "",
):
    to = wa_norm_number(to_number)
    token, phone_id = wa_env(workspace_email)
    ver = os.getenv("WHATSAPP_API_VERSION", "v20.0")
    url = f"https://graph.facebook.com/{ver}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    clean_parameters: List[str] = []
    if parameters is not None:
        if not isinstance(parameters, list):
            raise ValueError("WhatsApp template parameters must be a list")
        clean_parameters = [str(p).strip() if p is not None else "" for p in parameters]

    if expected_body_param_count is not None:
        expected = max(0, int(expected_body_param_count or 0))
        if len(clean_parameters) != expected:
            raise ValueError(
                f"Template '{template_name}' expects {expected} body parameter(s), "
                f"but {len(clean_parameters)} were provided."
            )
        if expected and any(not value for value in clean_parameters):
            raise ValueError(
                f"Template '{template_name}' has one or more empty required body parameters."
            )

    components = []
    if clean_parameters:
        components = [{
            "type": "body",
            "parameters": [{"type": "text", "text": value} for value in clean_parameters]
        }]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": wa_normalize_lang(lang_code)},
            "components": components
        }
    }

    resp = pyrequests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        try:
            app.logger.error("[WA TEMPLATE ERROR] %s %s", resp.status_code, resp.text)
        except Exception:
            pass
    return resp


@app.get("/api/whatsapp/health")
def whatsapp_health():
    config = wa_credentials()
    events = load_wa_webhook_events()
    workspace = _session_org_email()
    phone_id = str(config.get("phone_id") or "")
    can_view_default_diagnostics = (
        config.get("source") == "workspace"
        or _is_platform_owner(_session_email())
    )
    workspace_events = [
        event for event in events
        if event.get("user_email") == workspace
        or (phone_id and str(event.get("phone_number_id") or "") == phone_id)
    ]
    unmatched = [
        row for row in load_wa_unmatched()
        if can_view_default_diagnostics
        and (not phone_id or str(row.get("phone_number_id") or "") == phone_id)
    ]
    last_webhook = events[0].get("created_at") if events else None
    last_inbound = next((event.get("created_at") for event in workspace_events if event.get("kind") == "inbound_matched"), None)
    last_rejected = next((event.get("created_at") for event in events if event.get("kind") == "signature_rejected"), None)
    graph_ok = False
    graph_status = None
    graph_error = ""
    phone_display = ""
    verified_name = ""
    if config["token"] and config["phone_id"]:
        try:
            version = os.getenv("WHATSAPP_API_VERSION", "v24.0")
            check = pyrequests.get(
                f"https://graph.facebook.com/{version}/{config['phone_id']}",
                headers={"Authorization": f"Bearer {config['token']}"},
                params={"fields": "id,display_phone_number,verified_name,quality_rating"},
                timeout=10,
            )
            graph_status = check.status_code
            body = check.json() if check.content else {}
            graph_ok = bool(check.ok and body.get("id"))
            phone_display = str(body.get("display_phone_number") or "")
            verified_name = str(body.get("verified_name") or "")
            if not graph_ok:
                error = body.get("error") or {}
                graph_error = str(error.get("message") or f"Meta returned {check.status_code}")[:240]
        except Exception as exc:
            graph_error = f"Could not reach Meta: {exc}"[:240]
    return jsonify({
        "ok": bool(graph_ok),
        "graph_ok": bool(graph_ok),
        "graph_status": graph_status,
        "graph_error": graph_error,
        "phone_display": phone_display,
        "verified_name": verified_name,
        "has_token": bool(config["token"]),
        "has_phone_id": bool(config["phone_id"]),
        "has_waba_id": bool(config["waba_id"]),
        "credential_source": config["source"],
        "workspace_connection": config["source"] == "workspace",
        "has_verify_token": bool(os.getenv("WHATSAPP_VERIFY_TOKEN")),
        "has_app_secret": bool(os.getenv("APP_SECRET") or os.getenv("META_APP_SECRET")),
        "default_template": os.getenv("WHATSAPP_TEMPLATE_DEFAULT"),
        "default_lang_ui": wa_primary_lang(os.getenv("WHATSAPP_TEMPLATE_LANG", "en")) or "en",
        "default_lang_api": wa_normalize_lang(os.getenv("WHATSAPP_TEMPLATE_LANG", "en")),
        "webhook_last_seen_at": last_webhook,
        "last_matched_inbound_at": last_inbound,
        "last_signature_rejected_at": last_rejected,
        "unmatched_inbound_count": len(unmatched),
    }), 200


@app.route("/api/integrations/whatsapp", methods=["GET", "POST", "DELETE"])
def workspace_whatsapp_integration():
    actor = _session_email()
    workspace = _session_org_email()
    if actor != workspace and not _is_platform_owner(actor):
        return jsonify({"ok": False, "error": "Only the workspace owner can manage WhatsApp."}), 403

    users = load_users() or {}
    record = users.get(workspace) if isinstance(users, dict) else None
    if not isinstance(record, dict):
        return jsonify({"ok": False, "error": "Workspace not found"}), 404

    if request.method == "GET":
        config = wa_credentials(workspace)
        return jsonify({
            "ok": True,
            "connected": bool(config["token"] and config["phone_id"]),
            "source": config["source"],
            "phone_id": config["phone_id"],
            "waba_id": config["waba_id"],
            "business_number": config["business_number"],
            "has_workspace_token": bool(record.get("wa_access_token_encrypted")),
        }), 200

    if request.method == "DELETE":
        for key in (
            "wa_access_token_encrypted", "wa_phone_id", "wa_waba_id",
            "wa_business_number", "wa_connected_at",
        ):
            record.pop(key, None)
        users[workspace] = record
        save_users(users)
        _WABA_RES.clear()
        return jsonify({"ok": True, "source": "platform_default"}), 200

    data = request.get_json(silent=True) or {}
    previous_record = dict(record)
    access_token = str(data.get("access_token") or "").strip()
    phone_id = str(data.get("phone_id") or "").strip()
    waba_id = str(data.get("waba_id") or "").strip()
    business_number = str(data.get("business_number") or "").strip()
    if not phone_id or not waba_id or (not access_token and not record.get("wa_access_token_encrypted")):
        return jsonify({
            "ok": False,
            "error": "Access token, phone number ID, and WhatsApp business account ID are required.",
        }), 400
    if access_token:
        record["wa_access_token_encrypted"] = _encrypt_mfa_secret(access_token)
    record["wa_phone_id"] = phone_id
    record["wa_waba_id"] = waba_id
    record["wa_business_number"] = business_number
    record["wa_connected_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    users[workspace] = record
    save_users(users)
    _WABA_RES.clear()

    # Validate before reporting success; never return the secret.
    config = wa_credentials(workspace)
    try:
        version = os.getenv("WHATSAPP_API_VERSION", "v24.0")
        check = pyrequests.get(
            f"https://graph.facebook.com/{version}/{config['phone_id']}",
            headers={"Authorization": f"Bearer {config['token']}"},
            params={"fields": "id,display_phone_number,verified_name,quality_rating"},
            timeout=12,
        )
        body = check.json() if check.content else {}
        if not check.ok or not body.get("id"):
            users[workspace] = previous_record
            save_users(users)
            error = (body.get("error") or {}).get("message") or "Meta rejected these credentials."
            return jsonify({"ok": False, "error": str(error)[:240]}), 422

        waba_check = pyrequests.get(
            f"https://graph.facebook.com/{version}/{config['waba_id']}",
            headers={"Authorization": f"Bearer {config['token']}"},
            params={"fields": "id"},
            timeout=12,
        )
        waba_body = waba_check.json() if waba_check.content else {}
        if not waba_check.ok or str(waba_body.get("id") or "") != config["waba_id"]:
            users[workspace] = previous_record
            save_users(users)
            error = (waba_body.get("error") or {}).get("message") or "Meta could not validate this WhatsApp business account ID."
            return jsonify({"ok": False, "error": str(error)[:240]}), 422

        record["wa_business_number"] = body.get("display_phone_number") or business_number
        users[workspace] = record
        save_users(users)
        return jsonify({
            "ok": True,
            "connected": True,
            "source": "workspace",
            "phone_id": config["phone_id"],
            "waba_id": record.get("wa_waba_id") or "",
            "business_number": record.get("wa_business_number") or "",
            "verified_name": body.get("verified_name") or "",
        }), 200
    except Exception as exc:
        users[workspace] = previous_record
        save_users(users)
        return jsonify({"ok": False, "error": f"Could not validate with Meta: {exc}"}), 502


@app.get("/api/whatsapp/templates")
def list_templates():
    config = wa_credentials()
    if not config["token"] or not config["phone_id"]:
        return jsonify({"error": "Missing token or phone id"}), 400

    try:
        waba_id = wa_resolve_waba_id()
        r = wa_fetch_templates_raw()

        try:
            data = r.json()
            for t in (data.get("data", []) or []):
                t["normalized_language"] = wa_normalize_lang(t.get("language", ""))
        except Exception:
            data = {"raw": r.text}

        return jsonify({
            "status": r.status_code,
            "waba_id": waba_id,
            "data": data
        }), r.status_code

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to load templates: {e}"}), 500


@app.get("/api/whatsapp/template-info")
def whatsapp_template_info():
    """
    Frontend expects:
    {
      "ok": true,
      "templates": [
        {
          "name": "...",
          "language": "en_US",
          "normalized_language": "en_US",
          "status": "APPROVED",
          "category": "...",
          "components": [...],
          "body_text": "...",
          "body_param_count": 3
        }
      ]
    }
    """
    name = (request.args.get("name") or "").strip()
    lang_code = wa_normalize_lang(request.args.get("language_code") or "")

    if not name:
        return jsonify({"ok": False, "error": "name is required", "templates": []}), 400

    try:
        r = wa_fetch_templates_raw()
        if not getattr(r, "ok", False):
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text}
            return jsonify({
                "ok": False,
                "error": "Failed to fetch templates from Graph",
                "templates": [],
                "status": getattr(r, "status_code", None),
                "resp": body
            }), 502

        items = (r.json() or {}).get("data", []) or []
        out = []

        def build_template_row(t: dict) -> dict:
            return wa_extract_template_metadata(t)

        # exact name + optional exact language
        for t in items:
            if (t.get("name") or "").strip() != name:
                continue
            t_lang = wa_normalize_lang(t.get("language") or "")
            if lang_code and t_lang != lang_code:
                continue
            out.append(build_template_row(t))

        # fallback to same-name all locales if requested locale not found
        if not out and lang_code:
            for t in items:
                if (t.get("name") or "").strip() != name:
                    continue
                out.append(build_template_row(t))

        return jsonify({
            "ok": True,
            "templates": out
        }), 200

    except Exception as e:
        try:
            app.logger.exception("[WA TEMPLATE INFO ERROR] %s", e)
        except Exception:
            pass
        return jsonify({
            "ok": False,
            "error": str(e),
            "templates": []
        }), 500


@app.get("/api/whatsapp/template-state")
def template_state():
    name = (request.args.get("name") or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "") or "").strip()
    lang = request.args.get("language_code") or os.getenv("WHATSAPP_TEMPLATE_LANG", "en") or ""
    force = request.args.get("force") == "1"
    status = wa_lookup_template_status(name, lang, force)
    return jsonify({
        "name": name,
        "language": wa_normalize_lang(lang),
        "status": status.upper(),
        "approved": status.upper() == "APPROVED",
        "checked_at": datetime.datetime.utcnow().isoformat() + "Z"
    }), 200


@app.get("/api/whatsapp/window-state")
def whatsapp_window_state():
    user_email = (request.args.get("user_email") or "").strip().lower()
    lead_id = (request.args.get("lead_id") or "").strip()

    template_name = (request.args.get("template_name") or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "") or "").strip()
    lang_code = request.args.get("language_code") or os.getenv("WHATSAPP_TEMPLATE_LANG", "en") or ""
    force = request.args.get("force") == "1"

    lang_norm = wa_normalize_lang(lang_code)
    inside = within_24h(user_email, lead_id) if (user_email and lead_id) else False
    status = "APPROVED" if inside else wa_lookup_template_status(template_name, lang_norm, force)

    return jsonify({
        "inside24h": inside,
        "templateApproved": inside or (status.upper() == "APPROVED"),
        "templateStatus": status.upper(),
        "templateName": template_name,
        "language": lang_norm,
        "canFreeText": inside,
        "canTemplate": (not inside) and (status.upper() == "APPROVED")
    }), 200


def _get_thread_cached(user_email: str, lead_id: str):
    key = (str(user_email or ""), str(lead_id or ""))
    now = datetime.datetime.utcnow()
    cached = _MSG_CACHE.get(key)
    if cached and (now - cached["at"]).total_seconds() < _MSG_CACHE_TTL_SECONDS:
        return cached["data"], True

    chats = load_chats()
    user_chats = chats.get(user_email, {}) if isinstance(chats, dict) else {}
    raw_msgs = (user_chats or {}).get(str(lead_id), []) or []
    if not isinstance(raw_msgs, list):
        raw_msgs = [raw_msgs]
    msgs = [_normalize_stored_chat_row(item) for item in raw_msgs]
    _MSG_CACHE[key] = {"at": now, "data": msgs}
    return msgs, False


@app.route("/api/whatsapp/messages", methods=["GET"])
def get_whatsapp_messages():
    user_email = (request.args.get("user_email") or request.headers.get("X-User-Email") or "").strip().lower()
    lead_id = (request.args.get("lead_id") or "").strip()
    if not user_email or not lead_id:
        return jsonify({"error": "user_email and lead_id are required", "messages": []}), 400

    msgs, cached = _get_thread_cached(user_email, lead_id)
    statuses = load_statuses() or {}
    enriched = []
    for item in msgs:
        row = dict(item)
        message_id = str(row.get("message_id") or row.get("id") or "")
        if message_id and isinstance(statuses.get(message_id), dict):
            row["status"] = statuses[message_id].get("status") or row.get("status")
        enriched.append(row)
    msgs = enriched
    payload = {
        "ok": True,
        "messages": msgs,
        "count": len(msgs),
        "cached": bool(cached),
        "last_message_at": (msgs[-1].get("time") if msgs else None),
        "server_time": datetime.datetime.utcnow().isoformat() + "Z",
    }
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response, 200


@app.route("/api/whatsapp/conversations", methods=["GET"])
def get_whatsapp_conversations():
    """Return lightweight previews for every contact in the signed-in workspace."""
    user_email = _session_org_email()
    chats = load_chats() or {}
    user_chats = chats.get(user_email, {}) or {}
    statuses = load_statuses() or {}
    summaries = {}
    for lead_id, raw_messages in user_chats.items():
        source_messages = raw_messages if isinstance(raw_messages, list) else [raw_messages]
        messages = [_normalize_stored_chat_row(item) for item in source_messages if item is not None]
        last = messages[-1] if messages else {}
        unread = 1 if (
            messages
            and (
                (last or {}).get("direction") == "inbound"
                or (last or {}).get("from") == "lead"
            )
        ) else 0
        message_id = str((last or {}).get("id") or (last or {}).get("message_id") or "")
        summaries[str(lead_id)] = {
            "count": len(messages),
            "unread": unread,
            "text": str((last or {}).get("text") or ""),
            "time": (last or {}).get("time"),
            "direction": (last or {}).get("direction") or (
                "outbound" if (last or {}).get("from") == "user" else "inbound"
            ),
            "status": (statuses.get(message_id) or {}).get("status") if message_id else None,
        }
    phone_id = str(wa_credentials(user_email).get("phone_id") or "")
    config = wa_credentials(user_email)
    can_view_default_diagnostics = (
        config.get("source") == "workspace"
        or _is_platform_owner(_session_email())
    )
    unmatched_count = sum(
        1 for row in (load_wa_unmatched() or [])
        if can_view_default_diagnostics
        and (not phone_id or str((row or {}).get("phone_number_id") or "") == phone_id)
    )
    return jsonify({
        "ok": True,
        "conversations": summaries,
        # Count only: useful diagnostics without exposing another workspace's
        # sender number, profile, or message contents.
        "unmatched_count": unmatched_count,
        "server_time": datetime.datetime.utcnow().isoformat() + "Z",
    }), 200


@app.route("/api/whatsapp/reconcile", methods=["POST"])
def reconcile_whatsapp_replies():
    """Safely attach quarantined replies to a selected contact by exact phone match."""
    data = request.get_json(silent=True) or {}
    user_email = _session_org_email()
    lead_id = str(data.get("lead_id") or "").strip()
    if not lead_id:
        return jsonify({"ok": False, "error": "lead_id is required"}), 400

    leads_by_user = load_leads() or {}
    owner_leads = leads_by_user.get(user_email, []) or []
    lead = next((item for item in owner_leads if str((item or {}).get("id") or "") == lead_id), None)
    if not isinstance(lead, dict):
        return jsonify({"ok": False, "error": "Contact not found in this workspace"}), 404

    phone_id = str(wa_credentials(user_email).get("phone_id") or "")
    unmatched = load_wa_unmatched() or []
    matched = []
    remaining = []
    for item in unmatched:
        belongs_to_workspace = (
            not phone_id
            or str((item or {}).get("phone_number_id") or "") == phone_id
        )
        if belongs_to_workspace and lead_matches_wa(lead, str((item or {}).get("sender") or "")):
            matched.append(item)
        else:
            remaining.append(item)

    for item in reversed(matched):
        row = {
            "id": str(item.get("message_id") or item.get("id") or f"wain_{uuid4().hex[:16]}"),
            "message_id": str(item.get("message_id") or ""),
            "from": "lead",
            "direction": "inbound",
            "text": _wa_readable_text(item.get("text")) or "[message received]",
            "type": str(item.get("type") or "unknown"),
            "phone": wa_norm_number(item.get("sender") or ""),
            "profile_name": str(item.get("profile_name") or ""),
            "time": item.get("received_at") or datetime.datetime.utcnow().isoformat() + "Z",
            "reconciled": True,
        }
        append_chat_message(user_email, lead_id, row)

    if matched:
        save_wa_unmatched(remaining)
        newest = matched[0]
        for item in owner_leads:
            if str((item or {}).get("id") or "") == lead_id:
                item["last_reply_at"] = newest.get("received_at")
                item["last_inbound_at"] = newest.get("received_at")
                item["last_message"] = _wa_readable_text(newest.get("text"))
                item["last_message_direction"] = "inbound"
                break
        save_user_leads(user_email, owner_leads)
        _MSG_CACHE.pop((user_email, lead_id), None)

    return jsonify({"ok": True, "matched_count": len(matched)}), 200


@app.get("/api/whatsapp/status")
def get_message_status():
    mid = request.args.get("message_id")
    if not mid:
        return jsonify({"error": "message_id is required"}), 400
    statuses = load_statuses()
    return jsonify(statuses.get(mid) or {}), 200


@app.post("/api/whatsapp/optout")
def set_optout():
    data = request.get_json(force=True) or {}
    user_email = (data.get("user_email") or "").strip().lower()
    lead_id = str(data.get("lead_id") or "").strip()
    opt_out = bool(data.get("opt_out", True))

    if not user_email or not lead_id:
        return jsonify({"error": "user_email and lead_id required"}), 400

    leads = load_leads()
    arr = (leads.get(user_email, []) or [])
    for ld in arr:
        if str(ld.get("id")) == str(lead_id):
            ld["wa_opt_out"] = bool(opt_out)
    save_user_leads(user_email, arr)

    return jsonify({"ok": True, "opt_out": opt_out}), 200


@app.route("/api/whatsapp/send", methods=["POST"])
def send_whatsapp_message():
    """
    Inside 24h:
      - free text (requires message)

    Outside 24h:
      - template send with locale fallback
      - template_params become BODY parameters
    """
    data = request.get_json(force=True) or {}

    def clean(v):
        try:
            return _wa_readable_text(v)
        except Exception:
            return ""

    to_number = clean(data.get("to") or data.get("phone"))
    raw_msg = clean(data.get("message") or data.get("text"))
    user_email = _session_org_email()
    lead_id = clean(data.get("lead_id"))
    template_name = clean(data.get("template_name") or (os.getenv("WHATSAPP_TEMPLATE_DEFAULT") or ""))
    language_code = clean(data.get("language_code") or (os.getenv("WHATSAPP_TEMPLATE_LANG") or "en"))

    raw_params = data.get("template_params")
    if isinstance(raw_params, str):
        raw_params = [p.strip() for p in raw_params.split(",") if p.strip()]
    elif not isinstance(raw_params, list):
        raw_params = None

    params = raw_params if raw_params else None

    if not to_number:
        return jsonify({"ok": False, "error": "Recipient 'to' is required"}), 400

    # Opt-out check
    if user_email and lead_id:
        for ld in (load_leads().get(user_email, []) or []):
            if str(ld.get("id")) == str(lead_id) and bool(ld.get("wa_opt_out")):
                return jsonify({"ok": False, "error": "Lead has opted out of WhatsApp messages"}), 403

    inside24 = within_24h(user_email, lead_id) if (user_email and lead_id) else False
    requested = wa_normalize_lang(language_code)
    primary = wa_primary_lang(requested)
    to_number = wa_norm_number(to_number)

    waba_id = wa_resolve_waba_id(workspace_email=user_email)

    try:
        if inside24:
            if not raw_msg:
                return jsonify({"ok": False, "error": "Message text required inside 24h"}), 400

            resp = wa_send_text(to_number, raw_msg, workspace_email=user_email)
            mode = "free_text"
            sent_text = raw_msg
            used_lang = None
            locales = None
            fallback_reason = None

        else:
            if not template_name:
                return jsonify({
                    "ok": False,
                    "error": "Template name is required outside 24h.",
                    "code": "TEMPLATE_REQUIRED_OUTSIDE_24H"
                }), 422

            r_list = wa_fetch_templates_for_waba(waba_id, workspace_email=user_email)
            if not getattr(r_list, "ok", False):
                try:
                    body = r_list.json()
                except Exception:
                    body = {"raw": r_list.text}
                return jsonify({
                    "ok": False,
                    "error": "Failed to fetch templates from Graph.",
                    "code": "GRAPH_LIST_TEMPLATES_FAILED",
                    "status": getattr(r_list, "status_code", None),
                    "resp": body
                }), 502

            items = (r_list.json() or {}).get("data", [])
            locales = []

            for t in items:
                if (t.get("name") or "") == template_name:
                    ln = wa_normalize_lang(t.get("language") or "")
                    st = (t.get("status") or "").upper()
                    locales.append({"language": ln, "status": st})

            if not locales:
                return jsonify({
                    "ok": False,
                    "error": f"Template '{template_name}' does not exist on this WABA.",
                    "code": "TEMPLATE_NAME_NOT_FOUND_ON_WABA",
                    "template": template_name,
                    "waba_id": waba_id
                }), 404

            exact = next((x for x in locales if x["language"] == requested), None)
            approved_any = [x for x in locales if x["status"] == "APPROVED"]
            approved_same_primary = [x for x in approved_any if wa_primary_lang(x["language"]) == primary]

            used_lang = requested
            fallback_reason = None

            if exact and exact["status"] == "APPROVED":
                pass
            elif approved_same_primary:
                used_lang = approved_same_primary[0]["language"]
                fallback_reason = "requested_locale_missing_or_unapproved_same_primary_used"
            elif approved_any:
                used_lang = approved_any[0]["language"]
                fallback_reason = "requested_locale_missing_or_unapproved_any_approved_used"
            else:
                return jsonify({
                    "ok": False,
                    "error": "Template is not approved in any locale; cannot send outside 24h window.",
                    "code": "TEMPLATE_NOT_APPROVED_ANY_LOCALE",
                    "template": template_name,
                    "waba_id": waba_id,
                    "requestedLanguage": requested,
                    "availableLanguages": locales
                }), 409

            selected_template = next(
                (
                    template
                    for template in items
                    if (template.get("name") or "") == template_name
                    and wa_normalize_lang(template.get("language") or "") == used_lang
                ),
                None,
            )
            template_meta = wa_extract_template_metadata(selected_template)
            expected_count = int(template_meta.get("body_param_count") or 0)
            provided_params = params or []

            if not template_meta.get("supported_by_automations", True):
                return jsonify({
                    "ok": False,
                    "error": "This template requires dynamic header or button parameters that are not configured.",
                    "code": "TEMPLATE_COMPONENTS_UNSUPPORTED",
                    "template": template_name,
                    "language": used_lang,
                    "unsupported_reason": template_meta.get("unsupported_reason"),
                }), 422

            if len(provided_params) != expected_count:
                return jsonify({
                    "ok": False,
                    "error": (
                        f"Template '{template_name}' expects {expected_count} body parameter(s), "
                        f"but {len(provided_params)} were provided."
                    ),
                    "code": "TEMPLATE_PARAM_COUNT_MISMATCH",
                    "template": template_name,
                    "language": used_lang,
                    "expected": expected_count,
                    "received": len(provided_params),
                    "body_text": template_meta.get("body_text"),
                    "example_params": template_meta.get("body_example_params") or [],
                }), 422

            if expected_count and any(not str(value).strip() for value in provided_params):
                return jsonify({
                    "ok": False,
                    "error": "Every required WhatsApp template parameter must have a value.",
                    "code": "TEMPLATE_PARAM_EMPTY",
                    "template": template_name,
                    "language": used_lang,
                    "expected": expected_count,
                }), 422

            resp = wa_send_template(
                to_number,
                template_name,
                used_lang,
                provided_params if expected_count else None,
                expected_body_param_count=expected_count,
                workspace_email=user_email,
            )

            preview_parts = []
            if params:
                preview_parts.append(" | ".join([str(p) for p in params]))
            if raw_msg:
                preview_parts.append(raw_msg)
            preview = " — ".join([p for p in preview_parts if p]).strip()

            sent_text = _wa_render_template(
                template_meta.get("body_text") or "",
                provided_params,
                template_meta.get("body_param_keys") or [],
            )
            if not sent_text:
                sent_text = f"Template sent: {template_name}"
            mode = "template"

        try:
            result = resp.json()
        except Exception:
            result = {"raw": resp.text}

        if resp.status_code >= 400:
            err = {}
            try:
                err = result.get("error", {})
            except Exception:
                pass

            return jsonify({
                "ok": False,
                "mode": mode,
                "status": resp.status_code,
                "error": err.get("message") or "WhatsApp API error",
                "code": err.get("code") or "WA_ERROR",
                "details": (err.get("error_data") or {}),
                "waba_id": waba_id,
                "resp": result
            }), resp.status_code

        msg_id = None
        if isinstance(result, dict):
            arr = result.get("messages")
            if isinstance(arr, list) and arr:
                msg_id = arr[0].get("id")

        # Persist chat + warm cache
        try:
            if user_email and lead_id:
                chats = load_chats()
                user_chats = (chats.get(user_email, {}) or {})
                thread = (user_chats.get(str(lead_id), []) or [])
                outbound_row = {
                    "id": msg_id or f"waout_{uuid4().hex[:16]}",
                    "message_id": msg_id,
                    "from": "user",
                    "direction": "outbound",
                    "text": sent_text,
                    "time": datetime.datetime.utcnow().isoformat() + "Z",
                    "status": "sent_request",
                }
                thread = append_chat_message(user_email, str(lead_id), outbound_row)

                if msg_id:
                    statuses = load_statuses()
                    statuses[msg_id] = {
                        "status": "sent_request",
                        "user_email": user_email,
                        "lead_id": str(lead_id),
                        "to": to_number,
                        "mode": mode,
                        "time": datetime.datetime.utcnow().isoformat() + "Z"
                    }
                    save_statuses(statuses)

                _MSG_CACHE[(str(user_email or ""), str(lead_id or ""))] = {
                    "at": datetime.datetime.utcnow(),
                    "data": thread
                }

        except Exception as e:
            try:
                app.logger.warning("[WHATSAPP] save message/status error: %s", e)
            except Exception:
                pass
        out = {
            "ok": True,
            "mode": mode,
            "status": resp.status_code,
            "message_id": msg_id,
            "requestedLanguage": requested,
            "usedLanguage": used_lang,
            "waba_id": waba_id,
            "fallbackUsed": (used_lang is not None and used_lang != requested)
        }

        if mode == "template":
            out["availableLanguages"] = locales
            if out["fallbackUsed"] and fallback_reason:
                out["fallbackReason"] = fallback_reason

        if user_email:
            lead_name = ""
            try:
                leads_by_user = load_leads() or {}
                for ld in (leads_by_user.get(user_email, []) or []):
                    if str(ld.get("id") or "") == str(lead_id or ""):
                        lead_name = ld.get("name") or ld.get("first_name") or ""
                        break
            except Exception:
                pass

            add_notification(
                user_email=user_email,
                subject="WhatsApp sent",
                message=f"Sent WhatsApp message to {lead_name or to_number}.",
                channel="whatsapp",
                lead_email="",
                extra={
                    "lead_name": lead_name,
                    "mode": mode,
                    "message_id": msg_id,
                    "used_language": used_lang,
                },
            )

        return jsonify(out), resp.status_code

    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    except pyrequests.RequestException as e:
        return jsonify({"ok": False, "error": f"Network error: {e}"}), 502


@app.get("/api/whatsapp/debug/template-locales")
def debug_template_locales():
    r = wa_fetch_templates_raw()
    name = (request.args.get("name") or "").strip()
    items = (r.json() or {}).get("data", []) if r.ok else []

    locales = [
        {
            "language": wa_normalize_lang(t.get("language") or ""),
            "status": (t.get("status") or "").upper()
        }
        for t in items
        if (t.get("name") or "") == name
    ] if name else []

    token, phone_id = wa_env()
    return jsonify({
        "phone_id": phone_id,
        "resolved_waba_id": wa_resolve_waba_id(),
        "template_name": name or None,
        "locales": locales,
        "raw_status": r.status_code
    }), 200


def _verify_meta_signature(raw_body: bytes, header_sig: str) -> bool:
    secret = APP_SECRET
    if not secret or not header_sig:
        return False
    try:
        if not header_sig.startswith("sha256="):
            return False
        sent = header_sig.split("=", 1)[1]
        mac = hmac.new(secret.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
        return hmac.compare_digest(mac.hexdigest(), sent)
    except Exception:
        return False


@app.get("/api/whatsapp/inbound-health")
def whatsapp_inbound_health():
    user_email = _session_org_email()
    config = wa_credentials(user_email)
    phone_id = str(config.get("phone_id") or "")
    can_view_default_diagnostics = (
        config.get("source") == "workspace"
        or _is_platform_owner(_session_email())
    )

    events = load_wa_webhook_events()
    unmatched = [
        row for row in load_wa_unmatched()
        if can_view_default_diagnostics
        and (not phone_id or str((row or {}).get("phone_number_id") or "") == phone_id)
    ]

    matched_events = [event for event in events if event.get("kind") == "inbound_matched"]
    user_events = [event for event in matched_events if not user_email or event.get("user_email") == user_email]
    return jsonify({
        "ok": True,
        "webhook_last_seen_at": events[0].get("created_at") if events else None,
        "last_matched_inbound_at": user_events[0].get("created_at") if user_events else None,
        "recent_matched": user_events[:10],
        "recent_unmatched": [
            {
                "id": row.get("id"),
                "sender_masked": row.get("sender_masked"),
                "type": row.get("type"),
                "received_at": row.get("received_at"),
            }
            for row in unmatched[:10]
        ],
        "unmatched_count": len(unmatched),
    }), 200


@app.route("/api/whatsapp/webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    if request.method == "GET":
        verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN") or ""
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == verify_token:
            _wa_event("verification", ok=True)
            return challenge or "Verified", 200
        _wa_event("verification", ok=False)
        return "Invalid verification token", 403

    raw = request.get_data()
    header_sig = request.headers.get("X-Hub-Signature-256")
    if not _verify_meta_signature(raw, header_sig):
        _wa_event("signature_rejected")
        return "Signature mismatch", 403

    payload = request.get_json(silent=True) or {}
    _wa_event(
        "webhook_received",
        object=payload.get("object"),
        entry_count=len(payload.get("entry", []) or []),
    )

    try:
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value", {}) or {}
                metadata = value.get("metadata", {}) or {}
                phone_number_id = str(metadata.get("phone_number_id") or "")
                workspace_email = _wa_workspace_for_phone_id(phone_number_id)

                # Delivery/read/failure updates.
                status_rows = value.get("statuses", []) or []
                if status_rows:
                    statuses = load_statuses() or {}
                    for status in status_rows:
                        status_id = str(status.get("id") or "unknown")
                        # Preserve the thread metadata recorded when the message
                        # was sent; Meta's status callback does not repeat it.
                        statuses[status_id] = {
                            **(statuses.get(status_id) or {}),
                            "status": status.get("status"),
                            "timestamp": status.get("timestamp"),
                            "recipient": status.get("recipient_id"),
                            "conversation": _json_sanitize(status.get("conversation") or {}),
                            "pricing": _json_sanitize(status.get("pricing") or {}),
                            "errors": _json_sanitize(status.get("errors") or []),
                            "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
                        }
                        _wa_event(
                            "status",
                            message_id=status_id,
                            status=status.get("status"),
                            phone_number_id=phone_number_id,
                            user_email=workspace_email,
                            recipient_masked=_wa_mask_number(status.get("recipient_id") or ""),
                        )
                    save_statuses(statuses)

                contacts = value.get("contacts", []) or []
                contact_waid = str((contacts[0] or {}).get("wa_id") or "") if contacts else ""
                contact_name = str((((contacts[0] or {}).get("profile") or {}).get("name")) or "") if contacts else ""

                for message in value.get("messages", []) or []:
                    sender_waid = str(message.get("from") or contact_waid or "").strip()
                    message_id = str(message.get("id") or "").strip()
                    text_value = _wa_message_text(message)

                    if not sender_waid:
                        _wa_event("inbound_invalid", message_id=message_id, reason="missing_sender")
                        continue

                    user_email, lead_id, lead = resolve_whatsapp_lead(sender_waid, workspace_email)
                    if not user_email or not lead_id or not lead:
                        _wa_store_unmatched(sender_waid, message, text_value, phone_number_id, contact_name)
                        _wa_event(
                            "inbound_unmatched",
                            message_id=message_id,
                            phone_number_id=phone_number_id,
                            user_email=workspace_email,
                            sender_masked=_wa_mask_number(sender_waid),
                            message_type=message.get("type"),
                            text=str(text_value or "")[:180],
                        )
                        try:
                            app.logger.warning(
                                "[WA WEBHOOK] unmatched inbound sender=%s message_id=%s type=%s text=%s",
                                _wa_mask_number(sender_waid),
                                message_id,
                                message.get("type"),
                                str(text_value or "")[:180],
                            )
                        except Exception:
                            pass
                        continue

                    # STOP/START compliance is handled after resolving the exact lead.
                    normalized_command = str(text_value or "").strip().upper()
                    if normalized_command in ("STOP", "UNSUBSCRIBE", "STOP ALL", "CANCEL"):
                        lead["wa_opt_out"] = True
                    elif normalized_command in ("START", "UNSTOP", "SUBSCRIBE"):
                        lead["wa_opt_out"] = False

                    thread, inserted = _wa_append_inbound(
                        user_email=user_email,
                        lead_id=lead_id,
                        lead=lead,
                        sender_waid=sender_waid,
                        message=message,
                        text_value=text_value,
                    )

                    if not inserted:
                        _wa_event(
                            "inbound_duplicate",
                            message_id=message_id,
                            user_email=user_email,
                            lead_id=lead_id,
                        )
                        continue

                    _wa_event(
                        "inbound_matched",
                        message_id=message_id,
                        user_email=user_email,
                        phone_number_id=phone_number_id,
                        lead_id=lead_id,
                        sender_masked=_wa_mask_number(sender_waid),
                        message_type=message.get("type"),
                        text=str(text_value or "")[:180],
                    )
                    try:
                        app.logger.info(
                            "[WA WEBHOOK] matched inbound sender=%s workspace=%s lead_id=%s message_id=%s",
                            _wa_mask_number(sender_waid),
                            user_email,
                            lead_id,
                            message_id,
                        )
                    except Exception:
                        pass

                    lead_name = lead.get("name") or lead.get("first_name") or lead.get("email") or "Lead"
                    lead_email = lead.get("email") or ""
                    add_notification(
                        user_email=user_email,
                        subject="WhatsApp received",
                        message=str(text_value or "New inbound WhatsApp message received.")[:180],
                        channel="whatsapp",
                        lead_email=lead_email,
                        extra={
                            "lead_name": lead_name,
                            "lead_id": lead_id,
                            "type": "inbound",
                            "message_id": message_id,
                        },
                    )

                    # Optional appointment-intent processing. Disabled unless explicitly enabled.
                    if (os.getenv("WA_AUTO_APPOINTMENTS_ENABLED") or "false").strip().lower() == "true":
                        try:
                            from app_wa_auto_appointments import process_incoming_message
                            process_incoming_message(user_email, lead, str(text_value or ""))
                        except Exception as exc:
                            try:
                                app.logger.warning("[WA AUTO APPOINTMENT] inbound processing failed: %s", exc)
                            except Exception:
                                pass

                    # Compliance confirmation messages only.
                    if normalized_command in ("STOP", "UNSUBSCRIBE", "STOP ALL", "CANCEL"):
                        try:
                            wa_send_text(sender_waid, "You have been unsubscribed. Reply START to opt back in.", user_email)
                        except Exception:
                            pass
                    elif normalized_command in ("START", "UNSTOP", "SUBSCRIBE"):
                        try:
                            wa_send_text(sender_waid, "You are now opted back in. Reply STOP anytime to opt out.", user_email)
                        except Exception:
                            pass

    except Exception as exc:
        _wa_event("webhook_parse_error", error=str(exc))
        try:
            app.logger.exception("[WHATSAPP WEBHOOK] parse error: %s", exc)
        except Exception:
            pass

    # Meta expects a fast 200 response; diagnostics are persisted above.
    return "OK", 200

# ============================================================
# AI: prompt endpoints
# ============================================================
@app.route("/api/generate_prompt", methods=["POST"])
def generate_prompt():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON body"}), 400

    lead = data.get("lead") or {}
    lead_name = str(data.get("leadName") or lead.get("name") or "").strip()
    business_name = str(
        data.get("businessName") or
        data.get("business") or
        data.get("user_business") or
        ""
    ).strip()
    prompt_type = str(data.get("promptType") or "").strip()
    instruction = str(data.get("instruction") or "").strip()
    user_name = str(data.get("userName") or "").strip()
    tone = str(data.get("tone") or "warm").strip()[:40]
    length = str(data.get("length") or "standard").strip()[:40]
    additional_context = str(data.get("additionalContext") or "").strip()[:800]

    tags_val = data.get("tags") or lead.get("tags") or []
    if isinstance(tags_val, list):
        tags = ", ".join([str(t) for t in tags_val if str(t).strip()])
    else:
        tags = str(tags_val or "").strip()

    notes = str(data.get("notes") or lead.get("notes") or "").strip()
    last_message = str(data.get("last_message") or data.get("lastMessage") or "").strip()

    if not OPENROUTER_API_KEY:
        return jsonify({"error": "OPENROUTER_API_KEY is missing on the backend."}), 500

    prompt = (
        f"You are an emotionally intelligent CRM assistant for a business named '{business_name or 'this business'}'. "
        f"Write a message that matches the prompt type and instructions below. "
        f"ONLY output the message body (no greeting, no subject, no signature).\n"
        f"Recipient: {lead_name or 'Client'}\n"
        f"Business owner: {user_name or 'Business Owner'}\n"
        f"Tags: {tags or '-'}\n"
        f"Notes: {notes or '-'}\n"
        f"Prompt Type: {prompt_type or '-'}\n"
        f"Tone: {tone}\n"
        f"Length: {length}\n"
        f"Instruction: {instruction or '-'}\n"
        f"Additional context from the user: {additional_context or '-'}\n"
        f"Most recent inbound: \"{last_message or '-'}\"\n"
        "Never invent facts, dates, prices, promises, or customer preferences. "
        "Do not mention sensitive personal, medical, financial, or protected information. "
        "Use the provided context naturally, avoid manipulative urgency, and include no sign-off. "
        "Output one polished message body only."
    )

    try:
        resp = pyrequests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-4o",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a CRM messaging assistant. Output only the message body."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    },
                ],
                "max_tokens": 150,
                "temperature": 0.7,
            },
            timeout=30
        )

        if not resp.ok:
            try:
                err_json = resp.json()
            except Exception:
                err_json = {"raw": resp.text}

            try:
                app.logger.error("[AI GENERATE PROMPT] OpenRouter error %s %s", resp.status_code, err_json)
            except Exception:
                pass

            return jsonify({
                "error": "OpenRouter request failed.",
                "status": resp.status_code,
                "details": err_json
            }), 502

        try:
            j = resp.json()
        except Exception:
            try:
                app.logger.error("[AI GENERATE PROMPT] Non-JSON response: %s", resp.text[:500])
            except Exception:
                pass
            return jsonify({"error": "AI provider returned invalid JSON."}), 502

        choices = j.get("choices") or []
        if choices and choices[0].get("message", {}).get("content"):
            msg = choices[0]["message"]["content"].strip()
            return jsonify({"prompt": msg}), 200

        return jsonify({
            "error": (j.get("error") or {}).get("message") or "AI response was empty"
        }), 502

    except pyrequests.RequestException as ex:
        try:
            app.logger.error("[AI GENERATE PROMPT] Request exception: %s", str(ex))
        except Exception:
            pass
        return jsonify({"error": f"Failed to contact AI provider: {str(ex)}"}), 502

    except Exception as ex:
        try:
            app.logger.exception("[AI GENERATE PROMPT] Unexpected error: %s", str(ex))
        except Exception:
            pass
        return jsonify({"error": "Failed to get AI response"}), 500


@app.post("/api/ai-prompt")
def ai_prompt():
    data = request.get_json(force=True) or {}
    user_email = (data.get("user_email") or "").strip().lower()
    lead_id = str(data.get("lead_id") or "").strip()

    if not user_email or not lead_id:
        return jsonify({"error": "user_email and lead_id are required"}), 400

    users = load_users()
    leads_by_user = load_leads()
    chats_by_user = load_chats()

    user = users.get(user_email, {}) or {}
    user_name = (user.get("name") or "").strip()
    business = (user.get("business") or user.get("businessType") or "business").strip()

    lead = None
    for ld in (leads_by_user.get(user_email, []) or []):
        if str(ld.get("id")) == lead_id:
            lead = ld
            break

    lead_name = (lead.get("name") if lead else "") or ""
    lead_tags = ", ".join((lead or {}).get("tags", []))
    lead_notes = (lead or {}).get("notes", "") or "-"

    last_inbound = ""
    thread = (chats_by_user.get(user_email, {}) or {}).get(lead_id, []) or []
    for m in reversed(thread):
        if m.get("from") == "lead":
            t = m.get("text")
            if isinstance(t, str) and t.strip():
                last_inbound = t.strip()
                break

    if not os.getenv("OPENROUTER_API_KEY"):
        return jsonify({"error": "OPENROUTER_API_KEY is not configured"}), 500

    sys_msg = "You are a CRM messaging assistant. Output only the message body (no greetings or signatures)."
    user_msg = (
        f"You are a professional, emotionally intelligent assistant for a {business} business. "
        f"Write ONLY a direct, warm reply that could be sent in chat. "
        f"Do NOT include greeting lines or sign-offs.\n\n"
        f"Lead Name: {lead_name}\n"
        f"Tags: {lead_tags}\n"
        f"Notes: {lead_notes}\n"
        f"Most recent message from the lead: \"{last_inbound}\"\n"
        f"Reply as if you were {user_name or 'the business owner'} at {business}."
    )

    ok, txt, meta = _complete_openrouter_prompt(
        [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
        max_tokens=220,
        temperature=0.7,
        timeout=30,
    )
    if not ok or not txt:
        return jsonify({"error": "ai_failed", "detail": meta}), 502

    return jsonify({"prompt": _clean_ai_text(txt), "meta": meta}), 200

from sendgrid.helpers.mail import Email

@app.route("/api/send-ai-message", methods=["POST"])
def send_ai_message():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "Invalid JSON body"}), 400

    lead = data.get("lead") or {}
    to_email = (
        data.get("to")
        or data.get("email")
        or data.get("lead_email")
        or data.get("leadEmail")
        or lead.get("email")
        or ""
    )
    to_email = str(to_email).strip().lower()

    if not to_email:
        return jsonify({"ok": False, "error": "Recipient 'to' is required"}), 400

    owner_email = str(data.get("user_email") or request.headers.get("X-User-Email") or "").strip().lower()

    if not owner_email:
        try:
            lbsu = load_leads() or {}
            if isinstance(lbsu, dict):
                for owner, arr in lbsu.items():
                    for ld in (arr or []):
                        if str(ld.get("email") or "").strip().lower() == to_email:
                            owner_email = str(owner or "").strip().lower()
                            break
                    if owner_email:
                        break
        except Exception as e:
            try:
                app.logger.warning("[SEND AI MESSAGE] owner inference failed: %s", e)
            except Exception:
                pass

    try:
        users = load_users() or {}
    except Exception:
        users = {}

    user_profile = users.get(owner_email, {}) if isinstance(users, dict) and owner_email else {}
    if not isinstance(user_profile, dict):
        user_profile = {}

    business_name = (
        str(data.get("businessName") or data.get("business") or data.get("user_business") or "").strip()
        or str(user_profile.get("business") or "").strip()
        or str(user_profile.get("businessType") or "").strip()
        or "Your Business"
    )
    user_name = str(data.get("userName") or data.get("user_name") or user_profile.get("name") or "").strip()
    lead_name = str(data.get("leadName") or lead.get("name") or "").strip()

    prompt_type = str(data.get("promptType") or data.get("type") or "reengage").strip().lower()

    TEMPLATE_MAP = {
        "followup": SG_TEMPLATE_FOLLOWUP_LEAD,
        "reengage": SG_TEMPLATE_REENGAGE_LEAD,
        "apology": SG_TEMPLATE_APOLOGY_LEAD,
        "upsell": SG_TEMPLATE_UPSELL_LEAD,
        "birthday": SG_TEMPLATE_BIRTHDAY,
        "appointment": SG_TEMPLATE_APPT_CONFIRM,
    }
    template_id = TEMPLATE_MAP.get(prompt_type, SG_TEMPLATE_FOLLOWUP_LEAD)

    if not template_id:
        return jsonify({"ok": False, "error": f"No SendGrid template configured for prompt type '{prompt_type}'"}), 500

    model_text = (
        data.get("message")
        or data.get("prompt")
        or data.get("ai_text")
        or data.get("body")
        or data.get("text")
        or ""
    )
    model_text = str(model_text).strip()

    if not model_text:
        return jsonify({"ok": False, "error": "No AI text provided (pass it in 'message')."}), 422

    subject = str(
        data.get("subject")
        or data.get("emailSubject")
        or data.get("subjectLine")
        or "Quick note"
    ).strip()

    tags_val = data.get("tags") or lead.get("tags") or []
    if isinstance(tags_val, list):
        tags = ", ".join([str(t) for t in tags_val if str(t).strip()])
    else:
        tags = str(tags_val or "").strip()

    notes = str(data.get("notes") or lead.get("notes") or "").strip()
    booking_link = str(
        data.get("booking_link")
        or data.get("bookingLink")
        or user_profile.get("booking_link")
        or ""
    ).strip()

    dynamic_data = {
        "subject": subject,
        "lead_first_name": (lead_name.split(" ")[0] if lead_name else ""),
        "lead_name": lead_name,
        "business_name": business_name,
        "user_name": user_name,
        "user_email": owner_email,
        "tags": tags,
        "notes": notes,
        "booking_link": booking_link,
        "ai_text": model_text,
        "message": model_text,
        "content": model_text,
        "text": model_text,
        "body": model_text,
        "prompt": model_text,
    }

    try:
        reply_to_addr = make_inbound_reply_address(owner_email, to_email)

        ok = send_email_with_template(
            to_email=to_email,
            template_id=template_id,
            dynamic_data=dynamic_data,
            subject=subject,
            from_email=Email(SENDER_EMAIL, business_name),
            reply_to_email=reply_to_addr,
        )
    except Exception as e:
        try:
            app.logger.exception("[SEND AI MESSAGE] send_email_with_template failed: %s", e)
        except Exception:
            pass
        return jsonify({
            "ok": False,
            "error": "Failed to send AI message",
            "details": str(e),
        }), 502

    if not ok:
        return jsonify({
            "ok": False,
            "sent": False,
            "error": "SendGrid send failed",
            "template_id": template_id,
            "subject": subject,
            "to": to_email,
            "from_display": business_name,
            "from_email": SENDER_EMAIL,
            "reply_to": owner_email or None,
        }), 502

    if owner_email:
        add_notification(
            user_email=owner_email,
            subject="AI email sent",
            message=f"Sent AI-generated email to {lead_name or to_email}.",
            channel="email",
            lead_email=to_email,
            extra={
                "lead_name": lead_name,
                "type": "ai",
                "prompt_type": prompt_type,
            },
        )

    return jsonify({
        "ok": True,
        "sent": True,
        "template_id": template_id,
        "subject": subject,
        "to": to_email,
        "from_display": business_name,
        "from_email": SENDER_EMAIL,
        "reply_to": owner_email or None,
        "used_text": model_text,
    }), 200

# =================================================================
# AUTOMATIONS (INLINE) â€” Blueprint + Engine (prod-ready routes)
# =================================================================
@app.get("/api/billing/usage")
def billing_usage():
    workspace = _session_org_email()
    if not workspace:
        return jsonify({"error": "authentication_required"}), 401
    users = load_users() or {}
    record = users.get(workspace) or {}
    leads = (load_leads() or {}).get(workspace, []) or []
    chats_data = load_chats()
    chats = chats_data.get(workspace, {}) if isinstance(chats_data, dict) else {}
    message_count = sum(len(thread or []) for thread in (chats or {}).values())
    team_count = len([row for row in users.values() if str(row.get("org_owner_email") or "").lower() == workspace])
    flows_db = read_json(os.path.join(DATA_ROOT, "automations.json"), {"users": {}}) if "read_json" in globals() else {"users": {}}
    flows = (flows_db.get("users") or {}).get(workspace, []) if isinstance(flows_db, dict) else []
    return jsonify({
        "plan": record.get("plan") or "Standard", "billing_status": record.get("billing_status") or record.get("status") or "trial",
        "trial_days_remaining": _trial_details(record).get("daysRemaining", 0), "trial_ends_at": _trial_details(record).get("endsAt"),
        "next_payment_at": record.get("current_period_end") or record.get("subscription_period_end"),
        "whatsapp_messages": message_count, "ai_generations": int(record.get("ai_generations") or 0),
        "active_automations": len([flow for flow in flows if flow.get("enabled")]), "team_seats": team_count + 1,
        "contacts": len(leads), "invoices_created": int(record.get("invoices_created") or 0),
    }), 200

CHANNEL_EMAIL = "email"
CHANNEL_WHATSAPP = "whatsapp"

FILE_AUTOMATIONS = os.path.join(DATA_ROOT, os.getenv("FILE_AUTOMATIONS", "automations.json"))
FILE_STATE = os.path.join(DATA_ROOT, os.getenv("FILE_STATE", "automations_state.json"))
FILE_NOTIFICATIONS = os.path.join(DATA_ROOT, os.getenv("FILE_NOTIFICATIONS", "notifications.json"))
FILE_USERS = os.path.join(DATA_ROOT, os.getenv("FILE_USERS", "automation_users.json"))
FILE_SUBSCRIPTIONS = os.path.join(DATA_ROOT, os.getenv("FILE_SUBSCRIPTIONS", "subscriptions.json"))

def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)

def read_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path: str, data: Any):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def ensure_files():
    os.makedirs(DATA_ROOT, exist_ok=True)

    defaults = {
        FILE_AUTOMATIONS: {"users": {}},
        FILE_STATE: {},
        FILE_NOTIFICATIONS: {"notifications": []},
        FILE_USERS: {"users": {}},
        FILE_SUBSCRIPTIONS: {"subscriptions": {}},
    }

    for path, default_data in defaults.items():
        try:
            directory = os.path.dirname(path) or "."
            os.makedirs(directory, exist_ok=True)
            if not os.path.exists(path):
                write_json(path, default_data)
        except Exception as e:
            try:
                app.logger.warning("[AUTOMATIONS ensure_files] failed for %s: %s", path, e)
            except Exception:
                pass

def create_notification(owner_email: str, title: str, body: str):
    return add_notification(
        user_email=(owner_email or "").lower(),
        subject=title or "Automation notification",
        message=body or "",
        channel="automation",
    )

def load_user_profile(user_email: str) -> Dict[str, Any]:
    db = read_json(FILE_USERS, {"users": {}})
    return db.get("users", {}).get((user_email or "").lower(), {}) or {}

def save_user_profile(user_email: str, profile: Dict[str, Any]):
    db = read_json(FILE_USERS, {"users": {}})
    db.setdefault("users", {})[(user_email or "").lower()] = profile
    write_json(FILE_USERS, db)

def load_user_flows(user_email: str) -> List[Dict[str, Any]]:
    db = read_json(FILE_AUTOMATIONS, {"users": {}})
    return db.get("users", {}).get((user_email or "").lower(), []) or []

def save_user_flows(user_email: str, flows: List[Dict[str, Any]]):
    db = read_json(FILE_AUTOMATIONS, {"users": {}})
    db.setdefault("users", {})[(user_email or "").lower()] = flows
    write_json(FILE_AUTOMATIONS, db)

def load_state() -> Dict[str, Any]:
    return read_json(FILE_STATE, {}) or {}

def save_state(state: Dict[str, Any]):
    try:
        ensure_files()
        write_json(FILE_STATE, state or {})
    except Exception as e:
        try:
            app.logger.warning("[AUTOMATIONS save_state] failed: %s", e)
        except Exception:
            pass

def user_from_request() -> str:
    h = request.headers.get("X-User-Email")
    if h:
        return h.strip().lower()
    q = request.args.get("user") or (request.json.get("user") if request.is_json else None)
    return (q or "demo@retainai.ca").strip().lower()

def dt_parse(s: Optional[str]) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromisoformat(s) if s else None
    except Exception:
        return None

def is_valid_url(u: str) -> bool:
    try:
        p = urlparse(u)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

def in_quiet_hours(now: datetime.datetime, profile: Dict[str, Any]) -> bool:
    qs = profile.get("quiet_hours_start")
    qe = profile.get("quiet_hours_end")
    if qs is None or qe is None:
        return False
    hour = now.hour
    if qs > qe:
        return hour >= qs or hour < qe
    return qs <= hour < qe

_td = datetime.timedelta

def trig_no_reply(lead: Dict[str, Any], days: int) -> bool:
    last_inbound = dt_parse(lead.get("last_inbound_at"))
    last_outbound = dt_parse(lead.get("last_outbound_at"))
    last_any = dt_parse(lead.get("last_activity_at")) or last_inbound or last_outbound
    if not last_any:
        created = dt_parse(lead.get("createdAt")) or dt_parse(lead.get("created_at")) or (now_utc() - _td(days=999))
        return now_utc() - created >= _td(days=days)
    if last_inbound and (now_utc() - last_inbound < _td(days=days)):
        return False
    return now_utc() - last_any >= _td(days=days)

def trig_new_lead(lead: Dict[str, Any], within_hours: int = 24) -> bool:
    created = dt_parse(lead.get("createdAt")) or dt_parse(lead.get("created_at"))
    return bool(created and (now_utc() - created <= _td(hours=within_hours)))

def trig_no_show(lead: Dict[str, Any]) -> bool:
    for appt in (lead.get("appointments") or []):
        if str(appt.get("status") or "").lower().replace("_", "-") == "no-show" and not appt.get("automation_seen_no_show"):
            return True
    return False

def cond_no_reply_since(lead: Dict[str, Any], days: int) -> bool:
    last_inbound = dt_parse(lead.get("last_inbound_at"))
    return (not last_inbound) or (now_utc() - last_inbound >= _td(days=days))

def cond_no_booking_since(lead: Dict[str, Any], days: int = 2) -> bool:
    for appt in (lead.get("appointments") or []):
        if str(appt.get("status") or "").lower() in ("booked", "scheduled", "confirmed"):
            upd = dt_parse(appt.get("updated_at"))
            if upd and (now_utc() - upd < _td(days=days)):
                return False
    return True

MISSING = "â›”"

def render_text(tmpl: str, lead: Dict[str, Any], run: Dict[str, Any], profile: Dict[str, Any]) -> str:
    if not isinstance(tmpl, str):
        return str(tmpl)
    business_name = profile.get("business_name") or f"{MISSING} add your business name in Automations > Settings"
    booking_link = profile.get("booking_link") or f"{MISSING} add your booking link in Automations > Settings"
    out = tmpl
    out = out.replace("{{business_name}}", business_name)
    out = out.replace("{{booking_link}}", booking_link)
    out = out.replace("{{lead.first_name}}", str(lead.get("first_name") or (lead.get("name") or "").split(" ")[0] or ""))
    out = out.replace("{{lead.full_name}}", str(lead.get("name") or ""))
    out = out.replace("{{last_ai_text}}", (run.get("memo", {}).get("last_ai_text") or ""))
    return out

def contains_blockers(text: str) -> bool:
    return MISSING in (text or "")

_LAST_SEND_CACHE: Dict[str, Dict[str, Any]] = {}
_LAST_SEND_TTL_SEC = 120

def dedupe_ok(key: str) -> bool:
    now = time.time()
    item = _LAST_SEND_CACHE.get(key)
    if item and (now - item["at"] < _LAST_SEND_TTL_SEC):
        return False
    _LAST_SEND_CACHE[key] = {"at": now}
    return True

def choose_wa_template(preferred_name: Optional[str], preferred_lang: Optional[str], workspace_email: str = ""):
    name = (preferred_name or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "")).strip()
    if not name:
        return None, None, 0, {}

    waba_id = wa_resolve_waba_id(workspace_email=workspace_email)
    r_list = wa_fetch_templates_for_waba(waba_id, workspace_email)
    items = (r_list.json() or {}).get("data", []) if getattr(r_list, "ok", False) else []

    requested = wa_normalize_lang(preferred_lang or os.getenv("WHATSAPP_TEMPLATE_LANG", "en"))
    primary = wa_primary_lang(requested)

    candidates = []
    for template in items:
        if (template.get("name") or "") != name:
            continue
        meta = wa_extract_template_metadata(template)
        candidates.append((template, meta))

    approved = [(template, meta) for template, meta in candidates if meta.get("status") == "APPROVED"]
    exact = next((pair for pair in approved if pair[1].get("normalized_language") == requested), None)
    same_primary = next(
        (pair for pair in approved if wa_primary_lang(pair[1].get("normalized_language") or "") == primary),
        None,
    )
    selected = exact or same_primary or (approved[0] if approved else None)

    if not selected:
        return name, None, 0, {}

    _, metadata = selected
    used_lang = metadata.get("normalized_language") or requested
    return name, used_lang, int(metadata.get("body_param_count") or 0), metadata

def build_wa_params(count: int, lead: dict, profile: dict, run: dict, rendered_text: Optional[str]):
    vals: List[str] = []
    first = lead.get("first_name") or (lead.get("name") or "").split(" ")[0]
    if first:
        vals.append(str(first))
    if profile.get("business_name"):
        vals.append(str(profile["business_name"]))
    if profile.get("booking_link"):
        vals.append(str(profile["booking_link"]))
    if rendered_text:
        vals.append(str(rendered_text))
    vals = (vals + [""] * count)[:count]
    return vals

def append_automation_chat_message(user_email: str, lead_id: str, text: str):
    try:
        if not user_email or not lead_id:
            return
        row = {
            "id": f"waauto_{uuid4().hex[:16]}",
            "from": "user",
            "direction": "outbound",
            "text": _wa_readable_text(text),
            "time": now_utc().isoformat().replace("+00:00", "") + "Z",
            "status": "automation_sent",
        }
        arr = append_chat_message(user_email, str(lead_id), row)
        _MSG_CACHE[(str(user_email or ""), str(lead_id or ""))] = {
            "at": datetime.datetime.utcnow(),
            "data": arr,
        }
    except Exception as e:
        print("[Automations] append_chat_message error:", e)

def can_send(run: Dict[str, Any], channel: str, per_hours: int) -> bool:
    last = (run.get("last_sent") or {}).get(channel)
    if not last:
        return True
    try:
        last_dt = datetime.datetime.fromisoformat(last)
    except Exception:
        return True
    return (now_utc() - last_dt) >= _td(hours=per_hours)

def mark_sent(run: Dict[str, Any], channel: str):
    run.setdefault("last_sent", {})[channel] = now_utc().isoformat()

def send_whatsapp_with_window(flow, step, lead, run, caps, profile) -> bool:
    if caps.get("respect_quiet_hours", True) and in_quiet_hours(now_utc(), profile):
        return False

    per_hours = int(caps.get("per_lead_per_day", 1)) * 24
    if not can_send(run, CHANNEL_WHATSAPP, per_hours=per_hours):
        return False

    user_email = (lead.get("owner") or flow.get("owner") or "").lower()
    lead_id = str(lead.get("id") or "")
    if not user_email or not lead_id:
        return True

    to = lead.get("phone") or lead.get("whatsapp")
    if not to:
        return True
    if bool(lead.get("wa_opt_out")):
        return True

    raw = step.get("text") or run.get("memo", {}).get("last_ai_text") or ""
    body = render_text(raw, lead, run, profile)
    if contains_blockers(body):
        create_notification(user_email, "Setup needed",
                            "WhatsApp message blocked: missing profile values (booking link / business name).")
        return True

    inside24 = False
    try:
        inside24 = within_24h(user_email, lead_id)
    except Exception:
        inside24 = False

    if inside24:
        try:
            resp = wa_send_text(to, body, user_email)
            ok = getattr(resp, "status_code", 500) < 400
        except Exception as e:
            print("[Automations] WA free-text send error:", e)
            ok = False
        if ok:
            mark_sent(run, CHANNEL_WHATSAPP)
            append_automation_chat_message(user_email, lead_id, body)
            add_notification(
                user_email=user_email,
                subject="Automation WhatsApp sent",
                message=f"Automation sent a WhatsApp message to {lead.get('name') or lead.get('email') or 'lead'}.",
                channel="automation",
                lead_email=lead.get("email") or "",
                extra={
                    "lead_name": lead.get("name") or lead.get("first_name") or "",
                    "type": "automation",
                },
            )
        return True

    template_cfg = step.get("template") or {}
    preferred_name = template_cfg.get("name") or step.get("template_name")
    preferred_lang = template_cfg.get("language") or os.getenv("WHATSAPP_TEMPLATE_LANG", "en")
    tpl_name, used_lang, pcount, template_meta = choose_wa_template(preferred_name, preferred_lang, user_email)
    if not tpl_name or not used_lang:
        create_notification(user_email, "WhatsApp template unavailable",
                            "No approved template/locale available to send outside the 24h window.")
        return True

    if not template_meta.get("supported_by_automations", True):
        reason = template_meta.get("unsupported_reason") or "unsupported dynamic header or button parameters"
        create_notification(
            user_email,
            "WhatsApp template needs attention",
            f"Template '{tpl_name}' cannot run in Automations yet: {reason}.",
        )
        return True

    explicit_params: List[str] = []
    raw_params = template_cfg.get("params")
    if isinstance(raw_params, list):
        explicit_params = [str(p).strip() if p is not None else "" for p in raw_params]
    elif isinstance(raw_params, str):
        explicit_params = [p.strip() for p in raw_params.split(",")]

    if explicit_params:
        params = [render_text(value, lead, run, profile).strip() for value in explicit_params]
    else:
        params = build_wa_params(pcount, lead, profile, run, body)

    if len(params) != pcount:
        create_notification(
            user_email,
            "WhatsApp template parameter mismatch",
            f"Template '{tpl_name}' expects {pcount} body parameter(s), but the flow provides {len(params)}.",
        )
        return True

    if any((not str(value).strip()) or contains_blockers(str(value)) for value in params):
        create_notification(
            user_email,
            "WhatsApp template setup needed",
            f"Template '{tpl_name}' has an empty or unresolved required parameter. Open the flow and complete every parameter mapping.",
        )
        return True

    shown = f"[template:{tpl_name}/{used_lang}] {body}"
    try:
        resp = wa_send_template(
            to,
            tpl_name,
            used_lang,
            params if pcount else None,
            expected_body_param_count=pcount,
            workspace_email=user_email,
        )
        ok = getattr(resp, "status_code", 500) < 400
    except Exception as e:
        try:
            app.logger.error(
                "[AUTOMATIONS WA TEMPLATE PREFLIGHT] template=%s language=%s expected=%s provided=%s error=%s",
                tpl_name, used_lang, pcount, len(params), e,
            )
        except Exception:
            pass
        ok = False
    if ok:
        mark_sent(run, CHANNEL_WHATSAPP)
        append_automation_chat_message(user_email, lead_id, shown)
        add_notification(
            user_email=user_email,
            subject="Automation WhatsApp sent",
            message=f"Automation sent a WhatsApp template to {lead.get('name') or lead.get('email') or 'lead'}.",
            channel="automation",
            lead_email=lead.get("email") or "",
            extra={
                "lead_name": lead.get("name") or lead.get("first_name") or "",
                "type": "automation",
                "template_name": tpl_name,
                "used_language": used_lang,
            },
        )
    return True

def get_run(state: Dict[str, Any], flow_id: str, lead_key: str) -> Dict[str, Any]:
    return state.setdefault(flow_id, {}).setdefault(lead_key, {
        "step": 0,
        "created_at": now_utc().isoformat(),
        "last_step_at": None,
        "done": False,
        "last_sent": {},
        "memo": {},
        "events": [{"type": "entered", "label": "Lead entered flow", "at": now_utc().isoformat()}],
        "error": "",
    })

def advance(run: Dict[str, Any]):
    run["step"] = int(run.get("step", 0)) + 1
    run["last_step_at"] = now_utc().isoformat()

def automation_event(run: Dict[str, Any], event_type: str, label: str, **details):
    rows = run.setdefault("events", [])
    rows.append({"type": event_type, "label": label, "at": now_utc().isoformat(), **details})
    run["events"] = rows[-100:]

def trigger_met(trigger: Dict[str, Any], lead: Dict[str, Any]) -> bool:
    t = trigger.get("type")
    if t == "no_reply":
        return trig_no_reply(lead, int(trigger.get("days", 3)))
    if t == "new_lead":
        return trig_new_lead(lead, int(trigger.get("within_hours", 24)))
    if t == "appointment_no_show":
        return trig_no_show(lead)
    return False

def should_auto_stop(flow: Dict[str, Any], lead: Dict[str, Any], run: Dict[str, Any]) -> bool:
    if flow.get("auto_stop_on_reply", True):
        last_inbound = dt_parse(lead.get("last_inbound_at"))
        if last_inbound and last_inbound > dt_parse(run.get("created_at")):
            return True
    return False

def send_email_sendgrid_auto(
    to_email: str,
    subject: str,
    html: str,
    business_name: str,
    owner_email: str = "",
) -> bool:
    if not globals().get("SENDGRID_API_KEY"):
        print("[Automations] SENDGRID_API_KEY missing; skipping email send (simulated).")
        return True
    try:
        sg = SendGridAPIClient(globals()["SENDGRID_API_KEY"])
        msg = Mail(
            from_email=Email(globals().get("SENDER_EMAIL", "noreply@retainai.ca"), business_name or "RetainAI"),
            to_emails=to_email,
            subject=subject,
            html_content=html,
        )

        if owner_email:
            msg.reply_to = Email(make_inbound_reply_address(owner_email, to_email))

        resp = sg.send(msg)
        print("[Automations] SendGrid status:", resp.status_code)
        return 200 <= resp.status_code < 300
    except Exception as e:
        print("[Automations] SendGrid error:", e)
        return False

def ai_draft_message(context: Dict[str, Any]) -> str:
    business_name = context.get("business_name") or f"{MISSING} add your business name in Automations > Settings"
    booking = context.get("booking_link") or f"{MISSING} add your booking link in Automations > Settings"
    lead_name = (context.get("lead", {}).get("first_name") or context.get("lead", {}).get("name") or "there")
    if not os.getenv("OPENROUTER_API_KEY"):
        return f"Hey {lead_name}, just checking in â€” want to grab a spot with {business_name}? Book here: {booking}."
    try:
        prompt = (
            "Write a short, friendly follow-up message (<= 45 words).\n"
            f"Business: {business_name}.\n"
            f"Booking link: {booking}.\n"
            f"Lead context: {json.dumps(context.get('lead', {}))}.\n"
            "Tone: warm, human, no emojis, 1 sentence if possible."
        )
        r = pyrequests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}", "Content-Type": "application/json"},
            json={
                "model": "openrouter/auto",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
            },
            timeout=25,
        )
        data = r.json()
        txt = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return (txt or f"Quick check-in â€” want to grab a spot with {business_name}? {booking}").strip()
    except Exception as e:
        print("[Automations] AI draft error:", e)
        return f"Quick check-in â€” want to grab a spot with {business_name}? {booking}"

def execute_step(flow: Dict[str, Any], step: Dict[str, Any], lead: Dict[str, Any], run: Dict[str, Any],
                 caps: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    kind = step.get("type")

    if kind == "wait":
        last = dt_parse(run.get("last_step_at")) or dt_parse(run.get("created_at")) or now_utc()
        delta = _td(days=step.get("days", 0), hours=step.get("hours", 0), minutes=step.get("minutes", 0))
        return now_utc() - last >= delta

    if kind == "if_no_reply":
        within_days = int(step.get("within_days", 2))
        if cond_no_reply_since(lead, within_days):
            for s in (step.get("then") or []):
                execute_step(flow, s, lead, run, caps, profile)
        return True

    if kind == "if_no_booking":
        within_days = int(step.get("within_days", 2))
        if cond_no_booking_since(lead, within_days):
            for s in (step.get("then") or []):
                execute_step(flow, s, lead, run, caps, profile)
        return True

    if kind == "ai_draft":
        text = ai_draft_message({
            "lead": lead,
            "flow": flow,
            "business_name": profile.get("business_name"),
            "booking_link": profile.get("booking_link"),
        })
        run.setdefault("memo", {})["last_ai_text"] = text
        return True

    if kind == "send_whatsapp":
        return send_whatsapp_with_window(flow, step, lead, run, caps, profile)

    if kind == "send_email":
        if caps.get("respect_quiet_hours", True) and in_quiet_hours(now_utc(), profile):
            return False
        per_hours = int(caps.get("per_lead_per_day", 1)) * 24
        if not can_send(run, CHANNEL_EMAIL, per_hours=per_hours):
            return False
        email = lead.get("email")
        if not email:
            return True

        subject = render_text(step.get("subject") or "Quick check-in", lead, run, profile)
        html = render_text(
            step.get("html") or step.get("body") or "<p>Hi {{lead.first_name}}, just checking in. <a href='{{booking_link}}'>Book here</a>.</p>",
            lead, run, profile
        )
        html = html.replace("\n", "<br>")
        if contains_blockers(subject) or contains_blockers(html):
            create_notification(lead.get("owner") or flow.get("owner") or "", "Setup needed",
                                "Email blocked: missing profile values (booking link / business name).")
            return True

        ok = send_email_sendgrid_auto(
            email,
            subject,
            html,
            profile.get("business_name") or "RetainAI",
            owner_email=(lead.get("owner") or flow.get("owner") or "").lower(),
        )
        if ok:
            mark_sent(run, CHANNEL_EMAIL)
            add_notification(
                user_email=(lead.get("owner") or flow.get("owner") or "").lower(),
                subject="Automation email sent",
                message=f"Automation sent an email to {lead.get('name') or email}.",
                channel="automation",
                lead_email=email,
                extra={
                    "lead_name": lead.get("name") or lead.get("first_name") or "",
                    "type": "automation",
                },
            )
        return True

    if kind == "push_owner":
        owner = lead.get("owner") or flow.get("owner") or ""
        if owner:
            create_notification(owner, step.get("title") or "Lead to call", step.get("message") or str(lead.get("email")))
        return True

    if kind == "add_tag":
        tag = step.get("tag")
        if tag:
            tags = set((lead.get("tags") or []))
            tags.add(tag)
            lead["tags"] = sorted(list(tags))
            owner = (lead.get("owner") or flow.get("owner") or "").lower()
            if owner:
                leads_by_user = load_leads()
                arr = leads_by_user.get(owner, []) or []
                for i, ld in enumerate(arr):
                    if (ld.get("id") == lead.get("id")) or (ld.get("email") == lead.get("email")):
                        arr[i] = lead
                        break
                save_user_leads(owner, arr)
        return True

    return True

def engine_tick():
    try:
        ensure_files()
        flows_db = read_json(FILE_AUTOMATIONS, {"users": {}}) or {"users": {}}
        state = load_state() or {}
        leads_by_user = load_leads() or {}

        if not isinstance(flows_db, dict):
            flows_db = {"users": {}}
        if not isinstance(state, dict):
            state = {}
        if not isinstance(leads_by_user, dict):
            leads_by_user = {}

        for user, flows in (flows_db.get("users", {}) or {}).items():
            try:
                profile = load_user_profile(user)
                user_leads = leads_by_user.get(user, []) or []

                if not isinstance(user_leads, list):
                    user_leads = []
                if not isinstance(flows, list):
                    flows = []

                for flow in flows:
                    try:
                        if not isinstance(flow, dict):
                            continue
                        if not flow.get("enabled", False):
                            continue

                        flow_id = flow.get("id") or str(uuid4())
                        steps = flow.get("steps", []) or []
                        caps = flow.get("caps", {"per_lead_per_day": 1, "respect_quiet_hours": True}) or {}
                        trigger = flow.get("trigger", {}) or {}

                        if not isinstance(steps, list):
                            steps = []
                        if not isinstance(caps, dict):
                            caps = {"per_lead_per_day": 1, "respect_quiet_hours": True}
                        if not isinstance(trigger, dict):
                            trigger = {}

                        for lead in user_leads:
                            try:
                                if not isinstance(lead, dict):
                                    continue

                                owner = (lead.get("owner") or user or "").lower()
                                if owner != user:
                                    continue

                                lead_id = lead.get("id")
                                if lead_id is None:
                                    continue

                                lead_key = str(lead_id)
                                run = get_run(state, flow_id, lead_key)

                                if run.get("done"):
                                    continue

                                if run.get("step", 0) == 0:
                                    if not trigger_met(trigger, lead):
                                        state.setdefault(flow_id, {}).pop(lead_key, None)
                                        continue

                                if should_auto_stop(flow, lead, run):
                                    run["done"] = True
                                    run["completed_at"] = now_utc().isoformat()
                                    automation_event(run, "reply", "Flow stopped because the customer replied")
                                    continue

                                step_index = int(run.get("step", 0))
                                if step_index >= len(steps):
                                    run["done"] = True
                                    run["completed_at"] = now_utc().isoformat()
                                    automation_event(run, "completed", "Flow completed")
                                    continue

                                step = steps[step_index]
                                progressed = execute_step(flow, step, lead, run, caps, profile)
                                if progressed:
                                    automation_event(run, "step", f"{str(step.get('type') or 'step').replace('_', ' ').title()} completed", step_index=step_index)
                                    advance(run)

                            except Exception as e:
                                try:
                                    run["error"] = str(e)[:300]
                                    automation_event(run, "failed", "Step failed", reason=str(e)[:300])
                                except Exception:
                                    pass
                                try:
                                    app.logger.warning(
                                        "[AUTOMATIONS engine_tick] lead failure user=%s flow_id=%s lead_id=%s error=%s",
                                        user,
                                        flow_id,
                                        lead.get("id") if isinstance(lead, dict) else None,
                                        e,
                                    )
                                except Exception:
                                    pass
                                continue

                    except Exception as e:
                        try:
                            app.logger.warning(
                                "[AUTOMATIONS engine_tick] flow failure user=%s flow_id=%s error=%s",
                                user,
                                flow.get("id") if isinstance(flow, dict) else None,
                                e,
                            )
                        except Exception:
                            pass
                        continue

            except Exception as e:
                try:
                    app.logger.warning("[AUTOMATIONS engine_tick] user failure user=%s error=%s", user, e)
                except Exception:
                    pass
                continue

        save_state(state)

    except Exception as e:
        try:
            app.logger.warning("[AUTOMATIONS engine_tick] fatal error: %s", e)
        except Exception:
            pass

def _normalize_flow_for_user(flow: Dict[str, Any], user: str) -> Dict[str, Any]:
    f = dict(flow or {})
    f["id"] = str(f.get("id") or uuid4())
    f["owner"] = (user or "").lower()
    f["name"] = str(f.get("name") or "Untitled Flow")[:160]
    f["enabled"] = bool(f.get("enabled", False))

    trigger = f.get("trigger") or {}
    if not isinstance(trigger, dict):
        trigger = {}
    trigger["type"] = str(trigger.get("type") or "")
    f["trigger"] = trigger

    steps = f.get("steps") or []
    if not isinstance(steps, list):
        steps = []
    f["steps"] = steps

    caps = f.get("caps") or {}
    if not isinstance(caps, dict):
        caps = {}
    f["caps"] = {
        "per_lead_per_day": int(caps.get("per_lead_per_day", 1) or 1),
        "respect_quiet_hours": caps.get("respect_quiet_hours", True) is not False,
    }

    f["auto_stop_on_reply"] = f.get("auto_stop_on_reply", True) is not False
    return f


def _walk_automation_steps(steps: Any, prefix: str = ""):
    for index, step in enumerate(steps if isinstance(steps, list) else []):
        if not isinstance(step, dict):
            continue
        label = f"{prefix}step {index + 1}"
        yield label, step
        nested = step.get("then")
        if isinstance(nested, list):
            yield from _walk_automation_steps(nested, f"{label} -> ")


def validate_flow_whatsapp_templates(flow: Dict[str, Any]) -> List[str]:
    """Server-side activation validation so invalid template flows never go live."""
    whatsapp_steps = [
        (label, step)
        for label, step in _walk_automation_steps(flow.get("steps") or [])
        if step.get("type") == "send_whatsapp"
    ]
    if not whatsapp_steps:
        return []

    try:
        waba_id = wa_resolve_waba_id()
        response = wa_fetch_templates_for_waba(waba_id)
        if not getattr(response, "ok", False):
            return ["WhatsApp templates could not be verified with Meta. Try again before activating the flow."]
        items = (response.json() or {}).get("data", []) or []
    except Exception as exc:
        return [f"WhatsApp templates could not be verified: {exc}"]

    catalog = [wa_extract_template_metadata(item) for item in items]
    errors: List[str] = []

    for label, step in whatsapp_steps:
        config = step.get("template") or {}
        name = str(config.get("name") or step.get("template_name") or "").strip()
        requested = wa_normalize_lang(
            config.get("language") or os.getenv("WHATSAPP_TEMPLATE_LANG", "en")
        )

        if not name:
            errors.append(f"{label}: select an approved WhatsApp template fallback.")
            continue

        candidates = [
            meta for meta in catalog
            if meta.get("name") == name and meta.get("status") == "APPROVED"
        ]
        exact = next(
            (meta for meta in candidates if meta.get("normalized_language") == requested),
            None,
        )
        same_primary = next(
            (
                meta for meta in candidates
                if wa_primary_lang(meta.get("normalized_language") or "")
                == wa_primary_lang(requested)
            ),
            None,
        )
        selected = exact or same_primary or (candidates[0] if candidates else None)

        if not selected:
            errors.append(f"{label}: template '{name}' is missing or not approved.")
            continue

        if not selected.get("supported_by_automations", True):
            errors.append(
                f"{label}: template '{name}' requires "
                f"{selected.get('unsupported_reason') or 'unsupported dynamic components'}."
            )
            continue

        expected = int(selected.get("body_param_count") or 0)
        raw_params = config.get("params")
        if isinstance(raw_params, list):
            supplied = [str(value).strip() if value is not None else "" for value in raw_params]
        elif isinstance(raw_params, str) and raw_params.strip():
            supplied = [value.strip() for value in raw_params.split(",")]
        else:
            supplied = []

        if supplied and len(supplied) != expected:
            errors.append(
                f"{label}: template '{name}' expects {expected} body parameter(s), "
                f"but the flow contains {len(supplied)}."
            )
            continue

        if supplied and any(not value for value in supplied):
            errors.append(f"{label}: complete every parameter mapping for template '{name}'.")
            continue

        if not supplied and expected > 4:
            errors.append(
                f"{label}: template '{name}' expects {expected} parameters. "
                "Map them explicitly before activation."
            )

    return errors

automations_bp = Blueprint("automations", __name__)

@automations_bp.before_request
def _bf_ensure_files():
    ensure_files()

@automations_bp.route("/health", methods=["GET"])
def automations_health():
    return jsonify({"ok": True, "message": "automations alive"})

def _automation_history_for_user(user: str):
    flows = load_user_flows(user)
    flow_map = {str(flow.get("id")): flow for flow in flows if isinstance(flow, dict)}
    leads = {str(lead.get("id")): lead for lead in (load_leads().get(user, []) or []) if isinstance(lead, dict)}
    state = load_state()
    rows = []
    for flow_id, runs in (state.items() if isinstance(state, dict) else []):
        flow = flow_map.get(str(flow_id))
        if not flow or not isinstance(runs, dict):
            continue
        for lead_id, run in runs.items():
            if not isinstance(run, dict):
                continue
            lead = leads.get(str(lead_id), {})
            events = run.get("events") if isinstance(run.get("events"), list) else []
            rows.append({
                "id": f"{flow_id}:{lead_id}", "flow_id": str(flow_id), "flow_name": flow.get("name") or "Untitled flow",
                "lead_id": str(lead_id), "lead_name": lead.get("name") or lead.get("email") or "Unknown contact", "lead_email": lead.get("email") or "",
                "status": "failed" if run.get("error") else ("completed" if run.get("done") else "running"),
                "created_at": run.get("created_at"), "last_run": run.get("last_step_at") or run.get("created_at"),
                "completed_at": run.get("completed_at"), "current_step": int(run.get("step") or 0),
                "messages_sent": len([event for event in events if "send" in str(event.get("label") or "").lower()]),
                "replies_received": len([event for event in events if event.get("type") == "reply"]),
                "failure_reason": run.get("error") or "", "events": events[-50:],
            })
    rows.sort(key=lambda row: str(row.get("last_run") or ""), reverse=True)
    return rows

@automations_bp.get("/dashboard")
def automation_dashboard():
    user = user_from_request()
    flows = load_user_flows(user)
    history = _automation_history_for_user(user)
    return jsonify({
        "ok": True,
        "summary": {
            "flows": len(flows), "active_flows": len([flow for flow in flows if flow.get("enabled")]),
            "leads_entered": len(history), "completed": len([row for row in history if row["status"] == "completed"]),
            "running": len([row for row in history if row["status"] == "running"]), "failed": len([row for row in history if row["status"] == "failed"]),
            "messages_sent": sum(row["messages_sent"] for row in history), "replies": sum(row["replies_received"] for row in history),
            "next_evaluation": (now_utc() + _td(minutes=15)).isoformat(),
        }
    })

@automations_bp.get("/history")
def automation_history():
    user = user_from_request()
    rows = _automation_history_for_user(user)
    flow_id = str(request.args.get("flow_id") or "")
    status = str(request.args.get("status") or "")
    if flow_id:
        rows = [row for row in rows if row["flow_id"] == flow_id]
    if status:
        rows = [row for row in rows if row["status"] == status]
    limit = min(max(int(request.args.get("limit") or 100), 1), 500)
    return jsonify({"ok": True, "history": rows[:limit]}), 200

@automations_bp.post("/history/<flow_id>/<lead_id>/retry")
def retry_automation_run(flow_id, lead_id):
    user = user_from_request()
    if not any(str(flow.get("id")) == str(flow_id) for flow in load_user_flows(user)):
        return jsonify({"error": "Flow not found."}), 404
    state = load_state()
    run = (state.get(str(flow_id)) or {}).get(str(lead_id))
    if not isinstance(run, dict):
        return jsonify({"error": "Run not found."}), 404
    run["error"] = ""; run["done"] = False
    automation_event(run, "retry", "Run queued for retry")
    save_state(state)
    return jsonify({"ok": True}), 200

@automations_bp.route("/user/profile", methods=["GET"])
def get_user_profile_route():
    user = user_from_request()
    prof = load_user_profile(user)
    return jsonify({
        "ok": True,
        "profile": {
            "business_name": prof.get("business_name", ""),
            "booking_link": prof.get("booking_link", ""),
            "quiet_hours_start": prof.get("quiet_hours_start"),
            "quiet_hours_end": prof.get("quiet_hours_end"),
        }
    })

# --- LIVE automation test route ---
@app.route("/api/automations/test-live", methods=["POST", "OPTIONS"])
def automations_test_live():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        user_email = (
            request.headers.get("X-User-Email")
            or request.headers.get("x-user-email")
            or ""
        ).strip().lower()

        data = request.get_json(silent=True) or {}
        lead_email = (data.get("lead_email") or data.get("leadEmail") or "").strip().lower()
        flow = data.get("flow") or {}
        ignore_waits = bool(data.get("ignore_waits", True))
        ignore_quiet_hours = bool(data.get("ignore_quiet_hours", True))
        bypass_rate_limits = bool(data.get("bypass_rate_limits", True))

        if not user_email:
            return jsonify({"ok": False, "error": "missing_user_email"}), 400

        if not lead_email:
            return jsonify({"ok": False, "error": "missing_lead_email"}), 400

        if not isinstance(flow, dict) or not flow:
            return jsonify({"ok": False, "error": "missing_flow"}), 400

        all_leads = load_leads() or {}
        user_leads = all_leads.get(user_email, []) or []

        lead = None
        for item in user_leads:
            if (item.get("email") or "").strip().lower() == lead_email:
                lead = item
                break

        if not lead:
            return jsonify({"ok": False, "error": "lead_not_found"}), 404

        profile = load_user_profile(user_email) or {}
        steps = flow.get("steps", []) or []

        run = {
            "step": 0,
            "done": False,
            "started_at": datetime.datetime.utcnow().isoformat() + "Z",
            "events": [],
        }

        caps = flow.get("caps", {"per_lead_per_day": 1, "respect_quiet_hours": True}) or {}
        did = []

        for step in steps:
            step_type = (step.get("type") or "").strip()

            if not step_type:
                continue

            # ignore waits for testing
            if step_type == "wait" and ignore_waits:
                did.append({
                    "type": "wait",
                    "status": "skipped_for_test",
                    "info": {
                        "days": step.get("days", 0),
                        "hours": step.get("hours", 0),
                        "minutes": step.get("minutes", 0),
                    },
                })
                continue

            # direct live execution through your existing step executor
            progressed = execute_step(
                flow=flow,
                step=step,
                lead=lead,
                run=run,
                caps={
                    **caps,
                    "respect_quiet_hours": False if ignore_quiet_hours else caps.get("respect_quiet_hours", True),
                    "per_lead_per_day": 999 if bypass_rate_limits else caps.get("per_lead_per_day", 1),
                },
                profile=profile,
            )

            event = None
            if isinstance(run.get("events"), list) and run["events"]:
                event = run["events"][-1]

            did.append({
                "type": step_type,
                "status": "ok" if progressed else "no_action",
                "info": event or {},
            })

            if progressed:
                advance(run)

        return jsonify({
            "ok": True,
            "mode": "execute",
            "lead_email": lead_email,
            "did": did,
            "run": run,
        }), 200

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)[:500],
        }), 500
        
def _vp_int(v, name):
    if v is None or v == "":
        return None
    try:
        iv = int(v)
        if 0 <= iv <= 23:
            return iv
    except Exception:
        pass
    raise ValueError(f"{name} must be an integer 0-23")

def _vp_url(u):
    if u is None or u == "":
        return None
    if is_valid_url(u):
        return u
    raise ValueError("booking_link must be http(s) URL")

@automations_bp.route("/user/profile", methods=["POST"])
def set_user_profile_route():
    user = user_from_request()
    body = request.get_json(force=True) or {}
    prof = load_user_profile(user)
    try:
        if "business_name" in body:
            bn = str(body.get("business_name") or "").strip()
            prof["business_name"] = bn[:120]
        if "booking_link" in body:
            prof["booking_link"] = _vp_url(body.get("booking_link"))
        if "quiet_hours_start" in body:
            prof["quiet_hours_start"] = _vp_int(body.get("quiet_hours_start"), "quiet_hours_start")
        if "quiet_hours_end" in body:
            prof["quiet_hours_end"] = _vp_int(body.get("quiet_hours_end"), "quiet_hours_end")
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    save_user_profile(user, prof)
    return jsonify({"ok": True, "profile": prof})

def builtin_templates() -> List[Dict[str, Any]]:
    templates = [
        {
            "id": "cold-recovery-7d",
            "name": "Cold Lead Recovery (7-day)",
            "enabled": False,
            "trigger": {"type": "no_reply", "days": 3},
            "steps": [
                {"type": "ai_draft"},
                {"type": "send_whatsapp", "text": "{{last_ai_text}}"},
                {"type": "wait", "days": 2},
                {"type": "if_no_reply", "within_days": 2, "then": [
                    {"type": "send_email", "subject": "We still here?", "html": "<p>Quick check-in â€” want to grab a spot with {{business_name}}? <a href='{{booking_link}}'>Book here</a>.</p>"}
                ]}
            ],
            "caps": {"per_lead_per_day": 1, "respect_quiet_hours": True},
            "auto_stop_on_reply": True
        },
        {
            "id": "no-show-winback",
            "name": "No-Show Winback",
            "enabled": False,
            "trigger": {"type": "appointment_no_show"},
            "steps": [
                {"type": "send_whatsapp", "text": "Sorry we missed you â€” hereâ€™s 10% off to rebook: {{booking_link}}"},
                {"type": "wait", "hours": 48},
                {"type": "if_no_booking", "within_days": 2, "then": [
                    {"type": "send_email", "subject": "Ready to rebook?", "html": "<p>We saved you a spot â€” <a href='{{booking_link}}'>rebook here</a>.</p>"},
                    {"type": "add_tag", "tag": "Needs Attention"}
                ]}
            ],
            "caps": {"per_lead_per_day": 1, "respect_quiet_hours": True},
            "auto_stop_on_reply": True
        },
        {
            "id": "new-lead-nurture-3touch",
            "name": "New Lead Nurture (3-touch)",
            "enabled": False,
            "trigger": {"type": "new_lead", "within_hours": 24},
            "steps": [
                {"type": "send_whatsapp", "text": "Welcome! Iâ€™m from {{business_name}} â€” can I help you book? {{booking_link}}"},
                {"type": "wait", "hours": 24},
                {"type": "if_no_reply", "within_days": 2, "then": [
                    {"type": "send_email", "subject": "Welcome!", "html": "<p>Quick intro â€” hereâ€™s the booking link: <a href='{{booking_link}}'>Book now</a>.</p>"}
                ]},
                {"type": "wait", "hours": 48},
                {"type": "push_owner", "title": "Give them a quick call", "message": "New lead may need a call"}
            ],
            "caps": {"per_lead_per_day": 1, "respect_quiet_hours": True},
            "auto_stop_on_reply": True
        }
    ]
    industry_templates = [
        ("salon-rebook", "Salon · Rebook after service", "no_reply", "Ready for your next appointment? Book with {{business_name}} here: {{booking_link}}"),
        ("salon-review", "Salon · Review request", "no_reply", "Thanks for visiting {{business_name}}. We would love to hear how your appointment went."),
        ("salon-lapsed", "Salon · Lapsed client recovery", "no_reply", "We miss seeing you at {{business_name}}. Choose a time that works for you: {{booking_link}}"),
        ("home-quote", "Home services · Quote follow-up", "no_reply", "Just checking whether you had any questions about your quote from {{business_name}}."),
        ("home-missed-call", "Home services · Missed-call follow-up", "new_lead", "Sorry we missed your call. How can {{business_name}} help today?"),
        ("home-review", "Home services · Job-completion review", "no_reply", "Thanks for choosing {{business_name}}. How did everything go?"),
        ("coaching-discovery", "Coaching · Discovery-call follow-up", "new_lead", "Thanks for connecting with {{business_name}}. Your next step is here: {{booking_link}}"),
        ("coaching-renewal", "Coaching · Package renewal", "no_reply", "Ready to continue your progress with {{business_name}}? Book your next session: {{booking_link}}"),
        ("coaching-checkin", "Coaching · Client check-in", "no_reply", "A quick check-in from {{business_name}}: how are things going this week?"),
    ]
    for template_id, name, trigger_type, message in industry_templates:
        templates.append({
            "id": template_id, "name": name, "enabled": False,
            "trigger": {"type": trigger_type, **({"within_hours": 24} if trigger_type == "new_lead" else {"days": 7})},
            "steps": [{"type": "send_whatsapp", "text": message}, {"type": "wait", "days": 2}, {"type": "push_owner", "title": "Follow up personally", "message": "This customer may benefit from a personal check-in."}],
            "caps": {"per_lead_per_day": 1, "respect_quiet_hours": True}, "auto_stop_on_reply": True,
        })
    return templates

def _flow_actions_preview(flow: Dict[str, Any], lead: Dict[str, Any], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    run = {
        "step": 0,
        "created_at": now_utc().isoformat(),
        "last_step_at": None,
        "done": False,
        "last_sent": {},
        "memo": {},
    }
    caps = flow.get("caps", {"per_lead_per_day": 1, "respect_quiet_hours": True}) or {}
    out = []

    for step in (flow.get("steps") or []):
        kind = step.get("type")

        if kind == "ai_draft":
            text = ai_draft_message({
                "lead": lead,
                "flow": flow,
                "business_name": profile.get("business_name"),
                "booking_link": profile.get("booking_link"),
            })
            run.setdefault("memo", {})["last_ai_text"] = text
            out.append({
                "type": "ai_draft",
                "info": {"text": text},
                "status": "would_run",
            })
            continue

        if kind == "wait":
            out.append({
                "type": "wait",
                "info": {
                    "days": step.get("days", 0),
                    "hours": step.get("hours", 0),
                    "minutes": step.get("minutes", 0),
                },
                "status": "would_wait",
            })
            continue

        if kind == "send_whatsapp":
            body = render_text(step.get("text") or run.get("memo", {}).get("last_ai_text") or "", lead, run, profile)
            info = {"text": body, "to": lead.get("phone") or lead.get("whatsapp") or ""}
            template_cfg = step.get("template") or {}
            if template_cfg:
                info["template"] = template_cfg
            out.append({
                "type": "send_whatsapp",
                "info": info,
                "status": "would_send",
            })
            continue

        if kind == "send_email":
            subject = render_text(step.get("subject") or "Quick check-in", lead, run, profile)
            html = render_text(
                step.get("html") or step.get("body") or "<p>Hi {{lead.first_name}}, just checking in. <a href='{{booking_link}}'>Book here</a>.</p>",
                lead,
                run,
                profile,
            )
            html = html.replace("\n", "<br>")
            out.append({
                "type": "send_email",
                "info": {
                    "to": lead.get("email") or "",
                    "subject": subject,
                    "html": html,
                },
                "status": "would_send",
            })
            continue

        if kind == "push_owner":
            out.append({
                "type": "push_owner",
                "info": {
                    "title": step.get("title") or "Lead to call",
                    "message": step.get("message") or str(lead.get("email") or ""),
                },
                "status": "would_push",
            })
            continue

        if kind == "add_tag":
            out.append({
                "type": "add_tag",
                "info": {"tag": step.get("tag") or ""},
                "status": "would_add",
            })
            continue

        if kind == "if_no_reply":
            nested = step.get("then") or []
            out.append({
                "type": "if_no_reply",
                "info": {"within_days": int(step.get("within_days", 2))},
                "status": "branch_check",
            })
            for s in nested:
                nested_kind = s.get("type")
                if nested_kind == "send_email":
                    subject = render_text(s.get("subject") or "Quick check-in", lead, run, profile)
                    html = render_text(
                        s.get("html") or s.get("body") or "",
                        lead,
                        run,
                        profile,
                    ).replace("\n", "<br>")
                    out.append({
                        "type": "send_email",
                        "info": {"to": lead.get("email") or "", "subject": subject, "html": html},
                        "status": "would_send",
                    })
                elif nested_kind == "send_whatsapp":
                    txt = render_text(s.get("text") or run.get("memo", {}).get("last_ai_text") or "", lead, run, profile)
                    out.append({
                        "type": "send_whatsapp",
                        "info": {"to": lead.get("phone") or lead.get("whatsapp") or "", "text": txt},
                        "status": "would_send",
                    })
                elif nested_kind == "wait":
                    out.append({
                        "type": "wait",
                        "info": {
                            "days": s.get("days", 0),
                            "hours": s.get("hours", 0),
                            "minutes": s.get("minutes", 0),
                        },
                        "status": "would_wait",
                    })
            continue

        if kind == "if_no_booking":
            nested = step.get("then") or []
            out.append({
                "type": "if_no_booking",
                "info": {"within_days": int(step.get("within_days", 2))},
                "status": "branch_check",
            })
            for s in nested:
                nested_kind = s.get("type")
                if nested_kind == "send_email":
                    subject = render_text(s.get("subject") or "Quick check-in", lead, run, profile)
                    html = render_text(
                        s.get("html") or s.get("body") or "",
                        lead,
                        run,
                        profile,
                    ).replace("\n", "<br>")
                    out.append({
                        "type": "send_email",
                        "info": {"to": lead.get("email") or "", "subject": subject, "html": html},
                        "status": "would_send",
                    })
                elif nested_kind == "send_whatsapp":
                    txt = render_text(s.get("text") or run.get("memo", {}).get("last_ai_text") or "", lead, run, profile)
                    out.append({
                        "type": "send_whatsapp",
                        "info": {"to": lead.get("phone") or lead.get("whatsapp") or "", "text": txt},
                        "status": "would_send",
                    })
                elif nested_kind == "add_tag":
                    out.append({
                        "type": "add_tag",
                        "info": {"tag": s.get("tag") or ""},
                        "status": "would_add",
                    })
            continue

    return out


def _find_lead_for_test(user: str, lead_email: str) -> Optional[Dict[str, Any]]:
    leads_by_user = load_leads()
    arr = leads_by_user.get(user, []) or []
    target = (lead_email or "").strip().lower()

    for ld in arr:
        if (ld.get("email") or "").strip().lower() == target:
            return ld

    return None

@automations_bp.route("/test", methods=["POST"])
def automations_test_route():
    user = user_from_request()
    body = request.get_json(force=True) or {}

    mode = (body.get("mode") or "dryrun").strip().lower()
    lead_email = (body.get("lead_email") or "").strip().lower()

    if not lead_email:
        return jsonify({"ok": False, "error": "lead_email is required"}), 400

    lead = _find_lead_for_test(user, lead_email)
    if not lead:
        return jsonify({"ok": False, "error": "Lead not found for this user"}), 404

    profile = load_user_profile(user)

    flow = body.get("flow")
    if not flow:
        flow_id = body.get("flow_id")
        if not flow_id:
            return jsonify({"ok": False, "error": "flow or flow_id is required"}), 400
        flows = load_user_flows(user)
        flow = next((f for f in flows if f.get("id") == flow_id), None)
        if not flow:
            return jsonify({"ok": False, "error": "flow not found"}), 404

    flow = _normalize_flow_for_user(flow, user)

    if mode == "dryrun":
        would = _flow_actions_preview(flow, lead, profile)
        return jsonify({"ok": True, "mode": "dryrun", "would": would})

    if mode == "execute":
        run = {
            "step": 0,
            "created_at": now_utc().isoformat(),
            "last_step_at": None,
            "done": False,
            "last_sent": {},
            "memo": {},
        }
        caps = flow.get("caps", {"per_lead_per_day": 1, "respect_quiet_hours": True}) or {}
        did = []

        for step in (flow.get("steps") or []):
            kind = step.get("type")

            if kind == "wait" and body.get("ignore_waits", True):
                did.append({
                    "type": "wait",
                    "status": "skipped",
                    "info": {"reason": "ignore_waits"},
                })
                continue

            if kind == "ai_draft":
                text = ai_draft_message({
                    "lead": lead,
                    "flow": flow,
                    "business_name": profile.get("business_name"),
                    "booking_link": profile.get("booking_link"),
                })
                run.setdefault("memo", {})["last_ai_text"] = text
                did.append({
                    "type": "ai_draft",
                    "status": "ok",
                    "info": {"text": text},
                })
                continue

            if kind == "send_whatsapp":
                txt = render_text(step.get("text") or run.get("memo", {}).get("last_ai_text") or "", lead, run, profile)
                did.append({
                    "type": "send_whatsapp",
                    "status": "ok",
                    "info": {
                        "to": lead.get("phone") or lead.get("whatsapp") or lead_email,
                        "text": txt,
                        "template": step.get("template") or {},
                    },
                })
                continue

            if kind == "send_email":
                subject = render_text(step.get("subject") or "Quick check-in", lead, run, profile)
                html = render_text(
                    step.get("html") or step.get("body") or "",
                    lead,
                    run,
                    profile,
                ).replace("\n", "<br>")
                did.append({
                    "type": "send_email",
                    "status": "ok",
                    "info": {
                        "to": lead.get("email") or lead_email,
                        "subject": subject,
                        "html": html,
                    },
                })
                continue

            if kind == "push_owner":
                did.append({
                    "type": "push_owner",
                    "status": "ok",
                    "info": {
                        "title": step.get("title") or "Lead to call",
                        "message": step.get("message") or "",
                    },
                })
                continue

            if kind == "add_tag":
                did.append({
                    "type": "add_tag",
                    "status": "ok",
                    "info": {"tag": step.get("tag") or ""},
                })
                continue

            if kind in ("if_no_reply", "if_no_booking"):
                nested = step.get("then") or []
                for s in nested:
                    nk = s.get("type")
                    if nk == "send_email":
                        subject = render_text(s.get("subject") or "Quick check-in", lead, run, profile)
                        html = render_text(
                            s.get("html") or s.get("body") or "",
                            lead,
                            run,
                            profile,
                        ).replace("\n", "<br>")
                        did.append({
                            "type": "send_email",
                            "status": "ok",
                            "info": {
                                "to": lead.get("email") or lead_email,
                                "subject": subject,
                                "html": html,
                            },
                        })
                    elif nk == "send_whatsapp":
                        txt = render_text(s.get("text") or run.get("memo", {}).get("last_ai_text") or "", lead, run, profile)
                        did.append({
                            "type": "send_whatsapp",
                            "status": "ok",
                            "info": {
                                "to": lead.get("phone") or lead.get("whatsapp") or lead_email,
                                "text": txt,
                            },
                        })
                    elif nk == "add_tag":
                        did.append({
                            "type": "add_tag",
                            "status": "ok",
                            "info": {"tag": s.get("tag") or ""},
                        })
                continue

        return jsonify({"ok": True, "mode": "execute", "did": did})

    return jsonify({"ok": False, "error": "invalid mode"}), 400


@automations_bp.route("/run", methods=["POST"])
def automations_run_once_route():
    engine_tick()
    return jsonify({"ok": True, "message": "engine_tick completed"})

@automations_bp.route("/templates", methods=["GET"])
def automations_templates():
    return jsonify({"ok": True, "templates": builtin_templates()})

@automations_bp.route("/wa/templates", methods=["GET"])
def list_wa_templates():
    try:
        waba_id = wa_resolve_waba_id()
        r = wa_fetch_templates_for_waba(waba_id)
    except Exception as exc:
        return jsonify({
            "ok": False,
            "templates": [],
            "error": f"Unable to resolve WhatsApp templates: {exc}",
        }), 503

    if not getattr(r, "ok", False):
        try:
            details = r.json()
        except Exception:
            details = {"raw": getattr(r, "text", "")}
        return jsonify({
            "ok": False,
            "templates": [],
            "error": "WhatsApp templates are unavailable.",
            "details": details,
        }), 503

    data = r.json() or {}
    items = data.get("data", []) or []
    templates = [
        wa_extract_template_metadata(template)
        for template in items
        if str(template.get("status") or "").upper() == "APPROVED"
    ]
    templates.sort(
        key=lambda item: f"{item.get('name','')}-{item.get('normalized_language','')}".lower()
    )
    return jsonify({
        "ok": True,
        "waba_id": waba_id,
        "templates": templates,
        "count": len(templates),
    })

@automations_bp.route("/", methods=["GET"])
def list_flows_route():
    user = user_from_request()
    flows = [_normalize_flow_for_user(f, user) for f in load_user_flows(user)]
    save_user_flows(user, flows)
    return jsonify({"ok": True, "flows": flows})

@automations_bp.route("/", methods=["POST"])
def create_flow_route():
    user = user_from_request()
    body = request.get_json(force=True) or {}
    flow = _normalize_flow_for_user(body.get("flow", {}) or {}, user)
    if flow.get("enabled"):
        validation_errors = validate_flow_whatsapp_templates(flow)
        if validation_errors:
            return jsonify({
                "ok": False,
                "error": "Flow cannot be activated until its WhatsApp templates are valid.",
                "validation_errors": validation_errors,
            }), 422
    flows = load_user_flows(user)
    flows.append(flow)
    save_user_flows(user, flows)
    return jsonify({"ok": True, "flow": flow})

@automations_bp.route("/<flow_id>", methods=["PUT"])
def update_flow_route(flow_id):
    user = user_from_request()
    body = request.get_json(force=True) or {}
    incoming = body.get("flow", {}) or {}
    flows = load_user_flows(user)

    for i, f in enumerate(flows):
        if f.get("id") == flow_id:
            merged = {**f, **incoming}
            merged["id"] = flow_id
            merged["owner"] = user
            merged = _normalize_flow_for_user(merged, user)
            if merged.get("enabled"):
                validation_errors = validate_flow_whatsapp_templates(merged)
                if validation_errors:
                    return jsonify({
                        "ok": False,
                        "error": "Flow cannot be activated until its WhatsApp templates are valid.",
                        "validation_errors": validation_errors,
                    }), 422
            flows[i] = merged
            save_user_flows(user, flows)
            return jsonify({"ok": True, "flow": merged})

    return jsonify({"ok": False, "error": "not_found"}), 404

@automations_bp.route("/enable/<flow_id>", methods=["POST"])
def enable_flow_route(flow_id):
    user = user_from_request()
    body = request.get_json(force=True) or {}
    enabled = bool(body.get("enabled", True))
    flows = load_user_flows(user)

    for i, f in enumerate(flows):
        if f.get("id") == flow_id:
            f["enabled"] = enabled
            flows[i] = _normalize_flow_for_user(f, user)
            if enabled:
                validation_errors = validate_flow_whatsapp_templates(flows[i])
                if validation_errors:
                    return jsonify({
                        "ok": False,
                        "error": "Flow cannot be activated until its WhatsApp templates are valid.",
                        "validation_errors": validation_errors,
                    }), 422
            save_user_flows(user, flows)
            return jsonify({"ok": True, "flow": flows[i]})

    return jsonify({"ok": False, "error": "not_found"}), 404

@automations_bp.route("/<flow_id>", methods=["DELETE"])
def delete_flow_route(flow_id):
    user = user_from_request()
    flows = load_user_flows(user)
    flows = [f for f in flows if f.get("id") != flow_id]
    save_user_flows(user, flows)

    state = load_state()
    if flow_id in state:
      state.pop(flow_id, None)
      save_state(state)

    return jsonify({"ok": True})

if "automations" not in getattr(app, "blueprints", {}):
    app.register_blueprint(automations_bp, url_prefix="/api/automations")

# ----------------------------
# VAPID Push â€” persisted subscriptions
# ----------------------------
@app.route("/api/vapid-public-key", methods=["GET"])
def get_vapid_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})

def subs_load() -> Dict[str, Any]:
    ensure_files()
    data = read_json(FILE_SUBSCRIPTIONS, {"subscriptions": {}})
    return (data.get("subscriptions") or {})

def subs_save(subs: Dict[str, Any]):
    ensure_files()
    write_json(FILE_SUBSCRIPTIONS, {"subscriptions": subs})

@app.route("/api/save-subscription", methods=["POST"])
def save_subscription():
    ensure_files()
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    subscription = data.get("subscription")
    if not email or not subscription:
        return jsonify({"error": "Email and subscription required"}), 400

    subs = subs_load()
    subs[email] = subscription
    subs_save(subs)
    return jsonify({"message": "Subscription saved"}), 200


# ----------------------------
# Blueprints (import AFTER helpers)
# ----------------------------
from app_imports import imports_bp
from app_team import team_bp
from app_owner import owner_bp
from app_account import account_bp
from app_wa_auto_appointments import WA_AUTO_BP

app.register_blueprint(imports_bp)
app.register_blueprint(team_bp)
app.register_blueprint(owner_bp)
app.register_blueprint(account_bp)
app.register_blueprint(WA_AUTO_BP)


# ----------------------------
# JSON 404 for /api/*
# ----------------------------
@app.errorhandler(404)
def json_404(err):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not_found", "path": request.path}), 404
    return err


# ----------------------------
# Scheduler setup (safe + once)
# ----------------------------
scheduler = APScheduler()
scheduler.init_app(app)

scheduler.add_job(
    id="automations_tick",
    func=engine_tick,
    trigger="interval",
    minutes=10,
    replace_existing=True
)

def create_daily_platform_backup():
    from app_owner import _backup_files
    path, manifest = _backup_files()
    print(f"[BACKUP] Created {path} with {len(manifest.get('files') or [])} files")


def _start_scheduler_once():
    try:
        if scheduler.running:
            return

        scheduler.add_job(
            id="lead_reminders",
            func=check_for_lead_reminders,
            trigger="interval",
            hours=6,
            replace_existing=True
        )

        scheduler.add_job(
            id="birthdays",
            func=send_birthday_greetings,
            trigger="cron",
            hour=9,
            minute=5,
            replace_existing=True
        )

        scheduler.add_job(
            id="trial_ending",
            func=send_trial_ending_soon,
            trigger="cron",
            hour=9,
            minute=10,
            replace_existing=True
        )

        scheduler.add_job(
            id="post_appointment_update_prompts",
            func=send_post_appointment_update_prompts,
            trigger="interval",
            minutes=15,
            replace_existing=True
        )

        scheduler.add_job(
            id="daily_platform_backup",
            func=create_daily_platform_backup,
            trigger="cron",
            hour=3,
            minute=20,
            replace_existing=True
        )

        scheduler.start()
        print("[Scheduler] started")

    except Exception as e:
        print("[Scheduler] failed to start:", e)

SCHEDULER_ENABLED = (os.getenv("RUN_SCHEDULER", "0") == "1")

@app.before_request
def _bootstrap_scheduler():
    if not SCHEDULER_ENABLED:
        return
    if not app.config.get("BOOTSTRAP_DONE"):
        app.config["BOOTSTRAP_DONE"] = True
        _start_scheduler_once()

# ----------------------------
# Run local
# ----------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)

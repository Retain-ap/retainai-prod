# app.py (CONSOLIDATED + PROD-SAFE) — PART 1/2
import os
import re
import json
import time
import base64
import hmac
import hashlib
import datetime
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

from flask import Flask, request, jsonify, send_from_directory, redirect, current_app, Blueprint
from flask_cors import CORS
from dotenv import load_dotenv
from flask_apscheduler import APScheduler

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email

from google.oauth2 import id_token
from google.auth.transport import requests as grequests

from storage import (
    load_users, save_users, get_user, create_user,
    load_leads, save_leads, migrate_json_to_sqlite_if_needed,
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

# Cookies: secure in prod (Render/https), relax in local dev
IS_LOCAL = (
    os.getenv("FLASK_ENV", "").lower() == "development"
    or any("localhost" in origin for origin in ALLOWED)
)

app.config.update(
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=not IS_LOCAL,
)

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
INBOUND_REPLY_DOMAIN = (os.getenv("INBOUND_REPLY_DOMAIN") or "reply.retainai.ca").strip().lower()
STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
STRIPE_PRICE_ID = (os.getenv("STRIPE_PRICE_ID") or "").strip()
STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
STRIPE_CONNECT_CLIENT_ID = (os.getenv("STRIPE_CONNECT_CLIENT_ID") or "").strip()
STRIPE_REDIRECT_URI = (os.getenv("STRIPE_REDIRECT_URI") or "").strip()

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")

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
    tmp = file_path + ".tmp"
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

def load_statuses():
    return _legacy_load_json(STATUS_FILE)

def save_statuses(data):
    _legacy_save_json(STATUS_FILE, data)


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
# /api/profile (SINGLE SOURCE OF TRUTH) — FIXED (no duplicates)
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
        "role": role,
        "orgOwnerEmail": org_email,

        "canInviteTeam": role == "owner",
        "canEditBusiness": role == "owner",
        "canManageBilling": role == "owner",
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
            "role": role,
            "orgOwnerEmail": org_email,
            "canInviteTeam": role == "owner",
            "canEditBusiness": role == "owner",
            "canManageBilling": role == "owner",
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

@app.route("/api/profile/debug", methods=["GET"])
def api_profile_debug():
    email = (request.args.get("email") or "").strip().lower()
    ok = True
    msg = "ok"
    u = None
    try:
        u = get_user(email) if email else None
    except Exception as ex:
        ok = False
        msg = f"get_user raised: {ex}"

    return jsonify({
        "ok": ok,
        "message": msg,
        "email": email,
        "USE_SQLITE": bool(USE_SQLITE),
        "SQLITE_PATH": SQLITE_PATH,
        "DATA_ROOT": DATA_ROOT,
        "exists": bool(u) if email else None,
        "user_sample": _json_sanitize(u) if (ok and u) else None
    }), 200 if ok else 500


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
def create_ics_file(appt):
    uid = appt.get("id")
    dt_start = datetime.datetime.strptime(appt["appointment_time"], "%Y-%m-%dT%H:%M:%S")
    dt_end = dt_start + datetime.timedelta(minutes=int(appt.get("duration", 30)))
    summary = f"Appointment with {appt['user_name']} at {appt['business_name']}"
    description = f"Appointment at {appt['appointment_location']} with {appt['user_name']}"
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//RetainAI//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{dt_start.strftime("%Y%m%dT%H%M%SZ")}
DTSTART:{dt_start.strftime("%Y%m%dT%H%M%SZ")}
DTEND:{dt_end.strftime("%Y%m%dT%H%M%SZ")}
SUMMARY:{summary}
DESCRIPTION:{description}
LOCATION:{appt['appointment_location']}
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
    start_str = dt_start.strftime("%Y%m%dT%H%M%SZ")
    end_str = dt_end.strftime("%Y%m%dT%H%M%SZ")
    title = f"Appointment with {appt['user_name']} at {appt['business_name']}"
    location = (appt["appointment_location"] or "").replace(" ", "+")
    details = f"Appointment with {appt['user_name']} at {appt['business_name']}."
    return (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={title.replace(' ','+')}"
        f"&dates={start_str}/{end_str}"
        f"&details={details.replace(' ','+')}"
        f"&location={location}"
    )


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

def log_notification(user_email, subject, message, lead_email=None):
    notifications = load_notifications()
    notifications.setdefault(user_email, []).append({
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "subject": subject,
        "message": message,
        "lead_email": lead_email,
        "read": False
    })
    save_notifications(notifications)

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
        lead_list_html += (
            f"<li style='margin-bottom:16px;color:#FFD700;'>"
            f"<span style='font-weight:700;font-size:1.1em;'>{lead.get('name','-')}</span><br>"
            f"<span style='color:#fff;'>Email:</span> <span style='color:#FFD700;'>{lead.get('email','-')}</span><br>"
            f"<span style='color:#fff;'>Last Contacted:</span> <span style='color:#FFD700;'>{format_date(lead.get('last_contacted') or lead.get('createdAt','-'))}</span> "
            f"<span style='color:#b6b6b6;'>&nbsp;({lead.get('days_since_contact', '?')} days ago)</span><br>"
            f"<span style='color:#fff;'>Notes:</span> <span style='color:#FFD700;font-style:italic;'>{lead.get('notes','-')}</span>"
            "</li>"
        )
    lead_list_html += "</ul>"

    dynamic_data = {
        "user_name": user_name,
        "lead_list": lead_list_html,
        "crm_link": f"{FRONTEND_URL}/app/dashboard",
        "year": datetime.datetime.now().year,
        "interval": interval,
        "count": len(warning_leads)
    }
    send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_FOLLOWUP_USER,
        dynamic_data=dynamic_data,
        subject="⚠️ Leads Needing Attention",
        from_email=SENDER_EMAIL
    )

def send_post_appointment_update_email(user_email, user_name, lead_name, business_name, appointment_time):
    display_time = appointment_time
    try:
        dt = datetime.datetime.strptime(appointment_time, "%Y-%m-%dT%H:%M:%S")
        display_time = dt.strftime("%B %d, %Y at %I:%M %p")
    except Exception:
        pass

    crm_link = f"{FRONTEND_URL}/app/dashboard"

    return send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_POST_APPT_UPDATE,
        dynamic_data={
            "user_name": user_name or "",
            "lead_name": lead_name or "your lead",
            "business_name": business_name or "your business",
            "appointment_time": display_time,
            "crm_link": crm_link,
        },
        subject=f"Update your notes for {lead_name or 'your lead'}",
        from_email=SENDER_EMAIL,
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

def send_birthday_reminder_to_user(user_email, user_name, lead_name, business_name, birthday):
    send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_BDAY_REMINDER_USER,
        dynamic_data={"user_name": user_name, "lead_name": lead_name, "business_name": business_name, "birthday": birthday},
        subject=f"Birthday Reminder: {lead_name}'s birthday is tomorrow!",
        from_email="reminder@retainai.ca"
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
                        birthday=bday
                    )
                    log_notification(user_email, f"Reminder: {lead.get('name','')}'s birthday is tomorrow!", "Birthday reminder sent", lead.get("email"))

TRIAL_DAYS = 14

def _within_trial(user: dict, days: int = TRIAL_DAYS) -> bool:
    ts = user.get("trial_start")
    if not ts:
        return False
    try:
        t0 = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return False
    return (datetime.datetime.utcnow() - t0) <= datetime.timedelta(days=days)

def send_trial_ending_email(user_email, user_name, business_name, trial_end_date):
    send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_TRIAL_ENDING,
        dynamic_data={"user_name": user_name, "business_name": business_name, "trial_end_date": trial_end_date},
    )

def send_trial_ending_soon():
    users = load_users() or {}
    if not isinstance(users, dict):
        return

    now = datetime.datetime.utcnow()
    changed = False
    for email, user in users.items():
        trial_start = user.get("trial_start")
        if not trial_start or user.get("status") not in ["pending_payment", "active"]:
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
# LEADS API (PERSISTENT) — KEEP ONLY THIS
# - Frontend uses:
#   GET  /api/leads   (with header X-User-Email)
#   POST /api/leads   (with header X-User-Email, body {leads:[...]})
# - Storage uses load_leads()/save_leads() from storage.py (JSON or SQLite)
# ----------------------------

from flask import request, jsonify

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()

def _req_user_email() -> str:
    # Prefer headers (best for your app). Fallbacks just in case.
    payload = request.get_json(silent=True) or {}
    return _norm_email(
        request.headers.get("X-User-Email")
        or request.args.get("email")
        or payload.get("email")
    )

def _org_is_active(owner_record: dict) -> bool:
    if not owner_record or not isinstance(owner_record, dict):
        return False
    return (owner_record.get("status") == "active") or _within_trial(owner_record, TRIAL_DAYS)

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

        return jsonify({"ok": True, "email": email, "leads": leads}), 200
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
        all_leads = load_leads() or {}
        if not isinstance(all_leads, dict):
            all_leads = {}

        # Save ONLY this user's list (full replace)
        all_leads[email] = leads
        save_leads(all_leads)

        return jsonify({"ok": True, "email": email, "count": len(leads)}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500

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
            leads_by_user[owner_email] = arr
            save_leads(leads_by_user)
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

        send_email_with_template(
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
        )

        add_notification(
            appt.get("user_email", ""),
            "Appointment confirmation sent",
            f"Confirmation email sent to {appt.get('lead_first_name','Client')} for {display_time}.",
            channel="appointment",
            lead_email=appt.get("lead_email", ""),
            extra={"appointment_id": appt.get("id")}
        )

        return True
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
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"

    appt = {
        "id": str(uuid4()),
        "lead_email": data["lead_email"],
        "lead_first_name": data["lead_first_name"],
        "user_name": data["user_name"],
        "user_email": data["user_email"],
        "business_name": data["business_name"],
        "appointment_time": data["appointment_time"],
        "appointment_location": data["appointment_location"],
        "duration": data.get("duration", 30),
        "notes": data.get("notes", ""),
        "status": data.get("status", "scheduled"),
        "lead_id": data.get("lead_id"),
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    appointments = load_appointments() or {}
    if not isinstance(appointments, dict):
        appointments = {}
    appointments.setdefault(user_email, []).append(appt)
    save_appointments(appointments)

    # keep appointment email logic here so every created appointment sends confirmation
    create_ics_file(appt)

    display_time = datetime.datetime.strptime(
        appt["appointment_time"], "%Y-%m-%dT%H:%M:%S"
    ).strftime("%B %d, %Y, %I:%M %p")

    ics_file_url = f"{request.host_url.rstrip('/')}/ics/{appt['id']}.ics"
    google_calendar_link = make_google_calendar_link(appt)

    email_sent = send_email_with_template(
        to_email=appt["lead_email"],
        template_id=SG_TEMPLATE_APPT_CONFIRM,
        dynamic_data={
            "lead_first_name": appt["lead_first_name"],
            "user_name": appt["user_name"],
            "business_name": appt["business_name"],
            "display_time": display_time,
            "appointment_location": appt["appointment_location"],
            "google_calendar_link": google_calendar_link,
            "ics_file_url": ics_file_url,
            "user_email": appt["user_email"],
        }
    )

    add_notification(
        user_email=user_email,
        subject="Appointment created",
        message=f"Appointment booked with {appt.get('lead_first_name') or appt.get('lead_email') or 'lead'} for {display_time}.",
        channel="appointment",
        lead_email=appt.get("lead_email") or "",
        extra={
            "lead_name": appt.get("lead_first_name") or "",
            "appointment_id": appt.get("id"),
            "appointment_time": appt.get("appointment_time"),
            "email_sent": bool(email_sent),
        },
    )

    if email_sent:
        add_notification(
            user_email=user_email,
            subject="Appointment confirmation sent",
            message=f"Confirmation email sent to {appt.get('lead_first_name') or appt.get('lead_email') or 'lead'} for {display_time}.",
            channel="email",
            lead_email=appt.get("lead_email") or "",
            extra={
                "lead_name": appt.get("lead_first_name") or "",
                "appointment_id": appt.get("id"),
                "appointment_time": appt.get("appointment_time"),
            },
        )
    else:
        add_notification(
            user_email=user_email,
            subject="Appointment confirmation failed",
            message=f"Appointment was created, but the confirmation email did not send for {appt.get('lead_first_name') or appt.get('lead_email') or 'lead'}.",
            channel="email",
            lead_email=appt.get("lead_email") or "",
            extra={
                "lead_name": appt.get("lead_first_name") or "",
                "appointment_id": appt.get("id"),
                "appointment_time": appt.get("appointment_time"),
                "error_state": "send_failed",
            },
        )

    return jsonify({
        "message": "Appointment created and confirmation processed!",
        "appointment": appt,
        "confirmation_sent": bool(email_sent),
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
    Return (role, org_owner_email, org_owner_record, subject_record)
    role: "owner" or "member" (or None if not found)
    """
    email = _norm_email(email)
    owner = users.get(email)
    if owner:
        return ("owner", email, owner, owner)

    member = users.get(f"user::{email}")
    if member:
        org_email = _norm_email(member.get("org_id") or "")
        org_owner = users.get(org_email)
        if org_owner:
            return ("member", org_email, org_owner, member)

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

# app.py (CONSOLIDATED + PROD-SAFE) — PART 2/2 (CONTINUATION)

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
          <p><a href="{inv.hosted_invoice_url}">View &amp; pay your invoice →</a></p>
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

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email")
        if email:
            users = load_users() or {}
            if isinstance(users, dict):
                user = users.get(_norm_email(email))
                if user:
                    user["status"] = "active"
                    users[_norm_email(email)] = user
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

    if role == "member":
        base = org_owner
        display_name = subject.get("name", "") or base.get("name", "")
    else:
        base = subject
        display_name = base.get("name", "")

    logo = base.get("logo") or base.get("picture") or ""

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
        "role": role or user.get("role"),
        "org_id": org_email or user.get("org_id"),
        "orgOwnerEmail": org_email,

        "canInviteTeam": role == "owner",
        "canEditBusiness": role == "owner",
        "canManageBilling": role == "owner",
    }

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

    users[email] = {
        "email": email,
        "password": password,
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
        "trial_start": trial_start,
        "trial_ending_notice_sent": False,
    }
    save_users(users)

    try:
        send_email_with_template(
            to_email=email,
            template_id=SG_TEMPLATE_WELCOME,
            dynamic_data={"user_name": name or "", "business_type": businessName or ""},
            from_email="welcome@retainai.ca",
            subject="Welcome to RetainAI"
        )
    except Exception as e:
        print(f"[WARN] Couldn't send welcome email: {e}")

    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        return jsonify({"error": "Billing not configured. Missing STRIPE_SECRET_KEY or STRIPE_PRICE_ID."}), 500

    try:
        success_url = f"{FRONTEND_URL}/login?paid=1&session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url  = f"{FRONTEND_URL}/login?canceled=1"

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            customer_email=email,
            subscription_data={
                "trial_period_days": int(TRIAL_DAYS),
                "metadata": {"user_email": email},
            },
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return jsonify({"checkoutUrl": session.url}), 200

    except stripe.error.StripeError as e:
        print(f"[STRIPE ERROR] {getattr(e, 'user_message', str(e))}")
        return jsonify({"error": "Could not start payment process."}), 500
    except Exception as e:
        print(f"[STRIPE ERROR] {e}")
        return jsonify({"error": "Could not start payment process."}), 500

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = _norm_email(data.get("email"))
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Invalid credentials or account not active"}), 401

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    # 1) Owner login
    user = users.get(email)
    if user:
        allowed = (user.get("password") == password) and (
            (user.get("status") == "active") or _within_trial(user, TRIAL_DAYS)
        )
        if allowed:
            return jsonify({"message": "Login successful", "user": _user_payload(email, user)}), 200

    # 2) Member login with owner's password
    team_key = f"user::{email}"
    team_rec = users.get(team_key)
    if not team_rec:
        return jsonify({"error": "Invalid credentials or account not active"}), 401

    owner_email = _norm_email(team_rec.get("org_id") or "")
    owner_acct = users.get(owner_email) or {}
    owner_pw = owner_acct.get("password", "")
    owner_ok = (owner_acct.get("status") == "active") or _within_trial(owner_acct, TRIAL_DAYS)

    if not (owner_pw and password == owner_pw and owner_ok):
        return jsonify({"error": "Invalid credentials or account not active"}), 401

    member_user = {
        "email": email,
        "name": team_rec.get("name") or (email.split("@")[0].title()),
        "business": owner_acct.get("business", ""),
        "businessType": owner_acct.get("businessType", ""),
        "teamSize": owner_acct.get("teamSize", ""),
        "logo": owner_acct.get("logo") or owner_acct.get("picture") or "",
        "status": "active",
        "role": team_rec.get("role", "member"),
        "org_id": owner_acct.get("org_id") or owner_email,
    }

    return jsonify({"message": "Login successful", "user": _user_payload(email, member_user)}), 200

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

        if changed:
            users[email] = user
            save_users(users)

        if not (user.get("status") == "active" or _within_trial(user, TRIAL_DAYS)):
            return jsonify({"error": "Account not active. Please complete payment to activate."}), 403

        return jsonify({"message": "Google login successful", "user": _user_payload(email, user)}), 200

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
        sub_status = (sub.get("status") if isinstance(sub, dict) else None) or "active"

        if sub_status in ("active", "trialing", "past_due"):
            user["status"] = "active"
            user["stripe_customer_id"] = session_obj.get("customer")
            user["stripe_subscription_id"] = sub.get("id") if isinstance(sub, dict) else sub

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
    email = _norm_email(email)
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
    email = _norm_email(email)
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
    email = _norm_email(email)
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
    email = _norm_email(email)
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
# WhatsApp Cloud API — 24h gate, templates, webhook, etc.
# ============================================================

_TEMPLATE_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_TEMPLATE_TTL_SECONDS = 300

_MSG_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_MSG_CACHE_TTL_SECONDS = 2

_WABA_RES = {"id": None, "checked_at": None}
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


def lead_matches_wa(lead: dict, wa_digits: str) -> bool:
    for key in ("whatsapp", "phone"):
        if wa_norm_number(lead.get(key)) == wa_digits:
            return True
    return False


def find_user_by_whatsapp(wa_id: str) -> Optional[str]:
    wa = wa_norm_number(wa_id)
    leads_by_user = load_leads()
    for user_email, leads in (leads_by_user or {}).items():
        for lead in (leads or []):
            if lead_matches_wa(lead, wa):
                return user_email
    return None


def find_lead_by_whatsapp(wa_id: str) -> Optional[str]:
    wa = wa_norm_number(wa_id)
    leads_by_user = load_leads()
    for _, leads in (leads_by_user or {}).items():
        for lead in (leads or []):
            if lead_matches_wa(lead, wa):
                lid = lead.get("id")
                return str(lid) if lid is not None else None
    return None


def wa_env() -> Tuple[str, str]:
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_ID")
    if not token or not phone_id:
        raise RuntimeError("WhatsApp credentials missing (WHATSAPP_TOKEN / WHATSAPP_PHONE_ID)")
    return token, phone_id


def wa_resolve_waba_id(force: bool = False) -> str:
    now = datetime.datetime.utcnow()
    if (
        not force
        and _WABA_RES["id"]
        and _WABA_RES["checked_at"]
        and (now - _WABA_RES["checked_at"]).total_seconds() < _WABA_TTL_SECONDS
    ):
        return _WABA_RES["id"]

    try:
        token, phone_id = wa_env()
        url = f"https://graph.facebook.com/v20.0/{phone_id}"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"fields": "whatsapp_business_account{id},display_phone_number"}
        r = pyrequests.get(url, headers=headers, params=params, timeout=30)

        wid = None
        if r.ok:
            wid = (((r.json() or {}).get("whatsapp_business_account") or {}).get("id"))

        if not wid:
            wid = os.getenv("WHATSAPP_WABA_ID") or os.getenv("WHATSAPP_BUSINESS_ID", "")

        _WABA_RES["id"] = wid
        _WABA_RES["checked_at"] = now
        return wid

    except Exception as e:
        try:
            app.logger.warning("[WA WABA] resolve error: %s", e)
        except Exception:
            pass
        return os.getenv("WHATSAPP_WABA_ID") or os.getenv("WHATSAPP_BUSINESS_ID", "")


def wa_fetch_templates_for_waba(waba_id: str):
    if not waba_id:
        raise RuntimeError("WhatsApp WABA ID could not be resolved")
    headers = {"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"}
    params = {"fields": "name,language,status,category,components", "limit": 200}
    url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"
    return pyrequests.get(url, headers=headers, params=params, timeout=30)


def wa_fetch_templates_raw():
    waba_id = wa_resolve_waba_id()
    return wa_fetch_templates_for_waba(waba_id)


def wa_lookup_template_status(name: str, lang_api: str, force: bool = False) -> str:
    if not (os.getenv("WHATSAPP_TOKEN") and (os.getenv("WHATSAPP_WABA_ID") or os.getenv("WHATSAPP_PHONE_ID"))):
        return "UNKNOWN"

    normalized_name = (name or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "") or "").strip()
    lang_norm = wa_normalize_lang(lang_api or os.getenv("WHATSAPP_TEMPLATE_LANG", "en") or "")
    key = (normalized_name, lang_norm)

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
        
def wa_send_text(to_number: str, body: str):
    to = wa_norm_number(to_number)
    token, phone_id = wa_env()
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


def wa_send_template(
    to_number: str,
    template_name: str,
    lang_code: str,
    parameters: Optional[List[Any]] = None
):
    to = wa_norm_number(to_number)
    token, phone_id = wa_env()
    ver = os.getenv("WHATSAPP_API_VERSION", "v20.0")
    url = f"https://graph.facebook.com/{ver}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    components = []
    if parameters is not None:
        components = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in parameters]
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
    return jsonify({
        "ok": True,
        "has_token": bool(os.getenv("WHATSAPP_TOKEN")),
        "has_phone_id": bool(os.getenv("WHATSAPP_PHONE_ID")),
        "has_waba_id": bool(os.getenv("WHATSAPP_WABA_ID") or os.getenv("WHATSAPP_BUSINESS_ID")),
        "default_template": os.getenv("WHATSAPP_TEMPLATE_DEFAULT"),
        "default_lang_ui": wa_primary_lang(os.getenv("WHATSAPP_TEMPLATE_LANG", "en")) or "en",
        "default_lang_api": wa_normalize_lang(os.getenv("WHATSAPP_TEMPLATE_LANG", "en")),
    }), 200


@app.get("/api/whatsapp/templates")
def list_templates():
    if not os.getenv("WHATSAPP_TOKEN") or not os.getenv("WHATSAPP_PHONE_ID"):
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
            components = t.get("components") or []
            body_comp = next(
                (c for c in components if str(c.get("type") or "").upper() == "BODY"),
                {}
            )
            body_text = body_comp.get("text") or ""
            matches = re.findall(r"\{\{\s*(\d+)\s*\}\}", body_text)
            body_param_count = max([int(x) for x in matches], default=0)

            return {
                "name": t.get("name"),
                "language": t.get("language"),
                "normalized_language": wa_normalize_lang(t.get("language") or ""),
                "status": (t.get("status") or "").upper(),
                "category": t.get("category"),
                "components": components,
                "body_text": body_text,
                "body_param_count": body_param_count,
            }

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
    msgs = (chats.get(user_email, {}) or {}).get(str(lead_id), []) or []
    _MSG_CACHE[key] = {"at": now, "data": msgs}
    return msgs, False


@app.route("/api/whatsapp/messages", methods=["GET"])
def get_whatsapp_messages():
    user_email = (request.args.get("user_email") or "").strip().lower()
    lead_id = (request.args.get("lead_id") or "").strip()
    msgs, _ = _get_thread_cached(user_email, lead_id)
    return jsonify({"messages": msgs}), 200


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
    leads[user_email] = arr
    save_leads(leads)

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
            return str(v).strip() if v is not None else ""
        except Exception:
            return ""

    to_number = clean(data.get("to") or data.get("phone"))
    raw_msg = clean(data.get("message") or data.get("text"))
    user_email = clean(data.get("user_email")).lower()
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

    waba_id = wa_resolve_waba_id()

    try:
        if inside24:
            if not raw_msg:
                return jsonify({"ok": False, "error": "Message text required inside 24h"}), 400

            resp = wa_send_text(to_number, raw_msg)
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

            r_list = wa_fetch_templates_for_waba(waba_id)
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

            resp = wa_send_template(to_number, template_name, used_lang, params)

            preview_parts = []
            if params:
                preview_parts.append(" | ".join([str(p) for p in params]))
            if raw_msg:
                preview_parts.append(raw_msg)
            preview = " — ".join([p for p in preview_parts if p]).strip()

            sent_text = f"[template:{template_name}/{used_lang}] {preview}".strip()
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
                thread.append({
                    "from": "user",
                    "text": sent_text,
                    "time": datetime.datetime.utcnow().isoformat() + "Z"
                })
                user_chats[str(lead_id)] = thread
                chats[user_email] = user_chats
                save_chats(chats)

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
    secret = os.getenv("APP_SECRET") or os.getenv("META_APP_SECRET")
    if not secret or not header_sig:
        return True
    try:
        if not header_sig.startswith("sha256="):
            return False
        sent = header_sig.split("=", 1)[1]
        mac = hmac.new(secret.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
        return hmac.compare_digest(mac.hexdigest(), sent)
    except Exception:
        return False


@app.route("/api/whatsapp/webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == (os.getenv("WHATSAPP_VERIFY_TOKEN") or ""):
            return request.args.get("hub.challenge") or "Verified", 200
        return "Invalid verification token", 403

    raw = request.get_data()
    header_sig = request.headers.get("X-Hub-Signature-256")
    if not _verify_meta_signature(raw, header_sig):
        return "Signature mismatch", 403

    payload = request.get_json(silent=True) or {}

    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {}) or {}

                # delivery/read statuses
                for status in (value.get("statuses", []) or []):
                    statuses = load_statuses()
                    statuses[status.get("id") or "unknown"] = {
                        "status": status.get("status"),
                        "timestamp": status.get("timestamp"),
                        "recipient": status.get("recipient_id"),
                        "errors": status.get("errors")
                    }
                    save_statuses(statuses)

                # inbound messages
                messages = value.get("messages", []) or []
                contacts = value.get("contacts", []) or []
                sender_waid = contacts[0].get("wa_id") if contacts else None

                for m in messages:
                    t = m.get("type")
                    if t == "text":
                        text = m.get("text", {}).get("body", "")
                    elif t == "interactive":
                        text = str(m.get("interactive"))
                    elif t == "button":
                        text = str(m.get("button"))
                    else:
                        text = f"[{t} message]"

                    # opt-out / opt-in (best-effort)
                    if sender_waid and isinstance(text, str):
                        up = text.strip().upper()

                        if up in ("STOP", "UNSUBSCRIBE", "STOP ALL", "CANCEL"):
                            wa = wa_norm_number(sender_waid)
                            data = load_leads()
                            changed = False
                            for _, leads in (data or {}).items():
                                for ld in (leads or []):
                                    if lead_matches_wa(ld, wa):
                                        ld["wa_opt_out"] = True
                                        changed = True
                            if changed:
                                save_leads(data)
                            try:
                                wa_send_text(sender_waid, "You have been unsubscribed. Reply START to opt back in.")
                            except Exception:
                                pass

                        elif up in ("START", "UNSTOP", "SUBSCRIBE"):
                            wa = wa_norm_number(sender_waid)
                            data = load_leads()
                            changed = False
                            for _, leads in (data or {}).items():
                                for ld in (leads or []):
                                    if lead_matches_wa(ld, wa):
                                        ld["wa_opt_out"] = False
                                        changed = True
                            if changed:
                                save_leads(data)
                            try:
                                wa_send_text(sender_waid, "You are now opted back in. You can reply STOP anytime to opt out.")
                            except Exception:
                                pass

                    user_email = find_user_by_whatsapp(sender_waid) if sender_waid else None
                    lead_id = find_lead_by_whatsapp(sender_waid) if sender_waid else None

                    if not user_email or not lead_id:
                        try:
                            app.logger.warning(
                                "[WA WEBHOOK] inbound from unknown sender waid=%s text=%s",
                                sender_waid,
                                text
                            )
                        except Exception:
                            pass
                        continue

                    chats = load_chats()
                    user_chats = (chats.get(user_email, {}) or {})
                    thread = (user_chats.get(str(lead_id), []) or [])
                    thread.append({
                        "from": "lead",
                        "text": text,
                        "time": datetime.datetime.utcnow().isoformat() + "Z"
                    })
                    user_chats[str(lead_id)] = thread
                    chats[user_email] = user_chats
                    save_chats(chats)

                    _MSG_CACHE[(str(user_email or ""), str(lead_id or ""))] = {
                        "at": datetime.datetime.utcnow(),
                        "data": thread
                    }

                    # notification center hook
                    lead_name = ""
                    lead_email = ""
                    try:
                        leads_by_user = load_leads() or {}
                        for ld in (leads_by_user.get(user_email, []) or []):
                            if str(ld.get("id") or "") == str(lead_id):
                                lead_name = ld.get("name") or ld.get("first_name") or ""
                                lead_email = ld.get("email") or ""
                                break
                    except Exception:
                        pass

                    add_notification(
                        user_email=user_email,
                        subject="WhatsApp received",
                        message=text[:180] if isinstance(text, str) else "New inbound WhatsApp message received.",
                        channel="whatsapp",
                        lead_email=lead_email,
                        extra={
                            "lead_name": lead_name,
                            "type": "inbound",
                        },
                    )

    except Exception as e:
        try:
            app.logger.warning("[WHATSAPP WEBHOOK] parse error: %s", e)
        except Exception:
            pass

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
        f"Instruction: {instruction or '-'}\n"
        f"Most recent inbound: \"{last_message or '-'}\"\n"
        "No sign-offs; one concise, helpful message."
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
# AUTOMATIONS (INLINE) — Blueprint + Engine (prod-ready routes)
# =================================================================
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
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def ensure_files():
    os.makedirs(DATA_ROOT, exist_ok=True)
    if not os.path.exists(FILE_AUTOMATIONS):
        write_json(FILE_AUTOMATIONS, {"users": {}})
    if not os.path.exists(FILE_STATE):
        write_json(FILE_STATE, {})
    if not os.path.exists(FILE_NOTIFICATIONS):
        write_json(FILE_NOTIFICATIONS, {"notifications": []})
    if not os.path.exists(FILE_USERS):
        write_json(FILE_USERS, {"users": {}})
    if not os.path.exists(FILE_SUBSCRIPTIONS):
        write_json(FILE_SUBSCRIPTIONS, {"subscriptions": {}})

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
    write_json(FILE_STATE, state)

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

MISSING = "⛔"

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

def choose_wa_template(preferred_name: Optional[str], preferred_lang: Optional[str]):
    name = (preferred_name or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "")).strip()
    if not name:
        return None, None, 0

    waba_id = wa_resolve_waba_id()
    r_list = wa_fetch_templates_for_waba(waba_id)
    items = (r_list.json() or {}).get("data", []) if getattr(r_list, "ok", False) else []

    requested = wa_normalize_lang(preferred_lang or os.getenv("WHATSAPP_TEMPLATE_LANG", "en"))
    primary = wa_primary_lang(requested)

    locales = []
    for t in items:
        if (t.get("name") or "") == name:
            locales.append({"language": wa_normalize_lang(t.get("language") or ""), "status": (t.get("status") or "").upper()})

    used_lang = requested
    exact = next((x for x in locales if x["language"] == requested and x["status"] == "APPROVED"), None)
    if not exact:
        same_primary = next((x for x in locales if wa_primary_lang(x["language"]) == primary and x["status"] == "APPROVED"), None)
        any_appr = next((x for x in locales if x["status"] == "APPROVED"), None)
        used_lang = (same_primary or any_appr or {"language": requested})["language"]

    body_param_count = 0
    try:
        for t in items:
            if (t.get("name") == name) and (wa_normalize_lang(t.get("language") or "") == used_lang):
                comps = t.get("components") or []
                body = next((c for c in comps if (c.get("type") or "").upper() == "BODY"), {}) or {}
                ex = (body.get("example") or {})
                body_text = None
                if isinstance(ex.get("body_text"), list) and ex.get("body_text"):
                    body_text = ex.get("body_text")[0]
                if isinstance(body_text, str):
                    body_param_count = len(set(re.findall(r"\{\{(\d+)\}\}", body_text)))
                break
    except Exception:
        body_param_count = 0

    return name, used_lang, int(body_param_count or 0)

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

def append_chat_message(user_email: str, lead_id: str, text: str):
    try:
        if not user_email or not lead_id:
            return
        chats = load_chats()
        user_chats = (chats.get(user_email, {}) or {})
        lid = str(lead_id)
        arr = (user_chats.get(lid, []) or [])
        arr.append({"from": "user", "text": text, "time": now_utc().isoformat().replace("+00:00", "") + "Z"})
        user_chats[lid] = arr
        chats[user_email] = user_chats
        save_chats(chats)
        _MSG_CACHE[(str(user_email or ""), str(lead_id or ""))] = {"at": datetime.datetime.utcnow(), "data": arr}
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
            resp = wa_send_text(to, body)
            ok = getattr(resp, "status_code", 500) < 400
        except Exception as e:
            print("[Automations] WA free-text send error:", e)
            ok = False
        if ok:
            mark_sent(run, CHANNEL_WHATSAPP)
            append_chat_message(user_email, lead_id, body)
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
    tpl_name, used_lang, pcount = choose_wa_template(preferred_name, preferred_lang)
    if not tpl_name or not used_lang:
        create_notification(user_email, "WhatsApp template unavailable",
                            "No approved template/locale available to send outside the 24h window.")
        return True

    explicit_params = []
    raw_params = template_cfg.get("params")
    if isinstance(raw_params, str):
        explicit_params = [p.strip() for p in raw_params.split(",")]
    params = explicit_params if explicit_params else build_wa_params(pcount, lead, profile, run, body)
    params = (params + [""] * pcount)[:pcount]

    shown = f"[template:{tpl_name}/{used_lang}] {body}"
    try:
        resp = wa_send_template(to, tpl_name, used_lang, params)
        ok = getattr(resp, "status_code", 500) < 400
    except Exception as e:
        print("[Automations] WA template send error:", e)
        ok = False
    if ok:
        mark_sent(run, CHANNEL_WHATSAPP)
        append_chat_message(user_email, lead_id, shown)
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
        "memo": {}
    })

def advance(run: Dict[str, Any]):
    run["step"] = int(run.get("step", 0)) + 1
    run["last_step_at"] = now_utc().isoformat()

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
        return f"Hey {lead_name}, just checking in — want to grab a spot with {business_name}? Book here: {booking}."
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
        return (txt or f"Quick check-in — want to grab a spot with {business_name}? {booking}").strip()
    except Exception as e:
        print("[Automations] AI draft error:", e)
        return f"Quick check-in — want to grab a spot with {business_name}? {booking}"

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
                leads_by_user[owner] = arr
                save_leads(leads_by_user)
        return True

    return True

def engine_tick():
    ensure_files()
    flows_db = read_json(FILE_AUTOMATIONS, {"users": {}})
    state = load_state()
    leads_by_user = load_leads()

    for user, flows in (flows_db.get("users", {}) or {}).items():
        profile = load_user_profile(user)
        user_leads = leads_by_user.get(user, []) or []

        for flow in (flows or []):
            if not flow.get("enabled", False):
                continue
            flow_id = flow.get("id") or str(uuid4())
            steps = flow.get("steps", []) or []
            caps = flow.get("caps", {"per_lead_per_day": 1, "respect_quiet_hours": True}) or {}
            trigger = flow.get("trigger", {}) or {}

            for lead in user_leads:
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
                    continue

                step_index = int(run.get("step", 0))
                if step_index >= len(steps):
                    run["done"] = True
                    continue

                step = steps[step_index]
                progressed = execute_step(flow, step, lead, run, caps, profile)
                if progressed:
                    advance(run)

    save_state(state)

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

automations_bp = Blueprint("automations", __name__)

@automations_bp.before_request
def _bf_ensure_files():
    ensure_files()

@automations_bp.route("/health", methods=["GET"])
def automations_health():
    return jsonify({"ok": True, "message": "automations alive"})

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
    return [
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
                    {"type": "send_email", "subject": "We still here?", "html": "<p>Quick check-in — want to grab a spot with {{business_name}}? <a href='{{booking_link}}'>Book here</a>.</p>"}
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
                {"type": "send_whatsapp", "text": "Sorry we missed you — here’s 10% off to rebook: {{booking_link}}"},
                {"type": "wait", "hours": 48},
                {"type": "if_no_booking", "within_days": 2, "then": [
                    {"type": "send_email", "subject": "Ready to rebook?", "html": "<p>We saved you a spot — <a href='{{booking_link}}'>rebook here</a>.</p>"},
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
                {"type": "send_whatsapp", "text": "Welcome! I’m from {{business_name}} — can I help you book? {{booking_link}}"},
                {"type": "wait", "hours": 24},
                {"type": "if_no_reply", "within_days": 2, "then": [
                    {"type": "send_email", "subject": "Welcome!", "html": "<p>Quick intro — here’s the booking link: <a href='{{booking_link}}'>Book now</a>.</p>"}
                ]},
                {"type": "wait", "hours": 48},
                {"type": "push_owner", "title": "Give them a quick call", "message": "New lead may need a call"}
            ],
            "caps": {"per_lead_per_day": 1, "respect_quiet_hours": True},
            "auto_stop_on_reply": True
        }
    ]

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
    waba_id = wa_resolve_waba_id()
    r = wa_fetch_templates_for_waba(waba_id)
    if not getattr(r, "ok", False):
        return jsonify({"ok": False, "templates": [], "error": "unavailable"}), 503

    data = r.json() or {}
    items = data.get("data", []) or []
    approved = [t for t in items if (t.get("status") or "").upper() == "APPROVED"]
    approved.sort(key=lambda x: f"{x.get('name','')}-{x.get('language','')}".lower())
    return jsonify({"ok": True, "templates": approved})

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
# VAPID Push — persisted subscriptions
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
from app_wa_auto_appointments import WA_AUTO_BP

app.register_blueprint(imports_bp)
app.register_blueprint(team_bp)
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
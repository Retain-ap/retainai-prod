# app.py
from flask import Flask, request, jsonify, send_from_directory, redirect, Blueprint
# REMOVED: from automations import automations_bp, init_automations
from flask_cors import CORS
from dotenv import load_dotenv
import os, json, re, hmac, hashlib, base64, datetime, urllib.parse, time, threading, uuid, requests
from urllib.parse import urlparse
from uuid import uuid4
from typing import Any, Dict, List, Optional
import stripe
import requests as pyrequests
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email
from flask_apscheduler import APScheduler
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from flask import request, jsonify, redirect
import os, urllib
import stripe
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email
import zlib, random
from flask import current_app
from flask_cors import CORS
from flask import Flask, request, jsonify, make_response
from storage import (
    load_users, save_users, get_user, create_user,
    load_leads, save_leads, migrate_json_to_sqlite_if_needed,
    DATA_ROOT, USE_SQLITE, SQLITE_PATH
)

# ----------------------------
# BOOT + CONFIG + CORS + CORE API
# (DROP-IN REPLACEMENT: paste over your existing block down to the
#  "Blueprints" import lines)
# ----------------------------

# Kick off one-time JSON -> SQLite migration if needed
migrate_json_to_sqlite_if_needed()
print(f"[storage] USE_SQLITE={USE_SQLITE} DATA_ROOT={DATA_ROOT} SQLITE_PATH={SQLITE_PATH}")
print(f"[BOOT] RetainAI started (PID: {os.getpid()})")

class Config:
    SCHEDULER_API_ENABLED = True

load_dotenv()

app = Flask(__name__)
app.config.from_object(Config())

# ---- CORS (Render-friendly, credentials) ----
ALLOWED = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

CORS(
    app,
    origins=ALLOWED if ALLOWED else "*",
    supports_credentials=True,
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    expose_headers=["Content-Type"],
)

# Cookies (if you use them)
app.config.update(
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=True,
)

# Keep preflight happy even if a specific route doesn’t define OPTIONS
@app.after_request
def add_cors_headers(resp):
    origin = request.headers.get("Origin")
    if origin and (not ALLOWED or origin in ALLOWED):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return resp

# Generic OPTIONS responder for /api/* (helps when proxies send OPTIONS first)
@app.route("/api/<path:_any>", methods=["OPTIONS"])
def api_options(_any):
    return ("", 204)

# Keep your existing preflight for signup too
@app.route("/api/auth/signup", methods=["OPTIONS"])
def signup_preflight():
    return ("", 204)

# Health endpoints
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True), 200

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify(ok=True), 200


# ----------------------------
# Storage-related paths & legacy file helpers
# NOTE:
# - We DO NOT redefine load_users/save_users/load_leads/save_leads here
#   because those come from the `storage` adapter you imported above.
# - We keep legacy JSON helpers only for other files (notifications, chats, etc.).
# ----------------------------
SUBSCRIPTIONS = {}

LEADS_FILE = os.getenv("LEADS_FILE", "leads.json")   # still respected by storage adapter when in JSON mode
USERS_FILE = "users.json"                            # legacy JSON file (fallback only)

NOTIFICATIONS_FILE = "notifications.json"
APPOINTMENTS_FILE = "appointments.json"
CHAT_FILE = "whatsapp_chats.json"
STATUS_FILE = "whatsapp_status.json"    # per-message delivery/read status

ICS_DIR = os.path.abspath("ics_files")
os.makedirs(ICS_DIR, exist_ok=True)

CHANNEL_EMAIL = "email"
CHANNEL_WHATSAPP = "whatsapp"

# ---------- Persistent storage (atomic JSON) ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
FILE_AUTOMATIONS = os.path.join(BASE_DIR, "automations.json")
FILE_STATE       = os.path.join(BASE_DIR, "automation_state.json")
FILE_NOTIFICATIONS = os.path.join(BASE_DIR, "notifications.json")
FILE_USERS_FALLBACK = os.path.join(BASE_DIR, "users_profiles.json")  # older per-user profiles JSON (fallback only)

def _legacy_load_json(file_path):
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _legacy_save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_notifications():  # used elsewhere in your code
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
# /api/profile  (JSON, used by Settings.jsx)
# ----------------------------
def _get_user_by_email(email: str):
    """
    Primary: use storage adapter (SQLite when USE_SQLITE=1, JSON otherwise).
    Fallback: look in legacy JSON files if present.
    """
    if not email:
        return None
    email = email.strip().lower()

    # 1) storage adapter (authoritative)
    try:
        if callable(get_user):
            u = get_user(email)
            if u:
                return u  # already dict-like from the adapter
    except Exception:
        pass

    # 2) legacy users.json (flat list/dict)
    try:
        raw = _legacy_load_json(USERS_FILE)
        if isinstance(raw, dict):
            cand = raw.get(email)
            if cand:
                return cand
        elif isinstance(raw, list):
            for u in raw:
                if (u.get("email") or "").strip().lower() == email:
                    return u
    except Exception:
        pass

    # 3) legacy users_profiles.json
    try:
        raw = _legacy_load_json(FILE_USERS_FALLBACK)
        if isinstance(raw, dict):
            cand = raw.get(email)
            if cand:
                return cand
        elif isinstance(raw, list):
            for u in raw:
                if (u.get("email") or "").strip().lower() == email:
                    return u
    except Exception:
        pass

    return None

def _normalize_email(e: str) -> str:
    return (e or "").strip().lower()

def _to_dict(obj):
    """Coerce SQLAlchemy rows / tuples / namedtuples / objects into a plain dict."""
    if obj is None:
        return {}
    # If storage returns (record, created_flag) or similar, take first
    if isinstance(obj, tuple) and obj:
        obj = obj[0]
    # SQLAlchemy Row/RowMapping -> dict() works
    try:
        return dict(obj)
    except Exception:
        pass
    # namedtuple
    if hasattr(obj, "_asdict"):
        return dict(obj._asdict())
    # plain mapping
    if isinstance(obj, dict):
        return dict(obj)
    # object with __dict__
    if hasattr(obj, "__dict__"):
        try:
            return {k: v for k, v in obj.__dict__.items()}
        except Exception:
            return {}
    return {}

# keys we never want to persist/return
_BAD_KEYS = {
    "_sa_instance_state", "headers", "request", "cookies", "environ",
    "wsgi", "response", "session", "files", "form", "args", "json",
}

def _json_sanitize(val):
    """
    Recursively convert to JSON-safe types.
    - dict: sanitize entries, drop _BAD_KEYS, drop unserializable values
    - list/tuple/set: sanitize each, convert tuple/set -> list
    - datetime/date: isoformat
    - bytes: base64
    - other unknown objects: str() as last resort
    """
    import datetime as _dt
    import base64 as _b64

    # primitives pass through
    if val is None or isinstance(val, (bool, int, float, str)):
        return val

    # datetime
    if isinstance(val, (_dt.datetime, _dt.date)):
        try:
            return val.isoformat()
        except Exception:
            return str(val)

    # bytes
    if isinstance(val, (bytes, bytearray, memoryview)):
        try:
            return _b64.b64encode(bytes(val)).decode("ascii")
        except Exception:
            return str(val)

    # dict-like
    if isinstance(val, dict):
        out = {}
        for k, v in val.items():
            if k in _BAD_KEYS:
                continue
            try:
                out[str(k)] = _json_sanitize(v)
            except Exception:
                # drop anything that fails sanitation
                continue
        return out

    # iterable -> list
    if isinstance(val, (list, tuple, set)):
        out = []
        for x in val:
            try:
                out.append(_json_sanitize(x))
            except Exception:
                continue
        return out

    # fallback
    try:
        return str(val)
    except Exception:
        return None

def _merge_profile(existing: dict, patch: dict) -> dict:
    out = dict(existing or {})
    for k, v in (patch or {}).items():
        if v is not None:
            out[k] = v
    # normalize keys the frontend expects
    out.setdefault("businessName", out.get("business") or "")
    out.setdefault("business", out.get("businessName") or "")
    out.setdefault("teamSize", out.get("people") or 0)
    out.setdefault("people", out.get("teamSize") or 0)
    out.setdefault("logo", out.get("logo") or "")
    return out

def _clean_user_dict(u: dict, email: str) -> dict:
    u = _to_dict(u)
    # hard-drop bad keys if they slipped in
    for k in list(u.keys()):
        if k in _BAD_KEYS:
            u.pop(k, None)
    # enforce required keys
    u.setdefault("email", email)
    u.setdefault("name", u.get("name") or "")
    u.setdefault("business", u.get("business") or u.get("businessName") or "")
    u.setdefault("businessName", u.get("businessName") or u.get("business") or "")
    u.setdefault("businessType", u.get("businessType") or "")
    u.setdefault("location", u.get("location") or "")
    u.setdefault("people", u.get("people") or u.get("teamSize") or 0)
    u.setdefault("teamSize", u.get("teamSize") or u.get("people") or 0)
    u.setdefault("logo", u.get("logo") or "")
    return u

@app.get("/api/profile")
def api_profile_get():
    try:
        email = _normalize_email(request.args.get("email"))
        if not email:
            return jsonify({"error": "email_required"}), 400

        u = get_user(email)
        u = _clean_user_dict(u, email)

        if not u or not u.get("email"):
            # create minimal record so first load succeeds
            created = create_user(email=email, name="", businessName="", businessType="", people=0, location="")
            u = _clean_user_dict(created, email)

        # sanitize before jsonify to avoid "not JSON serializable"
        return jsonify(_json_sanitize(u)), 200
    except Exception as e:
        current_app.logger.exception("GET /api/profile failed")
        return jsonify({"error": "profile_get_failed", "detail": str(e)}), 500

@app.post("/api/oauth/google/complete")
def api_profile_save():
    """
    Accepts: { email, name, businessName|business, businessType, people|teamSize, location, logo }
    Upserts via storage layer (works with JSON or SQLite adapters).
    """
    try:
        data = request.get_json(force=True, silent=False) or {}
        email = _normalize_email(data.get("email"))
        if not email:
            return jsonify({"error": "email_required"}), 400

        curr = _clean_user_dict(get_user(email), email)

        patch = {
            "email": email,
            "name": data.get("name", curr.get("name")),
            "businessName": data.get("businessName", data.get("business", curr.get("businessName"))),
            "business": data.get("business", data.get("businessName", curr.get("business"))),
            "businessType": data.get("businessType", curr.get("businessType")),
            "location": data.get("location", curr.get("location")),
            "people": data.get("people", curr.get("people", 0)),
            "teamSize": data.get("teamSize", data.get("people", curr.get("teamSize", 0))),
            "logo": data.get("logo", curr.get("logo", "")),
        }

        merged = _merge_profile(curr, patch)

        # Persist (JSON or SQLite adapter). If JSON path fails, fall back to create_user as UPSERT.
        try:
            users = load_users()
            if isinstance(users, dict):
                users[email] = merged
                save_users(users)
            else:
                create_user(**merged)
        except Exception:
            create_user(**merged)

        return jsonify({"ok": True, "user": _json_sanitize(merged)}), 200
    except Exception as e:
        current_app.logger.exception("POST /api/oauth/google/complete failed")
        return jsonify({"error": "profile_save_failed", "detail": str(e)}), 500

# JSON 404 for /api/* so the frontend never sees HTML
@app.errorhandler(404)
def json_404(err):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not_found", "path": request.path}), 404
    return err

@app.route("/api/profile", methods=["GET", "OPTIONS"])
def api_profile():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        email = (request.args.get("email") or "").strip().lower()
        if not email:
            return jsonify({"error": "missing email query param"}), 400

        # storage.get_user handles both SQLite and JSON based on USE_SQLITE
        user = get_user(email)
        if not user:
            # For first-time users, create a minimal record so frontend has a shape
            user = {
                "email": email,
                "name": "",
                "businessName": "",
                "businessType": "",
                "location": "",
                "people": "",
                "logo": "",
                "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            }
            # create_user is idempotent in our storage adapter
            create_user(user)

        # Normalize keys expected by the frontend
        out = {
            "email": user.get("email", email),
            "name": user.get("name") or user.get("displayName") or "",
            "business": user.get("business") or user.get("businessName") or "",
            "businessName": user.get("businessName") or user.get("business") or "",
            "businessType": user.get("businessType") or user.get("type") or "",
            "location": user.get("location") or "",
            "people": user.get("people") or user.get("teamSize") or "",
            "teamSize": user.get("teamSize") or user.get("people") or "",
            "logo": user.get("logo") or "",
            "last_login": user.get("last_login"),
            "created_at": user.get("created_at"),
        }
        return jsonify(out), 200

    except Exception as e:
        # Log full stacktrace to Render logs
        current_app.logger.exception("api_profile failed")
        return jsonify({
            "error": "server_error",
            "message": str(e),
            "details": {
                "email": (request.args.get("email") or "").strip().lower(),
                "USE_SQLITE": bool(USE_SQLITE),
                "SQLITE_PATH": SQLITE_PATH,
                "DATA_ROOT": DATA_ROOT,
            }
        }), 500


# Optional: quick debug endpoint to verify storage wiring without the frontend
@app.route("/api/profile/debug", methods=["GET"])
def api_profile_debug():
    email = (request.args.get("email") or "").strip().lower()
    ok = True
    msg = "ok"
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
        "user_sample": u if (ok and u and isinstance(u, dict)) else None
    }), 200 if ok else 500

# ----------------------------
# Blueprints (import AFTER helpers so app_imports can import load_leads/save_leads)
# ----------------------------
from app_imports import imports_bp
from app_team import team_bp
from app_wa_auto_appointments import WA_AUTO_BP

app.register_blueprint(imports_bp)
app.register_blueprint(team_bp)
app.register_blueprint(WA_AUTO_BP)
# ----------------------------
# Env & third-party keys
# ----------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "noreply@retainai.ca")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_CONNECT_CLIENT_ID = os.getenv("STRIPE_CONNECT_CLIENT_ID")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
stripe.api_key = STRIPE_SECRET_KEY
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

AUTOMATIONS_PATH = os.path.join(DATA_DIR, "automations.json")     # (legacy path not used by new engine)
TEMPLATES_PATH   = os.path.join(DATA_DIR, "automation_templates.json")  # (legacy path not used by new engine)
ZERO_DECIMAL = {"bif","clp","djf","gnf","jpy","kmf","krw","mga","pyg","rwf","ugx","vnd","vuv","xaf","xof","xpf"}

# --- WhatsApp Cloud API ---
WHATSAPP_TOKEN    = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "retainai-verify")
# WABA id (either env name)
WHATSAPP_WABA_ID = os.getenv("WHATSAPP_WABA_ID") or os.getenv("WHATSAPP_BUSINESS_ID")
# Your real default template name (approved; can have 0..N params)
WHATSAPP_TEMPLATE_DEFAULT = os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "retainai_outreach")
# UI language default → API mapping handled below
WHATSAPP_TEMPLATE_LANG = os.getenv("WHATSAPP_TEMPLATE_LANG", "en_US")
# App secret for webhook signature (either env name)
APP_SECRET = os.getenv("APP_SECRET") or os.getenv("META_APP_SECRET")
# Country code auto-prefix for 10-digit NANP numbers (e.g., "1" for US/CA)
DEFAULT_COUNTRY_CODE = (os.getenv("DEFAULT_COUNTRY_CODE") or "1").strip()

# --- Google OAuth ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
]

# ----------------------------
# SendGrid templates
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

PROMPT_TYPE_TO_TEMPLATE = {
    "followup": SG_TEMPLATE_FOLLOWUP_LEAD,
    "reengage": SG_TEMPLATE_REENGAGE_LEAD,
    "apology":  SG_TEMPLATE_APOLOGY_LEAD,
    "upsell":   SG_TEMPLATE_UPSELL_LEAD,
    "birthday": SG_TEMPLATE_BIRTHDAY,
    "appointment": SG_TEMPLATE_APPT_CONFIRM,
}

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

# =========================
# OpenRouter helpers (shared)
# =========================
AI_MODEL_ORDER_PROMPT = [
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-1.5-pro",
    "meta-llama/llama-3.1-70b-instruct",
    "meta-llama/llama-3.1-8b-instruct",
]

def _clean_ai_text(text: str) -> str:
    import re
    s = (text or "").strip()
    s = re.sub(r"^(Subject|Lead Name|Recipient)\s*:\s*.*\n?", "", s, flags=re.I|re.M)
    s = re.sub(r"^\s*[\w \-]+:\s*$", "", s, flags=re.M)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _fallback_prompt(lead_name: str, business_name: str, booking: str) -> str:
    who = business_name or "our team"
    if booking:
        return f"Just checking in, {lead_name or 'there'} — happy to help you lock in a time with {who}. You can book here: {booking}."
    return f"Just checking in, {lead_name or 'there'} — happy to help with next steps."

def _complete_openrouter_prompt(messages, *, max_tokens=150, temperature=0.7, timeout=30):
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
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
                ct = r.headers.get("content-type","")
                j = r.json() if "application/json" in ct.lower() else {}

                if r.ok and j.get("choices"):
                    txt = j["choices"][0]["message"]["content"]
                    return True, _clean_ai_text(txt), {"model": model, "status": r.status_code, "tokens": attempt_tokens}

                if r.status_code == 402:
                    import re, json as _json
                    m = re.search(r"afford\s+(\d+)", _json.dumps(j or r.text))
                    if m:
                        afford = max(40, int(m.group(1)) - 5)
                        if afford < attempt_tokens:
                            attempt_tokens = afford
                            continue
                    last_err = {"status": 402, "body": j or r.text}; break

                if r.status_code == 429 or (500 <= r.status_code < 600):
                    import time
                    time.sleep(0.7 + attempt * 0.4)
                    attempt_tokens = max(60, int(attempt_tokens * 0.9))
                    continue

                last_err = {"status": r.status_code, "body": j or r.text}
                break

            except Exception as e:
                import time
                last_err = {"exception": str(e)}
                time.sleep(0.4 + attempt * 0.3)
                continue

    return False, "", {"error": "all_models_failed", "last": last_err}

def _text_to_html(s: str) -> str:
    import html as _html
    s = (s or "").replace("\r\n", "\n").strip()
    parts = []
    for p in s.split("\n\n"):
        p = p.strip()
        if not p:
            continue
        esc = _html.escape(p).replace("\n", "<br>")
        parts.append("<p>" + esc + "</p>")
    return "".join(parts) or "<p></p>"

# ----------------------------
# Email via SendGrid
# ----------------------------
def send_email_with_template(to_email, template_id, dynamic_data, subject=None, from_email=None, reply_to_email=None):
    from_email = from_email or SENDER_EMAIL
    if not subject:
        subject = "Message from RetainAI"
    dynamic_data["subject"] = subject
    message = Mail(from_email=from_email, to_emails=to_email, subject=subject)
    message.template_id = template_id
    message.dynamic_template_data = dynamic_data
    if reply_to_email:
        message.reply_to = Email(reply_to_email)
    try:
        sg = SendGridAPIClient(VAPID_PRIVATE_KEY if template_id == "fake" else os.getenv("SENDGRID_API_KEY"))
        response = sg.send(message)
        print(f"[SENDGRID] Status: {response.status_code} | To: {to_email} | Subject: {subject}")
        return response.status_code == 202
    except Exception as e:
        print(f"[SENDGRID ERROR] Failed to send to {to_email}: {e}")
        return False

def send_welcome_email(to_email, user_name=None, business_type=None):
    send_email_with_template(
        to_email=to_email,
        template_id=SG_TEMPLATE_WELCOME,
        dynamic_data={"user_name": user_name or "", "business_type": business_type or ""},
        from_email="welcome@retainai.ca"
    )

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
        dynamic_data={
            "user_name": user_name, "lead_name": lead_name, "business_name": business_name, "birthday": birthday
        },
        subject=f"Birthday Reminder: {lead_name}'s birthday is tomorrow!",
        from_email="reminder@retainai.ca"
    )

def send_trial_ending_email(user_email, user_name, business_name, trial_end_date):
    send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_TRIAL_ENDING,
        dynamic_data={"user_name": user_name, "business_name": business_name, "trial_end_date": trial_end_date},
    )

def send_followup_reminder(user_email, lead):
    send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_FOLLOWUP_USER,
        dynamic_data={
            "lead_name": lead.get("name", ""),
            "lead_email": lead.get("email", ""),
            "user_email": user_email or "",
            "last_contacted": lead.get("last_contacted", ""),
            "notes": lead.get("notes", ""),
            "tags": ', '.join(lead.get("tags", []))
        }
    )

# ----------------------------
# Calendar / ICS helpers
# ----------------------------
def create_ics_file(appt):
    uid = appt.get('id')
    dt_start = datetime.datetime.strptime(appt['appointment_time'], "%Y-%m-%dT%H:%M:%S")
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
    with open(os.path.join(ICS_DIR, fname), "w") as f:
        f.write(ics_content)
    return fname

@app.route('/ics/<filename>')
def serve_ics(filename):
    return send_from_directory(ICS_DIR, filename, as_attachment=True)

def make_google_calendar_link(appt):
    dt_start = datetime.datetime.strptime(appt['appointment_time'], "%Y-%m-%dT%H:%M:%S")
    dt_end = dt_start + datetime.timedelta(minutes=int(appt.get("duration", 30)))
    start_str = dt_start.strftime("%Y%m%dT%H%M%SZ")
    end_str = dt_end.strftime("%Y%m%dT%H%M%SZ")
    title = f"Appointment with {appt['user_name']} at {appt['business_name']}"
    location = appt['appointment_location'].replace(" ", "+")
    details = f"Appointment with {appt['user_name']} at {appt['business_name']}."
    return (
        f"https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={title.replace(' ','+')}"
        f"&dates={start_str}/{end_str}"
        f"&details={details.replace(' ','+')}"
        f"&location={location}"
    )

# ----------------------------
# Notifications & scheduler
# ----------------------------
def log_notification(user_email, subject, message, lead_email=None):
    notifications = load_notifications()
    notifications.setdefault(user_email, []).append({
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
        "subject":     subject,
        "message":     message,
        "lead_email":  lead_email,
        "read":        False
    })
    save_notifications(notifications)

def send_warning_summary_email(user_email, warning_leads, interval):
    if not warning_leads:
        return
    users = load_users()
    user = users.get(user_email, {})
    user_name = user.get('name') or user_email.split('@')[0].capitalize()

    def format_date(dtstr):
        if not dtstr: return "-"
        try: return dtstr.split("T")[0]
        except Exception: return dtstr

    lead_list_html = "<ul style='padding-left:24px;margin:0;'>"
    for lead in warning_leads:
        lead_list_html += (
            f"<li style='margin-bottom:16px;color:#FFD700;'>"
            f"<span style='font-weight:700;font-size:1.1em;'>{lead.get('name','-')}</span><br>"
            f"<span style='color:#fff;'>Email:</span> <span style='color:#FFD700;'>{lead.get('email','-')}</span><br>"
            f"<span style='color:#fff;'>Last Contacted:</span> <span style='color:#FFD700;'>{format_date(lead.get('last_contacted', '-') or lead.get('createdAt', '-'))}</span> "
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

def check_for_lead_reminders():
    print("[Scheduler] Checking for leads needing follow-up...")
    leads_by_user = load_leads()
    users_by_email = load_users()
    now = datetime.datetime.utcnow()
    for user_email, leads in leads_by_user.items():
        user = users_by_email.get(user_email)
        business_type = (user.get("business", "") if user else "").lower()
        interval = BUSINESS_TYPE_INTERVALS.get(business_type, 14)
        warning_leads = []
        for lead in leads:
            last_contacted = lead.get("last_contacted") or lead.get("createdAt")
            if not last_contacted: continue
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
                    f"{len(warning_leads)} leads require follow-up: " + ", ".join(lead["name"] for lead in warning_leads)
                )
            except Exception as e:
                print("[WARN] lead reminder email/log error:", e)

def send_birthday_greetings():
    leads_by_user = load_leads()
    users_by_email = load_users()
    today = datetime.datetime.utcnow().strftime("%m-%d")
    tomorrow = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).strftime("%m-%d")
    for user_email, leads in leads_by_user.items():
        user = users_by_email.get(user_email, {})
        business = user.get("business", "")
        user_name = user.get("name", "")
        for lead in leads:
            bday = lead.get("birthday", "")
            if bday and len(bday.split("-")) >= 3:
                mmdd = "-".join(bday.split("-")[1:3])
                if mmdd == today:
                    send_birthday_email(lead.get("email", ""), lead.get("name", ""), business)
                    log_notification(user_email, f"Happy Birthday, {lead.get('name','')}!", "Automated birthday email", lead.get("email"))
                if mmdd == tomorrow:
                    send_birthday_reminder_to_user(
                        user_email=user_email, user_name=user_name, lead_name=lead.get("name", ""), business_name=business, birthday=bday
                    )
                    log_notification(user_email, f"Reminder: {lead.get('name','')}'s birthday is tomorrow!", "Birthday reminder sent", lead.get("email"))

def send_trial_ending_soon():
    users = load_users()
    now = datetime.datetime.utcnow()
    changed = False
    for email, user in users.items():
        trial_start = user.get("trial_start")
        if not trial_start or user.get('status') not in ['pending_payment', 'active']:
            continue
        try:
            trial_start_dt = datetime.datetime.fromisoformat(trial_start)
        except Exception:
            continue
        trial_end = trial_start_dt + datetime.timedelta(days=14)
        days_left = (trial_end - now).days
        if days_left == 2 and not user.get("trial_ending_notice_sent"):
            send_trial_ending_email(
                user_email=email,
                user_name=user.get("name", ""),
                business_name=user.get("business", ""),
                trial_end_date=trial_end.strftime("%B %d, %Y")
            )
            user["trial_ending_notice_sent"] = True
            changed = True
    if changed:
        save_users(users)

def _build_member_view(users: dict, member_email: str):
    """
    If member_email exists under team namespace 'user::<email>',
    construct a synthetic user profile using the owner's business details.
    Returns (member_view_dict, owner_email) or (None, None) if not a member.
    """
    key = f"user::{_norm_email(member_email)}"
    team_rec = users.get(key)
    if not team_rec:
        return None, None

    owner_email = _norm_email(team_rec.get("org_id") or "")
    owner_acct  = users.get(owner_email) or {}
    if not owner_acct:
        return None, None  # orphaned team record

    view = {
        "email": member_email,
        "name":  team_rec.get("name") or (member_email.split("@")[0].title()),
        "role":  team_rec.get("role", "member"),
        "org_id": owner_acct.get("org_id") or owner_email,
        # borrow business visuals/details from the owner so Settings can render
        "business":      owner_acct.get("business", ""),
        "businessType":  owner_acct.get("businessType", ""),
        "teamSize":      owner_acct.get("teamSize", ""),
        "logo":          owner_acct.get("logo") or owner_acct.get("picture") or "",
        # always treat active if the owner is active or in trial
        "status": "active",
    }
    return view, owner_email

def _resolve_org_and_role(email: str, users: dict):
    """Return (role, org_owner_email, org_owner_record, subject_record) or (None, None, None, None)."""
    email = _norm_email(email)
    owner = users.get(email)
    if owner:  # top-level owner record
        return ("owner", email, owner, owner)

    member = users.get(f"user::{email}")
    if member:
        org_email = _norm_email(member.get("org_id") or "")
        org_owner = users.get(org_email)
        if org_owner:
            return ("member", org_email, org_owner, member)
    return (None, None, None, None)


def _org_is_active(owner_record: dict) -> bool:
    return (owner_record.get("status") == "active") or _within_trial(owner_record, TRIAL_DAYS)

# ----------------------------
# Appointments
# ----------------------------
@app.route('/api/appointments/<user_email>', methods=['GET'])
def get_appointments(user_email):
    data = load_appointments()
    return jsonify({"appointments": data.get(user_email, [])}), 200

@app.route('/api/appointments/<user_email>', methods=['POST'])
def create_appointment(user_email):
    data = request.json
    appt = {
        "id": str(uuid4()),
        "lead_email": data['lead_email'],
        "lead_first_name": data['lead_first_name'],
        "user_name": data['user_name'],
        "user_email": data['user_email'],
        "business_name": data['business_name'],
        "appointment_time": data['appointment_time'],
        "appointment_location": data['appointment_location'],
        "duration": data.get('duration', 30),
        "notes": data.get('notes', "")
    }
    appointments = load_appointments()
    appointments.setdefault(user_email, []).append(appt)
    save_appointments(appointments)
    create_ics_file(appt)
    # send email
    display_time = datetime.datetime.strptime(appt['appointment_time'], "%Y-%m-%dT%H:%M:%S").strftime("%B %d, %Y, %I:%M %p")
    ics_file_url = f"{request.host_url.rstrip('/')}/ics/{appt['id']}.ics"
    google_calendar_link = make_google_calendar_link(appt)
    send_email_with_template(
        to_email=appt['lead_email'],
        template_id=SG_TEMPLATE_APPT_CONFIRM,
        dynamic_data={
            "lead_first_name": appt["lead_first_name"],
            "user_name": appt["user_name"],
            "business_name": appt["business_name"],
            "display_time": display_time,
            "appointment_location": appt["appointment_location"],
            "google_calendar_link": google_calendar_link,
            "ics_file_url": ics_file_url,
            "user_email": appt["user_email"]
        }
    )
    return jsonify({"message": "Appointment created and confirmation sent!", "appointment": appt}), 201

@app.route('/api/appointments/<user_email>/<appt_id>', methods=['PUT'])
def update_appointment(user_email, appt_id):
    data = request.json
    appointments = load_appointments()
    user_appts = appointments.get(user_email, [])
    updated = False
    idx = -1
    for i, appt in enumerate(user_appts):
        if appt['id'] == appt_id:
            for k in data:
                user_appts[i][k] = data[k]
            updated = True
            idx = i
            create_ics_file(user_appts[i])
            break
    appointments[user_email] = user_appts
    save_appointments(appointments)
    return jsonify({"updated": updated, "appointment": user_appts[idx] if updated else None}), 200

@app.route('/api/appointments/<user_email>/<appt_id>', methods=['DELETE'])
def delete_appointment(user_email, appt_id):
    appointments = load_appointments()
    user_appts = appointments.get(user_email, [])
    before = len(user_appts)
    user_appts = [a for a in user_appts if a['id'] != appt_id]
    after = len(user_appts)
    appointments[user_email] = user_appts
    save_appointments(appointments)
    fname = os.path.join(ICS_DIR, f"{appt_id}.ics")
    if os.path.exists(fname):
        os.remove(fname)
    return jsonify({"deleted": before - after}), 200

# ----------------------------
# Stripe Connect / Billing (ORG-AWARE + MEMBER SAFE)
# ----------------------------
# assumes: load_users(), save_users(), FRONTEND_URL, STRIPE_CONNECT_CLIENT_ID,
# STRIPE_WEBHOOK_SECRET, stripe + SendGrid imports and API keys configured

import urllib.parse  # used in oauth callback

ZERO_DECIMAL = {
    "bif","clp","djf","gnf","jpy","kmf","krw","mga","pyg","rwf",
    "ugx","vnd","vuv","xaf","xof","xpf"
}

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()

def _resolve_org_and_role(email: str, users: dict):
    """
    Return (role, org_owner_email, org_owner_record, subject_record)
    role: "owner" or "member" (or None if not found)
    """
    email = _norm_email(email)
    owner = users.get(email)
    if owner:  # top-level owner record
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
    if not ue:
        return None
    return _norm_email(ue)

def to_minor(amount, currency):
    c = (currency or "usd").lower()
    return int(round(float(amount) * (1 if c in ZERO_DECIMAL else 100)))

def from_minor(value, currency):
    c = (currency or "usd").lower()
    denom = 1 if c in ZERO_DECIMAL else 100.0
    return (value or 0) / denom

def _safe_get(obj, *path, default=None):
    """Safe getattr for nested stripe objects/dicts."""
    cur = obj
    for p in path:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = getattr(cur, p, None)
    return cur if cur is not None else default

def serialize_invoice(inv):
    """Uniform shape for both list + create responses (already expanded 'customer')."""
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
        "amount_due":   round(amount_due, 2),
        "amount_paid":  round(amount_paid, 2),
        "amount_display": round(display, 2),
        "currency": currency,
        "due_date": inv.due_date,
        "status": inv.status,
        "invoice_url": inv.hosted_invoice_url,
        "number": getattr(inv, "number", None)
    }

def _connected_acct_for(email: str):
    """
    Resolve the *org owner's* connected account for any subject email (owner/member).
    Returns (role, org_email, org_owner_record, acct_id) or (None, None, None, None)
    """
    users = load_users()
    role, org_email, org_owner, _subject = _resolve_org_and_role(email, users)
    if not role:
        return (None, None, None, None)
    return (role, org_email, org_owner, org_owner.get("stripe_account_id"))

# --- CONNECT / ONBOARDING ---

@app.route("/api/stripe/connect-url", methods=["GET"])
def get_stripe_connect_url():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    users = load_users()
    role, org_email, org_owner, _ = _resolve_org_and_role(user_email, users)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403

    # Create an Express account for the ORG OWNER
    acct = stripe.Account.create(type="express", email=org_email)

    org_owner = users.get(org_email, {}) or {}
    org_owner["stripe_account_id"] = acct.id
    org_owner["stripe_connected"]  = True  # mirrors your existing behavior
    users[org_email] = org_owner
    save_users(users)

    return_url  = f"{FRONTEND_URL}/app?stripe_connected=1"
    refresh_url = f"{FRONTEND_URL}/app?stripe_refresh=1"
    link = stripe.AccountLink.create(
        account=acct.id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return jsonify({"url": link.url}), 200

@app.route("/api/stripe/oauth/connect", methods=["GET"])
def stripe_oauth_connect():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    users = load_users()
    role, org_email, org_owner, _ = _resolve_org_and_role(user_email, users)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403

    redirect_uri = os.getenv("STRIPE_REDIRECT_URI")
    oauth_url = (
        "https://connect.stripe.com/oauth/authorize"
        f"?response_type=code"
        f"&client_id={STRIPE_CONNECT_CLIENT_ID}"
        f"&scope=read_write"
        f"&redirect_uri={redirect_uri}"
        f"&state={org_email}"
    )
    return jsonify({"url": oauth_url}), 200

@app.route("/api/stripe/oauth/callback", methods=["GET"])
def stripe_oauth_callback():
    error      = request.args.get("error")
    error_desc = request.args.get("error_description", "")
    user_email = request.args.get("state")
    if error:
        msg = urllib.parse.quote_plus(error_desc or error)
        return redirect(f"{FRONTEND_URL}/app?stripe_error=1&stripe_error_desc={msg}")

    code = request.args.get("code")
    if not code or not user_email:
        return redirect(f"{FRONTEND_URL}/app?stripe_error=1&stripe_error_desc=missing_code_or_state")

    # Exchange code → connected account
    resp = stripe.OAuth.token(grant_type="authorization_code", code=code)
    stripe_user_id = resp["stripe_user_id"]

    users = load_users()
    role, org_email, org_owner, _ = _resolve_org_and_role(user_email, users)
    if not role:
        return redirect(f"{FRONTEND_URL}/app?stripe_error=1&stripe_error_desc=user_not_found")

    # Always save on ORG OWNER
    org = users.get(org_email, {}) or {}
    org["stripe_account_id"] = stripe_user_id
    org["stripe_connected"]  = True
    users[org_email] = org
    save_users(users)
    return redirect(f"{FRONTEND_URL}/app?stripe_connected=1")

# --- DASHBOARD / ACCOUNT ---

@app.route("/api/stripe/dashboard-link", methods=["GET"])
def stripe_dashboard_link():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    users = load_users()
    role, org_email, org_owner, acct_id = _connected_acct_for(user_email)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 400

    acct = stripe.Account.retrieve(acct_id)
    if getattr(acct, "type", None) in ("express", "custom"):
        link = stripe.Account.create_login_link(acct_id)
        return jsonify({"url": link.url}), 200
    # Standard accounts: generic dashboard link
    return jsonify({"url": f"https://dashboard.stripe.com/{acct_id}"}), 200

# Fetch connected account details (default_currency, etc.)
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

    # 'email' may not exist on some account types; fall back to business_profile.support_email
    email = getattr(acct, "email", None)
    if email is None:
        email = _safe_get(acct, "business_profile", "support_email")

    return jsonify({
        "account": {
            "id": acct.id,
            "type": getattr(acct, "type", None),
            "default_currency": getattr(acct, "default_currency", None),
            "details_submitted": getattr(acct, "details_submitted", None),
            "email": email
        }
    }), 200

# --- INVOICING ---

@app.route("/api/stripe/invoice", methods=["POST"])
def create_stripe_invoice():
    data = request.json or {}
    user_email     = _norm_email(data.get("user_email"))
    customer_name  = data.get("customer_name")
    customer_email = data.get("customer_email")
    description    = data.get("description")
    amount         = data.get("amount")
    unit_amount    = data.get("unit_amount")
    quantity       = int(data.get("quantity") or 1)
    currency       = (data.get("currency") or "").lower().strip() or None

    if not all([user_email, customer_name, customer_email, description]):
        return jsonify({"error": "Missing required fields"}), 400

    # compute total
    try:
        if amount is not None:
            total_float = float(amount)
        else:
            total_float = float(unit_amount) * quantity
        assert total_float > 0
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
        # pick account default currency if not provided
        if not currency:
            acct = stripe.Account.retrieve(acct_id)
            currency = (getattr(acct, "default_currency", None) or "usd").lower()

        # upsert customer in CONNECTED account
        existing = stripe.Customer.list(
            email=customer_email, limit=1, stripe_account=acct_id
        ).data
        if existing:
            cust = existing[0]
            stripe.Customer.modify(cust.id, name=customer_name, stripe_account=acct_id)
        else:
            cust = stripe.Customer.create(
                email=customer_email, name=customer_name, stripe_account=acct_id
            )
        cust_id = cust.id

        # 1) create invoice shell for that customer
        inv = stripe.Invoice.create(
            customer=cust_id,
            collection_method="send_invoice",
            days_until_due=7,
            auto_advance=False,
            metadata={"user_email": user_email, "customer_name": customer_name},
            stripe_account=acct_id,
        )

        # 2) attach a single line item (sets invoice currency)
        total_minor = to_minor(total_float, currency)
        stripe.InvoiceItem.create(
            customer=cust_id,
            invoice=inv.id,
            amount=total_minor,
            currency=currency,
            description=description,
            metadata={
                "user_email": user_email,
                "customer_name": customer_name,
                "quantity": quantity
            },
            stripe_account=acct_id,
        )

        # 3) finalize so Stripe computes totals and hosted URL
        inv = stripe.Invoice.finalize_invoice(inv.id, stripe_account=acct_id)

        # 4) return UPDATED LIST so the UI can refresh instantly without another GET
        latest = stripe.Invoice.list(
            limit=100, expand=["data.customer"], stripe_account=acct_id
        ).data
        invoices = [serialize_invoice(x) for x in latest]

        return jsonify({
            "success": True,
            "account_id": acct_id,
            "invoice_id": inv.id,
            "invoice_url": inv.hosted_invoice_url,
            "amount_due":   from_minor(inv.amount_due, inv.currency),
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

    invs = stripe.Invoice.list(
        limit=100, expand=["data.customer"], stripe_account=acct_id
    ).data
    out = [serialize_invoice(inv) for inv in invs]
    return jsonify({"invoices": out, "account_id": acct_id}), 200

@app.route("/api/stripe/invoice/send", methods=["POST"])
def resend_invoice_email():
    data = request.json or {}
    invoice_id = data.get("invoice_id")
    user_email = _norm_email(data.get("user_email"))
    if not invoice_id or not user_email:
        return jsonify({"error": "Missing invoice_id or user_email"}), 400

    users = load_users()
    role, org_email, org_owner, acct_id = _connected_acct_for(user_email)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 400

    user_name = org_owner.get("name", "")
    business  = org_owner.get("business", "")

    try:
        inv = stripe.Invoice.retrieve(
            invoice_id, expand=["customer"], stripe_account=acct_id
        )
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
        SendGridAPIClient(os.getenv("SENDGRID_API_KEY")).send(msg)
        return jsonify({"success": True}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- WEBHOOK / DISCONNECT ---

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
            users = load_users()
            user = users.get(_norm_email(email))
            if user:
                user["status"] = "active"
                save_users(users)
    return "", 200

@app.route("/api/stripe/disconnect", methods=["POST"])
def stripe_disconnect():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    users = load_users()
    role, org_email, org_owner, acct_id = _connected_acct_for(user_email)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403
    if not acct_id:
        return jsonify({"error": "No Stripe account to disconnect"}), 400

    try:
        stripe.OAuth.deauthorize(
            client_id=STRIPE_CONNECT_CLIENT_ID,
            stripe_user_id=acct_id
        )
    except Exception as e:
        app.logger.warning(f"Stripe deauth failed for {acct_id}: {e}")

    org_owner.pop("stripe_account_id", None)
    org_owner["stripe_connected"] = False
    users[org_email] = org_owner
    save_users(users)
    return ("", 204)

# --- GOOGLE OAUTH SAVE NAME "COMPLETE" NO-OP (prevents 404 spam) ---

@app.route('/api/oauth/google/complete', methods=['POST'])
def google_complete_noop():
    # Frontend may POST here after profile updates; keep it harmless.
    return jsonify({"ok": True}), 200

# ----------------------------
# Auth & Google OAuth  (trial-gated + Stripe verify)
# ----------------------------
TRIAL_DAYS = 14  # change if you want a different trial length

def _norm_email(s: str) -> str:
    return (s or "").strip().lower()

def _user_payload(email: str, user: dict) -> dict:
    # Prefer 'logo', but fall back to legacy 'picture'
    logo = user.get('logo') or user.get('picture') or ''
    return {
        'email':             _norm_email(email),
        'name':              user.get('name', ''),
        'logo':              logo,
        'businessType':      user.get('businessType', ''),
        'business':          user.get('business', ''),
        'people':            user.get('people', ''),
        'location':          user.get('location', ''),
        'stripe_account_id': user.get('stripe_account_id'),
        'stripe_connected':  user.get('stripe_connected', False),
        'status':            user.get('status', '')
    }

def _within_trial(user: dict, days: int = TRIAL_DAYS) -> bool:
    ts = user.get("trial_start")
    if not ts:
        return False
    try:
        t0 = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return False
    return (datetime.datetime.utcnow() - t0) <= datetime.timedelta(days=days)

# --- SIGNUP ROUTE (supports /api/signup and /api/auth/signup) ---
@app.route('/api/signup', methods=['POST', 'OPTIONS'])
@app.route('/api/auth/signup', methods=['POST', 'OPTIONS'])
def signup():
    """
    Create a user record in users.json (with optional profile fields),
    send a welcome email, and kick off a Stripe Checkout subscription
    with trial (TRIAL_DAYS). Returns { checkoutUrl } on success.

    Accepts JSON:
    {
      email, password, name?,
      businessType?, businessName?, teamSize?, logo?,
      phone?, website?, instagram?, location?
    }
    """

    # Handle CORS preflight politely if your UI sends it
    if request.method == 'OPTIONS':
        return ('', 204)

    # Robust JSON read
    data = request.get_json(silent=True) or {}

    # Normalize & gather fields
    email         = _norm_email(data.get('email'))
    password      = (data.get('password') or '').strip()
    name          = (data.get('name') or '').strip()

    businessType  = (data.get('businessType') or '').strip()
    businessName  = (data.get('businessName') or businessType or '').strip()
    teamSize      = (data.get('teamSize') or '').strip()
    logo          = (data.get('logo') or '').strip()

    phone         = (data.get('phone') or '').strip()
    website       = (data.get('website') or '').strip()
    instagram     = (data.get('instagram') or '').strip()
    location      = (data.get('location') or '').strip()

    # Validation
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    users = load_users()
    if email in users:
        return jsonify({'error': 'User already exists'}), 409

    # Create local user
    trial_start = datetime.datetime.utcnow().isoformat()
    users[email] = {
        'password':                  password,
        'name':                      name,
        'businessType':              businessType,
        # Keep prior key ('business') for compatibility; also store businessName verbatim
        'business':                  businessName,
        'businessName':              businessName,
        'teamSize':                  teamSize,
        'logo':                      logo,
        'phone':                     phone,
        'website':                   website,
        'instagram':                 instagram,
        'location':                  location,
        'status':                    'pending_payment',
        'trial_start':               trial_start,
        'trial_ending_notice_sent':  False,
    }
    save_users(users)

    # Fire-and-forget welcome email
    try:
        # Adjust signature if your helper takes different args
        send_welcome_email(email, name, businessName)
    except Exception as e:
        print(f"[WARN] Couldn't send welcome email: {e}")

    # Stripe is optional but preferred; surface a clear error if not configured
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        return jsonify({'error': 'Billing not configured. Missing STRIPE_SECRET_KEY or STRIPE_PRICE_ID.'}), 500

    # Create Checkout Session with subscription + trial
    try:
        success_url = f"{FRONTEND_URL.rstrip('/')}/login?paid=1&session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url  = f"{FRONTEND_URL.rstrip('/')}/login?canceled=1"

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            mode='subscription',
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            customer_email=email,
            subscription_data={
                'trial_period_days': int(TRIAL_DAYS),
                'metadata': {'user_email': email}
            },
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return jsonify({'checkoutUrl': session.url}), 200

    except stripe.error.StripeError as e:
        print(f"[STRIPE ERROR] {getattr(e, 'user_message', str(e))}")
        return jsonify({'error': 'Could not start payment process.'}), 500
    except Exception as e:
        print(f"[STRIPE ERROR] {e}")
        return jsonify({'error': 'Could not start payment process.'}), 500


@app.route('/api/login', methods=['POST'])
def login():
    """
    Owner login (active or within trial), with teammate fallback:
    teammates can sign in using the owner's password if the org is active/in trial.
    """
    data     = request.get_json(silent=True) or {}
    email    = _norm_email(data.get('email'))
    password = (data.get('password') or '').strip()

    if not email or not password:
        return jsonify({'error': 'Invalid credentials or account not active'}), 401

    users = load_users()

    # ---- 1) Owner / materialized user
    user = users.get(email)
    if user:
        allowed = (user.get('password') == password) and (
            (user.get('status') == 'active') or _within_trial(user, TRIAL_DAYS)
        )
        if allowed:
            return jsonify({
                'message': 'Login successful',
                'user': _user_payload(email, user)
            }), 200
        # fall through to teammate path if top-level record exists but isn't allowed

    # ---- 2) Teammate: login with OWNER's password
    team_key = f"user::{email}"
    team_rec = users.get(team_key)
    if not team_rec:
        return jsonify({'error': 'Invalid credentials or account not active'}), 401

    owner_email = _norm_email(team_rec.get('org_id') or "")
    owner_acct  = users.get(owner_email) or {}
    owner_pw    = owner_acct.get('password', '')
    owner_ok    = (owner_acct.get('status') == 'active') or _within_trial(owner_acct, TRIAL_DAYS)

    if not (owner_pw and password == owner_pw and owner_ok):
        return jsonify({'error': 'Invalid credentials or account not active'}), 401

    # Synthetic member view that borrows business visuals/info from the org owner
    member_user = {
        "email": email,
        "name":  team_rec.get("name") or (email.split("@")[0].title()),
        "business":      owner_acct.get("business", ""),
        "businessType":  owner_acct.get("businessType", ""),
        "teamSize":      owner_acct.get("teamSize", ""),
        "logo":          owner_acct.get("logo") or owner_acct.get("picture") or "",
        "status":        "active",
        "role":          team_rec.get("role", "member"),
        "org_id":        owner_acct.get("org_id") or owner_email,
    }

    # If there’s also a (failing) top-level user, prefer any of its non-empty fields
    if user:
        merged = dict(member_user)
        merged.update({k: v for k, v in user.items() if v not in (None, "", [])})
        member_user = merged

    return jsonify({
        'message': 'Login successful',
        'user': _user_payload(email, member_user)
    }), 200

@app.route('/api/oauth/google', methods=['POST'])
def google_oauth():
    """
    Validates the Google ID token, requires an existing account,
    updates missing name/logo opportunistically, and logs the user in
    if their account is active or within trial.
    """
    data = request.get_json(silent=True) or {}
    token = data.get('credential')
    if not token:
        return jsonify({'error': 'No Google token provided'}), 400

    try:
        idinfo  = id_token.verify_oauth2_token(token, grequests.Request(), GOOGLE_CLIENT_ID)
        email   = _norm_email(idinfo['email'])
        name    = idinfo.get('name', '') or ''
        picture = idinfo.get('picture', '') or ''

        users = load_users()
        user  = users.get(email)

        # No auto-provisioning — require prior signup
        if not user:
            return jsonify({'error': 'No account found for this Google email. Please sign up first.'}), 404

        # Opportunistic enrichment of missing fields
        changed = False
        if not user.get('name') and name:
            user['name'] = name; changed = True
        if not user.get('logo') and picture:
            user['logo'] = picture; changed = True
        if user.get('picture') and not user.get('logo'):
            user['logo'] = user['picture']; changed = True
        if changed:
            users[email] = user
            save_users(users)

        # Gate by active or in-trial
        if not (user.get('status') == 'active' or _within_trial(user, TRIAL_DAYS)):
            return jsonify({'error': 'Account not active. Please complete payment to activate.'}), 403

        return jsonify({'message': 'Google login successful', 'user': _user_payload(email, user)}), 200

    except Exception as e:
        print("[GOOGLE OAUTH ERROR]", e)
        return jsonify({'error': 'Invalid Google token'}), 401


@app.route('/api/oauth/google/complete', methods=['POST'])
def google_oauth_complete():
    """
    Unified 'complete' endpoint:
    - If called with no meaningful fields, behaves like a safe NO-OP (prevents 404 spam).
    - If profile fields are provided, updates the existing user (keeps status).
    """
    data         = request.get_json(silent=True) or {}
    email        = _norm_email(data.get('email'))
    businessType = (data.get('businessType') or '').strip()
    businessName = (data.get('businessName') or businessType).strip()
    name         = (data.get('name') or '').strip()
    logo         = (data.get('logo') or '').strip()
    people       = (data.get('people') or '').strip()

    if not email:
        # Strictly keep old noop’s success shape to avoid front-end errors
        return jsonify({"ok": True}), 200

    users = load_users()
    if email not in users:
        return jsonify({'error': 'User not found'}), 404

    user = users[email]
    # Only enrich; do not change status here
    user.update({
        'businessType': businessType or user.get('businessType',''),
        'business':     businessName or user.get('business',''),
        'name':         name or user.get('name',''),
        'logo':         logo or user.get('logo') or user.get('picture',''),
        'people':       people or user.get('people',''),
    })
    users[email] = user
    save_users(users)

    return jsonify({'message': 'Profile updated', 'user': _user_payload(email, users[email])}), 200


# ---------- Stripe: verify Checkout and activate ----------
@app.route("/api/stripe/verify", methods=["GET"])
def stripe_verify():
    sid = request.args.get("session_id")
    if not sid:
        return jsonify({"ok": False, "error": "missing session_id"}), 400

    try:
        # Retrieve Checkout Session and expand subscription for status
        session_obj = stripe.checkout.Session.retrieve(
            sid, expand=["subscription", "customer"]
        )

        email = (
            (session_obj.get("customer_details") or {}).get("email")
            or session_obj.get("customer_email")
            or (session_obj.get("metadata") or {}).get("user_email")
            or ""
        )
        email = _norm_email(email)
        if not email:
            return jsonify({"ok": False, "error": "no email on session"}), 400

        users = load_users()
        if email not in users:
            return jsonify({"ok": False, "error": "user not found"}), 404

        user = users[email]
        sub  = session_obj.get("subscription")
        sub_status = (sub.get("status") if isinstance(sub, dict) else None) or "active"

        # Treat active/trialing/past_due as allowed for app access
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

# ---------- helpers for Calendar token handling ----------
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
    users = load_users()
    user = users.get(email, {}) or {}
    if access_token:
        user["gcal_access_token"] = access_token
    # keep existing refresh token if Google doesn't send a new one
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
    access_token  = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")  # may be None if user already granted
    scope         = tokens.get("scope")
    if not access_token:
        return "Failed to obtain tokens", 400

    users = load_users()
    user = users.get(state, {})
    if not refresh_token:
        refresh_token = user.get("gcal_refresh_token")

    # Fetch calendars once (optional), tolerate failures
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

    # Save tokens & calendars
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
    users = load_users()
    user = users.get(email)
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
    users = load_users()
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
    users = load_users()
    user = users.get(email)
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
            _save_user_tokens(email, access_token=access_token)  # persist new AT
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
    users = load_users()
    user = users.get(email)
    if not user or not user.get("gcal_connected"):
        return jsonify({"error": "Not connected"}), 401

    access_token  = user.get("gcal_access_token")
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

    # Refresh once on 401
    if resp.status_code == 401 and refresh_token:
        try:
            new_tok = _google_refresh_access_token(refresh_token)
            access_token = new_tok.get("access_token") or access_token
            _save_user_tokens(email, access_token=access_token)  # store refreshed AT
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
from datetime import datetime as dt, timedelta

# cache template approvals (5m)
_TEMPLATE_CACHE = {}   # (name, lang_norm) -> {"status": "...", "checked_at": dt}
_TEMPLATE_TTL_SECONDS = 300

# in-memory throttle/cache for GET /api/whatsapp/messages
_MSG_CACHE = {}  # key=(user_email,lead_id) -> {"at": dt, "data": [...]}
_MSG_CACHE_TTL_SECONDS = 2

def _normalize_lang(code: str) -> str:
    """
    Keep 'en' as 'en'. Only normalize case/format:
      - ll      -> ll
      - ll_CC   -> ll_CC
    """
    import os
    default = (os.getenv("WHATSAPP_TEMPLATE_LANG") or "en").strip()
    if not code:
        return default
    c = str(code).replace("-", "_").strip()
    parts = c.split("_")
    if len(parts) == 1:
        return parts[0].lower()            # 'en'
    if len(parts) >= 2 and parts[0] and parts[1]:
        return parts[0].lower() + "_" + parts[1].upper()  # 'en_us' -> 'en_US'
    return c.lower()

def _primary_lang(code: str) -> str:
    if not code: return ""
    return code.replace("-", "_").split("_", 1)[0].lower()

def _norm_wa(s: str) -> str:
    """Normalize to digits; auto-prefix 10-digit NANP numbers with DEFAULT_COUNTRY_CODE."""
    import os, re
    d = re.sub(r"\D", "", s or "")
    dcc = os.getenv("DEFAULT_COUNTRY_CODE", "1")
    if len(d) == 10 and dcc.isdigit():
        d = dcc + d
    return d

def _lead_matches_wa(lead, wa_digits):
    for key in ("whatsapp", "phone"):
        if _norm_wa(lead.get(key)) == wa_digits:
            return True
    return False

def find_user_by_whatsapp(wa_id):
    wa = _norm_wa(wa_id)
    leads_by_user = load_leads()
    for user_email, leads in leads_by_user.items():
        for lead in leads:
            if _lead_matches_wa(lead, wa):
                return user_email
    return None

def find_lead_by_whatsapp(wa_id):
    wa = _norm_wa(wa_id)
    leads_by_user = load_leads()
    for user_email, leads in leads_by_user.items():
        for lead in leads:
            if _lead_matches_wa(lead, wa):
                return lead.get("id")
    return None

def _wa_env():
    import os
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_ID")
    if not token or not phone_id:
        raise RuntimeError("WhatsApp credentials missing")
    return token, phone_id

def build_personalized_body(user_email: str, lead_id: str, raw_text: str) -> str:
    users = load_users()
    leads_by_user = load_leads()
    u = users.get(user_email or "", {})
    user_name = (u.get("name") or "").strip()
    business  = (u.get("business") or "").strip()
    lead_name = ""
    if user_email and lead_id:
        for ld in leads_by_user.get(user_email, []):
            if str(ld.get("id")) == str(lead_id):
                lead_name = (ld.get("name") or "").strip()
                break
    parts = []
    if lead_name: parts.append(f"Hi {lead_name},")
    who = "it’s "
    if user_name and business: who += f"{user_name} from {business}"
    elif user_name: who += user_name
    elif business: who += business
    else: who = ""
    if who: parts.append(who + " —")
    raw = (raw_text or "").strip()
    body = (" ".join(parts) + " " + raw) if parts else raw
    return body[:4000] if len(body) > 4000 else body

def get_last_inbound_ts(user_email: str, lead_id: str):
    chats = load_chats()
    msgs = (chats.get(user_email, {}) or {}).get(lead_id, []) or []
    for m in reversed(msgs):
        if m.get("from") == "lead":
            return m.get("time")
    return None

def within_24h(user_email: str, lead_id: str) -> bool:
    ts = get_last_inbound_ts(user_email, lead_id)
    if not ts: return False
    try:
        last_dt = dt.fromisoformat(ts.replace("Z", ""))
    except Exception:
        return False
    return (dt.utcnow() - last_dt) <= timedelta(hours=24)

@app.get("/api/whatsapp/template-info")
def template_info():
    """
    Returns the components for a given template name from the sender phone's WABA,
    including a computed body parameter count and positions.
    """
    import os
    import requests as pyrequests

    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    # resolve WABA via phone
    waba_id = _resolve_waba_id()
    headers = {"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"}
    params = {"fields": "name,language,status,category,components", "limit": 200}
    url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"

    r = pyrequests.get(url, headers=headers, params=params, timeout=30)
    if not r.ok:
        try: body = r.json()
        except Exception: body = {"raw": r.text}
        return jsonify({"error": "graph_list_failed", "status": r.status_code, "resp": body}), r.status_code

    items = (r.json() or {}).get("data", [])
    out = []
    for t in items:
        if (t.get("name") or "") != name:
            continue
        comps = t.get("components") or []
        body = next((c for c in comps if (c.get("type") or "").upper() == "BODY"), {})
        params_list = body.get("parameters") or body.get("example", {}).get("body_text") or []
        if isinstance(params_list, list):
            if params_list and isinstance(params_list[0], list):
                body_param_count = max((len(x) for x in params_list), default=0)
            else:
                body_param_count = len(params_list)
        else:
            body_param_count = 0

        out.append({
            "name": t.get("name"),
            "language": _normalize_lang(t.get("language") or ""),
            "status": (t.get("status") or "").upper(),
            "body_param_count": body_param_count,
            "components": comps
        })

    if not out:
        return jsonify({"error": "template_not_found_on_phone_waba", "name": name, "waba_id": waba_id}), 404
    return jsonify({"waba_id": waba_id, "templates": out}), 200

def send_wa_text(to_number: str, body: str):
    import os
    import requests as pyrequests

    to = _norm_wa(to_number)
    token, phone_id = _wa_env()
    ver = os.getenv("WHATSAPP_API_VERSION", "v20.0")
    url = f"https://graph.facebook.com/{ver}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}}
    resp = pyrequests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        app.logger.error("[WA SEND ERROR] %s %s", resp.status_code, resp.text)
    return resp

def send_wa_template(to_number: str, template_name: str, lang_code: str, parameters: list | None = None):
    import os
    import requests as pyrequests

    to = _norm_wa(to_number)
    token, phone_id = _wa_env()
    ver = os.getenv("WHATSAPP_API_VERSION", "v20.0")
    url = f"https://graph.facebook.com/{ver}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    components = []
    if parameters is not None:
        components = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in parameters]}]
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {"name": template_name, "language": {"code": _normalize_lang(lang_code)}, "components": components}
    }
    resp = pyrequests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        app.logger.error("[WA TEMPLATE ERROR] %s %s", resp.status_code, resp.text)
    return resp

def _fetch_templates_raw():
    import os
    import requests as pyrequests
    waba_id = _resolve_waba_id()
    url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"
    params = {"fields": "name,language,status,category", "limit": 200}
    headers = {"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"}
    return pyrequests.get(url, headers=headers, params=params, timeout=30)

def _lookup_template_status(name: str, lang_api: str, force: bool = False) -> str:
    """Return status string. Exact (name+lang), else fallback to same primary language."""
    import os
    if not os.getenv("WHATSAPP_WABA_ID") and not os.getenv("WHATSAPP_PHONE_ID"):
        return "UNKNOWN"

    normalized_name = (name or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "") or "").strip()
    lang_norm = _normalize_lang(lang_api or os.getenv("WHATSAPP_TEMPLATE_LANG", "en") or "")
    key = (normalized_name, lang_norm)

    now = dt.utcnow()
    if not force:
        cached = _TEMPLATE_CACHE.get(key)
        if cached and (now - cached["checked_at"]) < timedelta(seconds=_TEMPLATE_TTL_SECONDS):
            return cached["status"]

    try:
        r = _fetch_templates_raw()
        items = (r.json() or {}).get("data", []) if r.ok else []
        primary = _primary_lang(lang_norm)
        exact_status = None
        fallback_status = None
        for t in items:
            if (t.get("name") or "") != normalized_name:
                continue
            tl_norm = _normalize_lang(t.get("language") or "")
            if tl_norm == lang_norm:
                exact_status = (t.get("status") or "UNKNOWN")
            if _primary_lang(tl_norm) == primary:
                st = (t.get("status") or "UNKNOWN")
                if (fallback_status or "").upper() != "APPROVED":
                    fallback_status = st

        status = exact_status or fallback_status or "PENDING"
        _TEMPLATE_CACHE[key] = {"status": status, "checked_at": now}
        return status
    except Exception as e:
        app.logger.warning(f"[WA TPL CHECK ERROR] {e}")
        _TEMPLATE_CACHE[key] = {"status": "UNKNOWN", "checked_at": now}
        return "UNKNOWN"

def is_template_approved(name: str, lang: str, force: bool = False) -> bool:
    return _lookup_template_status(name, lang, force).upper() == "APPROVED"

# Cache phone->WABA resolution (5 min)
_WABA_RES = {"id": None, "checked_at": None}
_WABA_TTL_SECONDS = 300

def _resolve_waba_id(force: bool = False) -> str:
    import os
    import requests as pyrequests

    now = dt.utcnow()
    if (
        not force
        and _WABA_RES["id"]
        and _WABA_RES["checked_at"]
        and (now - _WABA_RES["checked_at"]).total_seconds() < _WABA_TTL_SECONDS
    ):
        return _WABA_RES["id"]
    try:
        token, phone_id = _wa_env()
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
        app.logger.info("[WA WABA] resolved WABA id=%s", wid)
        return wid
    except Exception as e:
        app.logger.warning("[WA WABA] resolve error: %s", e)
        import os as _os
        return _os.getenv("WHATSAPP_WABA_ID") or _os.getenv("WHATSAPP_BUSINESS_ID", "")

def _fetch_templates_for_waba(waba_id: str):
    import os
    import requests as pyrequests
    headers = {"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"}
    params = {"fields": "name,language,status,category", "limit": 200}
    url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"
    return pyrequests.get(url, headers=headers, params=params, timeout=30)

# ---------- WhatsApp Routes ----------
@app.get("/api/whatsapp/health")
def whatsapp_health():
    import os
    return jsonify({
        "ok": True,
        "has_token": bool(os.getenv("WHATSAPP_TOKEN")),
        "has_phone_id": bool(os.getenv("WHATSAPP_PHONE_ID")),
        "has_waba_id": bool(os.getenv("WHATSAPP_WABA_ID")),
        "default_template": os.getenv("WHATSAPP_TEMPLATE_DEFAULT"),
        "default_lang_ui": _primary_lang(os.getenv("WHATSAPP_TEMPLATE_LANG", "en")) or "en",
        "default_lang_api": _normalize_lang(os.getenv("WHATSAPP_TEMPLATE_LANG", "en")),
    }), 200

@app.get("/api/whatsapp/templates")
def list_templates():
    import os
    if not os.getenv("WHATSAPP_TOKEN") or not os.getenv("WHATSAPP_PHONE_ID"):
        return jsonify({"error": "Missing token or phone id"}), 400
    waba_id = _resolve_waba_id()
    r = _fetch_templates_raw()
    try:
        data = r.json()
        for t in data.get("data", []):
            t["normalized_language"] = _normalize_lang(t.get("language",""))
    except Exception:
        data = {"raw": r.text}
    return jsonify({"status": r.status_code, "waba_id": waba_id, "data": data}), r.status_code

@app.get("/api/whatsapp/template-state")
def template_state():
    import os
    name = (request.args.get("name") or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "") or "").strip()
    lang = request.args.get("language_code") or os.getenv("WHATSAPP_TEMPLATE_LANG", "en") or ""
    force = request.args.get("force") == "1"
    status = _lookup_template_status(name, lang, force)
    return jsonify({
        "name": name,
        "language": _normalize_lang(lang),
        "status": status.upper(),
        "approved": status.upper() == "APPROVED",
        "checked_at": dt.utcnow().isoformat() + "Z"
    }), 200

@app.get("/api/whatsapp/window-state")
def whatsapp_window_state():
    import os
    user_email = request.args.get("user_email", "")
    lead_id    = request.args.get("lead_id", "")
    template_name = (request.args.get("template_name") or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "") or "").strip()
    lang_code     = request.args.get("language_code") or os.getenv("WHATSAPP_TEMPLATE_LANG", "en") or ""
    force = request.args.get("force") == "1"

    lang_norm = _normalize_lang(lang_code)
    inside = within_24h(user_email, lead_id)
    status = "APPROVED" if inside else _lookup_template_status(template_name, lang_norm, force)

    return jsonify({
        "inside24h": inside,
        "templateApproved": inside or (status.upper() == "APPROVED"),
        "templateStatus": status.upper(),
        "templateName": template_name,
        "language": lang_norm,
        "canFreeText": inside,
        "canTemplate": (not inside) and (status.upper() == "APPROVED")
    }), 200

# ---- throttle/cache helper for messages
def _get_thread_cached(user_email, lead_id):
    key = (str(user_email or ""), str(lead_id or ""))
    now = dt.utcnow()
    cached = _MSG_CACHE.get(key)
    if cached and (now - cached["at"]).total_seconds() < _MSG_CACHE_TTL_SECONDS:
        return cached["data"], True
    chats = load_chats()
    msgs = (chats.get(user_email, {}) or {}).get(lead_id, []) or []
    _MSG_CACHE[key] = {"at": now, "data": msgs}
    return msgs, False

@app.route('/api/whatsapp/messages', methods=['GET'])
def get_whatsapp_messages():
    user_email = request.args.get("user_email")
    lead_id = request.args.get("lead_id")
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
    user_email = data.get("user_email")
    lead_id = data.get("lead_id")
    opt_out = bool(data.get("opt_out", True))
    if not user_email or not lead_id:
        return jsonify({"error": "user_email and lead_id required"}), 400
    leads = load_leads()
    arr = leads.get(user_email, []) or []
    for ld in arr:
        if str(ld.get("id")) == str(lead_id):
            ld["wa_opt_out"] = bool(opt_out)
    leads[user_email] = arr
    save_leads(leads)
    return jsonify({"ok": True, "opt_out": opt_out}), 200

@app.route('/api/whatsapp/send', methods=['POST'])
def send_whatsapp_message():
    """
    Inside 24h: free text (requires 'message') — NOW sends EXACTLY what the user typed (no intro).
    Outside 24h:
      • Resolve the SENDER PHONE's WABA
      • List templates from THAT WABA
      • Choose locale:
          1) exact requested if APPROVED
          2) any APPROVED with same primary (e.g., en_*)
          3) any APPROVED
        If none approved → 409 with availableLanguages (no raw 132001 to client).
    """
    import os
    import requests as pyrequests

    data = request.get_json(force=True) or {}

    def clean(v):
        try: return str(v).strip() if v is not None else ""
        except Exception: return ""

    to_number       = clean(data.get("to") or data.get("phone"))
    raw_msg         = clean(data.get("message") or data.get("text"))
    user_email      = clean(data.get("user_email"))
    lead_id         = clean(data.get("lead_id"))
    # deprecated: skip_personalization support retained but ignored inside 24h
    skip_personalization = bool(data.get("skip_personalization", False))
    template_name   = clean(data.get("template_name") or (os.getenv("WHATSAPP_TEMPLATE_DEFAULT") or ""))
    language_code   = clean(data.get("language_code") or (os.getenv("WHATSAPP_TEMPLATE_LANG") or "en"))

    # Only include components if explicitly provided
    raw_params = data.get("template_params")
    if isinstance(raw_params, str):
        raw_params = [p.strip() for p in raw_params.split(",") if p.strip()]
    elif not isinstance(raw_params, list):
        raw_params = None
    params = raw_params if raw_params and len(raw_params) > 0 else None

    if not to_number:
        return jsonify({"ok": False, "error": "Recipient 'to' is required"}), 400

    # Opt-out check
    if user_email and lead_id:
        for ld in load_leads().get(user_email, []) or []:
            if str(ld.get("id")) == str(lead_id) and bool(ld.get("wa_opt_out")):
                return jsonify({"ok": False, "error": "Lead has opted out of WhatsApp messages"}), 403

    inside24 = within_24h(user_email, lead_id)
    requested_raw = language_code
    requested     = _normalize_lang(language_code)
    primary       = _primary_lang(requested)
    to_number     = _norm_wa(to_number)

    # Resolve the EXACT WABA tied to the PHONE we send from
    waba_id = _resolve_waba_id()
    app.logger.info("[WA SEND V3] to=%s tpl=%s requested=%s (raw=%s) inside24h=%s waba=%s",
                    to_number, template_name, requested, requested_raw, inside24, waba_id)

    try:
        if inside24:
            # === FIX: ALWAYS send the raw user text during the 24h window (no intro/prefix) ===
            if not raw_msg:
                return jsonify({"ok": False, "error": "Message text required inside 24h"}), 400
            body = raw_msg
            resp = send_wa_text(to_number, body)
            mode = "free_text"; sent_text = body; used_lang = None

        else:
            if not template_name:
                return jsonify({"ok": False, "error": "Template name is required outside 24h.", "code": "TEMPLATE_REQUIRED_OUTSIDE_24H"}), 422

            # List templates FROM THE PHONE'S WABA
            r_list = _fetch_templates_for_waba(waba_id)
            if not getattr(r_list, "ok", False):
                try: body = r_list.json()
                except Exception: body = {"raw": r_list.text}
                app.logger.error("[WA SEND V3] list_templates failed status=%s body=%s",
                                 getattr(r_list, "status_code", None), body)
                return jsonify({
                    "ok": False,
                    "error": "Failed to fetch templates from Graph.",
                    "code": "GRAPH_LIST_TEMPLATES_FAILED",
                    "status": getattr(r_list, "status_code", None),
                    "resp": body
                }), 502

            items = (r_list.json() or {}).get("data", [])

            # Collect locales for this template name on THIS WABA
            locales = []
            for t in items:
                if (t.get("name") or "") == template_name:
                    ln = _normalize_lang(t.get("language") or "")
                    st = (t.get("status") or "").upper()
                    locales.append({"language": ln, "status": st})

            if not locales:
                app.logger.warning("[WA SEND V3] template not found on phone's WABA: %s (waba=%s)", template_name, waba_id)
                return jsonify({
                    "ok": False,
                    "error": f"Template '{template_name}' does not exist on this WABA.",
                    "code": "TEMPLATE_NAME_NOT_FOUND_ON_WABA",
                    "template": template_name,
                    "waba_id": waba_id
                }), 404

            exact = next((x for x in locales if x["language"] == requested), None)
            approved_any = [x for x in locales if x["status"] == "APPROVED"]
            approved_same_primary = [x for x in approved_any if _primary_lang(x["language"]) == primary]

            fallback_used = False
            fallback_reason = None
            used_lang = requested

            if exact and exact["status"] == "APPROVED":
                reason = "exact_locale_approved"
            elif approved_same_primary:
                used_lang = approved_same_primary[0]["language"]; fallback_used = True
                fallback_reason = "requested_locale_missing_or_unapproved_same_primary_used"; reason = "fallback_same_primary"
            elif approved_any:
                used_lang = approved_any[0]["language"]; fallback_used = True
                fallback_reason = "requested_locale_missing_or_unapproved_any_approved_used"; reason = "fallback_any"
            else:
                app.logger.info("[WA SEND V3] no approved locales for tpl=%s on waba=%s locales=%s", template_name, waba_id, locales)
                return jsonify({
                    "ok": False,
                    "error": "Template is not approved in any locale; cannot send outside 24h window.",
                    "code": "TEMPLATE_NOT_APPROVED_ANY_LOCALE",
                    "template": template_name,
                    "waba_id": waba_id,
                    "requestedLanguage": requested,
                    "availableLanguages": locales
                }), 409

            app.logger.info("[WA SEND V3] tpl=%s choose_lang=%s reason=%s requested=%s waba=%s locales=%s",
                            template_name, used_lang, reason, requested, waba_id, locales)

            resp = send_wa_template(to_number, template_name, used_lang, params)
            # we persist an echo for UI; your frontend strips the tag for display
            sent_text = f"[template:{template_name}/{used_lang}] {raw_msg or ''}"
            mode = "template"

        # Parse Graph response
        try: result = resp.json()
        except Exception: result = {"raw": resp.text}

        if resp.status_code >= 400:
            err = {}
            try: err = result.get("error", {})
            except Exception: pass
            app.logger.error("[WA SEND V3 ERROR] status=%s error=%s", resp.status_code, resp.text)
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

        # message id
        msg_id = None
        if isinstance(result, dict):
            arr = result.get("messages")
            if isinstance(arr, list) and arr:
                msg_id = arr[0].get("id")

        # persist + warm cache
        try:
            chats = load_chats()
            user_chats = (chats.get(user_email, {}) or {})
            arr = (user_chats.get(lead_id, []) or [])
            arr.append({"from": "user", "text": sent_text, "time": dt.utcnow().isoformat() + "Z"})
            user_chats[lead_id] = arr; chats[user_email] = user_chats; save_chats(chats)
            if msg_id:
                statuses = load_statuses()
                statuses[msg_id] = {"status": "sent_request", "user_email": user_email, "lead_id": lead_id,
                                    "to": to_number, "mode": mode, "time": dt.utcnow().isoformat() + "Z"}
                save_statuses(statuses)
            _MSG_CACHE[(str(user_email or ""), str(lead_id or ""))] = {"at": dt.utcnow(), "data": arr}
        except Exception as e:
            app.logger.warning("[WHATSAPP] save message/status error: %s", e)

        out = {"ok": True, "mode": mode, "status": resp.status_code, "message_id": msg_id,
               "requestedLanguage": requested, "usedLanguage": used_lang,
               "waba_id": waba_id,
               "fallbackUsed": (used_lang is not None and used_lang != requested)}
        if mode == "template":
            out["availableLanguages"] = locales
            if out["fallbackUsed"]: out["fallbackReason"] = fallback_reason
        return jsonify(out), resp.status_code

    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    except pyrequests.RequestException as e:
        return jsonify({"ok": False, "error": f"Network error: {e}"}), 502


@app.get("/api/whatsapp/debug/template-locales")
def debug_template_locales():
    import os
    r = _fetch_templates_raw()
    name = (request.args.get("name") or "").strip()
    items = (r.json() or {}).get("data", []) if r.ok else []
    locales = [{"language": _normalize_lang(t.get("language") or ""), "status": (t.get("status") or "").upper()}
               for t in items if (t.get("name") or "") == name] if name else []
    token, phone_id = _wa_env()
    return jsonify({
        "phone_id": phone_id,
        "resolved_waba_id": _resolve_waba_id(),
        "template_name": name or None,
        "locales": locales,
        "raw_status": r.status_code
    }), 200

def _verify_meta_signature(raw_body: bytes, header_sig: str) -> bool:
    import os, hmac, hashlib
    secret = os.getenv("APP_SECRET") or os.getenv("META_APP_SECRET")
    if not secret or not header_sig:
        return True
    try:
        if not header_sig.startswith("sha256="): return False
        sent = header_sig.split("=", 1)[1]
        mac = hmac.new(secret.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
        return hmac.compare_digest(mac.hexdigest(), sent)
    except Exception:
        return False

@app.route("/api/whatsapp/webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    import os
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
                value = change.get("value", {})

                # delivery/read statuses
                for status in value.get("statuses", []):
                    statuses = load_statuses()
                    statuses[status.get("id") or "unknown"] = {
                        "status": status.get("status"),
                        "timestamp": status.get("timestamp"),
                        "recipient": status.get("recipient_id"),
                        "errors": status.get("errors")
                    }
                    save_statuses(statuses)

                # inbound messages
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])
                sender_waid = contacts[0].get("wa_id") if contacts else None

                for m in messages:
                    t = m.get("type")
                    if t == "text": text = m.get("text", {}).get("body", "")
                    elif t == "interactive": text = str(m.get("interactive"))
                    elif t == "button": text = str(m.get("button"))
                    else: text = f"[{t} message]"

                    # opt-out / opt-in
                    if sender_waid and isinstance(text, str):
                        up = text.strip().upper()
                        if up in ("STOP", "UNSUBSCRIBE", "STOP ALL", "CANCEL"):
                            wa = _norm_wa(sender_waid)
                            data = load_leads()
                            changed = False
                            for _, leads in data.items():
                                for ld in leads:
                                    if _lead_matches_wa(ld, wa):
                                        ld["wa_opt_out"] = True
                                        changed = True
                            if changed: save_leads(data)
                            try: send_wa_text(sender_waid, "You have been unsubscribed. Reply START to opt back in.")
                            except Exception: pass
                        elif up in ("START", "UNSTOP", "SUBSCRIBE"):
                            wa = _norm_wa(sender_waid)
                            data = load_leads()
                            changed = False
                            for _, leads in data.items():
                                for ld in leads:
                                    if _lead_matches_wa(ld, wa):
                                        ld["wa_opt_out"] = False
                                        changed = True
                            if changed: save_leads(data)
                            try: send_wa_text(sender_waid, "You are now opted back in. You can reply STOP anytime to opt out.")
                            except Exception: pass

                    # save inbound to proper thread
                    user_email = find_user_by_whatsapp(sender_waid) if sender_waid else None
                    lead_id = find_lead_by_whatsapp(sender_waid) if sender_waid else None
                    chats = load_chats()
                    user_chats = (chats.get(user_email, {}) or {})
                    arr = (user_chats.get(lead_id, []) or [])
                    arr.append({"from": "lead", "text": text, "time": dt.utcnow().isoformat() + "Z"})
                    user_chats[lead_id] = arr
                    chats[user_email] = user_chats
                    save_chats(chats)
                    _MSG_CACHE[(str(user_email or ""), str(lead_id or ""))] = {"at": dt.utcnow(), "data": arr}

    except Exception as e:
        app.logger.warning("[WHATSAPP WEBHOOK] parse error: %s", e)

    return "OK", 200

# --- AI: lightweight prompt for chat composer ---
@app.post("/api/ai-prompt")
def ai_prompt():
    import os, re
    import requests

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    user_email = (data.get("user_email") or "").strip()
    lead_id    = str(data.get("lead_id") or "").strip()

    if not user_email or not lead_id:
        return jsonify({"error": "user_email and lead_id are required"}), 400

    users = load_users()
    leads_by_user = load_leads()
    chats_by_user = load_chats()

    user = users.get(user_email, {}) or {}
    user_name = (user.get("name") or "").strip()
    business  = (user.get("business") or user.get("businessType") or "business").strip()

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

    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    if not OPENROUTER_API_KEY:
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

    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-4o",
                "messages": [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 220,
                "temperature": 0.7,
            },
            timeout=30,
        )
        j = r.json() if r.ok else {}
        prompt = (
            (j.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not prompt:
            return jsonify({"error": j.get("error", {}).get("message", "AI response was empty")}), 502

        def _clean(t: str) -> str:
            s = str(t or "")
            s = re.sub(r"^(Subject|Lead Name|Recipient)\s*:\s*.*\n?", "", s, flags=re.I | re.M)
            s = re.sub(r"^\s*[\w ]+:\s*$", "", s, flags=re.M)
            s = re.sub(r"^\s*\n+", "", s)
            return s.strip()

        return jsonify({"prompt": _clean(prompt)}), 200

    except Exception as e:
        app.logger.warning(f"[AI PROMPT ERROR] {e}")
        return jsonify({"error": "Failed to get AI response"}), 502

# =================================================================
# AUTOMATIONS (INLINE) — Blueprint + Engine (prod-ready routes)
# =================================================================
# Assumes you already have: app (Flask), request, jsonify, os, json,
# datetime, uuid, urlparse, List, Dict, Any, Optional, requests,
# and your app-level helpers: load_leads, save_leads, load_chats,
# save_chats, SENDGRID_API_KEY, SENDER_EMAIL, OPENROUTER_API_KEY,
# FILE_AUTOMATIONS, FILE_STATE, FILE_NOTIFICATIONS, FILE_USERS, etc.
# =================================================================

# ---------- Channels ----------
CHANNEL_EMAIL = "email"
CHANNEL_WHATSAPP = "whatsapp"

# ---------- Utilities ----------
def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)

def _read_json2(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json2(path: str, data: Any):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def _ensure_files2():
    if not os.path.exists(FILE_AUTOMATIONS):
        _write_json2(FILE_AUTOMATIONS, {"users": {}})
    if not os.path.exists(FILE_STATE):
        _write_json2(FILE_STATE, {})
    if not os.path.exists(FILE_NOTIFICATIONS):
        _write_json2(FILE_NOTIFICATIONS, {"notifications": []})
    if not os.path.exists(FILE_USERS):
        _write_json2(FILE_USERS, {"users": {}})

# ---------- Notifications ----------
def _create_notification(owner_email: str, title: str, body: str):
    data = _read_json2(FILE_NOTIFICATIONS, {"notifications": []})
    notif = {
        "id": str(uuid.uuid4()),
        "owner": (owner_email or "").lower(),
        "title": title,
        "body": body,
        "created_at": _now_utc().isoformat()
    }
    data.setdefault("notifications", []).insert(0, notif)
    _write_json2(FILE_NOTIFICATIONS, data)

# ---------- User Profiles ----------
def _load_user_profile(user_email: str) -> Dict[str, Any]:
    db = _read_json2(FILE_USERS, {"users": {}})
    return db.get("users", {}).get((user_email or "").lower(), {})

def _save_user_profile(user_email: str, profile: Dict[str, Any]):
    db = _read_json2(FILE_USERS, {"users": {}})
    db.setdefault("users", {})[(user_email or "").lower()] = profile
    _write_json2(FILE_USERS, db)

# ---------- Automations storage ----------
def _load_user_flows(user_email: str) -> List[Dict[str, Any]]:
    db = _read_json2(FILE_AUTOMATIONS, {"users": {}})
    return db.get("users", {}).get((user_email or "").lower(), [])

def _save_user_flows(user_email: str, flows: List[Dict[str, Any]]):
    db = _read_json2(FILE_AUTOMATIONS, {"users": {}})
    db.setdefault("users", {})[(user_email or "").lower()] = flows
    _write_json2(FILE_AUTOMATIONS, db)

def _load_state() -> Dict[str, Any]:
    return _read_json2(FILE_STATE, {})

def _save_state(state: Dict[str, Any]):
    _write_json2(FILE_STATE, state)

# ---------- Request helper ----------
def _user_from_request() -> str:
    h = request.headers.get("X-User-Email")
    if h:
        return h.strip().lower()
    q = request.args.get("user") or (request.json.get("user") if request.is_json else None)
    return (q or "demo@retainai.ca").strip().lower()

# ---------- Time helpers ----------
def _dt(s: Optional[str]) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromisoformat(s) if s else None
    except Exception:
        return None

def _is_valid_url(u: str) -> bool:
    try:
        p = urlparse(u)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

def _in_quiet_hours(now_utc: datetime.datetime, profile: Dict[str, Any]) -> bool:
    qs = profile.get("quiet_hours_start")
    qe = profile.get("quiet_hours_end")
    if qs is None or qe is None:
        return False
    hour = now_utc.hour
    if qs > qe:
        return hour >= qs or hour < qe
    else:
        return qs <= hour < qe

# ---------- Triggers & Conditions ----------
from datetime import timedelta as _td

def trig_no_reply(lead: Dict[str, Any], days: int) -> bool:
    last_inbound = _dt(lead.get("last_inbound_at"))
    last_outbound = _dt(lead.get("last_outbound_at"))
    last_any = _dt(lead.get("last_activity_at")) or last_inbound or last_outbound
    if not last_any:
        created = _dt(lead.get("createdAt")) or _dt(lead.get("created_at")) or (_now_utc() - _td(days=999))
        return _now_utc() - created >= _td(days=days)
    if last_inbound and (_now_utc() - last_inbound < _td(days=days)):
        return False
    return _now_utc() - last_any >= _td(days=days)

def trig_new_lead(lead: Dict[str, Any], within_hours: int = 24) -> bool:
    created = _dt(lead.get("createdAt")) or _dt(lead.get("created_at"))
    return bool(created and (_now_utc() - created <= _td(hours=within_hours)))

def trig_no_show(lead: Dict[str, Any]) -> bool:
    for appt in (lead.get("appointments") or []):
        if str(appt.get("status") or "").lower().replace("_", "-") == "no-show" and not appt.get("automation_seen_no_show"):
            return True
    return False

def cond_no_reply_since(lead: Dict[str, Any], days: int) -> bool:
    last_inbound = _dt(lead.get("last_inbound_at"))
    return not last_inbound or (_now_utc() - last_inbound >= _td(days=days))

def cond_no_booking_since(lead: Dict[str, Any], days: int = 2) -> bool:
    for appt in (lead.get("appointments") or []):
        if str(appt.get("status") or "").lower() in ("booked", "scheduled", "confirmed"):
            upd = _dt(appt.get("updated_at"))
            if upd and (_now_utc() - upd < _td(days=days)):
                return False
    return True

# ---------- Token rendering ----------
MISSING = "⛔"

def _render_text(tmpl: str, lead: Dict[str, Any], run: Dict[str, Any], profile: Dict[str, Any]) -> str:
    if not isinstance(tmpl, str):
        return tmpl
    business_name = profile.get("business_name") or f"{MISSING} add your business name in Automations > Settings"
    booking_link = profile.get("booking_link") or f"{MISSING} add your booking link in Automations > Settings"
    out = tmpl
    out = out.replace("{{business_name}}", business_name)
    out = out.replace("{{booking_link}}", booking_link)
    out = out.replace("{{lead.first_name}}", str(lead.get("first_name") or lead.get("name") or ""))
    out = out.replace("{{lead.full_name}}", str(lead.get("name") or ""))
    out = out.replace("{{last_ai_text}}", (run.get("memo", {}).get("last_ai_text") or ""))
    return out

def _contains_blockers(text: str) -> bool:
    return MISSING in (text or "")

# ---------- External channel actions ----------
def send_email_sendgrid_auto(to_email: str, subject: str, html: str, business_name: str) -> bool:
    if not SENDGRID_API_KEY:
        print("[Automations] SENDGRID_API_KEY missing; skipping email send (simulated).")
        return True
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email
        sg = sendgrid.SendGridAPIClient(SENDGRID_API_KEY)
        msg = Mail(
            from_email=Email(SENDER_EMAIL, business_name or "RetainAI"),
            to_emails=to_email,
            subject=subject,
            html_content=html,
        )
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
    if not OPENROUTER_API_KEY:
        return f"Hey {lead_name}, just checking in — want to grab a spot with {business_name}? Book here: {booking}."
    try:
        prompt = (
            "Write a short, friendly follow-up message (<= 45 words).\n"
            f"Business: {business_name}.\n"
            f"Booking link: {booking}.\n"
            f"Lead context: {json.dumps(context.get('lead', {}))}.\n"
            "Tone: warm, human, no emojis, 1 sentence if possible."
        )
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
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

from sendgrid.helpers.mail import Email
import hashlib, time

_LAST_SEND_CACHE = {}
_LAST_SEND_TTL_SEC = 120  # duplicate-click guard

def _first_nonempty(*vals):
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _dedupe_ok(key):
    now = time.time()
    item = _LAST_SEND_CACHE.get(key)
    if item and (now - item["at"] < _LAST_SEND_TTL_SEC):
        return False
    _LAST_SEND_CACHE[key] = {"at": now}
    return True

def _coalesce_to_email(data: dict) -> str:
    lead_obj = data.get("lead") or {}
    return _first_nonempty(
        data.get("to"), data.get("email"), data.get("lead_email"), data.get("leadEmail"),
        data.get("recipient"), lead_obj.get("email"), lead_obj.get("mail")
    )

def _find_owner_by_lead_email(lead_email: str) -> str | None:
    """If FE didn't send user_email, infer the owner from leads.json by recipient email."""
    if not lead_email:
        return None
    lbsu = load_leads()
    for owner_email, arr in (lbsu or {}).items():
        for ld in arr or []:
            if (ld.get("email") or "").strip().lower() == lead_email.strip().lower():
                return owner_email
    return None

# --- FE compatibility: /api/send-ai-message  -------------------------------
from sendgrid.helpers.mail import Email

@app.route('/api/send-ai-message', methods=['POST'])
def send_ai_message():
    """
    Sends the AI-written message via your SendGrid dynamic templates.

    From:     "<Business Name>" <noreply@retainai.ca>
    Reply-To: owner (user) email
    Subject:  EXACTLY what the caller provides (not the template type)
    Body:     EXACT AI text you provide in `message` (also mirrored to a few keys)
    """
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON body"}), 400

    # recipient
    lead = data.get("lead") or {}
    to_email = (
        data.get("to") or data.get("email") or data.get("lead_email") or
        data.get("leadEmail") or lead.get("email")
    )
    if not to_email:
        return jsonify({"error": "Recipient 'to' is required"}), 400

    # owner / user
    owner_email = (data.get("user_email") or request.headers.get("X-User-Email") or "").strip().lower()
    if not owner_email:
        # try to infer owner by searching leads store
        lbsu = load_leads()
        for owner, arr in (lbsu or {}).items():
            for ld in (arr or []):
                if (ld.get("email") or "").strip().lower() == to_email.strip().lower():
                    owner_email = (owner or "").lower()
                    break
            if owner_email:
                break

    users = load_users()
    user_profile = users.get(owner_email, {}) if owner_email else {}

    # display name = business name (fallbacks)
    business_name = (
        (data.get("businessName") or data.get("business") or data.get("user_business") or "").strip()
        or user_profile.get("business") or user_profile.get("businessType") or "Your Business"
    )
    user_name = (data.get("userName") or data.get("user_name") or user_profile.get("name") or "").strip()
    lead_name = (data.get("leadName") or lead.get("name") or "").strip()

    # choose SendGrid template by promptType (subject is independent)
    prompt_type = (data.get("promptType") or data.get("type") or "reengage").strip().lower()
    TEMPLATE_MAP = {
        "followup":    SG_TEMPLATE_FOLLOWUP_LEAD,
        "reengage":    SG_TEMPLATE_REENGAGE_LEAD,
        "apology":     SG_TEMPLATE_APOLOGY_LEAD,
        "upsell":      SG_TEMPLATE_UPSELL_LEAD,
        "birthday":    SG_TEMPLATE_BIRTHDAY,
        "appointment": SG_TEMPLATE_APPT_CONFIRM,
    }
    template_id = TEMPLATE_MAP.get(prompt_type, SG_TEMPLATE_FOLLOWUP_LEAD)

    # AI body text (must come from caller; e.g., /api/generate_prompt)
    model_text = (
        data.get("message") or data.get("prompt") or data.get("ai_text") or
        data.get("body") or data.get("text") or ""
    ).strip()
    if not model_text:
        return jsonify({"error": "No AI text provided (pass it in 'message')."}), 422

    # subject = exactly what the caller sends
    subject = (data.get("subject") or data.get("emailSubject") or data.get("subjectLine") or "Quick note").strip()

    # optional extras your templates may use
    tags_val = data.get("tags") or lead.get("tags") or []
    tags = ", ".join([str(t) for t in tags_val]) if isinstance(tags_val, list) else str(tags_val or "")
    notes = (data.get("notes") or lead.get("notes") or "").strip()
    booking_link = (data.get("booking_link") or data.get("bookingLink") or user_profile.get("booking_link") or "").strip()

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
        # expose the AI body under multiple keys (whichever your template expects)
        "ai_text": model_text, "message": model_text, "content": model_text,
        "text": model_text, "body": model_text, "prompt": model_text
    }

    ok = send_email_with_template(
        to_email=to_email,
        template_id=template_id,
        dynamic_data=dynamic_data,
        subject=subject,
        from_email=Email(SENDER_EMAIL, business_name),  # shows the user's business as the sender name
        reply_to_email=owner_email or None              # pass a STRING here (not Email()) to avoid the earlier TypeError
    )

    return jsonify({
        "sent": bool(ok),
        "template_id": template_id,
        "subject": subject,
        "to": to_email,
        "from_display": business_name,
        "from_email": SENDER_EMAIL,
        "reply_to": owner_email or None,
        "used_text": model_text
    }), (200 if ok else 502)

# ---------- WhatsApp helpers ----------
def _normalize_lang(s: str) -> str:
    s = (s or "").strip().replace("-", "_")
    return s.lower()

def _primary_lang(s: str) -> str:
    s = _normalize_lang(s)
    return s.split("_", 1)[0] if s else ""

def _resolve_waba_id() -> Optional[str]:
    return os.getenv("WHATSAPP_WABA_ID") or None

def _fetch_templates_for_waba(waba_id: Optional[str]):
    class _Resp:
        ok = False
        def json(self): return {}
    if not waba_id:
        return _Resp()
    try:
        url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"
        headers = {"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN','')}"}
        params = {"fields": "name,language,status,components", "limit": 200}
        r = requests.get(url, headers=headers, params=params, timeout=30)
        return r
    except Exception:
        return _Resp()

# These are referenced by the engine; you likely already have implementations:
# within_24h(user_email, lead_id), send_wa_text(to, text), send_wa_template(to, name, lang, params)

def _append_chat_message(user_email: str, lead_id: str, text: str):
    try:
        chats = load_chats()
        user_chats = (chats.get(user_email, {}) or {})
        lid = str(lead_id or "")
        arr = (user_chats.get(lid, []) or [])
        arr.append({"from": "user", "text": text, "time": _now_utc().isoformat().replace("+00:00", "") + "Z"})
        user_chats[lid] = arr
        chats[user_email] = user_chats
        save_chats(chats)
        try:
            _MSG_CACHE[(str(user_email or ""), str(lead_id or ""))] = {"at": datetime.datetime.utcnow(), "data": arr}
        except Exception:
            pass
    except Exception as e:
        print("[Automations] append_chat_message error:", e)

def _choose_wa_template(preferred_name: str | None, preferred_lang: str | None):
    import os
    name = (preferred_name or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "")).strip()
    if not name:
        return None, None, 0

    waba_id = _resolve_waba_id()
    r_list = _fetch_templates_for_waba(waba_id)
    items = (r_list.json() or {}).get("data", []) if getattr(r_list, "ok", False) else []

    requested = _normalize_lang(preferred_lang or os.getenv("WHATSAPP_TEMPLATE_LANG", "en"))
    primary = _primary_lang(requested)

    locales = []
    for t in items:
        if (t.get("name") or "") == name:
            locales.append({"language": _normalize_lang(t.get("language") or ""), "status": (t.get("status") or "").upper()})

    used_lang = requested
    exact = next((x for x in locales if x["language"] == requested and x["status"] == "APPROVED"), None)
    if not exact:
        same_primary = next((x for x in locales if _primary_lang(x["language"]) == primary and x["status"] == "APPROVED"), None)
        any_appr = next((x for x in locales if x["status"] == "APPROVED"), None)
        used_lang = (same_primary or any_appr or {"language": requested})["language"]

    # Re-compute BODY param count for chosen locale
    body_param_count = 0
    try:
        for t in items:
            if (t.get("name") == name) and (_normalize_lang(t.get("language") or "") == used_lang):
                comps = t.get("components") or []
                body = next((c for c in comps if (c.get("type") or "").upper() == "BODY"), {})
                params_list = body.get("parameters") or body.get("example", {}).get("body_text") or []
                if isinstance(params_list, list):
                    if params_list and isinstance(params_list[0], list):
                        body_param_count = max((len(x) for x in params_list), default=0)
                    else:
                        body_param_count = len(params_list)
                break
    except Exception as e:
        print("[Automations] template components fetch error:", e)

    return name, used_lang, int(body_param_count or 0)

def _build_wa_params(count: int, lead: dict, profile: dict, run: dict, rendered_text: str | None):
    vals = []
    first = lead.get("first_name") or (lead.get("name") or "").split(" ")[0]
    if first: vals.append(first)
    if profile.get("business_name"): vals.append(profile["business_name"])
    if profile.get("booking_link"):  vals.append(profile["booking_link"])
    if rendered_text: vals.append(rendered_text)
    vals = (vals + [""] * count)[:count]
    return vals

def _send_whatsapp_with_window(flow, step, lead, run, caps, profile) -> bool:
    if caps.get("respect_quiet_hours", True) and _in_quiet_hours(_now_utc(), profile):
        return False
    per_hours = int(caps.get("per_lead_per_day", 1)) * 24
    if not _can_send(run, CHANNEL_WHATSAPP, per_hours=per_hours):
        return False

    user_email = (lead.get("owner") or flow.get("owner") or "").lower()
    lead_id = str(lead.get("id") or lead.get("email") or lead.get("phone") or "")
    to = lead.get("phone") or lead.get("whatsapp")
    if not to:
        return True
    if bool(lead.get("wa_opt_out")):
        return True

    raw = step.get("text") or run.get("memo", {}).get("last_ai_text") or ""
    body = _render_text(raw, lead, run, profile)
    if _contains_blockers(body):
        _create_notification(user_email, "Setup needed",
                             "WhatsApp message blocked: missing profile values (booking link / business name).")
        return True

    inside24 = False
    try:
        inside24 = within_24h(user_email, lead_id)
    except Exception:
        pass

    if inside24:
        try:
            resp = send_wa_text(to, body)
            ok = getattr(resp, "status_code", 500) < 400
        except Exception as e:
            print("[Automations] WA free-text send error:", e)
            ok = False
        if ok:
            _mark_sent(run, CHANNEL_WHATSAPP)
            _append_chat_message(user_email, lead_id, body)
        return True

    tpl_name, used_lang, pcount = _choose_wa_template(step.get("template_name"), os.getenv("WHATSAPP_TEMPLATE_LANG", "en"))
    if not tpl_name or not used_lang:
        _create_notification(user_email, "WhatsApp template unavailable",
                             "No approved template/locale available to send outside the 24h window.")
        return True

    params = _build_wa_params(pcount, lead, profile, run, body)
    shown = f"[template:{tpl_name}/{used_lang}] {body}"
    try:
        resp = send_wa_template(to, tpl_name, used_lang, params)
        ok = getattr(resp, "status_code", 500) < 400
    except Exception as e:
        print("[Automations] WA template send error:", e)
        ok = False
    if ok:
        _mark_sent(run, CHANNEL_WHATSAPP)
        _append_chat_message(user_email, lead_id, shown)
    return True

# ---------- Engine bits used below ----------
def _get_run(state: Dict[str, Any], flow_id: str, lead_key: str) -> Dict[str, Any]:
    return state.setdefault(flow_id, {}).setdefault(lead_key, {
        "step": 0,
        "created_at": _now_utc().isoformat(),
        "last_step_at": None,
        "done": False,
        "last_sent": {},
        "memo": {}
    })

def _advance(run: Dict[str, Any]):
    run["step"] = int(run.get("step", 0)) + 1
    run["last_step_at"] = _now_utc().isoformat()

def _trigger_met(trigger: Dict[str, Any], lead: Dict[str, Any]) -> bool:
    t = trigger.get("type")
    if t == "no_reply":
        return trig_no_reply(lead, int(trigger.get("days", 3)))
    if t == "new_lead":
        return trig_new_lead(lead, int(trigger.get("within_hours", 24)))
    if t == "appointment_no_show":
        return trig_no_show(lead)
    return False

def _should_auto_stop(flow: Dict[str, Any], lead: Dict[str, Any], run: Dict[str, Any]) -> bool:
    if flow.get("auto_stop_on_reply", True):
        last_inbound = _dt(lead.get("last_inbound_at"))
        if last_inbound and last_inbound > _dt(run.get("created_at")):
            return True
    return False

def _can_send(run: Dict[str, Any], channel: str, per_hours: int) -> bool:
    last = (run.get("last_sent") or {}).get(channel)
    if not last:
        return True
    try:
        last_dt = datetime.datetime.fromisoformat(last)
    except Exception:
        return True
    return (_now_utc() - last_dt) >= _td(hours=per_hours)

def _mark_sent(run: Dict[str, Any], channel: str):
    run.setdefault("last_sent", {})[channel] = _now_utc().isoformat()

def _execute_step(flow: Dict[str, Any], step: Dict[str, Any], lead: Dict[str, Any], run: Dict[str, Any], caps: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    kind = step.get("type")

    if kind == "wait":
        last = _dt(run.get("last_step_at")) or _dt(run.get("created_at")) or _now_utc()
        delta = _td(days=step.get("days", 0), hours=step.get("hours", 0), minutes=step.get("minutes", 0))
        return _now_utc() - last >= delta

    if kind == "if_no_reply":
        within_days = int(step.get("within_days", 2))
        if cond_no_reply_since(lead, within_days):
            for s in (step.get("then") or []):
                _execute_step(flow, s, lead, run, caps, profile)
            return True
        return True

    if kind == "if_no_booking":
        within_days = int(step.get("within_days", 2))
        if cond_no_booking_since(lead, within_days):
            for s in (step.get("then") or []):
                _execute_step(flow, s, lead, run, caps, profile)
            return True
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
        return _send_whatsapp_with_window(flow, step, lead, run, caps, profile)

    if kind == "send_email":
        if caps.get("respect_quiet_hours", True) and _in_quiet_hours(_now_utc(), profile):
            return False
        per_hours = int(caps.get("per_lead_per_day", 1)) * 24
        if not _can_send(run, CHANNEL_EMAIL, per_hours=per_hours):
            return False
        email = lead.get("email")
        if not email:
            return True
        subject = _render_text(step.get("subject") or "Quick check-in", lead, run, profile)
        html = _render_text(step.get("html") or "<p>Hi {{lead.first_name}}, just checking in. <a href='{{booking_link}}'>Book here</a>.</p>", lead, run, profile)
        if _contains_blockers(subject) or _contains_blockers(html):
            _create_notification(lead.get("owner") or flow.get("owner") or "", "Setup needed", "Email blocked: missing profile values (booking link / business name).")
            return True
        ok = send_email_sendgrid_auto(email, subject, html, profile.get("business_name") or "RetainAI")
        if ok:
            _mark_sent(run, CHANNEL_EMAIL)
        return True

    if kind == "push_owner":
        owner = lead.get("owner") or flow.get("owner") or ""
        if owner:
            _create_notification(owner, step.get("title") or "Lead to call", step.get("message") or str(lead.get("email")))
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
    flows_db = _read_json2(FILE_AUTOMATIONS, {"users": {}})
    state = _load_state()
    leads_by_user = load_leads()

    for user, flows in flows_db.get("users", {}).items():
        profile = _load_user_profile(user)
        user_leads = leads_by_user.get(user, []) or []

        for flow in flows:
            if not flow.get("enabled", False):
                continue
            flow_id = flow.get("id") or str(uuid.uuid4())
            steps = flow.get("steps", [])
            caps = flow.get("caps", {"per_lead_per_day": 1, "respect_quiet_hours": True})
            trigger = flow.get("trigger", {})

            for lead in user_leads:
                owner = (lead.get("owner") or user or "").lower()
                if owner != user:
                    continue

                lead_key = str(lead.get("id") or lead.get("email") or lead.get("phone") or uuid.uuid4())
                run = _get_run(state, flow_id, lead_key)
                if run.get("done"):
                    continue

                if run.get("step", 0) == 0:
                    if not _trigger_met(trigger, lead):
                        state.setdefault(flow_id, {}).pop(lead_key, None)
                        continue

                if _should_auto_stop(flow, lead, run):
                    run["done"] = True
                    continue

                step_index = int(run.get("step", 0))
                if step_index >= len(steps):
                    run["done"] = True
                    continue

                step = steps[step_index]
                progressed = _execute_step(flow, step, lead, run, caps, profile)
                if progressed:
                    _advance(run)

    _save_state(state)

# ---------- API (Blueprint) ----------
automations_bp = Blueprint("automations", __name__)

@automations_bp.before_request
def _bf_ensure_files():
    _ensure_files2()

# Health check (handy for debugging)
@automations_bp.route("/health", methods=["GET"])
def automations_health():
    return jsonify({"ok": True, "message": "automations alive"})

# User profile
@automations_bp.route("/user/profile", methods=["GET"])
def get_user_profile():
    user = _user_from_request()
    prof = _load_user_profile(user)
    return jsonify({
        "profile": {
            "business_name": prof.get("business_name", ""),
            "booking_link": prof.get("booking_link", ""),
            "quiet_hours_start": prof.get("quiet_hours_start"),
            "quiet_hours_end": prof.get("quiet_hours_end"),
        }
    })

def _vp_int(v, name):
    if v is None:
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
    if _is_valid_url(u):
        return u
    raise ValueError("booking_link must be http(s) URL")

@automations_bp.route("/user/profile", methods=["POST"])
def set_user_profile():
    user = _user_from_request()
    body = request.get_json(force=True) or {}
    prof = _load_user_profile(user)
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
    _save_user_profile(user, prof)
    return jsonify({"ok": True, "profile": prof})

# Built-in templates (used by GET /templates and preview fallback)
def _builtin_templates() -> List[Dict[str, Any]]:
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

# GET /api/automations/templates
@automations_bp.route("/templates", methods=["GET"])
def automations_templates():
    return jsonify({"templates": _builtin_templates()})

# OPTIONAL: List approved WA templates for UI picker
@automations_bp.route("/wa/templates", methods=["GET"])
def list_wa_templates():
    waba_id = _resolve_waba_id()
    r = _fetch_templates_for_waba(waba_id)
    if not getattr(r, "ok", False):
        return jsonify({"ok": False, "templates": [], "error": "unavailable"}), 503
    data = r.json() or {}
    items = data.get("data", []) or []
    # only approved, sorted by name
    approved = [t for t in items if (t.get("status") or "").upper() == "APPROVED"]
    approved.sort(key=lambda x: f"{x.get('name','')}-{x.get('language','')}".lower())
    return jsonify({"ok": True, "templates": approved})

# Flows CRUD
@automations_bp.route("/", methods=["GET"])
def list_flows():
    user = _user_from_request()
    flows = _load_user_flows(user)
    for f in flows:
        f.setdefault("id", str(uuid.uuid4()))
    return jsonify({"flows": flows})

@automations_bp.route("/", methods=["POST"])
def create_flow():
    user = _user_from_request()
    body = request.get_json(force=True) or {}
    flow = body.get("flow", {})
    flow.setdefault("id", str(uuid.uuid4()))
    flow.setdefault("enabled", False)
    flow["owner"] = user
    flows = _load_user_flows(user)
    flows.append(flow)
    _save_user_flows(user, flows)
    return jsonify({"ok": True, "flow": flow})

@automations_bp.route("/<flow_id>", methods=["PUT"])
def update_flow(flow_id):
    user = _user_from_request()
    body = request.get_json(force=True) or {}
    flows = _load_user_flows(user)
    for i, f in enumerate(flows):
        if f.get("id") == flow_id:
            merged = {**f, **(body.get("flow", {}))}
            merged["id"] = flow_id
            flows[i] = merged
            _save_user_flows(user, flows)
            return jsonify({"ok": True, "flow": merged})
    return jsonify({"ok": False, "error": "not_found"}), 404

@automations_bp.route("/enable/<flow_id>", methods=["POST"])
def enable_flow(flow_id):
    user = _user_from_request()
    body = request.get_json(force=True) or {}
    enabled = bool(body.get("enabled", True))
    flows = _load_user_flows(user)
    for i, f in enumerate(flows):
        if f.get("id") == flow_id:
            f["enabled"] = enabled
            _save_user_flows(user, flows)
            return jsonify({"ok": True, "flow": f})
    return jsonify({"ok": False, "error": "not_found"}), 404

@automations_bp.route("/<flow_id>", methods=["DELETE"])
def delete_flow(flow_id):
    user = _user_from_request()
    flows = _load_user_flows(user)
    flows = [f for f in flows if f.get("id") != flow_id]
    _save_user_flows(user, flows)
    state = _load_state()
    if flow_id in state:
        state.pop(flow_id, None)
        _save_state(state)
    return jsonify({"ok": True})

# --- Preview + Execute (authoritative endpoint) ---
@automations_bp.route("/test", methods=["POST"])
def automations_test():
    """
    Accepts:
      mode: "dryrun" | "execute"
      flow_id (string) OR flow (full flow object)
      lead_email (string)
      profile (dict) optional override
      ignore_waits / ignore_quiet_hours / bypass_rate_limits (bool) for execute
    """
    data = request.get_json(silent=True) or {}
    user = _user_from_request()
    flow_id = str(data.get("flow_id") or "").strip()
    flow = data.get("flow") if isinstance(data.get("flow"), dict) else None
    lead_email = (data.get("lead_email") or "").strip()
    mode = (data.get("mode") or "dryrun").strip().lower()

    # Resolve flow
    if not flow and flow_id:
        for f in _load_user_flows(user):
            if str(f.get("id")) == flow_id:
                flow = f
                break
    if not flow and flow_id:
        for t in _builtin_templates():
            if str(t.get("id")) == flow_id:
                flow = {**t, "owner": user, "enabled": False}
                break
    if not flow:
        return jsonify(ok=False, error="flow_not_found"), 404

    # Profile (stored + override)
    profile = _load_user_profile(user) or {}
    if isinstance(data.get("profile"), dict):
        profile = {**profile, **data["profile"]}

    # Helpers
    def _first_name_from_email(email: str) -> str:
        if not email:
            return ""
        local = email.split("@", 1)[0]
        return local.replace(".", " ").replace("_", " ").title()

    def _plaintext_to_html(s: str) -> str:
        import html as _html
        if not isinstance(s, str):
            s = "" if s is None else str(s)
        s = s.replace("\r\n", "\n")
        blocks = [p.strip() for p in s.split("\n\n")]
        parts = []
        for p in blocks:
            if not p:
                continue
            esc = _html.escape(p).replace("\n", "<br>")
            parts.append("<p>" + esc + "</p>")
        return "".join(parts)

    # ---------- DRY-RUN ----------
    if mode == "dryrun":
        def _subst(s: str) -> str:
            s = s or ""
            return (
                s.replace("{{business_name}}", profile.get("business_name", ""))
                 .replace("{{booking_link}}", profile.get("booking_link", ""))
                 .replace("{{lead.first_name}}", _first_name_from_email(lead_email))
                 .replace("{{last_ai_text}}", "(AI draft here)")
            )

        would = []
        for s in (flow.get("steps") or []):
            t = s.get("type")
            if t == "ai_draft":
                would.append({"type": "ai_draft"})
            elif t == "send_whatsapp":
                info = {"to": lead_email, "text": _subst(s.get("text"))}
                if s.get("template"):
                    info["template"] = s["template"]
                if s.get("template_name"):
                    info.setdefault("template", {})["name"] = s["template_name"]
                would.append({"type": "send_whatsapp", "info": info})
            elif t == "send_email":
                subj = _subst(s.get("subject"))
                if s.get("html"):
                    html_body = _subst(s.get("html"))
                else:
                    body_plain = _subst(s.get("body") or "")
                    html_body = _plaintext_to_html(body_plain)
                would.append({"type": "send_email", "info": {"to": lead_email, "subject": subj, "html": html_body}})
            elif t == "wait":
                would.append({"type": "wait", "info": {
                    "days": s.get("days"), "hours": s.get("hours"), "minutes": s.get("minutes")
                }})
            elif t in ("if_no_reply", "if_no_booking"):
                would.append({"type": t, "info": {"within_days": s.get("within_days", 2)}})
                for sub in (s.get("then") or []):
                    tt = sub.get("type")
                    if tt == "wait":
                        would.append({"type": f"{t}→wait", "info": {
                            "days": sub.get("days"), "hours": sub.get("hours"), "minutes": sub.get("minutes")
                        }})
                    else:
                        info = {
                            "to": lead_email,
                            "subject": _subst(sub.get("subject")),
                            "text": _subst(sub.get("text")),
                            "html": _subst(sub.get("html") or _plaintext_to_html(sub.get("body") or "")),
                            "tag": _subst(sub.get("tag")),
                        }
                        if sub.get("template"):
                            info["template"] = sub["template"]
                        if sub.get("template_name"):
                            info.setdefault("template", {})["name"] = sub["template_name"]
                        would.append({"type": f"{t}→{tt}", "info": info})
            elif t == "push_owner":
                would.append({"type": "push_owner", "info": {"title": _subst(s.get("title")), "message": _subst(s.get("message"))}})
            elif t == "add_tag":
                would.append({"type": "add_tag", "info": {"tag": _subst(s.get("tag"))}})
            else:
                would.append({"type": t or "unknown"})
        return jsonify(ok=True, profile=profile, would=would)

    # ---------- EXECUTE NOW ----------
    leads_by_user = load_leads()
    lead = None
    for ld in (leads_by_user.get(user, []) or []):
        if (ld.get("email") or "").strip().lower() == lead_email.lower():
            lead = dict(ld)
            break
    if not lead:
        lead = {
            "id": f"test-{uuid.uuid4().hex[:8]}",
            "email": lead_email,
            "name": _first_name_from_email(lead_email),
            "owner": user,
        }

    run = {
        "_ignore_waits": bool(data.get("ignore_waits", True)),
        "_ignore_quiet_hours": bool(data.get("ignore_quiet_hours", True)),
        "_bypass_rate_limits": bool(data.get("bypass_rate_limits", True)),
        "_collector": [],
        "created_at": _now_utc().isoformat(),
        "step": 0,
        "memo": {},
        "last_sent": {},
    }
    caps = flow.get("caps", {"per_lead_per_day": 1, "respect_quiet_hours": True})
    def _collector() -> list: return run.setdefault("_collector", [])

    def _exec_send_email(step):
        if caps.get("respect_quiet_hours", True) and not run.get("_ignore_quiet_hours", False):
            if _in_quiet_hours(_now_utc(), profile):
                _collector().append({"type": "send_email", "status": "skipped", "info": {"reason": "quiet_hours"}})
                return
        if not run.get("_bypass_rate_limits", False):
            if not _can_send(run, CHANNEL_EMAIL, per_hours=int(caps.get("per_lead_per_day", 1)) * 24):
                _collector().append({"type": "send_email", "status": "skipped", "info": {"reason": "rate_limit"}})
                return

        to_email = lead.get("email")
        if not to_email:
            _collector().append({"type": "send_email", "status": "skipped", "info": {"reason": "no_email"}})
            return

        subject = _render_text(step.get("subject") or "Quick check-in", lead, run, profile)
        if step.get("html"):
            html_body = _render_text(step.get("html") or "", lead, run, profile)
        else:
            body_plain = _render_text(step.get("body") or "", lead, run, profile)
            html_body = _plaintext_to_html(body_plain or "Hi {{lead.first_name}},\n\nJust checking in.\n\n{{business_name}}")

        if _contains_blockers(subject) or _contains_blockers(html_body):
            _create_notification(lead.get("owner") or flow.get("owner") or "", "Setup needed",
                                 "Email blocked: missing profile values (booking link / business name).")
            _collector().append({"type": "send_email", "status": "skipped", "info": {"reason": "missing_profile"}})
            return

        ok = send_email_sendgrid_auto(to_email, subject, html_body, profile.get("business_name") or "RetainAI")
        if ok:
            _mark_sent(run, CHANNEL_EMAIL)
            _collector().append({"type": "send_email", "status": "ok", "info": {"to": to_email, "subject": subject, "html": html_body}})
        else:
            _collector().append({"type": "send_email", "status": "error", "info": {"to": to_email, "subject": subject}})

    def _exec_send_whatsapp(step):
        if caps.get("respect_quiet_hours", True) and not run.get("_ignore_quiet_hours", False):
            if _in_quiet_hours(_now_utc(), profile):
                _collector().append({"type": "send_whatsapp", "status": "skipped", "info": {"reason": "quiet_hours"}})
                return
        if not run.get("_bypass_rate_limits", False):
            if not _can_send(run, CHANNEL_WHATSAPP, per_hours=int(caps.get("per_lead_per_day", 1)) * 24):
                _collector().append({"type": "send_whatsapp", "status": "skipped", "info": {"reason": "rate_limit"}})
                return

        to = lead.get("phone") or lead.get("whatsapp")
        if not to:
            _collector().append({"type": "send_whatsapp", "status": "skipped", "info": {"reason": "no_whatsapp"}})
            return
        if bool(lead.get("wa_opt_out")):
            _collector().append({"type": "send_whatsapp", "status": "skipped", "info": {"reason": "opt_out"}})
            return

        raw = step.get("text") or run.get("memo", {}).get("last_ai_text") or ""
        body_text = _render_text(raw, lead, run, profile)
        if _contains_blockers(body_text):
            _create_notification(lead.get("owner") or flow.get("owner") or "", "Setup needed",
                                 "WhatsApp message blocked: missing profile values (booking link / business name).")
            _collector().append({"type": "send_whatsapp", "status": "skipped", "info": {"reason": "missing_profile"}})
            return

        inside24 = False
        try:
            inside24 = within_24h(user, str(lead.get("id") or lead.get("email") or lead.get("phone") or ""))
        except Exception:
            pass

        if inside24:
            try:
                resp = send_wa_text(to, body_text)
                ok = getattr(resp, "status_code", 500) < 400
            except Exception as e:
                print("[Automations] WA free-text send error:", e)
                ok = False
            if ok:
                _mark_sent(run, CHANNEL_WHATSAPP)
                _append_chat_message(user, str(lead.get("id") or lead.get("email") or lead.get("phone") or ""), body_text)
                _collector().append({"type": "send_whatsapp", "status": "ok", "info": {"to": to, "mode": "text", "text": body_text}})
            else:
                _collector().append({"type": "send_whatsapp", "status": "error", "info": {"to": to, "mode": "text", "text": body_text}})
            return

        tpl_block = step.get("template") or {}
        preferred_name = step.get("template_name") or tpl_block.get("name")
        preferred_lang = tpl_block.get("language") or os.getenv("WHATSAPP_TEMPLATE_LANG", "en")
        tpl_name, used_lang, pcount = _choose_wa_template(preferred_name, preferred_lang)
        if not tpl_name or not used_lang:
            _create_notification(user, "WhatsApp template unavailable",
                                 "No approved template/locale available to send outside the 24h window.")
            _collector().append({"type": "send_whatsapp", "status": "skipped", "info": {"reason": "no_template"}})
            return

        raw_params = tpl_block.get("params")
        if isinstance(raw_params, str) and raw_params.strip():
            parts = [p.strip() for p in raw_params.split(",")]
            params = [_render_text(p, lead, run, profile) for p in parts]
            params = (params + [""] * pcount)[:pcount]
        else:
            params = _build_wa_params(pcount, lead, profile, run, body_text)

        shown = f"[template:{tpl_name}/{used_lang}] {body_text}"
        try:
            resp = send_wa_template(to, tpl_name, used_lang, params)
            ok = getattr(resp, "status_code", 500) < 400
        except Exception as e:
            print("[Automations] WA template send error:", e)
            ok = False
        if ok:
            _mark_sent(run, CHANNEL_WHATSAPP)
            _append_chat_message(user, str(lead.get("id") or lead.get("email") or lead.get("phone") or ""), shown)
            _collector().append({"type": "send_whatsapp", "status": "ok",
                                 "info": {"to": to, "mode": "template",
                                          "template": {"name": tpl_name, "language": used_lang},
                                          "text": body_text}})
        else:
            _collector().append({"type": "send_whatsapp", "status": "error",
                                 "info": {"to": to, "mode": "template",
                                          "template": {"name": tpl_name, "language": used_lang},
                                          "text": body_text}})

    def _exec_if_no_reply(step):
        within_days = int(step.get("within_days", 2))
        match = cond_no_reply_since(lead, within_days)
        _collector().append({"type": "if_no_reply", "status": "ok", "info": {"within_days": within_days, "match": bool(match)}})
        if match:
            for sub in (step.get("then") or []):
                _exec_step(sub)

    def _exec_if_no_booking(step):
        within_days = int(step.get("within_days", 2))
        match = cond_no_booking_since(lead, within_days)
        _collector().append({"type": "if_no_booking", "status": "ok", "info": {"within_days": within_days, "match": bool(match)}})
        if match:
            for sub in (step.get("then") or []):
                _exec_step(sub)

    def _exec_push_owner(step):
        owner = lead.get("owner") or flow.get("owner") or ""
        if owner:
            _create_notification(owner, step.get("title") or "Lead to call", step.get("message") or str(lead.get("email")))
        _collector().append({"type": "push_owner", "status": "ok", "info": {"title": step.get("title"), "message": step.get("message")}})

    def _exec_add_tag(step):
        tag = step.get("tag")
        if tag:
            tags = set((lead.get("tags") or []))
            tags.add(tag)
            lead["tags"] = sorted(list(tags))
            owner = (lead.get("owner") or flow.get("owner") or "").lower()
            if owner:
                lbsu = load_leads()
                arr = lbsu.get(owner, []) or []
                for i, ld in enumerate(arr):
                    if (ld.get("id") == lead.get("id")) or (ld.get("email") == lead.get("email")):
                        arr[i] = lead
                        break
                lbsu[owner] = arr
                save_leads(lbsu)
        _collector().append({"type": "add_tag", "status": "ok", "info": {"tag": tag}})

    def _exec_step(step):
        t = step.get("type")
        if t == "wait":
            if run.get("_ignore_waits"):
                _collector().append({"type": "wait", "status": "skipped"})
            else:
                _collector().append({"type": "wait", "status": "pending"})
            return
        if t == "ai_draft":
            text = ai_draft_message({
                "lead": lead,
                "flow": flow,
                "business_name": profile.get("business_name"),
                "booking_link": profile.get("booking_link"),
            })
            run.setdefault("memo", {})["last_ai_text"] = text
            _collector().append({"type": "ai_draft", "status": "ok", "info": {"text": text}})
            return
        if t == "send_email":
            _exec_send_email(step); return
        if t == "send_whatsapp":
            _exec_send_whatsapp(step); return
        if t == "if_no_reply":
            _exec_if_no_reply(step); return
        if t == "if_no_booking":
            _exec_if_no_booking(step); return
        if t == "push_owner":
            _exec_push_owner(step); return
        if t == "add_tag":
            _exec_add_tag(step); return
        _collector().append({"type": t or "unknown", "status": "ok"})

    for s in (flow.get("steps") or []):
        _exec_step(s)

    did = run.get("_collector", [])
    return jsonify(ok=True, did=did)

# ---------- Blueprint registration (fixes 404 at /api/automations/templates) ----------
# Mount the blueprint under /api/automations ONLY once.
if "automations" not in app.blueprints:
    app.register_blueprint(automations_bp, url_prefix="/api/automations")


# ----------------------------
# Leads CRUD + status coloring
# ----------------------------
@app.route('/api/leads/<user_email>', methods=['GET'])
def get_leads(user_email):
    leads_by_user = load_leads()
    leads = leads_by_user.get(user_email, [])
    users = load_users()
    user = users.get(user_email)
    business_type = (user.get("business", "") if user else "").lower()
    interval = BUSINESS_TYPE_INTERVALS.get(business_type, 14)
    now = datetime.datetime.utcnow()
    updated_leads = []
    for lead in leads:
        last_contacted = lead.get("last_contacted") or lead.get("createdAt")
        try:
            last_dt = datetime.datetime.fromisoformat(last_contacted.replace("Z", ""))
            days_since = (now - last_dt).days
        except Exception:
            days_since = 0
        if days_since > interval + 2:
            status = "cold";   status_color = "#e66565"
        elif interval <= days_since <= interval + 2:
            status = "warning"; status_color = "#f7cb53"
        else:
            status = "active";  status_color = "#1bc982"
        lead["status"] = status
        lead["status_color"] = status_color
        lead["days_since_contact"] = days_since
        updated_leads.append(lead)
    return jsonify({"leads": updated_leads}), 200

@app.route('/api/leads/<user_email>', methods=['POST'])
def save_user_leads(user_email):
    data = request.json
    leads = data.get("leads", [])
    if not isinstance(leads, list):
        return jsonify({"error": "Leads must be a list"}), 400
    now = datetime.datetime.utcnow().isoformat() + "Z"
    leads_by_user = load_leads()
    # ensure last_contacted
    for lead in leads:
        if not lead.get("last_contacted"):
            lead["last_contacted"] = lead.get("createdAt") or now
    leads_by_user[user_email] = leads
    save_leads(leads_by_user)
    return jsonify({"message": "Leads updated", "leads": leads}), 200

@app.route('/api/leads/<user_email>/<lead_id>/contacted', methods=['POST'])
def mark_lead_contacted(user_email, lead_id):
    leads_by_user = load_leads()
    leads = leads_by_user.get(user_email, [])
    updated = False
    for lead in leads:
        if str(lead.get("id")) == str(lead_id):
            lead["last_contacted"] = datetime.datetime.utcnow().isoformat() + "Z"
            updated = True
    if updated:
        save_leads(leads_by_user)
        return jsonify({"message": "Lead marked as contacted.", "lead_id": lead_id}), 200
    else:
        return jsonify({"error": "Lead not found."}), 404

# ----------------------------
# Notifications API
# ----------------------------
@app.route('/api/notifications/<user_email>', methods=['GET'])
def get_notifications(user_email):
    notes = load_notifications().get(user_email, [])
    for n in notes:
        n.setdefault('read', False)
    return jsonify({"notifications": notes}), 200

@app.route('/api/notifications/<user_email>/<int:idx>/mark_read', methods=['POST'])
def mark_notification_read(user_email, idx):
    all_notes = load_notifications()
    user_notes = all_notes.get(user_email)
    if not user_notes or idx < 0 or idx >= len(user_notes):
        return jsonify({"error": "Notification not found"}), 404
    user_notes[idx]['read'] = True
    all_notes[user_email] = user_notes
    save_notifications(all_notes)
    return ('', 204)

# ----------------------------
# VAPID Push
# ----------------------------
@app.route('/api/vapid-public-key', methods=['GET'])
def get_vapid_key():
    return jsonify({'publicKey': VAPID_PUBLIC_KEY})

@app.route('/api/save-subscription', methods=['POST'])
def save_subscription():
    data = request.json
    email = data.get('email')
    subscription = data.get('subscription')
    if not email or not subscription:
        return jsonify({'error': 'Email and subscription required'}), 400
    SUBSCRIPTIONS[email] = subscription
    return jsonify({'message': 'Subscription saved'}), 200

# ----------------------------
# AI helpers (reply drafts)
# ----------------------------
@app.route('/api/generate-message', methods=['POST'])
def generate_message():
    data = request.json
    lead = data.get("lead", {})
    last_message = data.get("last_message", "")
    user_business = data.get("user_business", "business")
    lead_name = lead.get('name', '')
    user_name = data.get("user_name", "")
    prompt = (
        f"You are a professional, emotionally intelligent assistant for a {user_business} business. "
        f"Given the context below, write ONLY a direct, warm, natural message that could be sent in chat or email, with no greeting lines, subjects, or sign-offs. Only output the message body.\n\n"
        f"Lead Name: {lead_name}\n"
        f"Tags: {', '.join(lead.get('tags', []))}\n"
        f"Notes: {lead.get('notes', '-')}\n"
        f"Most recent message from the lead: \"{last_message}\"\n"
        "Your reply should be concise, helpful, and conversational. Do NOT include subject lines, greetings, or closings. Reply as if you were the business owner responding to the client."
    )
    try:
        resp = pyrequests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "openai/gpt-4o",
                "messages": [
                    {"role": "system", "content": "You are a CRM messaging assistant. Output only the message body."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 200,
                "temperature": 0.7
            },
            timeout=30
        )
        result = resp.json()
        if "choices" in result and result["choices"]:
            reply = result["choices"][0]["message"]["content"].strip()
            return jsonify({"reply": reply}), 200
        return jsonify({"error": result.get("error", {}).get("message", "AI response was incomplete.")}), 500
    except Exception as ex:
        print("AI Request Error:", str(ex))
        return jsonify({"error": "Failed to get AI response"}), 500

# --- Body generator: /api/generate_prompt  -------------------------------

@app.route('/api/generate_prompt', methods=['POST'])
def generate_prompt():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON body"}), 400

    lead           = data.get("lead") or {}
    lead_name      = (data.get("leadName") or lead.get("name") or "").strip()
    business_name  = (data.get("businessName") or data.get("business") or data.get("user_business") or "").strip()
    prompt_type    = (data.get("promptType") or "").strip()
    instruction    = (data.get("instruction") or "").strip()
    user_name      = (data.get("userName") or "").strip()
    tags_val       = data.get("tags") or lead.get("tags") or []
    tags           = ", ".join([str(t) for t in tags_val]) if isinstance(tags_val, list) else str(tags_val or "")
    notes          = (data.get("notes") or lead.get("notes") or "").strip()
    last_message   = (data.get("last_message") or data.get("lastMessage") or "").strip()

    prompt = (
        f"You are an emotionally intelligent CRM assistant for a business named '{business_name}'. "
        f"Write a message that matches the prompt type and instructions below. "
        f"ONLY output the message body (no greeting, no subject, no signature).\n"
        f"Recipient: {lead_name}\nTags: {tags}\nNotes: {notes}\n"
        f"Prompt Type: {prompt_type}\nInstruction: {instruction}\n"
        f"Most recent inbound: \"{last_message}\"\n"
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
                    {"role": "system", "content": "You are a CRM messaging assistant. Output only the message body."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 150,
                "temperature": 0.7,
            },
            timeout=30
        )
        j = resp.json() if resp.ok else {}
        if "choices" in j and j["choices"]:
            msg = j["choices"][0]["message"]["content"].strip()
            return jsonify({"prompt": msg}), 200
        return jsonify({"error": (j.get("error") or {}).get("message", "AI response was empty")}), 502
    except Exception as ex:
        print("AI Request Error:", str(ex))
        return jsonify({"error": "Failed to get AI response"}), 500


# ----------------------------
# User info & Push
# ----------------------------
@app.route('/api/user/<path:email>', methods=['GET'])
def get_user(email):
    email = _norm_email(email)
    users = load_users()

    role, org_email, org_owner, subject = _resolve_org_and_role(email, users)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if not _org_is_active(org_owner):
        return jsonify({"error": "account_inactive"}), 403

    # Base fields come from org for members, from owner for owners
    base = org_owner if role == "member" else subject

    out = {
      "email":        email,
      "name":         subject.get("name","") if role == "member" else base.get("name",""),
      "logo":         (base.get("logo") or base.get("picture","")),
      "businessType": base.get("businessType",""),
      "business":     base.get("business",""),
      "people":       base.get("people",""),
      "location":     base.get("location",""),
      "stripe_account_id":  base.get("stripe_account_id"),
      "stripe_connected":   base.get("stripe_connected", False),
      "whatsapp":           base.get("whatsapp",""),
      # permissions for UI (non-breaking)
      "role": role,
      "orgOwnerEmail": org_email,
      "canInviteTeam":   role == "owner",
      "canEditBusiness": role == "owner",
      "canManageBilling": role == "owner",
    }
    return jsonify(out), 200

@app.route('/api/user/<path:email>', methods=['PUT', 'PATCH'])
def update_user(email):
    email = _norm_email(email)
    body  = request.get_json() or {}
    users = load_users()

    role, org_email, org_owner, subject = _resolve_org_and_role(email, users)
    if not role:
        return jsonify({"error": "not_found"}), 404
    if not _org_is_active(org_owner):
        return jsonify({"error": "account_inactive"}), 403

    if role == "owner":
        # Owner can edit business profile fields
        for k in ["name", "logo", "businessType", "business", "people", "location", "whatsapp"]:
            if k in body:
                subject[k] = body[k]
        users[email] = subject
    else:
        # Member can only edit their own display bits
        if "name" in body:
            subject["name"] = body["name"]
        if "logo" in body:
            # store a personal avatar (optional); org logo stays with owner
            subject["logo"] = body["logo"]
        users[f"user::{email}"] = subject

    save_users(users)
    # Reuse the GET serializer so UI stays consistent
    return get_user(email)


@app.route('/api/push/notify', methods=['POST'])
def push_notify():
    data = request.json
    lead_email   = data.get('lead_email')
    notification = data.get('notification', {})
    sub = SUBSCRIPTIONS.get(lead_email)
    if not sub:
        return jsonify({'error': 'No subscription for that lead'}), 404
    # NOTE: pywebpush import intentionally removed in this cleaned build to keep deps light.
    return jsonify({'error': 'Push disabled in this build'}), 501

# ----------------------------
# Home & Scheduler
# ----------------------------
@app.route('/')
def home():
    return jsonify({"status": "RetainAI backend running."})

def start_scheduler_once():
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        if not hasattr(app, "scheduler_started"):
            scheduler = APScheduler()
            scheduler.init_app(app)
            scheduler.start()
            scheduler.add_job(id='lead_reminder_job', func=check_for_lead_reminders, trigger='interval', minutes=1)
            scheduler.add_job(id='birthday_greetings_job', func=send_birthday_greetings, trigger='cron', hour=8)
            scheduler.add_job(id='trial_ending_soon_job', func=send_trial_ending_soon, trigger='cron', hour=9)
            print("JOBS:", scheduler.get_jobs())
            app.scheduler_started = True

if __name__ == '__main__':
    start_scheduler_once()
    app.run(debug=True, use_reloader=False)

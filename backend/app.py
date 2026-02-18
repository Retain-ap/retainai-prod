# app.py (CONSOLIDATED + PROD-HARDENED) — PART 1/2
import os
import re
import json
import time
import base64
import hmac
import uuid
import hashlib
import datetime
import urllib.parse
from uuid import uuid4
from typing import Any, Dict, Optional, List, Tuple
from urllib.parse import urlparse

import stripe
import requests as pyrequests

from flask import Flask, request, jsonify, send_from_directory, redirect, current_app
from flask_cors import CORS
from dotenv import load_dotenv
from flask_apscheduler import APScheduler
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

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
    JSONIFY_PRETTYPRINT_REGULAR = False

load_dotenv()

# One-time JSON -> SQLite migration if enabled
migrate_json_to_sqlite_if_needed()
print(f"[storage] USE_SQLITE={USE_SQLITE} DATA_ROOT={DATA_ROOT} SQLITE_PATH={SQLITE_PATH}")
print(f"[BOOT] RetainAI started (PID: {os.getpid()})")

app = Flask(__name__)
app.config.from_object(Config())

# Trust Render/Proxy headers so HTTPS/callbacks behave correctly
# (Render sends X-Forwarded-* headers)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Secret key (needed for sessions even if you don't use them heavily)
app.secret_key = (os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or os.urandom(32))

# Only mark cookies secure if you're actually HTTPS
# (ProxyFix makes request.is_secure accurate behind Render)
@app.before_request
def _secure_cookie_defaults():
    is_secure = bool(request.is_secure)
    app.config.update(
        SESSION_COOKIE_SAMESITE="None" if is_secure else "Lax",
        SESSION_COOKIE_SECURE=True if is_secure else False,
    )

# ----------------------------
# ENV / third-party keys
# ----------------------------
OPENROUTER_API_KEY = (os.getenv("OPENROUTER_API_KEY") or "").strip()
SENDGRID_API_KEY = (os.getenv("SENDGRID_API_KEY") or "").strip()

VAPID_PUBLIC_KEY  = (os.getenv("VAPID_PUBLIC_KEY") or "").strip()
VAPID_PRIVATE_KEY = (os.getenv("VAPID_PRIVATE_KEY") or "").strip()

SENDER_EMAIL = os.getenv("SENDER_EMAIL", "noreply@retainai.ca")

STRIPE_SECRET_KEY        = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
STRIPE_PRICE_ID          = (os.getenv("STRIPE_PRICE_ID") or "").strip()
STRIPE_WEBHOOK_SECRET    = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
STRIPE_CONNECT_CLIENT_ID = (os.getenv("STRIPE_CONNECT_CLIENT_ID") or "").strip()
STRIPE_REDIRECT_URI      = (os.getenv("STRIPE_REDIRECT_URI") or "").strip()

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")

# WhatsApp
WHATSAPP_TOKEN    = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "retainai-verify")
WHATSAPP_WABA_ID = os.getenv("WHATSAPP_WABA_ID") or os.getenv("WHATSAPP_BUSINESS_ID")
WHATSAPP_TEMPLATE_DEFAULT = os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "retainai_outreach")
WHATSAPP_TEMPLATE_LANG = os.getenv("WHATSAPP_TEMPLATE_LANG", "en_US")
APP_SECRET = os.getenv("APP_SECRET") or os.getenv("META_APP_SECRET")
DEFAULT_COUNTRY_CODE = (os.getenv("DEFAULT_COUNTRY_CODE") or "1").strip()
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v20.0")

# Google OAuth / Calendar
GOOGLE_CLIENT_ID     = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
GOOGLE_CLIENT_SECRET = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
GOOGLE_REDIRECT_URI  = (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
]

stripe.api_key = STRIPE_SECRET_KEY

ZERO_DECIMAL = {"bif","clp","djf","gnf","jpy","kmf","krw","mga","pyg","rwf","ugx","vnd","vuv","xaf","xof","xpf"}

# ----------------------------
# CORS (PROD-SAFE)
# ----------------------------
# IMPORTANT: credentials + wildcard origin is not valid in browsers.
# If ALLOWED_ORIGINS empty, default to FRONTEND_URL.
_raw_allowed = os.getenv("ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in _raw_allowed.split(",") if o.strip()] if _raw_allowed else [FRONTEND_URL]

CORS(
    app,
    origins=ALLOWED_ORIGINS,
    supports_credentials=True,
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-User-Email"],
    expose_headers=["Content-Type"],
)

@app.route("/api/<path:_any>", methods=["OPTIONS"])
def api_options(_any):
    return ("", 204)

# ----------------------------
# DATA ROOT for legacy JSON + ICS (DO NOT WRITE OUTSIDE DATA_ROOT)
# ----------------------------
def _p(*parts: str) -> str:
    os.makedirs(DATA_ROOT, exist_ok=True)
    return os.path.join(DATA_ROOT, *parts)

ICS_DIR = _p("ics_files")
os.makedirs(ICS_DIR, exist_ok=True)

NOTIFICATIONS_FILE = _p("notifications.json")
APPOINTMENTS_FILE  = _p("appointments.json")
CHAT_FILE          = _p("whatsapp_chats.json")
STATUS_FILE        = _p("whatsapp_status.json")

FILE_AUTOMATIONS   = os.getenv("FILE_AUTOMATIONS")   or _p("automations.json")
FILE_STATE         = os.getenv("FILE_STATE")         or _p("automations_state.json")
FILE_NOTIFICATIONS = os.getenv("FILE_NOTIFICATIONS") or _p("notifications_automation.json")
FILE_USERS         = os.getenv("FILE_USERS")         or _p("automation_users.json")
FILE_SUBSCRIPTIONS = os.getenv("FILE_SUBSCRIPTIONS") or _p("subscriptions.json")

# ----------------------------
# JSON IO (ATOMIC) — avoids partial writes/corruption
# ----------------------------
def read_json(path: str, default: Any):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

# Legacy helpers
def load_notifications():
    return read_json(NOTIFICATIONS_FILE, {})

def save_notifications(data):
    write_json(NOTIFICATIONS_FILE, data)

def load_appointments():
    return read_json(APPOINTMENTS_FILE, {})

def save_appointments(data):
    write_json(APPOINTMENTS_FILE, data)

def load_chats():
    return read_json(CHAT_FILE, {})

def save_chats(data):
    write_json(CHAT_FILE, data)

def load_statuses():
    return read_json(STATUS_FILE, {})

def save_statuses(data):
    write_json(STATUS_FILE, data)

# ----------------------------
# HEALTH / TEST
# ----------------------------
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True), 200

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify(ok=True), 200

@app.route("/api/debug/config", methods=["GET"])
def debug_config():
    return jsonify({
        "ok": True,
        "FRONTEND_URL": FRONTEND_URL,
        "ALLOWED_ORIGINS": ALLOWED_ORIGINS,
        "USE_SQLITE": bool(USE_SQLITE),
        "DATA_ROOT": DATA_ROOT,
        "SQLITE_PATH": SQLITE_PATH,
        "is_secure": bool(request.is_secure),
        "ENABLE_SCHEDULER": os.getenv("ENABLE_SCHEDULER", "0"),
    }), 200

# ----------------------------
# Utilities
# ----------------------------
_BAD_KEYS = {
    "_sa_instance_state", "headers", "request", "cookies", "environ",
    "wsgi", "response", "session", "files", "form", "args", "json",
}

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()

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

# ----------------------------
# Passwords (backwards-compatible upgrade)
# ----------------------------
def _is_hashed(pw: str) -> bool:
    return isinstance(pw, str) and (pw.startswith("pbkdf2:") or pw.startswith("scrypt:"))

def _verify_password(stored: str, provided: str) -> bool:
    if not stored:
        return False
    if _is_hashed(stored):
        return check_password_hash(stored, provided)
    # legacy plaintext
    return stored == provided

def _maybe_upgrade_password(users: dict, email: str, provided: str):
    # if legacy plaintext matches, upgrade to hashed
    try:
        u = users.get(email) or {}
        stored = u.get("password") or ""
        if stored and (not _is_hashed(stored)) and stored == provided:
            u["password"] = generate_password_hash(provided)
            users[email] = u
            save_users(users)
    except Exception:
        pass

# ----------------------------
# /api/profile (SINGLE SOURCE OF TRUTH)
# ----------------------------
@app.route("/api/profile", methods=["GET", "POST", "OPTIONS"])
def api_profile():
    if request.method == "OPTIONS":
        return ("", 204)

    if request.method == "GET":
        try:
            email = (request.args.get("email") or request.headers.get("X-User-Email") or "").strip()
            if not email:
                return jsonify({"error": "missing_email"}), 400

            raw = None
            try:
                raw = get_user(email)
            except Exception:
                raw = None

            profile = _normalize_profile(email, raw)
            return jsonify(profile), 200

        except Exception as e:
            current_app.logger.exception("GET /api/profile failed")
            return jsonify({"error": "profile_get_failed", "detail": str(e)}), 500

    # POST upsert
    try:
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or request.headers.get("X-User-Email") or "").strip()
        if not email:
            return jsonify({"error": "missing_email"}), 400

        def _int(v, default=0):
            try:
                return int(v)
            except Exception:
                return default

        people = _int(data.get("people", data.get("teamSize", 0)), 0)

        patch = {
            "name": (data.get("name") or "").strip(),
            "logo": (data.get("logo") or "").strip(),
            "business": (data.get("business") or data.get("businessName") or "").strip(),
            "businessName": (data.get("businessName") or data.get("business") or "").strip(),
            "businessType": (data.get("businessType") or "").strip(),
            "location": (data.get("location") or "").strip(),
            "people": people,
            "teamSize": _int(data.get("teamSize", people), people),
        }

        merged = _upsert_user(email, patch)
        return jsonify(_normalize_profile(email, merged)), 200

    except Exception as e:
        current_app.logger.exception("POST /api/profile failed")
        return jsonify({"error": "profile_update_failed", "detail": str(e)}), 500

# ----------------------------
# SendGrid email helper
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

# ============================
# Notifications & scheduler jobs
# ============================
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

def check_for_lead_reminders():
    print("[Scheduler] Checking for leads needing follow-up...")
    leads_by_user = load_leads() or {}
    users_by_email = load_users() or {}
    now = datetime.datetime.utcnow()

    if not isinstance(leads_by_user, dict) or not isinstance(users_by_email, dict):
        return

    for user_email, leads in leads_by_user.items():
        user = users_by_email.get(user_email, {}) or {}
        business_type = (user.get("business", "") or "").lower()
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

    if not isinstance(leads_by_user, dict) or not isinstance(users_by_email, dict):
        return

    for user_email, leads in leads_by_user.items():
        user = users_by_email.get(user_email, {}) or {}
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
        try:
            t0 = datetime.datetime.fromisoformat(ts)
        except Exception:
            return False
    return (datetime.datetime.utcnow() - t0.replace(tzinfo=None)) <= datetime.timedelta(days=days)

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
            try:
                trial_start_dt = datetime.datetime.fromisoformat(trial_start.replace("Z", ""))
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

# ============================
# Appointments
# ============================
@app.route("/api/appointments/<path:user_email>", methods=["GET"])
def get_appointments(user_email):
    user_email = _norm_email(user_email)
    data = load_appointments()
    return jsonify({"appointments": (data.get(user_email, []) if isinstance(data, dict) else [])}), 200

@app.route("/api/appointments/<path:user_email>", methods=["POST"])
def create_appointment(user_email):
    user_email = _norm_email(user_email)
    data = request.get_json(silent=True) or {}

    required = ["lead_email", "lead_first_name", "user_name", "user_email", "business_name", "appointment_time", "appointment_location"]
    for k in required:
        if k not in data:
            return jsonify({"error": f"missing_{k}"}), 400

    appt = {
        "id": str(uuid4()),
        "lead_email": data["lead_email"],
        "lead_first_name": data["lead_first_name"],
        "user_name": data["user_name"],
        "user_email": _norm_email(data["user_email"]),
        "business_name": data["business_name"],
        "appointment_time": data["appointment_time"],
        "appointment_location": data["appointment_location"],
        "duration": data.get("duration", 30),
        "notes": data.get("notes", "")
    }

    appointments = load_appointments()
    if not isinstance(appointments, dict):
        appointments = {}
    appointments.setdefault(user_email, []).append(appt)
    save_appointments(appointments)

    create_ics_file(appt)

    display_time = datetime.datetime.strptime(appt["appointment_time"], "%Y-%m-%dT%H:%M:%S").strftime("%B %d, %Y, %I:%M %p")
    ics_file_url = f"{request.host_url.rstrip('/')}/ics/{appt['id']}.ics"
    google_calendar_link = make_google_calendar_link(appt)

    send_email_with_template(
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
            "user_email": appt["user_email"]
        }
    )

    return jsonify({"message": "Appointment created and confirmation sent!", "appointment": appt}), 201

@app.route("/api/appointments/<path:user_email>/<appt_id>", methods=["PUT"])
def update_appointment(user_email, appt_id):
    user_email = _norm_email(user_email)
    data = request.get_json(silent=True) or {}
    appointments = load_appointments()
    if not isinstance(appointments, dict):
        appointments = {}
    user_appts = appointments.get(user_email, [])
    updated = False
    updated_obj = None

    for i, appt in enumerate(user_appts):
        if appt.get("id") == appt_id:
            for k, v in data.items():
                user_appts[i][k] = v
            updated = True
            updated_obj = user_appts[i]
            create_ics_file(updated_obj)
            break

    appointments[user_email] = user_appts
    save_appointments(appointments)
    return jsonify({"updated": updated, "appointment": updated_obj}), 200

@app.route("/api/appointments/<path:user_email>/<appt_id>", methods=["DELETE"])
def delete_appointment(user_email, appt_id):
    user_email = _norm_email(user_email)
    appointments = load_appointments()
    if not isinstance(appointments, dict):
        appointments = {}
    user_appts = appointments.get(user_email, [])
    before = len(user_appts)
    user_appts = [a for a in user_appts if a.get("id") != appt_id]
    after = len(user_appts)

    appointments[user_email] = user_appts
    save_appointments(appointments)

    fname = os.path.join(ICS_DIR, f"{appt_id}.ics")
    if os.path.exists(fname):
        try:
            os.remove(fname)
        except Exception:
            pass

    return jsonify({"deleted": before - after}), 200

# ============================
# Stripe Connect / Billing (ORG-AWARE + MEMBER SAFE)
# ============================
def _resolve_org_and_role(email: str, users: dict):
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

@app.route("/api/stripe/connect-url", methods=["GET"])
def get_stripe_connect_url():
    user_email = _require_user_email_arg()
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    role, org_email, org_owner, _ = _resolve_org_and_role(user_email, users)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403

    acct = stripe.Account.create(type="express", email=org_email)

    org_owner = users.get(org_email, {}) or {}
    org_owner["stripe_account_id"] = acct.id
    org_owner["stripe_connected"] = True
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

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    role, org_email, org_owner, _ = _resolve_org_and_role(user_email, users)
    if not role:
        return jsonify({"error": "User not found"}), 404
    if role != "owner":
        return jsonify({"error": "forbidden"}), 403
    if not STRIPE_CONNECT_CLIENT_ID or not STRIPE_REDIRECT_URI:
        return jsonify({"error": "Stripe Connect not configured"}), 500

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
    user_email = request.args.get("state")

    if error:
        msg = urllib.parse.quote_plus(error_desc or error)
        return redirect(f"{FRONTEND_URL}/app?stripe_error=1&stripe_error_desc={msg}")

    code = request.args.get("code")
    if not code or not user_email:
        return redirect(f"{FRONTEND_URL}/app?stripe_error=1&stripe_error_desc=missing_code_or_state")

    resp = stripe.OAuth.token(grant_type="authorization_code", code=code)
    stripe_user_id = resp["stripe_user_id"]

    users = load_users() or {}
    if not isinstance(users, dict):
        return redirect(f"{FRONTEND_URL}/app?stripe_error=1&stripe_error_desc=storage_not_ready")

    role, org_email, org_owner, _ = _resolve_org_and_role(user_email, users)
    if not role:
        return redirect(f"{FRONTEND_URL}/app?stripe_error=1&stripe_error_desc=user_not_found")

    org = users.get(org_email, {}) or {}
    org["stripe_account_id"] = stripe_user_id
    org["stripe_connected"] = True
    users[org_email] = org
    save_users(users)

    return redirect(f"{FRONTEND_URL}/app?stripe_connected=1")

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

    acct = stripe.Account.retrieve(acct_id)
    if getattr(acct, "type", None) in ("express", "custom"):
        link = stripe.Account.create_login_link(acct_id)
        return jsonify({"url": link.url}), 200

    return jsonify({"url": f"https://dashboard.stripe.com/{acct_id}"}), 200

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
    # If STRIPE_WEBHOOK_SECRET not set, reject webhook to avoid spoofed activations
    if not STRIPE_WEBHOOK_SECRET:
        return "", 400

    payload = request.data
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return "", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email") or ((session.get("customer_details") or {}).get("email"))
        if email:
            users = load_users() or {}
            if isinstance(users, dict):
                e = _norm_email(email)
                user = users.get(e)
                if user:
                    user["status"] = "active"
                    users[e] = user
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
            stripe.OAuth.deauthorize(client_id=STRIPE_CONNECT_CLIENT_ID, stripe_user_id=acct_id)
    except Exception as e:
        app.logger.warning(f"Stripe deauth failed for {acct_id}: {e}")

    org_owner = users.get(org_email, {}) or {}
    org_owner.pop("stripe_account_id", None)
    org_owner["stripe_connected"] = False
    users[org_email] = org_owner
    save_users(users)
    return ("", 204)

# ============================
# Auth & Google OAuth (trial gated)
# ============================
def _user_payload(email: str, user: dict) -> dict:
    logo = user.get("logo") or user.get("picture") or ""
    return {
        "email": _norm_email(email),
        "name": user.get("name", ""),
        "logo": logo,
        "businessType": user.get("businessType", ""),
        "business": user.get("business", ""),
        "people": user.get("people", ""),
        "location": user.get("location", ""),
        "stripe_account_id": user.get("stripe_account_id"),
        "stripe_connected": user.get("stripe_connected", False),
        "status": user.get("status", ""),
        "role": user.get("role"),
        "org_id": user.get("org_id"),
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
        "trial_start": trial_start,
        "trial_ending_notice_sent": False,
    }
    save_users(users)

    # Welcome email (best-effort)
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
        allowed = _verify_password(user.get("password", ""), password) and (
            (user.get("status") == "active") or _within_trial(user, TRIAL_DAYS)
        )
        if allowed:
            _maybe_upgrade_password(users, email, password)
            return jsonify({"message": "Login successful", "user": _user_payload(email, users.get(email) or user)}), 200

    # 2) Member login with owner's password
    team_key = f"user::{email}"
    team_rec = users.get(team_key)
    if not team_rec:
        return jsonify({"error": "Invalid credentials or account not active"}), 401

    owner_email = _norm_email(team_rec.get("org_id") or "")
    owner_acct = users.get(owner_email) or {}
    owner_pw = owner_acct.get("password", "")
    owner_ok = (owner_acct.get("status") == "active") or _within_trial(owner_acct, TRIAL_DAYS)

    if not (owner_pw and _verify_password(owner_pw, password) and owner_ok):
        return jsonify({"error": "Invalid credentials or account not active"}), 401

    # Upgrade owner's pw if needed (if member used plaintext legacy)
    _maybe_upgrade_password(users, owner_email, password)

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
    data = request.get_json(silent=True) or {}
    token = data.get("credential")
    if not token:
        return jsonify({"error": "No Google token provided"}), 400
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "GOOGLE_CLIENT_ID not configured"}), 500

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

# ============================
# Google Calendar token handling
# ============================
def _google_refresh_access_token(refresh_token: str):
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
        raise RuntimeError("Google OAuth not configured")

    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    r = pyrequests.post("https://oauth2.googleapis.com/token", data=data, timeout=30)
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
    if not (GOOGLE_CLIENT_ID and GOOGLE_REDIRECT_URI):
        return jsonify({"error": "Google OAuth not configured"}), 500

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

    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI):
        return "Google OAuth not configured", 500

    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    token_resp = pyrequests.post("https://oauth2.googleapis.com/token", data=data, timeout=30)
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
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30
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
            headers={"Authorization": f"Bearer {atok}"},
            timeout=30
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
        return pyrequests.get(url, headers={"Authorization": f"Bearer {atok}"}, timeout=30)

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
# WhatsApp Cloud API — cleaned + prod-safe (single-file)
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
    leads_by_user = load_leads() or {}
    if not isinstance(leads_by_user, dict):
        return None
    for user_email, leads in leads_by_user.items():
        for lead in (leads or []):
            if lead_matches_wa(lead, wa):
                return user_email
    return None

def find_lead_by_whatsapp(wa_id: str) -> Optional[str]:
    wa = wa_norm_number(wa_id)
    leads_by_user = load_leads() or {}
    if not isinstance(leads_by_user, dict):
        return None
    for _, leads in leads_by_user.items():
        for lead in (leads or []):
            if lead_matches_wa(lead, wa):
                lid = lead.get("id")
                return str(lid) if lid is not None else None
    return None

def wa_env() -> Tuple[str, str]:
    token = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
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
        url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_id}"
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
    except Exception:
        return os.getenv("WHATSAPP_WABA_ID") or os.getenv("WHATSAPP_BUSINESS_ID", "")

def wa_fetch_templates_for_waba(waba_id: str):
    headers = {"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"}
    params = {"fields": "name,language,status,category,components", "limit": 200}
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{waba_id}/message_templates"
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
    except Exception:
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

def wa_send_text(to_number: str, body: str):
    to = wa_norm_number(to_number)
    token, phone_id = wa_env()
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}}
    return pyrequests.post(url, headers=headers, json=payload, timeout=30)

def wa_send_template(to_number: str, template_name: str, lang_code: str, parameters: Optional[List[Any]] = None):
    to = wa_norm_number(to_number)
    token, phone_id = wa_env()
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    components = []
    if parameters is not None:
        components = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in parameters]}]

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
    return pyrequests.post(url, headers=headers, json=payload, timeout=30)

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

    waba_id = wa_resolve_waba_id()
    r = wa_fetch_templates_raw()
    try:
        data = r.json()
        for t in (data.get("data", []) or []):
            t["normalized_language"] = wa_normalize_lang(t.get("language", ""))
    except Exception:
        data = {"raw": r.text}
    return jsonify({"status": r.status_code, "waba_id": waba_id, "data": data}), r.status_code

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
    lead_id    = (request.args.get("lead_id") or "").strip()

    template_name = (request.args.get("template_name") or os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "") or "").strip()
    lang_code     = request.args.get("language_code") or os.getenv("WHATSAPP_TEMPLATE_LANG", "en") or ""
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

    leads = load_leads() or {}
    if not isinstance(leads, dict):
        return jsonify({"error": "storage_not_ready"}), 500
    arr = (leads.get(user_email, []) or [])
    for ld in arr:
        if str(ld.get("id")) == str(lead_id):
            ld["wa_opt_out"] = bool(opt_out)
    leads[user_email] = arr
    save_leads(leads)
    return jsonify({"ok": True, "opt_out": opt_out}), 200

@app.route("/api/whatsapp/send", methods=["POST"])
def send_whatsapp_message():
    data = request.get_json(force=True) or {}

    def clean(v):
        try:
            return str(v).strip() if v is not None else ""
        except Exception:
            return ""

    to_number     = clean(data.get("to") or data.get("phone"))
    raw_msg       = clean(data.get("message") or data.get("text"))
    user_email    = clean(data.get("user_email")).lower()
    lead_id       = clean(data.get("lead_id"))
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

    # opt-out check
    if user_email and lead_id:
        for ld in ((load_leads() or {}).get(user_email, []) or []):
            if str(ld.get("id")) == str(lead_id) and bool(ld.get("wa_opt_out")):
                return jsonify({"ok": False, "error": "Lead has opted out of WhatsApp messages"}), 403

    inside24 = within_24h(user_email, lead_id) if (user_email and lead_id) else False
    requested = wa_normalize_lang(language_code)
    primary   = wa_primary_lang(requested)
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
                return jsonify({"ok": False, "error": "Template name is required outside 24h.", "code": "TEMPLATE_REQUIRED_OUTSIDE_24H"}), 422

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
            sent_text = f"[template:{template_name}/{used_lang}] {raw_msg or ''}"
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

        # persist chat thread if possible
        try:
            if user_email and lead_id:
                chats = load_chats()
                user_chats = (chats.get(user_email, {}) or {})
                thread = (user_chats.get(str(lead_id), []) or [])
                thread.append({"from": "user", "text": sent_text, "time": datetime.datetime.utcnow().isoformat() + "Z"})
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

                _MSG_CACHE[(str(user_email or ""), str(lead_id or ""))] = {"at": datetime.datetime.utcnow(), "data": thread}
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
        return jsonify(out), resp.status_code

    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    except pyrequests.RequestException as e:
        return jsonify({"ok": False, "error": f"Network error: {e}"}), 502

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
                            data = load_leads() or {}
                            if isinstance(data, dict):
                                changed = False
                                for _, leads in data.items():
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
                            data = load_leads() or {}
                            if isinstance(data, dict):
                                changed = False
                                for _, leads in data.items():
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

                    # save inbound to proper thread
                    user_email = find_user_by_whatsapp(sender_waid) if sender_waid else None
                    lead_id = find_lead_by_whatsapp(sender_waid) if sender_waid else None
                    if not user_email or not lead_id:
                        continue

                    chats = load_chats()
                    user_chats = (chats.get(user_email, {}) or {})
                    thread = (user_chats.get(str(lead_id), []) or [])
                    thread.append({"from": "lead", "text": text, "time": datetime.datetime.utcnow().isoformat() + "Z"})
                    user_chats[str(lead_id)] = thread
                    chats[user_email] = user_chats
                    save_chats(chats)

                    _MSG_CACHE[(str(user_email or ""), str(lead_id or ""))] = {"at": datetime.datetime.utcnow(), "data": thread}

    except Exception as e:
        try:
            app.logger.warning("[WHATSAPP WEBHOOK] parse error: %s", e)
        except Exception:
            pass

    return "OK", 200

# ============================================================
# AI: lightweight prompt for chat composer
# ============================================================
@app.post("/api/ai-prompt")
def ai_prompt():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    user_email = (data.get("user_email") or "").strip().lower()
    lead_id    = str(data.get("lead_id") or "").strip()

    if not user_email or not lead_id:
        return jsonify({"error": "user_email and lead_id are required"}), 400

    users = load_users() or {}
    leads_by_user = load_leads() or {}
    chats_by_user = load_chats() or {}

    user = (users.get(user_email, {}) if isinstance(users, dict) else {}) or {}
    user_name = (user.get("name") or "").strip()
    business  = (user.get("business") or user.get("businessType") or "business").strip()

    lead = None
    for ld in (leads_by_user.get(user_email, []) if isinstance(leads_by_user, dict) else []) or []:
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
        r = pyrequests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "openai/gpt-4o",
                "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
                "max_tokens": 220,
                "temperature": 0.7,
            },
            timeout=30,
        )

        j = r.json() if r.ok else {}
        prompt = ((j.get("choices") or [{}])[0].get("message", {}) or {}).get("content", "").strip()
        if not prompt:
            return jsonify({"error": (j.get("error", {}) or {}).get("message", "AI response was empty")}), 502

        # clean output
        prompt = re.sub(r"^(Subject|Lead Name|Recipient)\s*:\s*.*\n?", "", prompt, flags=re.I|re.M).strip()
        prompt = re.sub(r"\n{3,}", "\n\n", prompt).strip()

        return jsonify({"prompt": prompt}), 200

    except Exception as e:
        try:
            app.logger.warning("[AI PROMPT ERROR] %s", e)
        except Exception:
            pass
        return jsonify({"error": "Failed to get AI response"}), 502

# ============================================================
# AUTOMATIONS (INLINE) — engine + routes
# ============================================================
CHANNEL_EMAIL = "email"
CHANNEL_WHATSAPP = "whatsapp"

def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)

def ensure_files():
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
    data = read_json(FILE_NOTIFICATIONS, {"notifications": []})
    notif = {
        "id": str(uuid.uuid4()),
        "owner": (owner_email or "").lower(),
        "title": title,
        "body": body,
        "created_at": now_utc().isoformat()
    }
    data.setdefault("notifications", []).insert(0, notif)
    write_json(FILE_NOTIFICATIONS, data)

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

def send_email_sendgrid_auto(to_email: str, subject: str, html: str, business_name: str) -> bool:
    if not SENDGRID_API_KEY:
        print("[Automations] SENDGRID_API_KEY missing; skipping email send (simulated).")
        return True
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        msg = Mail(
            from_email=Email(SENDER_EMAIL, business_name or "RetainAI"),
            to_emails=to_email,
            subject=subject,
            html_content=html,
        )
        resp = sg.send(msg)
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
        r = pyrequests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "openrouter/auto",
                "messages": [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
            timeout=25,
        )
        data = r.json()
        txt = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return (txt or f"Quick check-in — want to grab a spot with {business_name}? {booking}").strip()
    except Exception:
        return f"Quick check-in — want to grab a spot with {business_name}? {booking}"

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
    if not to or bool(lead.get("wa_opt_out")):
        return True

    raw = step.get("text") or run.get("memo", {}).get("last_ai_text") or ""
    body = render_text(raw, lead, run, profile)
    if contains_blockers(body):
        create_notification(user_email, "Setup needed", "WhatsApp message blocked: missing profile values (booking link / business name).")
        return True

    inside24 = within_24h(user_email, lead_id)
    if inside24:
        try:
            resp = wa_send_text(to, body)
            ok = getattr(resp, "status_code", 500) < 400
        except Exception:
            ok = False
        if ok:
            mark_sent(run, CHANNEL_WHATSAPP)
            append_chat_message(user_email, lead_id, body)
        return True

    tpl_name, used_lang, pcount = choose_wa_template(step.get("template_name"), os.getenv("WHATSAPP_TEMPLATE_LANG", "en"))
    if not tpl_name or not used_lang:
        create_notification(user_email, "WhatsApp template unavailable", "No approved template/locale available to send outside the 24h window.")
        return True

    params = build_wa_params(pcount, lead, profile, run, body)
    shown = f"[template:{tpl_name}/{used_lang}] {body}"
    try:
        resp = wa_send_template(to, tpl_name, used_lang, params)
        ok = getattr(resp, "status_code", 500) < 400
    except Exception:
        ok = False
    if ok:
        mark_sent(run, CHANNEL_WHATSAPP)
        append_chat_message(user_email, lead_id, shown)
    return True

def execute_step(flow: Dict[str, Any], step: Dict[str, Any], lead: Dict[str, Any], run: Dict[str, Any], caps: Dict[str, Any], profile: Dict[str, Any]) -> bool:
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
        text = ai_draft_message({"lead": lead, "flow": flow, "business_name": profile.get("business_name"), "booking_link": profile.get("booking_link")})
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
        html = render_text(step.get("html") or "<p>Hi {{lead.first_name}}, just checking in. <a href='{{booking_link}}'>Book here</a>.</p>", lead, run, profile)
        if contains_blockers(subject) or contains_blockers(html):
            create_notification(lead.get("owner") or flow.get("owner") or "", "Setup needed", "Email blocked: missing profile values (booking link / business name).")
            return True

        ok = send_email_sendgrid_auto(email, subject, html, profile.get("business_name") or "RetainAI")
        if ok:
            mark_sent(run, CHANNEL_EMAIL)
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
                leads_by_user = load_leads() or {}
                arr = leads_by_user.get(owner, []) or []
                for i, ld in enumerate(arr):
                    if (ld.get("id") == lead.get("id")) or (ld.get("email") == lead.get("email")):
                        arr[i] = lead
                        break
                leads_by_user[owner] = arr
                save_leads(leads_by_user)
        return True

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

def engine_tick():
    ensure_files()
    flows_db = read_json(FILE_AUTOMATIONS, {"users": {}})
    state = load_state()
    leads_by_user = load_leads() or {}

    if not isinstance(leads_by_user, dict):
        return

    for user, flows in (flows_db.get("users", {}) or {}).items():
        profile = load_user_profile(user)
        user_leads = leads_by_user.get(user, []) or []

        for flow in (flows or []):
            if not flow.get("enabled", False):
                continue
            flow_id = flow.get("id") or str(uuid.uuid4())
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

# ----------------------------
# Automations blueprint
# ----------------------------
from flask import Blueprint
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
        }
    ]

@automations_bp.route("/templates", methods=["GET"])
def automations_templates():
    return jsonify({"templates": builtin_templates()})

@automations_bp.route("/", methods=["GET"])
def list_flows_route():
    user = user_from_request()
    flows = load_user_flows(user)
    for f in flows:
        f.setdefault("id", str(uuid.uuid4()))
    return jsonify({"flows": flows})

@automations_bp.route("/", methods=["POST"])
def create_flow_route():
    user = user_from_request()
    body = request.get_json(force=True) or {}
    flow = body.get("flow", {}) or {}
    flow.setdefault("id", str(uuid.uuid4()))
    flow.setdefault("enabled", False)
    flow["owner"] = user
    flows = load_user_flows(user)
    flows.append(flow)
    save_user_flows(user, flows)
    return jsonify({"ok": True, "flow": flow})

@automations_bp.route("/<flow_id>", methods=["PUT"])
def update_flow_route(flow_id):
    user = user_from_request()
    body = request.get_json(force=True) or {}
    flows = load_user_flows(user)
    for i, f in enumerate(flows):
        if f.get("id") == flow_id:
            merged = {**f, **(body.get("flow", {}) or {})}
            merged["id"] = flow_id
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
    for f in flows:
        if f.get("id") == flow_id:
            f["enabled"] = enabled
            save_user_flows(user, flows)
            return jsonify({"ok": True, "flow": f})
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

# ============================
# VAPID Push — persisted subscriptions
# ============================
@app.route("/api/vapid-public-key", methods=["GET"])
def get_vapid_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})

def subs_load() -> Dict[str, Any]:
    data = read_json(FILE_SUBSCRIPTIONS, {"subscriptions": {}})
    return (data.get("subscriptions") or {})

def subs_save(subs: Dict[str, Any]):
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
# Scheduler (PROD SAFE)
# ----------------------------
scheduler = APScheduler()
scheduler.init_app(app)

def _start_scheduler_once():
    """
    DO NOT run this in multiple gunicorn workers.
    Best practice: create a separate "worker" service for scheduler with:
      ENABLE_SCHEDULER=1 and WEB_CONCURRENCY=1
    """
    if os.getenv("ENABLE_SCHEDULER", "0") != "1":
        return
    try:
        if not scheduler.running:
            scheduler.add_job(id="lead_reminders", func=check_for_lead_reminders, trigger="interval", hours=6, replace_existing=True)
            scheduler.add_job(id="birthdays", func=send_birthday_greetings, trigger="cron", hour=9, minute=5, replace_existing=True)
            scheduler.add_job(id="trial_ending", func=send_trial_ending_soon, trigger="cron", hour=9, minute=10, replace_existing=True)
            # Automations engine tick every 5 minutes
            scheduler.add_job(id="automations_tick", func=engine_tick, trigger="interval", minutes=5, replace_existing=True)

            scheduler.start()
            print("[Scheduler] started")
    except Exception as e:
        print("[Scheduler] failed to start:", e)

@app.before_request
def _bootstrap_scheduler():
    _start_scheduler_once()

# ----------------------------
# Run local (NO debug in production)
# ----------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)

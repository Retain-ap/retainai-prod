# ============================
# app.py (PRODUCTION READY)
# RetainAI Backend - single-file build
# Part 1 of 2
# ============================

import os
import json
import re
import hmac
import hashlib
import uuid
import datetime
import urllib.parse
from typing import Any, Dict, List, Optional

import requests as pyrequests
import stripe
from dotenv import load_dotenv

from flask import (
    Flask,
    request,
    jsonify,
    redirect,
    send_from_directory,
    Blueprint,
)

from flask_cors import CORS
from flask_apscheduler import APScheduler

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email

from google.oauth2 import id_token
from google.auth.transport import requests as grequests

from datetime import datetime as dt, timedelta

def home():
    return jsonify({"status": "RetainAI backend running.", "env": ENV})

# ------------------------------------------------------------
# Env / Boot
# ------------------------------------------------------------
ENV = (os.getenv("FLASK_ENV") or os.getenv("ENV") or "production").lower()
IS_PROD = ENV == "production"

if not IS_PROD:
    load_dotenv()  # local/dev only

print(f"[BOOT] RetainAI started | ENV={ENV} | PID={os.getpid()}")

app = Flask(__name__)

# CORS: allow FRONTEND_URL in prod + localhost in dev
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
CORS(
    app,
    resources={r"/api/*": {"origins": [FRONTEND_URL, "http://localhost:3000", "http://127.0.0.1:3000"]}},
    supports_credentials=True,
)

# Scheduler toggle (prevents duplicates in multi-worker gunicorn)
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "0") == "1"

# ------------------------------------------------------------
# Persistent storage root (Render disk in prod)
# ------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
DATA_ROOT = os.getenv("DATA_DIR") or os.getenv("DATA_DIR") or os.getenv("DATA_ROOT") or os.path.join(BASE_DIR, "data")
os.makedirs(DATA_ROOT, exist_ok=True)

LEADS_FILE         = os.path.join(DATA_ROOT, "leads.json")
USERS_FILE         = os.path.join(DATA_ROOT, "users.json")
NOTIFICATIONS_FILE = os.path.join(DATA_ROOT, "notifications.json")
APPOINTMENTS_FILE  = os.path.join(DATA_ROOT, "appointments.json")
CHAT_FILE          = os.path.join(DATA_ROOT, "whatsapp_chats.json")
STATUS_FILE        = os.path.join(DATA_ROOT, "whatsapp_status.json")

ICS_DIR = os.path.join(DATA_ROOT, "ics_files")
os.makedirs(ICS_DIR, exist_ok=True)

# Automations engine files (kept in same disk root)
FILE_AUTOMATIONS     = os.path.join(DATA_ROOT, "automations.json")
FILE_STATE           = os.path.join(DATA_ROOT, "automation_state.json")
FILE_NOTIFICATIONS2  = os.path.join(DATA_ROOT, "notifications_v2.json")
FILE_USERS2          = os.path.join(DATA_ROOT, "users_profiles.json")


# ------------------------------------------------------------
# Third-party keys
# ------------------------------------------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
SENDGRID_API_KEY   = os.getenv("SENDGRID_API_KEY")
SENDER_EMAIL       = os.getenv("SENDER_EMAIL", "noreply@retainai.ca")

VAPID_PUBLIC_KEY   = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY  = os.getenv("VAPID_PRIVATE_KEY")

# Stripe
STRIPE_SECRET_KEY        = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID          = os.getenv("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET    = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_CONNECT_CLIENT_ID = os.getenv("STRIPE_CONNECT_CLIENT_ID")
STRIPE_REDIRECT_URI      = os.getenv("STRIPE_REDIRECT_URI")  # used by oauth connect flow
stripe.api_key = STRIPE_SECRET_KEY

ZERO_DECIMAL = {"bif","clp","djf","gnf","jpy","kmf","krw","mga","pyg","rwf","ugx","vnd","vuv","xaf","xof","xpf"}

# WhatsApp Cloud API (used in Part 2)
WHATSAPP_TOKEN         = os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_ID      = os.getenv("WHATSAPP_PHONE_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN  = os.getenv("WHATSAPP_VERIFY_TOKEN", "retainai-verify")
WHATSAPP_WABA_ID       = os.getenv("WHATSAPP_WABA_ID") or os.getenv("WHATSAPP_BUSINESS_ID")
WHATSAPP_TEMPLATE_DEFAULT = os.getenv("WHATSAPP_TEMPLATE_DEFAULT", "retainai_outreach")
WHATSAPP_TEMPLATE_LANG = os.getenv("WHATSAPP_TEMPLATE_LANG", "en_US")
APP_SECRET             = os.getenv("APP_SECRET") or os.getenv("META_APP_SECRET")
DEFAULT_COUNTRY_CODE   = (os.getenv("DEFAULT_COUNTRY_CODE") or "1").strip()

# Google OAuth (used in Part 1)
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI")
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
]


# ------------------------------------------------------------
# Optional blueprints (won't break if missing)
# ------------------------------------------------------------
def _try_register_blueprints():
    # NOTE: these imports were in your original build.
    # We keep them optional so production never hard-crashes if a file is missing.
    for mod, bp_name, url_prefix in [
        ("app_imports", "imports_bp", "/api/imports"),
        ("app_team", "team_bp", "/api/team"),
        ("app_wa_auto_appointments", "WA_AUTO_BP", "/api/wa-auto"),
    ]:
        try:
            m = __import__(mod, fromlist=[bp_name])
            bp = getattr(m, bp_name, None)
            if bp and bp.name not in app.blueprints:
                app.register_blueprint(bp, url_prefix=url_prefix)
                print(f"[BOOT] Registered blueprint {mod}.{bp_name} at {url_prefix}")
        except Exception as e:
            print(f"[BOOT] Blueprint skipped ({mod}): {e}")

_try_register_blueprints()


# ------------------------------------------------------------
# Helpers: time, atomic JSON, normalization
# ------------------------------------------------------------
def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)

def _iso_utc() -> str:
    return _now_utc().isoformat().replace("+00:00", "") + "Z"

def _parse_dt_utc(ts: Optional[str]) -> Optional[datetime.datetime]:
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None

def _atomic_write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def _read_json(path: str, default: Any) -> Any:
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _norm_email(s: Optional[str]) -> str:
    return (s or "").strip().lower()

def _ensure_store_files():
    # Create empty stores if missing (never crash on first run)
    if not os.path.exists(LEADS_FILE): _atomic_write_json(LEADS_FILE, {})
    if not os.path.exists(USERS_FILE): _atomic_write_json(USERS_FILE, {})
    if not os.path.exists(NOTIFICATIONS_FILE): _atomic_write_json(NOTIFICATIONS_FILE, {})
    if not os.path.exists(APPOINTMENTS_FILE): _atomic_write_json(APPOINTMENTS_FILE, {})
    if not os.path.exists(CHAT_FILE): _atomic_write_json(CHAT_FILE, {})
    if not os.path.exists(STATUS_FILE): _atomic_write_json(STATUS_FILE, {})
    if not os.path.exists(FILE_AUTOMATIONS): _atomic_write_json(FILE_AUTOMATIONS, {"users": {}})
    if not os.path.exists(FILE_STATE): _atomic_write_json(FILE_STATE, {})
    if not os.path.exists(FILE_NOTIFICATIONS2): _atomic_write_json(FILE_NOTIFICATIONS2, {"notifications": []})
    if not os.path.exists(FILE_USERS2): _atomic_write_json(FILE_USERS2, {"users": {}})

_ensure_store_files()


# ------------------------------------------------------------
# Storage accessors
# ------------------------------------------------------------
def load_leads() -> Dict[str, List[Dict[str, Any]]]:
    return _read_json(LEADS_FILE, {}) or {}

def save_leads(data: Dict[str, List[Dict[str, Any]]]) -> None:
    _atomic_write_json(LEADS_FILE, data or {})

def load_users() -> Dict[str, Dict[str, Any]]:
    return _read_json(USERS_FILE, {}) or {}

def save_users(users: Dict[str, Dict[str, Any]]) -> None:
    _atomic_write_json(USERS_FILE, users or {})

def load_notifications() -> Dict[str, List[Dict[str, Any]]]:
    return _read_json(NOTIFICATIONS_FILE, {}) or {}

def save_notifications(data: Dict[str, List[Dict[str, Any]]]) -> None:
    _atomic_write_json(NOTIFICATIONS_FILE, data or {})

def load_appointments() -> Dict[str, List[Dict[str, Any]]]:
    return _read_json(APPOINTMENTS_FILE, {}) or {}

def save_appointments(data: Dict[str, List[Dict[str, Any]]]) -> None:
    _atomic_write_json(APPOINTMENTS_FILE, data or {})

def load_chats() -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    return _read_json(CHAT_FILE, {}) or {}

def save_chats(data: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> None:
    _atomic_write_json(CHAT_FILE, data or {})

def load_statuses() -> Dict[str, Dict[str, Any]]:
    return _read_json(STATUS_FILE, {}) or {}

def save_statuses(data: Dict[str, Dict[str, Any]]) -> None:
    _atomic_write_json(STATUS_FILE, data or {})


# ------------------------------------------------------------
# SendGrid email helpers
# ------------------------------------------------------------
def send_email_with_template(
    to_email: str,
    template_id: str,
    dynamic_data: Dict[str, Any],
    subject: Optional[str] = None,
    from_email: Optional[str] = None,
    reply_to_email: Optional[str] = None,
) -> bool:
    if not SENDGRID_API_KEY:
        print("[SENDGRID] SENDGRID_API_KEY missing; skipping send (simulated ok).")
        return True

    to_email = (to_email or "").strip()
    if not to_email:
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
        resp = sg.send(message)
        ok = (resp.status_code == 202)
        print(f"[SENDGRID] status={resp.status_code} to={to_email} template={template_id}")
        return ok
    except Exception as e:
        print(f"[SENDGRID ERROR] to={to_email} template={template_id} err={e}")
        return False


# Templates (as provided)
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


def send_welcome_email(to_email: str, user_name: str = "", business_type: str = "") -> bool:
    return send_email_with_template(
        to_email=to_email,
        template_id=SG_TEMPLATE_WELCOME,
        dynamic_data={"user_name": user_name or "", "business_type": business_type or ""},
        subject="Welcome to RetainAI",
        from_email="welcome@retainai.ca",
    )

def send_birthday_email(lead_email: str, lead_name: str, business_name: str) -> bool:
    return send_email_with_template(
        to_email=lead_email,
        template_id=SG_TEMPLATE_BIRTHDAY,
        dynamic_data={"lead_name": lead_name, "business_name": business_name},
        subject=f"Happy Birthday, {lead_name}!",
        from_email=SENDER_EMAIL,
    )

def send_birthday_reminder_to_user(user_email: str, user_name: str, lead_name: str, business_name: str, birthday: str) -> bool:
    return send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_BDAY_REMINDER_USER,
        dynamic_data={"user_name": user_name, "lead_name": lead_name, "business_name": business_name, "birthday": birthday},
        subject=f"Birthday Reminder: {lead_name}'s birthday is tomorrow",
        from_email="reminder@retainai.ca",
    )

def send_trial_ending_email(user_email: str, user_name: str, business_name: str, trial_end_date: str) -> bool:
    return send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_TRIAL_ENDING,
        dynamic_data={"user_name": user_name, "business_name": business_name, "trial_end_date": trial_end_date},
        subject="Your trial is ending soon",
        from_email=SENDER_EMAIL,
    )


# ------------------------------------------------------------
# Health
# ------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return "ok", 200


# ------------------------------------------------------------
# Calendar / ICS helpers
# ------------------------------------------------------------
def create_ics_file(appt: Dict[str, Any]) -> str:
    uid = appt.get("id") or str(uuid.uuid4())
    # appt['appointment_time'] expected like "YYYY-mm-ddTHH:MM:SS"
    dt_start = datetime.datetime.strptime(appt["appointment_time"], "%Y-%m-%dT%H:%M:%S")
    dt_end = dt_start + datetime.timedelta(minutes=int(appt.get("duration", 30)))
    summary = f"Appointment with {appt.get('user_name','')} at {appt.get('business_name','')}"
    description = f"Appointment at {appt.get('appointment_location','')} with {appt.get('user_name','')}"
    ics_content = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//RetainAI//EN\n"
        "BEGIN:VEVENT\n"
        f"UID:{uid}\n"
        f"DTSTAMP:{dt_start.strftime('%Y%m%dT%H%M%SZ')}\n"
        f"DTSTART:{dt_start.strftime('%Y%m%dT%H%M%SZ')}\n"
        f"DTEND:{dt_end.strftime('%Y%m%dT%H%M%SZ')}\n"
        f"SUMMARY:{summary}\n"
        f"DESCRIPTION:{description}\n"
        f"LOCATION:{appt.get('appointment_location','')}\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )
    fname = f"{uid}.ics"
    with open(os.path.join(ICS_DIR, fname), "w", encoding="utf-8") as f:
        f.write(ics_content)
    return fname

@app.route("/ics/<path:filename>")
def serve_ics(filename):
    return send_from_directory(ICS_DIR, filename, as_attachment=True)

def make_google_calendar_link(appt: Dict[str, Any]) -> str:
    dt_start = datetime.datetime.strptime(appt["appointment_time"], "%Y-%m-%dT%H:%M:%S")
    dt_end = dt_start + datetime.timedelta(minutes=int(appt.get("duration", 30)))
    start_str = dt_start.strftime("%Y%m%dT%H%M%SZ")
    end_str = dt_end.strftime("%Y%m%dT%H%M%SZ")
    title = f"Appointment with {appt.get('user_name','')} at {appt.get('business_name','')}"
    location = urllib.parse.quote_plus(appt.get("appointment_location", ""))
    details = urllib.parse.quote_plus(f"Appointment with {appt.get('user_name','')} at {appt.get('business_name','')}.")
    return (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={urllib.parse.quote_plus(title)}"
        f"&dates={start_str}/{end_str}"
        f"&details={details}"
        f"&location={location}"
    )


# ------------------------------------------------------------
# Notifications + scheduler tasks (email reminders)
# ------------------------------------------------------------
def log_notification(user_email: str, subject: str, message: str, lead_email: Optional[str] = None) -> None:
    user_email = _norm_email(user_email)
    notes = load_notifications()
    notes.setdefault(user_email, []).append({
        "timestamp": _iso_utc(),
        "subject": subject,
        "message": message,
        "lead_email": lead_email,
        "read": False,
    })
    save_notifications(notes)

def _send_warning_summary_email(user_email: str, warning_leads: List[Dict[str, Any]], interval: int) -> None:
    if not warning_leads:
        return
    users = load_users()
    user = users.get(user_email, {})
    user_name = (user.get("name") or (user_email.split("@")[0].title() if user_email else ""))
    lead_list_html = "<ul style='padding-left:24px;margin:0;'>"
    for lead in warning_leads:
        lead_list_html += (
            "<li style='margin-bottom:16px;color:#FFD700;'>"
            f"<span style='font-weight:700;font-size:1.1em;'>{(lead.get('name') or '-')}</span><br>"
            f"<span style='color:#fff;'>Email:</span> <span style='color:#FFD700;'>{(lead.get('email') or '-')}</span><br>"
            f"<span style='color:#fff;'>Last Contacted:</span> <span style='color:#FFD700;'>{(lead.get('last_contacted') or lead.get('createdAt') or '-')}</span>"
            "</li>"
        )
    lead_list_html += "</ul>"

    send_email_with_template(
        to_email=user_email,
        template_id=SG_TEMPLATE_FOLLOWUP_USER,
        dynamic_data={
            "user_name": user_name,
            "lead_list": lead_list_html,
            "crm_link": f"{FRONTEND_URL}/app/dashboard",
            "year": datetime.datetime.now().year,
            "interval": interval,
            "count": len(warning_leads),
        },
        subject="⚠️ Leads Needing Attention",
        from_email=SENDER_EMAIL,
    )

def check_for_lead_reminders():
    try:
        leads_by_user = load_leads()
        users_by_email = load_users()
        now = _now_utc()

        for user_email, leads in (leads_by_user or {}).items():
            user = users_by_email.get(user_email) or {}
            business_type = (user.get("business") or "").lower()
            interval = BUSINESS_TYPE_INTERVALS.get(business_type, 14)

            warning = []
            for lead in leads or []:
                last = lead.get("last_contacted") or lead.get("createdAt")
                dt_last = _parse_dt_utc(last)
                if not dt_last:
                    continue
                days_since = (now - dt_last).days
                if interval <= days_since <= interval + 2:
                    x = dict(lead)
                    x["days_since_contact"] = days_since
                    warning.append(x)

            if warning:
                _send_warning_summary_email(user_email, warning, interval)
                log_notification(
                    user_email,
                    "Leads needing follow-up",
                    f"{len(warning)} leads require follow-up: " + ", ".join((l.get("name") or "?") for l in warning),
                )
    except Exception as e:
        print("[Scheduler] check_for_lead_reminders error:", e)

def send_birthday_greetings():
    try:
        leads_by_user = load_leads()
        users_by_email = load_users()
        today = _now_utc().strftime("%m-%d")
        tomorrow = (_now_utc() + datetime.timedelta(days=1)).strftime("%m-%d")

        for user_email, leads in (leads_by_user or {}).items():
            user = users_by_email.get(user_email) or {}
            business = user.get("business", "")
            user_name = user.get("name", "")

            for lead in leads or []:
                bday = (lead.get("birthday") or "").strip()
                if not bday or len(bday.split("-")) < 3:
                    continue
                mmdd = "-".join(bday.split("-")[1:3])

                if mmdd == today:
                    send_birthday_email(lead.get("email",""), lead.get("name",""), business)
                    log_notification(user_email, f"Happy Birthday, {lead.get('name','')}!", "Automated birthday email", lead.get("email"))

                if mmdd == tomorrow:
                    send_birthday_reminder_to_user(
                        user_email=user_email,
                        user_name=user_name,
                        lead_name=lead.get("name",""),
                        business_name=business,
                        birthday=bday,
                    )
                    log_notification(user_email, f"Reminder: {lead.get('name','')}'s birthday is tomorrow!", "Birthday reminder sent", lead.get("email"))
    except Exception as e:
        print("[Scheduler] send_birthday_greetings error:", e)

def send_trial_ending_soon():
    try:
        users = load_users()
        now = _now_utc()
        changed = False

        for email, user in (users or {}).items():
            if user.get("status") not in ["pending_payment", "active"]:
                continue

            trial_start = _parse_dt_utc(user.get("trial_start"))
            if not trial_start:
                continue

            trial_end = trial_start + datetime.timedelta(days=14)
            days_left = (trial_end - now).days

            if days_left == 2 and not user.get("trial_ending_notice_sent"):
                send_trial_ending_email(
                    user_email=email,
                    user_name=user.get("name",""),
                    business_name=user.get("business",""),
                    trial_end_date=trial_end.strftime("%B %d, %Y"),
                )
                user["trial_ending_notice_sent"] = True
                changed = True

        if changed:
            save_users(users)
    except Exception as e:
        print("[Scheduler] send_trial_ending_soon error:", e)


# ------------------------------------------------------------
# Appointments API
# ------------------------------------------------------------
@app.route("/api/appointments/<path:user_email>", methods=["GET"])
def get_appointments(user_email):
    data = load_appointments()
    return jsonify({"appointments": data.get(_norm_email(user_email), [])}), 200

@app.route("/api/appointments/<path:user_email>", methods=["POST"])
def create_appointment(user_email):
    user_email = _norm_email(user_email)
    data = request.get_json(force=True) or {}

    appt = {
        "id": str(uuid.uuid4()),
        "lead_email": data.get("lead_email"),
        "lead_first_name": data.get("lead_first_name") or "",
        "user_name": data.get("user_name") or "",
        "user_email": data.get("user_email") or user_email,
        "business_name": data.get("business_name") or "",
        "appointment_time": data.get("appointment_time"),
        "appointment_location": data.get("appointment_location") or "",
        "duration": int(data.get("duration") or 30),
        "notes": data.get("notes") or "",
    }

    if not appt["lead_email"] or not appt["appointment_time"]:
        return jsonify({"error": "lead_email and appointment_time are required"}), 400

    appointments = load_appointments()
    appointments.setdefault(user_email, []).append(appt)
    save_appointments(appointments)

    create_ics_file(appt)
    display_time = datetime.datetime.strptime(appt["appointment_time"], "%Y-%m-%dT%H:%M:%S").strftime("%B %d, %Y, %I:%M %p")
    ics_url = f"{request.host_url.rstrip('/')}/ics/{appt['id']}.ics"
    gcal = make_google_calendar_link(appt)

    send_email_with_template(
        to_email=appt["lead_email"],
        template_id=SG_TEMPLATE_APPT_CONFIRM,
        dynamic_data={
            "lead_first_name": appt["lead_first_name"],
            "user_name": appt["user_name"],
            "business_name": appt["business_name"],
            "display_time": display_time,
            "appointment_location": appt["appointment_location"],
            "google_calendar_link": gcal,
            "ics_file_url": ics_url,
            "user_email": appt["user_email"],
        },
        subject="Appointment Confirmation",
        from_email=SENDER_EMAIL,
    )

    return jsonify({"message": "Appointment created and confirmation sent!", "appointment": appt}), 201

@app.route("/api/appointments/<path:user_email>/<appt_id>", methods=["PUT"])
def update_appointment(user_email, appt_id):
    user_email = _norm_email(user_email)
    data = request.get_json(force=True) or {}
    appointments = load_appointments()
    arr = appointments.get(user_email, []) or []
    updated = None
    for i, appt in enumerate(arr):
        if appt.get("id") == appt_id:
            for k, v in data.items():
                arr[i][k] = v
            updated = arr[i]
            create_ics_file(updated)
            break
    appointments[user_email] = arr
    save_appointments(appointments)
    return jsonify({"updated": bool(updated), "appointment": updated}), 200

@app.route("/api/appointments/<path:user_email>/<appt_id>", methods=["DELETE"])
def delete_appointment(user_email, appt_id):
    user_email = _norm_email(user_email)
    appointments = load_appointments()
    arr = appointments.get(user_email, []) or []
    before = len(arr)
    arr = [a for a in arr if a.get("id") != appt_id]
    appointments[user_email] = arr
    save_appointments(appointments)

    fname = os.path.join(ICS_DIR, f"{appt_id}.ics")
    if os.path.exists(fname):
        try: os.remove(fname)
        except Exception: pass

    return jsonify({"deleted": before - len(arr)}), 200


# ------------------------------------------------------------
# Stripe helpers + endpoints
# ------------------------------------------------------------
def to_minor(amount: float, currency: str) -> int:
    c = (currency or "usd").lower()
    return int(round(float(amount) * (1 if c in ZERO_DECIMAL else 100)))

def from_minor(value: int, currency: str) -> float:
    c = (currency or "usd").lower()
    denom = 1 if c in ZERO_DECIMAL else 100.0
    return (value or 0) / denom

def get_connected_acct(user_email: str) -> Optional[str]:
    users = load_users()
    return (users.get(_norm_email(user_email), {}) or {}).get("stripe_account_id")

def serialize_invoice(inv) -> Dict[str, Any]:
    currency = inv.currency
    cust_name = (
        (getattr(getattr(inv, "customer", None), "name", None))
        or (getattr(inv, "metadata", {}) or {}).get("customer_name")
        or inv.customer_email
    )
    amount_total = from_minor(getattr(inv, "total", None) or inv.amount_due, currency)
    amount_due   = from_minor(inv.amount_due, currency)
    amount_paid  = from_minor(getattr(inv, "amount_paid", 0), currency)
    display      = amount_total if inv.status == "paid" else amount_due
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
    }

@app.route("/api/stripe/connect-url", methods=["GET"])
def get_stripe_connect_url():
    user_email = _norm_email(request.args.get("user_email"))
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400
    acct = stripe.Account.create(type="express", email=user_email)
    users = load_users()
    users.setdefault(user_email, {})
    users[user_email]["stripe_account_id"] = acct.id
    users[user_email]["stripe_connected"] = True
    save_users(users)

    return_url = f"{FRONTEND_URL}/app?stripe_connected=1"
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
    user_email = _norm_email(request.args.get("user_email"))
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400
    if not STRIPE_CONNECT_CLIENT_ID or not STRIPE_REDIRECT_URI:
        return jsonify({"error": "Stripe Connect not configured"}), 500

    oauth_url = (
        "https://connect.stripe.com/oauth/authorize"
        f"?response_type=code"
        f"&client_id={urllib.parse.quote_plus(STRIPE_CONNECT_CLIENT_ID)}"
        f"&scope=read_write"
        f"&redirect_uri={urllib.parse.quote_plus(STRIPE_REDIRECT_URI)}"
        f"&state={urllib.parse.quote_plus(user_email)}"
    )
    return jsonify({"url": oauth_url}), 200

@app.route("/api/stripe/dashboard-link", methods=["GET"])
def stripe_dashboard_link():
    user_email = _norm_email(request.args.get("user_email"))
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400
    users = load_users()
    acct_id = (users.get(user_email, {}) or {}).get("stripe_account_id")
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 400
    acct = stripe.Account.retrieve(acct_id)
    if acct.type in ("express", "custom"):
        link = stripe.Account.create_login_link(acct_id)
        return jsonify({"url": link.url}), 200
    return jsonify({"url": f"https://dashboard.stripe.com/{acct_id}"}), 200

@app.route("/api/stripe/oauth/callback", methods=["GET"])
def stripe_oauth_callback():
    error = request.args.get("error")
    error_desc = request.args.get("error_description", "")
    user_email = _norm_email(request.args.get("state"))
    if error:
        msg = urllib.parse.quote_plus(error_desc)
        return redirect(f"{FRONTEND_URL}/app?stripe_error=1&stripe_error_desc={msg}")

    code = request.args.get("code")
    if not code or not user_email:
        return redirect(f"{FRONTEND_URL}/app?stripe_error=1&stripe_error_desc=missing_code_or_state")

    resp = stripe.OAuth.token(grant_type="authorization_code", code=code)
    stripe_user_id = resp["stripe_user_id"]

    users = load_users()
    users.setdefault(user_email, {})
    users[user_email]["stripe_account_id"] = stripe_user_id
    users[user_email]["stripe_connected"] = True
    save_users(users)

    return redirect(f"{FRONTEND_URL}/app?stripe_connected=1")

@app.route("/api/stripe/account", methods=["GET"])
def get_stripe_account():
    user_email = _norm_email(request.args.get("user_email"))
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400
    acct_id = get_connected_acct(user_email)
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 404
    acct = stripe.Account.retrieve(acct_id)
    return jsonify({
        "account": {
            "id": acct.id,
            "default_currency": acct.default_currency,
            "details_submitted": acct.details_submitted,
            "email": acct.email,
        }
    }), 200

@app.route("/api/stripe/invoice", methods=["POST"])
def create_stripe_invoice():
    data = request.get_json(force=True) or {}

    user_email = _norm_email(data.get("user_email"))
    customer_name = (data.get("customer_name") or "").strip()
    customer_email = (data.get("customer_email") or "").strip()
    description = (data.get("description") or "").strip()
    amount = data.get("amount")
    currency = (data.get("currency") or "").lower().strip() or None
    quantity = int(data.get("quantity") or 1)

    if not all([user_email, customer_name, customer_email, description, amount]):
        return jsonify({"error": "Missing required fields"}), 400

    try:
        total_float = float(amount)
        if total_float <= 0:
            raise ValueError()
    except Exception:
        return jsonify({"error": "Amount must be a number > 0"}), 400

    acct_id = get_connected_acct(user_email)
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 400

    try:
        if not currency:
            acct = stripe.Account.retrieve(acct_id)
            currency = (acct.default_currency or "usd").lower()

        existing = stripe.Customer.list(email=customer_email, limit=1, stripe_account=acct_id).data
        if existing:
            cust = existing[0]
            stripe.Customer.modify(cust.id, name=customer_name, stripe_account=acct_id)
        else:
            cust = stripe.Customer.create(email=customer_email, name=customer_name, stripe_account=acct_id)

        inv = stripe.Invoice.create(
            customer=cust.id,
            collection_method="send_invoice",
            days_until_due=7,
            auto_advance=False,
            metadata={"user_email": user_email, "customer_name": customer_name},
            stripe_account=acct_id,
        )

        total_minor = to_minor(total_float, currency)
        stripe.InvoiceItem.create(
            customer=cust.id,
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
            "invoice_id": inv.id,
            "invoice_url": inv.hosted_invoice_url,
            "amount_due": from_minor(inv.amount_due, inv.currency),
            "amount_total": from_minor(getattr(inv, "total", None) or inv.amount_due, inv.currency),
            "currency": inv.currency,
            "invoice": serialize_invoice(inv),
            "invoices": invoices,
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stripe/invoices", methods=["GET"])
def list_stripe_invoices():
    user_email = _norm_email(request.args.get("user_email"))
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400
    acct_id = get_connected_acct(user_email)
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 400

    invs = stripe.Invoice.list(limit=100, expand=["data.customer"], stripe_account=acct_id).data
    out = [serialize_invoice(inv) for inv in invs]
    return jsonify({"invoices": out}), 200

@app.route("/api/stripe/invoice/send", methods=["POST"])
def resend_invoice_email():
    data = request.get_json(force=True) or {}
    invoice_id = data.get("invoice_id")
    user_email = _norm_email(data.get("user_email"))
    if not invoice_id or not user_email:
        return jsonify({"error": "Missing invoice_id or user_email"}), 400

    users = load_users()
    user = users.get(user_email)
    if not user:
        return jsonify({"error": "User not found"}), 404
    acct_id = user.get("stripe_account_id")
    if not acct_id:
        return jsonify({"error": "Stripe account not connected"}), 400

    user_name = user.get("name", "")
    business = user.get("business", "")

    try:
        inv = stripe.Invoice.retrieve(invoice_id, expand=["customer"], stripe_account=acct_id)
        total = from_minor(getattr(inv, "total", None) or inv.amount_due, inv.currency)
        cust = inv.customer
        html = f"""
          <p>Hi {(inv.metadata.get("customer_name","") or "")},</p>
          <p>Your invoice <strong>#{inv.number}</strong> from <strong>{business}</strong> is now available.</p>
          <p><strong>Amount:</strong> {total:.2f} {inv.currency.upper()}</p>
          <p><a href="{inv.hosted_invoice_url}">View &amp; pay your invoice →</a></p>
          <br/>
          <p>Thanks for working with {business}!</p>
        """
        msg = Mail(
            from_email=Email("billing@retainai.ca", name=f"{user_name} at {business}"),
            to_emails=getattr(cust, "email", None) or inv.customer_email,
            subject=f"Invoice #{inv.number} from {business}",
            html_content=html,
        )
        if not SENDGRID_API_KEY:
            return jsonify({"success": True, "note": "SENDGRID_API_KEY missing; simulated"}), 200
        SendGridAPIClient(SENDGRID_API_KEY).send(msg)
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    if not STRIPE_WEBHOOK_SECRET:
        return "", 200

    payload = request.data
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
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
    user_email = _norm_email(request.args.get("user_email"))
    if not user_email:
        return jsonify({"error": "Missing user_email"}), 400
    users = load_users()
    user = users.get(user_email)
    if not user or not user.get("stripe_account_id"):
        return jsonify({"error": "No Stripe account to disconnect"}), 400
    acct_id = user["stripe_account_id"]
    try:
        if STRIPE_CONNECT_CLIENT_ID:
            stripe.OAuth.deauthorize(client_id=STRIPE_CONNECT_CLIENT_ID, stripe_user_id=acct_id)
    except Exception as e:
        app.logger.warning(f"Stripe deauth failed for {acct_id}: {e}")
    user.pop("stripe_account_id", None)
    user["stripe_connected"] = False
    save_users(users)
    return ("", 204)


# ------------------------------------------------------------
# Auth + Google OAuth
# NOTE: Keeps your behavior: login requires status=active
# ------------------------------------------------------------
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "14"))

@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True) or {}
    email = _norm_email(data.get("email"))
    password = data.get("password")
    businessType = (data.get("businessType") or "").strip()
    businessName = (data.get("businessName") or businessType).strip()
    name = (data.get("name") or "").strip()
    teamSize = (data.get("teamSize") or "").strip()
    logo = (data.get("logo") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    users = load_users()
    if email in users:
        return jsonify({"error": "User already exists"}), 409

    trial_start = _now_utc().isoformat()  # timezone safe
    users[email] = {
        "password": password,
        "businessType": businessType,
        "business": businessName,
        "name": name,
        "teamSize": teamSize,
        "logo": logo,
        "status": "pending_payment",
        "trial_start": trial_start,
        "trial_ending_notice_sent": False,
        "stripe_connected": False,
    }
    save_users(users)

    try:
        send_welcome_email(email, name, businessName)
    except Exception as e:
        print("[WARN] send_welcome_email failed:", e)

    # Stripe Checkout subscription
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        # allow dev/testing without stripe
        return jsonify({"ok": True, "note": "Stripe not configured; user created pending_payment"}), 200

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            customer_email=email,
            subscription_data={"trial_period_days": TRIAL_DAYS, "metadata": {"user_email": email}},
            success_url=f"{FRONTEND_URL}/login?paid=1",
            cancel_url=f"{FRONTEND_URL}/login?canceled=1",
        )
        return jsonify({"checkoutUrl": session.url}), 200
    except Exception as e:
        print("[STRIPE ERROR]", e)
        return jsonify({"error": "Could not start payment process."}), 500

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    email = _norm_email(data.get("email"))
    password = data.get("password")

    users = load_users()
    user = users.get(email)
    if not user or user.get("password") != password or user.get("status") != "active":
        return jsonify({"error": "Invalid credentials or account not active"}), 401

    return jsonify({
        "message": "Login successful",
        "user": {
            "email": email,
            "name": user.get("name",""),
            "logo": user.get("picture","") or user.get("logo",""),
            "businessType": user.get("businessType",""),
            "business": user.get("business",""),
            "people": user.get("people",""),
            "location": user.get("location",""),
            "stripe_account_id": user.get("stripe_account_id"),
            "stripe_connected": user.get("stripe_connected", False),
        }
    }), 200

@app.route("/api/oauth/google", methods=["POST"])
def google_oauth():
    data = request.get_json(force=True) or {}
    token = data.get("credential")
    if not token:
        return jsonify({"error": "No Google token provided"}), 400
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "GOOGLE_CLIENT_ID not configured"}), 500

    try:
        idinfo = id_token.verify_oauth2_token(token, grequests.Request(), GOOGLE_CLIENT_ID)
        email = _norm_email(idinfo.get("email"))
        name = idinfo.get("name","")
        picture = idinfo.get("picture","")

        users = load_users()
        user = users.get(email)
        if not user:
            users[email] = {
                "password": None,
                "businessType": "",
                "business": "",
                "name": name,
                "picture": picture,
                "people": "",
                "trial_start": _now_utc().isoformat(),
                "status": "pending_payment",
                "trial_ending_notice_sent": False,
                "stripe_connected": False,
            }
        else:
            if not user.get("name") and name:
                user["name"] = name
            if not user.get("picture") and picture:
                user["picture"] = picture

        save_users(users)

        return jsonify({
            "message": "Google login successful",
            "user": {
                "email": email,
                "name": users[email].get("name", name),
                "logo": users[email].get("picture", picture),
                "businessType": users[email].get("businessType",""),
                "business": users[email].get("business",""),
                "people": users[email].get("people",""),
                "stripe_account_id": users[email].get("stripe_account_id"),
                "stripe_connected": users[email].get("stripe_connected", False),
            }
        }), 200

    except Exception as e:
        print("[GOOGLE OAUTH ERROR]", e)
        return jsonify({"error": "Invalid Google token"}), 401

@app.route("/api/oauth/google/complete", methods=["POST"])
def google_oauth_complete():
    data = request.get_json(force=True) or {}
    email = _norm_email(data.get("email"))
    if not email:
        return jsonify({"error": "Email required"}), 400

    businessType = (data.get("businessType") or "").strip()
    businessName = (data.get("businessName") or businessType).strip()
    name = (data.get("name") or "").strip()
    logo = (data.get("logo") or "").strip()
    people = (data.get("people") or "").strip()

    users = load_users()
    if email not in users:
        return jsonify({"error": "User not found"}), 404

    users[email].update({
        "businessType": businessType,
        "business": businessName,
        "name": name or users[email].get("name",""),
        "picture": logo or users[email].get("picture",""),
        "people": people,
    })
    save_users(users)

    return jsonify({
        "message": "Profile updated",
        "user": {
            "email": email,
            "name": users[email].get("name",""),
            "logo": users[email].get("picture",""),
            "businessType": users[email].get("businessType",""),
            "business": users[email].get("business",""),
            "people": users[email].get("people",""),
            "stripe_account_id": users[email].get("stripe_account_id"),
            "stripe_connected": users[email].get("stripe_connected", False),
        }
    }), 200

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

    token_resp = pyrequests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    tokens = token_resp.json() if token_resp.ok else {}
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not access_token:
        return "Failed to obtain access token", 400

    cal_resp = pyrequests.get(
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    calendars = (cal_resp.json() or {}).get("items", []) if cal_resp.ok else []

    users = load_users()
    user = users.get(state, {}) or {}
    user["gcal_connected"] = True
    user["gcal_access_token"] = access_token
    if refresh_token:
        user["gcal_refresh_token"] = refresh_token
    user["gcal_calendars"] = [
        {"id": c.get("id"), "summary": c.get("summary"), "primary": c.get("primary", False)}
        for c in calendars
    ]
    users[state] = user
    save_users(users)

    return "Google Calendar connected! You may close this tab and return to the app."

@app.route("/api/google/status/<path:email>")
def google_status(email):
    users = load_users()
    user = users.get(_norm_email(email))
    if not user or not user.get("gcal_connected"):
        return jsonify({"connected": False})
    return jsonify({"connected": True, "calendars": user.get("gcal_calendars", [])})

@app.route("/api/google/disconnect/<path:email>", methods=["POST"])
def google_disconnect(email):
    email = _norm_email(email)
    users = load_users()
    user = users.get(email)
    if user:
        user.pop("gcal_access_token", None)
        user.pop("gcal_refresh_token", None)
        user.pop("gcal_calendars", None)
        user["gcal_connected"] = False
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

    access_token = user["gcal_access_token"]
    resp = pyrequests.get(
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if resp.status_code != 200:
        return jsonify({"error": resp.text}), 500

    items = (resp.json() or {}).get("items", [])
    out = [{"id": c.get("id"), "summary": c.get("summary"), "primary": c.get("primary", False)} for c in items]
    return jsonify({"calendars": out})

@app.route("/api/google/events/<path:email>")
def google_events(email):
    email = _norm_email(email)
    calendar_id = request.args.get("calendarId")

    users = load_users()
    user = users.get(email)
    if not user or not user.get("gcal_connected"):
        return jsonify({"error": "Not connected"}), 401

    access_token = user.get("gcal_access_token")
    if not access_token:
        return jsonify({"error": "No access token"}), 401

    if not calendar_id:
        calendar_id = "primary"
        for c in (user.get("gcal_calendars") or []):
            if c.get("primary"):
                calendar_id = c.get("id") or "primary"
                break

    now = _now_utc().isoformat().replace("+00:00", "") + "Z"
    max_time = (_now_utc() + datetime.timedelta(days=30)).isoformat().replace("+00:00", "") + "Z"
    url = (
        "https://www.googleapis.com/calendar/v3/calendars/"
        f"{urllib.parse.quote(calendar_id)}/events"
        f"?timeMin={urllib.parse.quote(now)}&timeMax={urllib.parse.quote(max_time)}"
        "&singleEvents=true&orderBy=startTime"
    )
    resp = pyrequests.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    if resp.status_code != 200:
        return jsonify({"error": resp.text}), 500
    return jsonify(resp.json() or {}), 200


# ------------------------------------------------------------
# Leads CRUD + status coloring
# ------------------------------------------------------------
@app.route("/api/leads/<path:user_email>", methods=["GET"])
def get_leads(user_email):
    user_email = _norm_email(user_email)
    leads_by_user = load_leads()
    leads = leads_by_user.get(user_email, []) or []

    users = load_users()
    user = users.get(user_email) or {}
    business_type = (user.get("business") or "").lower()
    interval = BUSINESS_TYPE_INTERVALS.get(business_type, 14)

    now = _now_utc()
    out = []

    for lead in leads:
        lead = dict(lead)
        last_contacted = lead.get("last_contacted") or lead.get("createdAt")
        last_dt = _parse_dt_utc(last_contacted)
        days_since = (now - last_dt).days if last_dt else 0

        if days_since > interval + 2:
            status = "cold";   status_color = "#e66565"
        elif interval <= days_since <= interval + 2:
            status = "warning"; status_color = "#f7cb53"
        else:
            status = "active";  status_color = "#1bc982"

        lead["status"] = status
        lead["status_color"] = status_color
        lead["days_since_contact"] = days_since

        out.append(lead)

    return jsonify({"leads": out}), 200

@app.route("/api/leads/<path:user_email>", methods=["POST"])
def save_user_leads(user_email):
    user_email = _norm_email(user_email)
    data = request.get_json(force=True) or {}
    leads = data.get("leads", [])

    if not isinstance(leads, list):
        return jsonify({"error": "Leads must be a list"}), 400

    now_iso = _iso_utc()
    for lead in leads:
        if isinstance(lead, dict) and not lead.get("last_contacted"):
            lead["last_contacted"] = lead.get("createdAt") or now_iso

    leads_by_user = load_leads()
    leads_by_user[user_email] = leads
    save_leads(leads_by_user)

    return jsonify({"message": "Leads updated", "leads": leads}), 200

@app.route("/api/leads/<path:user_email>/<lead_id>/contacted", methods=["POST"])
def mark_lead_contacted(user_email, lead_id):
    user_email = _norm_email(user_email)
    leads_by_user = load_leads()
    arr = leads_by_user.get(user_email, []) or []
    updated = False
    for lead in arr:
        if str(lead.get("id")) == str(lead_id):
            lead["last_contacted"] = _iso_utc()
            updated = True
    if updated:
        leads_by_user[user_email] = arr
        save_leads(leads_by_user)
        return jsonify({"message": "Lead marked as contacted.", "lead_id": lead_id}), 200
    return jsonify({"error": "Lead not found."}), 404


# ------------------------------------------------------------
# Notifications API (simple)
# ------------------------------------------------------------
@app.route("/api/notifications/<path:user_email>", methods=["GET"])
def get_notifications(user_email):
    user_email = _norm_email(user_email)
    notes = load_notifications().get(user_email, []) or []
    for n in notes:
        n.setdefault("read", False)
    return jsonify({"notifications": notes}), 200

@app.route("/api/notifications/<path:user_email>/<int:idx>/mark_read", methods=["POST"])
def mark_notification_read(user_email, idx):
    user_email = _norm_email(user_email)
    all_notes = load_notifications()
    user_notes = all_notes.get(user_email)
    if not user_notes or idx < 0 or idx >= len(user_notes):
        return jsonify({"error": "Notification not found"}), 404
    user_notes[idx]["read"] = True
    all_notes[user_email] = user_notes
    save_notifications(all_notes)
    return ("", 204)


# ------------------------------------------------------------
# VAPID + Push (subscription storage)
# NOTE: Real push send kept disabled unless you add pywebpush
# ------------------------------------------------------------
SUBSCRIPTIONS: Dict[str, Any] = {}

@app.route("/api/vapid-public-key", methods=["GET"])
def get_vapid_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})

@app.route("/api/save-subscription", methods=["POST"])
def save_subscription():
    data = request.get_json(force=True) or {}
    email = _norm_email(data.get("email"))
    subscription = data.get("subscription")
    if not email or not subscription:
        return jsonify({"error": "Email and subscription required"}), 400
    SUBSCRIPTIONS[email] = subscription
    return jsonify({"message": "Subscription saved"}), 200

@app.route("/api/push/notify", methods=["POST"])
def push_notify():
    data = request.get_json(force=True) or {}
    lead_email = _norm_email(data.get("lead_email"))
    sub = SUBSCRIPTIONS.get(lead_email)
    if not sub:
        return jsonify({"error": "No subscription for that lead"}), 404
    return jsonify({"error": "Push disabled in this build (add pywebpush to enable)"}), 501


# ------------------------------------------------------------
# User info API
# ------------------------------------------------------------
@app.route("/api/user/<path:email>", methods=["GET"])
def get_user(email):
    email = _norm_email(email)
    users = load_users()
    user = users.get(email)
    if not user:
        return jsonify({"error": "User not found"}), 404
    out = {
        "email": email,
        "name": user.get("name",""),
        "logo": user.get("picture","") or user.get("logo",""),
        "businessType": user.get("businessType",""),
        "business": user.get("business",""),
        "people": user.get("people",""),
        "location": user.get("location",""),
        "stripe_account_id": user.get("stripe_account_id"),
        "stripe_connected": user.get("stripe_connected", False),
        "whatsapp": user.get("whatsapp",""),
    }
    return jsonify(out), 200

# ------------------------------------------------------------
# WhatsApp Cloud API helpers + routes
# ------------------------------------------------------------
_TEMPLATE_CACHE: Dict[Any, Any] = {}
_TEMPLATE_TTL_SECONDS = 300

_MSG_CACHE: Dict[Any, Any] = {}
_MSG_CACHE_TTL_SECONDS = 2

_WABA_RES = {"id": None, "checked_at": None}
_WABA_TTL_SECONDS = 300


def _normalize_lang(code: str) -> str:
    default = (os.getenv("WHATSAPP_TEMPLATE_LANG") or "en_US").strip()
    if not code:
        return default
    c = str(code).replace("-", "_").strip()
    parts = c.split("_")
    if len(parts) == 1:
        return parts[0].lower()
    if len(parts) >= 2 and parts[0] and parts[1]:
        return parts[0].lower() + "_" + parts[1].upper()
    return c.lower()

def _primary_lang(code: str) -> str:
    if not code:
        return ""
    return code.replace("-", "_").split("_", 1)[0].lower()

def _norm_wa(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    if len(d) == 10 and DEFAULT_COUNTRY_CODE.isdigit():
        d = DEFAULT_COUNTRY_CODE + d
    return d

def _lead_matches_wa(lead: Dict[str, Any], wa_digits: str) -> bool:
    for key in ("whatsapp", "phone"):
        if _norm_wa(str(lead.get(key) or "")) == wa_digits:
            return True
    return False

def find_user_by_whatsapp(wa_id: str) -> Optional[str]:
    wa = _norm_wa(wa_id)
    leads_by_user = load_leads()
    for user_email, leads in (leads_by_user or {}).items():
        for lead in leads or []:
            if _lead_matches_wa(lead, wa):
                return user_email
    return None

def find_lead_by_whatsapp(wa_id: str) -> Optional[str]:
    wa = _norm_wa(wa_id)
    leads_by_user = load_leads()
    for user_email, leads in (leads_by_user or {}).items():
        for lead in leads or []:
            if _lead_matches_wa(lead, wa):
                return str(lead.get("id"))
    return None

def _wa_env():
    token = WHATSAPP_TOKEN
    phone_id = WHATSAPP_PHONE_ID
    if not token or not phone_id:
        raise RuntimeError("WhatsApp credentials missing (WHATSAPP_TOKEN / WHATSAPP_PHONE_ID)")
    return token, phone_id

def get_last_inbound_ts(user_email: str, lead_id: str) -> Optional[str]:
    chats = load_chats()
    msgs = ((chats.get(user_email, {}) or {}).get(lead_id, []) or [])
    for m in reversed(msgs):
        if m.get("from") == "lead":
            return m.get("time")
    return None

def within_24h(user_email: str, lead_id: str) -> bool:
    ts = get_last_inbound_ts(user_email, lead_id)
    if not ts:
        return False
    try:
        last_dt = dt.fromisoformat(ts.replace("Z", ""))
    except Exception:
        return False
    return (dt.utcnow() - last_dt) <= timedelta(hours=24)

def _resolve_waba_id(force: bool = False) -> str:
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
            wid = WHATSAPP_WABA_ID or ""
        _WABA_RES["id"] = wid
        _WABA_RES["checked_at"] = now
        app.logger.info("[WA WABA] resolved WABA id=%s", wid)
        return wid
    except Exception as e:
        app.logger.warning("[WA WABA] resolve error: %s", e)
        return WHATSAPP_WABA_ID or ""

def _fetch_templates_for_waba(waba_id: str):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    params = {"fields": "name,language,status,category,components", "limit": 200}
    url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"
    return pyrequests.get(url, headers=headers, params=params, timeout=30)

def _lookup_template_status(name: str, lang_api: str, force: bool = False) -> str:
    normalized_name = (name or WHATSAPP_TEMPLATE_DEFAULT or "").strip()
    lang_norm = _normalize_lang(lang_api or WHATSAPP_TEMPLATE_LANG or "en_US")
    key = (normalized_name, lang_norm)
    now = dt.utcnow()

    if not force:
        cached = _TEMPLATE_CACHE.get(key)
        if cached and (now - cached["checked_at"]) < timedelta(seconds=_TEMPLATE_TTL_SECONDS):
            return cached["status"]

    try:
        waba_id = _resolve_waba_id()
        r = _fetch_templates_for_waba(waba_id)
        items = (r.json() or {}).get("data", []) if r.ok else []
        primary = _primary_lang(lang_norm)

        exact_status = None
        fallback_status = None
        for t in items:
            if (t.get("name") or "") != normalized_name:
                continue
            tl_norm = _normalize_lang(t.get("language") or "")
            st = (t.get("status") or "UNKNOWN")
            if tl_norm == lang_norm:
                exact_status = st
            if _primary_lang(tl_norm) == primary:
                if (fallback_status or "").upper() != "APPROVED":
                    fallback_status = st

        status = exact_status or fallback_status or "PENDING"
        _TEMPLATE_CACHE[key] = {"status": status, "checked_at": now}
        return status
    except Exception as e:
        app.logger.warning(f"[WA TPL CHECK ERROR] {e}")
        _TEMPLATE_CACHE[key] = {"status": "UNKNOWN", "checked_at": now}
        return "UNKNOWN"

def send_wa_text(to_number: str, body: str):
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

def send_wa_template(to_number: str, template_name: str, lang_code: str, parameters: Optional[list] = None):
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
        "template": {"name": template_name, "language": {"code": _normalize_lang(lang_code)}, "components": components},
    }
    resp = pyrequests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        app.logger.error("[WA TEMPLATE ERROR] %s %s", resp.status_code, resp.text)
    return resp

def _get_thread_cached(user_email: str, lead_id: str):
    key = (str(user_email or ""), str(lead_id or ""))
    now = dt.utcnow()
    cached = _MSG_CACHE.get(key)
    if cached and (now - cached["at"]).total_seconds() < _MSG_CACHE_TTL_SECONDS:
        return cached["data"], True
    chats = load_chats()
    msgs = ((chats.get(user_email, {}) or {}).get(lead_id, []) or [])
    _MSG_CACHE[key] = {"at": now, "data": msgs}
    return msgs, False

@app.get("/api/whatsapp/health")
def whatsapp_health():
    return jsonify({
        "ok": True,
        "has_token": bool(WHATSAPP_TOKEN),
        "has_phone_id": bool(WHATSAPP_PHONE_ID),
        "has_waba_id": bool(WHATSAPP_WABA_ID),
        "resolved_waba": _resolve_waba_id(),
        "default_template": WHATSAPP_TEMPLATE_DEFAULT,
        "default_lang_api": _normalize_lang(WHATSAPP_TEMPLATE_LANG),
    }), 200

@app.get("/api/whatsapp/templates")
def list_templates():
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        return jsonify({"error": "Missing token or phone id"}), 400
    waba_id = _resolve_waba_id()
    r = _fetch_templates_for_waba(waba_id)
    try:
        data = r.json() if r.ok else {"raw": r.text}
        if isinstance(data, dict) and "data" in data:
            for t in data.get("data", []):
                t["normalized_language"] = _normalize_lang(t.get("language",""))
    except Exception:
        data = {"raw": r.text}
    return jsonify({"status": r.status_code, "waba_id": waba_id, "data": data}), r.status_code

@app.get("/api/whatsapp/window-state")
def whatsapp_window_state():
    user_email = _norm_email(request.args.get("user_email", ""))
    lead_id = str(request.args.get("lead_id", "") or "")
    template_name = (request.args.get("template_name") or WHATSAPP_TEMPLATE_DEFAULT or "").strip()
    lang_code = request.args.get("language_code") or WHATSAPP_TEMPLATE_LANG or "en_US"
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
        "canTemplate": (not inside) and (status.upper() == "APPROVED"),
    }), 200

@app.route("/api/whatsapp/messages", methods=["GET"])
def get_whatsapp_messages():
    user_email = _norm_email(request.args.get("user_email"))
    lead_id = str(request.args.get("lead_id") or "")
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
    user_email = _norm_email(data.get("user_email"))
    lead_id = str(data.get("lead_id") or "")
    opt_out = bool(data.get("opt_out", True))
    if not user_email or not lead_id:
        return jsonify({"error": "user_email and lead_id required"}), 400
    leads = load_leads()
    arr = leads.get(user_email, []) or []
    for ld in arr:
        if str(ld.get("id")) == lead_id:
            ld["wa_opt_out"] = opt_out
    leads[user_email] = arr
    save_leads(leads)
    return jsonify({"ok": True, "opt_out": opt_out}), 200

@app.route("/api/whatsapp/send", methods=["POST"])
def send_whatsapp_message():
    data = request.get_json(force=True) or {}

    to_number = (data.get("to") or data.get("phone") or "").strip()
    raw_msg = (data.get("message") or data.get("text") or "").strip()
    user_email = _norm_email(data.get("user_email"))
    lead_id = str(data.get("lead_id") or "").strip()
    template_name = (data.get("template_name") or WHATSAPP_TEMPLATE_DEFAULT or "").strip()
    language_code = (data.get("language_code") or WHATSAPP_TEMPLATE_LANG or "en_US").strip()

    raw_params = data.get("template_params")
    if isinstance(raw_params, str):
        raw_params = [p.strip() for p in raw_params.split(",") if p.strip()]
    elif not isinstance(raw_params, list):
        raw_params = None
    params = raw_params if raw_params else None

    if not to_number:
        return jsonify({"ok": False, "error": "Recipient 'to' is required"}), 400

    # opt-out
    if user_email and lead_id:
        for ld in (load_leads().get(user_email, []) or []):
            if str(ld.get("id")) == lead_id and bool(ld.get("wa_opt_out")):
                return jsonify({"ok": False, "error": "Lead has opted out of WhatsApp messages"}), 403

    inside24 = within_24h(user_email, lead_id)
    requested = _normalize_lang(language_code)
    primary = _primary_lang(requested)
    to_number = _norm_wa(to_number)

    waba_id = _resolve_waba_id()
    app.logger.info("[WA SEND] to=%s tpl=%s lang=%s inside24h=%s waba=%s",
                    to_number, template_name, requested, inside24, waba_id)

    try:
        if inside24:
            if not raw_msg:
                return jsonify({"ok": False, "error": "Message text required inside 24h"}), 400
            resp = send_wa_text(to_number, raw_msg)
            mode = "free_text"
            used_lang = None
            sent_text = raw_msg
        else:
            if not template_name:
                return jsonify({"ok": False, "error": "Template name required outside 24h", "code": "TEMPLATE_REQUIRED"}), 422

            r_list = _fetch_templates_for_waba(waba_id)
            if not r_list.ok:
                try: body = r_list.json()
                except Exception: body = {"raw": r_list.text}
                return jsonify({"ok": False, "error": "Failed to fetch templates", "resp": body}), 502

            items = (r_list.json() or {}).get("data", [])
            locales = []
            for t in items:
                if (t.get("name") or "") == template_name:
                    locales.append({"language": _normalize_lang(t.get("language") or ""), "status": (t.get("status") or "").upper()})

            if not locales:
                return jsonify({
                    "ok": False,
                    "error": f"Template '{template_name}' not found on this WABA",
                    "code": "TEMPLATE_NOT_FOUND",
                    "waba_id": waba_id,
                }), 404

            exact = next((x for x in locales if x["language"] == requested), None)
            approved_any = [x for x in locales if x["status"] == "APPROVED"]
            approved_same_primary = [x for x in approved_any if _primary_lang(x["language"]) == primary]

            used_lang = requested
            fallback_reason = None

            if exact and exact["status"] == "APPROVED":
                pass
            elif approved_same_primary:
                used_lang = approved_same_primary[0]["language"]
                fallback_reason = "fallback_same_primary"
            elif approved_any:
                used_lang = approved_any[0]["language"]
                fallback_reason = "fallback_any"
            else:
                return jsonify({
                    "ok": False,
                    "error": "Template not approved in any locale",
                    "code": "TEMPLATE_NOT_APPROVED_ANY_LOCALE",
                    "availableLanguages": locales,
                    "requestedLanguage": requested,
                }), 409

            resp = send_wa_template(to_number, template_name, used_lang, params)
            mode = "template"
            sent_text = f"[template:{template_name}/{used_lang}] {raw_msg or ''}"

        try:
            result = resp.json()
        except Exception:
            result = {"raw": resp.text}

        if resp.status_code >= 400:
            err = (result.get("error") or {}) if isinstance(result, dict) else {}
            return jsonify({
                "ok": False,
                "mode": mode,
                "status": resp.status_code,
                "error": err.get("message") or "WhatsApp API error",
                "code": err.get("code") or "WA_ERROR",
                "resp": result,
            }), resp.status_code

        msg_id = None
        if isinstance(result, dict):
            arr = result.get("messages")
            if isinstance(arr, list) and arr:
                msg_id = arr[0].get("id")

        # persist thread
        try:
            if user_email and lead_id:
                chats = load_chats()
                user_chats = (chats.get(user_email, {}) or {})
                thread = (user_chats.get(lead_id, []) or [])
                thread.append({"from": "user", "text": sent_text, "time": _iso_utc()})
                user_chats[lead_id] = thread
                chats[user_email] = user_chats
                save_chats(chats)
                _MSG_CACHE[(str(user_email), str(lead_id))] = {"at": dt.utcnow(), "data": thread}

                if msg_id:
                    statuses = load_statuses()
                    statuses[msg_id] = {
                        "status": "sent_request",
                        "user_email": user_email,
                        "lead_id": lead_id,
                        "to": to_number,
                        "mode": mode,
                        "time": _iso_utc(),
                    }
                    save_statuses(statuses)
        except Exception as e:
            app.logger.warning("[WA] persist error: %s", e)

        out = {
            "ok": True,
            "mode": mode,
            "status": resp.status_code,
            "message_id": msg_id,
            "requestedLanguage": requested,
            "usedLanguage": used_lang,
            "waba_id": waba_id,
        }
        if mode == "template":
            out["fallbackUsed"] = bool(used_lang and used_lang != requested)
            if out["fallbackUsed"]:
                out["fallbackReason"] = fallback_reason
        return jsonify(out), resp.status_code

    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    except pyrequests.RequestException as e:
        return jsonify({"ok": False, "error": f"Network error: {e}"}), 502


def _verify_meta_signature(raw_body: bytes, header_sig: Optional[str]) -> bool:
    secret = APP_SECRET
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
        if request.args.get("hub.verify_token") == (WHATSAPP_VERIFY_TOKEN or ""):
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

                # statuses
                for status in (value.get("statuses") or []):
                    statuses = load_statuses()
                    sid = status.get("id") or "unknown"
                    statuses[sid] = {
                        "status": status.get("status"),
                        "timestamp": status.get("timestamp"),
                        "recipient": status.get("recipient_id"),
                        "errors": status.get("errors"),
                    }
                    save_statuses(statuses)

                # inbound messages
                messages = value.get("messages") or []
                contacts = value.get("contacts") or []
                sender_waid = contacts[0].get("wa_id") if contacts else None

                for m in messages:
                    t = m.get("type")
                    if t == "text":
                        text = (m.get("text") or {}).get("body", "")
                    elif t == "interactive":
                        text = json.dumps(m.get("interactive") or {})
                    elif t == "button":
                        text = json.dumps(m.get("button") or {})
                    else:
                        text = f"[{t} message]"

                    # STOP/START opt-out logic
                    if sender_waid and isinstance(text, str):
                        up = text.strip().upper()
                        if up in ("STOP", "UNSUBSCRIBE", "STOP ALL", "CANCEL"):
                            wa = _norm_wa(sender_waid)
                            data = load_leads()
                            changed = False
                            for _, leads in (data or {}).items():
                                for ld in leads or []:
                                    if _lead_matches_wa(ld, wa):
                                        ld["wa_opt_out"] = True
                                        changed = True
                            if changed:
                                save_leads(data)
                            try:
                                send_wa_text(sender_waid, "You have been unsubscribed. Reply START to opt back in.")
                            except Exception:
                                pass

                        elif up in ("START", "UNSTOP", "SUBSCRIBE"):
                            wa = _norm_wa(sender_waid)
                            data = load_leads()
                            changed = False
                            for _, leads in (data or {}).items():
                                for ld in leads or []:
                                    if _lead_matches_wa(ld, wa):
                                        ld["wa_opt_out"] = False
                                        changed = True
                            if changed:
                                save_leads(data)
                            try:
                                send_wa_text(sender_waid, "You are now opted back in. You can reply STOP anytime to opt out.")
                            except Exception:
                                pass

                    user_email = find_user_by_whatsapp(sender_waid) if sender_waid else None
                    lead_id = find_lead_by_whatsapp(sender_waid) if sender_waid else None

                    if not user_email or not lead_id:
                        continue

                    chats = load_chats()
                    user_chats = (chats.get(user_email, {}) or {})
                    thread = (user_chats.get(lead_id, []) or [])
                    thread.append({"from": "lead", "text": text, "time": _iso_utc()})
                    user_chats[lead_id] = thread
                    chats[user_email] = user_chats
                    save_chats(chats)
                    _MSG_CACHE[(str(user_email), str(lead_id))] = {"at": dt.utcnow(), "data": thread}

    except Exception as e:
        app.logger.warning("[WHATSAPP WEBHOOK] parse error: %s", e)

    return "OK", 200


# ------------------------------------------------------------
# AI prompt endpoints
# ------------------------------------------------------------
@app.post("/api/ai-prompt")
def ai_prompt():
    data = request.get_json(force=True) or {}
    user_email = _norm_email(data.get("user_email"))
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
            return jsonify({"error": (j.get("error") or {}).get("message", "AI response was empty")}), 502

        prompt = re.sub(r"(?im)^\s*subject\s*:\s*.*$", "", prompt).strip()
        return jsonify({"prompt": prompt}), 200

    except Exception as e:
        app.logger.warning(f"[AI PROMPT ERROR] {e}")
        return jsonify({"error": "Failed to get AI response"}), 502


@app.route("/api/send-ai-message", methods=["POST"])
def send_ai_message():
    body = request.get_json(force=True) or {}

    lead_email = (body.get("leadEmail") or "").strip()
    user_email = _norm_email(body.get("userEmail"))
    subject = (body.get("subject") or "").strip() or "Message from RetainAI"
    message = (body.get("message") or "").strip()
    prompt_type = (body.get("promptType") or "followup").strip().lower()

    lead_name = (body.get("leadName") or "").strip()
    user_name = (body.get("userName") or "").strip()
    business_name = (body.get("businessName") or "").strip()

    if not lead_email or not message:
        return jsonify({"error": "leadEmail and message are required"}), 400

    template_id = PROMPT_TYPE_TO_TEMPLATE.get(prompt_type) or PROMPT_TYPE_TO_TEMPLATE["followup"]
    first_name = (lead_name.split(" ", 1)[0] if lead_name else "")

    dynamic = {
        "subject": subject,
        "lead_name": lead_name,
        "lead_first_name": first_name,
        "user_name": user_name,
        "business_name": business_name,
        "message": message,
        "message_body": message,
        "body": message,
        "year": datetime.datetime.now().year,
        "prompt_type": prompt_type,
    }

    accepted = send_email_with_template(
        to_email=lead_email,
        template_id=template_id,
        dynamic_data=dynamic,
        subject=subject,
        from_email=SENDER_EMAIL,
        reply_to_email=user_email or None,
    )
    if not accepted:
        return jsonify({"ok": False, "template_id": template_id, "accepted": False}), 502
    return jsonify({"ok": True, "template_id": template_id, "accepted": True}), 200


# ------------------------------------------------------------
# AUTOMATIONS (Blueprint + Engine)
# (keeps your API surface so Settings.jsx doesn't break)
# ------------------------------------------------------------
CHANNEL_EMAIL = "email"
CHANNEL_WHATSAPP = "whatsapp"
MISSING = "⛔"

def _read_json2(path: str, default: Any):
    return _read_json(path, default)

def _write_json2(path: str, data: Any):
    _atomic_write_json(path, data)

def _ensure_files2():
    if not os.path.exists(FILE_AUTOMATIONS): _write_json2(FILE_AUTOMATIONS, {"users": {}})
    if not os.path.exists(FILE_STATE): _write_json2(FILE_STATE, {})
    if not os.path.exists(FILE_NOTIFICATIONS2): _write_json2(FILE_NOTIFICATIONS2, {"notifications": []})
    if not os.path.exists(FILE_USERS2): _write_json2(FILE_USERS2, {"users": {}})

def _create_notification(owner_email: str, title: str, body: str):
    db = _read_json2(FILE_NOTIFICATIONS2, {"notifications": []})
    notif = {"id": str(uuid.uuid4()), "owner": _norm_email(owner_email), "title": title, "body": body, "created_at": _now_utc().isoformat()}
    db.setdefault("notifications", []).insert(0, notif)
    _write_json2(FILE_NOTIFICATIONS2, db)

def _load_user_profile(user_email: str) -> Dict[str, Any]:
    db = _read_json2(FILE_USERS2, {"users": {}})
    return (db.get("users", {}) or {}).get(_norm_email(user_email), {}) or {}

def _save_user_profile(user_email: str, profile: Dict[str, Any]):
    db = _read_json2(FILE_USERS2, {"users": {}})
    db.setdefault("users", {})[_norm_email(user_email)] = profile or {}
    _write_json2(FILE_USERS2, db)

def _load_user_flows(user_email: str) -> List[Dict[str, Any]]:
    db = _read_json2(FILE_AUTOMATIONS, {"users": {}})
    return (db.get("users", {}) or {}).get(_norm_email(user_email), []) or []

def _save_user_flows(user_email: str, flows: List[Dict[str, Any]]):
    db = _read_json2(FILE_AUTOMATIONS, {"users": {}})
    db.setdefault("users", {})[_norm_email(user_email)] = flows or []
    _write_json2(FILE_AUTOMATIONS, db)

def _load_state() -> Dict[str, Any]:
    return _read_json2(FILE_STATE, {}) or {}

def _save_state(state: Dict[str, Any]):
    _write_json2(FILE_STATE, state or {})

def _user_from_request() -> str:
    h = request.headers.get("X-User-Email")
    if h:
        return _norm_email(h)
    q = request.args.get("user") or (request.json.get("user") if request.is_json else None)
    return _norm_email(q or "demo@retainai.ca")

def _dt(s: Optional[str]) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromisoformat(s) if s else None
    except Exception:
        return None

def _is_valid_url(u: str) -> bool:
    try:
        p = urllib.parse.urlparse(u)
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
    return qs <= hour < qe

def trig_no_reply(lead: Dict[str, Any], days: int) -> bool:
    last_any = _dt(lead.get("last_activity_at")) or _dt(lead.get("last_inbound_at")) or _dt(lead.get("last_outbound_at"))
    if not last_any:
        created = _dt(lead.get("createdAt")) or _dt(lead.get("created_at")) or (_now_utc() - datetime.timedelta(days=999))
        return _now_utc() - created >= datetime.timedelta(days=days)
    return _now_utc() - last_any >= datetime.timedelta(days=days)

def trig_new_lead(lead: Dict[str, Any], within_hours: int = 24) -> bool:
    created = _dt(lead.get("createdAt")) or _dt(lead.get("created_at"))
    return bool(created and (_now_utc() - created <= datetime.timedelta(hours=within_hours)))

def cond_no_reply_since(lead: Dict[str, Any], days: int) -> bool:
    last_inbound = _dt(lead.get("last_inbound_at"))
    return (not last_inbound) or (_now_utc() - last_inbound >= datetime.timedelta(days=days))

def cond_no_booking_since(lead: Dict[str, Any], days: int = 2) -> bool:
    for appt in (lead.get("appointments") or []):
        if str(appt.get("status") or "").lower() in ("booked", "scheduled", "confirmed"):
            upd = _dt(appt.get("updated_at"))
            if upd and (_now_utc() - upd < datetime.timedelta(days=days)):
                return False
    return True

def _render_text(tmpl: str, lead: Dict[str, Any], run: Dict[str, Any], profile: Dict[str, Any]) -> str:
    if not isinstance(tmpl, str):
        return str(tmpl)
    business_name = profile.get("business_name") or f"{MISSING} add your business name in Automations > Settings"
    booking_link = profile.get("booking_link") or f"{MISSING} add your booking link in Automations > Settings"
    out = tmpl
    out = out.replace("{{business_name}}", business_name)
    out = out.replace("{{booking_link}}", booking_link)
    out = out.replace("{{lead.first_name}}", str(lead.get("first_name") or (lead.get("name") or "")))
    out = out.replace("{{lead.full_name}}", str(lead.get("name") or ""))
    out = out.replace("{{last_ai_text}}", (run.get("memo", {}).get("last_ai_text") or ""))
    return out

def _contains_blockers(text: str) -> bool:
    return MISSING in (text or "")

def send_email_sendgrid_auto(to_email: str, subject: str, html: str, business_name: str) -> bool:
    if not SENDGRID_API_KEY:
        print("[Automations] SENDGRID_API_KEY missing; simulated ok")
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
        return f"Quick check-in — want to book with {business_name}? {booking}"
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
        txt = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return (txt or f"Quick check-in — want to book with {business_name}? {booking}").strip()
    except Exception:
        return f"Quick check-in — want to book with {business_name}? {booking}"

def _append_chat_message(user_email: str, lead_id: str, text: str):
    try:
        chats = load_chats()
        user_chats = (chats.get(user_email, {}) or {})
        lid = str(lead_id or "")
        arr = (user_chats.get(lid, []) or [])
        arr.append({"from": "user", "text": text, "time": _iso_utc()})
        user_chats[lid] = arr
        chats[user_email] = user_chats
        save_chats(chats)
        _MSG_CACHE[(str(user_email), str(lead_id))] = {"at": dt.utcnow(), "data": arr}
    except Exception as e:
        print("[Automations] append_chat_message error:", e)

def _get_run(state: Dict[str, Any], flow_id: str, lead_key: str) -> Dict[str, Any]:
    return state.setdefault(flow_id, {}).setdefault(lead_key, {
        "step": 0,
        "created_at": _now_utc().isoformat(),
        "last_step_at": None,
        "done": False,
        "last_sent": {},
        "memo": {},
    })

def _advance(run: Dict[str, Any]):
    run["step"] = int(run.get("step", 0)) + 1
    run["last_step_at"] = _now_utc().isoformat()

def _can_send(run: Dict[str, Any], channel: str, per_hours: int) -> bool:
    last = (run.get("last_sent") or {}).get(channel)
    if not last:
        return True
    try:
        last_dt = datetime.datetime.fromisoformat(last)
    except Exception:
        return True
    return (_now_utc() - last_dt) >= datetime.timedelta(hours=per_hours)

def _mark_sent(run: Dict[str, Any], channel: str):
    run.setdefault("last_sent", {})[channel] = _now_utc().isoformat()

def _trigger_met(trigger: Dict[str, Any], lead: Dict[str, Any]) -> bool:
    t = (trigger or {}).get("type")
    if t == "no_reply":
        return trig_no_reply(lead, int(trigger.get("days", 3)))
    if t == "new_lead":
        return trig_new_lead(lead, int(trigger.get("within_hours", 24)))
    return False

def _execute_step(flow: Dict[str, Any], step: Dict[str, Any], lead: Dict[str, Any], run: Dict[str, Any], caps: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    kind = step.get("type")

    if kind == "wait":
        last = _dt(run.get("last_step_at")) or _dt(run.get("created_at")) or _now_utc()
        delta = datetime.timedelta(days=step.get("days", 0), hours=step.get("hours", 0), minutes=step.get("minutes", 0))
        return (_now_utc() - last) >= delta

    if kind == "if_no_reply":
        within_days = int(step.get("within_days", 2))
        if cond_no_reply_since(lead, within_days):
            for s in (step.get("then") or []):
                _execute_step(flow, s, lead, run, caps, profile)
        return True

    if kind == "if_no_booking":
        within_days = int(step.get("within_days", 2))
        if cond_no_booking_since(lead, within_days):
            for s in (step.get("then") or []):
                _execute_step(flow, s, lead, run, caps, profile)
        return True

    if kind == "ai_draft":
        text = ai_draft_message({"lead": lead, "flow": flow, "business_name": profile.get("business_name"), "booking_link": profile.get("booking_link")})
        run.setdefault("memo", {})["last_ai_text"] = text
        return True

    if kind == "send_whatsapp":
        if caps.get("respect_quiet_hours", True) and _in_quiet_hours(_now_utc(), profile):
            return False
        per_hours = int(caps.get("per_lead_per_day", 1)) * 24
        if not _can_send(run, CHANNEL_WHATSAPP, per_hours=per_hours):
            return False

        to = lead.get("phone") or lead.get("whatsapp")
        if not to or bool(lead.get("wa_opt_out")):
            return True

        raw = step.get("text") or run.get("memo", {}).get("last_ai_text") or ""
        body = _render_text(raw, lead, run, profile)
        if _contains_blockers(body):
            _create_notification(lead.get("owner") or flow.get("owner") or "", "Setup needed",
                                 "WhatsApp message blocked: missing profile values.")
            return True

        user_email = _norm_email(lead.get("owner") or flow.get("owner") or "")
        lead_id = str(lead.get("id") or lead.get("email") or lead.get("phone") or "")
        inside24 = within_24h(user_email, lead_id) if user_email and lead_id else False

        try:
            if inside24:
                resp = send_wa_text(to, body)
                ok = getattr(resp, "status_code", 500) < 400
                if ok:
                    _mark_sent(run, CHANNEL_WHATSAPP)
                    _append_chat_message(user_email, lead_id, body)
            else:
                tpl = (step.get("template_name") or WHATSAPP_TEMPLATE_DEFAULT or "").strip()
                lang = _normalize_lang(WHATSAPP_TEMPLATE_LANG or "en_US")
                # simplest: use template with same text as one param if needed
                resp = send_wa_template(to, tpl, lang, [])
                ok = getattr(resp, "status_code", 500) < 400
                if ok:
                    _mark_sent(run, CHANNEL_WHATSAPP)
                    _append_chat_message(user_email, lead_id, f"[template:{tpl}/{lang}] {body}")
        except Exception:
            pass
        return True

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
            _create_notification(lead.get("owner") or flow.get("owner") or "", "Setup needed",
                                 "Email blocked: missing profile values.")
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
            owner = _norm_email(lead.get("owner") or flow.get("owner") or "")
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

    for user, flows in (flows_db.get("users", {}) or {}).items():
        profile = _load_user_profile(user)
        user_leads = leads_by_user.get(user, []) or []

        for flow in flows or []:
            if not flow.get("enabled", False):
                continue
            flow_id = flow.get("id") or str(uuid.uuid4())
            steps = flow.get("steps", []) or []
            caps = flow.get("caps", {"per_lead_per_day": 1, "respect_quiet_hours": True})
            trigger = flow.get("trigger", {}) or {}

            for lead in user_leads:
                owner = _norm_email(lead.get("owner") or user)
                if owner != user:
                    continue
                lead_key = str(lead.get("id") or lead.get("email") or lead.get("phone") or uuid.uuid4())
                run = _get_run(state, flow_id, lead_key)
                if run.get("done"):
                    continue

                if int(run.get("step", 0)) == 0:
                    if not _trigger_met(trigger, lead):
                        state.setdefault(flow_id, {}).pop(lead_key, None)
                        continue

                step_index = int(run.get("step", 0))
                if step_index >= len(steps):
                    run["done"] = True
                    continue

                progressed = _execute_step(flow, steps[step_index], lead, run, caps, profile)
                if progressed:
                    _advance(run)

    _save_state(state)

automations_bp = Blueprint("automations", __name__)

@automations_bp.before_request
def _bf_ensure_files():
    _ensure_files2()

@automations_bp.route("/health", methods=["GET"])
def automations_health():
    return jsonify({"ok": True, "message": "automations alive"})

@automations_bp.route("/user/profile", methods=["GET"])
def get_user_profile():
    user = _user_from_request()
    prof = _load_user_profile(user)
    return jsonify({"profile": {
        "business_name": prof.get("business_name", ""),
        "booking_link": prof.get("booking_link", ""),
        "quiet_hours_start": prof.get("quiet_hours_start"),
        "quiet_hours_end": prof.get("quiet_hours_end"),
    }})

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
                    {"type": "send_email", "subject": "Quick check-in", "html": "<p>Quick check-in — want to grab a spot with {{business_name}}? <a href='{{booking_link}}'>Book here</a>.</p>"}
                ]}
            ],
            "caps": {"per_lead_per_day": 1, "respect_quiet_hours": True},
            "auto_stop_on_reply": True,
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
                {"type": "push_owner", "title": "Give them a quick call", "message": "New lead may need a call"},
            ],
            "caps": {"per_lead_per_day": 1, "respect_quiet_hours": True},
            "auto_stop_on_reply": True,
        },
    ]

@automations_bp.route("/templates", methods=["GET"])
def automations_templates():
    return jsonify({"templates": _builtin_templates()})

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
    flow = body.get("flow", {}) or {}
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
            merged = {**f, **(body.get("flow", {}) or {})}
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
    for f in flows:
        if f.get("id") == flow_id:
            f["enabled"] = enabled
            _save_user_flows(user, flows)
            return jsonify({"ok": True, "flow": f})
    return jsonify({"ok": False, "error": "not_found"}), 404

@automations_bp.route("/<flow_id>", methods=["DELETE"])
def delete_flow(flow_id):
    user = _user_from_request()
    flows = [f for f in _load_user_flows(user) if f.get("id") != flow_id]
    _save_user_flows(user, flows)
    state = _load_state()
    if flow_id in state:
        state.pop(flow_id, None)
        _save_state(state)
    return jsonify({"ok": True})

# Register automations blueprint (fixes /api/automations/templates 404)
if "automations" not in app.blueprints:
    app.register_blueprint(automations_bp, url_prefix="/api/automations")


# ------------------------------------------------------------
# Scheduler startup (gunicorn-safe + env toggle)
# ------------------------------------------------------------
_scheduler_started = False
_scheduler_lock = __import__("threading").Lock()

def start_scheduler_once():
    global _scheduler_started
    if not SCHEDULER_ENABLED:
        return
    with _scheduler_lock:
        if _scheduler_started:
            return
        scheduler = APScheduler()
        scheduler.init_app(app)
        scheduler.start()
        scheduler.add_job(id="lead_reminder_job", func=check_for_lead_reminders, trigger="interval", minutes=1)
        scheduler.add_job(id="birthday_greetings_job", func=send_birthday_greetings, trigger="cron", hour=8)
        scheduler.add_job(id="trial_ending_soon_job", func=send_trial_ending_soon, trigger="cron", hour=9)
        app._scheduler = scheduler
        _scheduler_started = True
        print("[Scheduler] started; jobs:", scheduler.get_jobs())

@app.before_request
def _kick_scheduler_once():
    # safe for gunicorn: triggers once per worker, but guarded by env + lock
    if not getattr(app, "_scheduler_booted", False):
        start_scheduler_once()
        app._scheduler_booted = True


# ------------------------------------------------------------
# Local dev runner ONLY
# ------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=not IS_PROD, port=int(os.getenv("PORT", "5000")))


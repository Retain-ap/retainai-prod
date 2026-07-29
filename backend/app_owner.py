import datetime
import json
import os
import time
from collections import Counter
from uuid import uuid4

from flask import Blueprint, jsonify, request, session

from storage import DATA_ROOT, load_leads, load_users, save_users


owner_bp = Blueprint("owner_bp", __name__)

AUDIT_FILE = os.path.join(DATA_ROOT, "platform_audit.json")
FEATURE_FLAGS_FILE = os.path.join(DATA_ROOT, "platform_features.json")
DEFAULT_PLATFORM_OWNERS = "owner@retainai.ca,mateo.zuf23@gmail.com"


def _norm(value):
    return str(value or "").strip().lower()


def platform_owner_emails():
    raw = os.getenv("PLATFORM_OWNER_EMAILS", DEFAULT_PLATFORM_OWNERS)
    return {_norm(value) for value in raw.split(",") if _norm(value)}


def is_platform_owner(email):
    return _norm(email) in platform_owner_emails()


def _actor():
    return _norm(session.get("user_email"))


def _require_owner():
    actor = _actor()
    if not actor:
        return None, (jsonify({"error": "authentication_required"}), 401)
    if not is_platform_owner(actor):
        return None, (jsonify({"error": "platform_owner_required"}), 403)
    return actor, None


def _load_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
            return value
    except Exception:
        return fallback


def _save_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.{uuid4().hex}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
    os.replace(temp_path, path)


def _audit(actor, action, target="", details=None):
    rows = _load_json(AUDIT_FILE, [])
    if not isinstance(rows, list):
        rows = []
    rows.insert(
        0,
        {
            "id": f"audit_{uuid4().hex[:12]}",
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "actor": actor,
            "action": action,
            "target": _norm(target),
            "details": details or {},
        },
    )
    _save_json(AUDIT_FILE, rows[:1000])


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _owner_accounts(users):
    return {
        email: record
        for email, record in (users or {}).items()
        if isinstance(record, dict)
        and "@" in str(email)
        and not str(email).startswith("user::")
        and not (
            record.get("org_id")
            and _norm(record.get("org_id")) != _norm(email)
            and str(record.get("role") or "").lower() in {"manager", "member"}
        )
    }


def _integration_summary(record):
    return {
        "whatsapp": bool(record.get("whatsapp") or record.get("whatsapp_connected")),
        "google": bool(record.get("gcal_connected") or record.get("google_refresh_token")),
        "stripe": bool(record.get("stripe_connected") or record.get("stripe_account_id")),
    }


def _account_row(email, record, leads_by_user, users):
    leads = leads_by_user.get(email, []) if isinstance(leads_by_user, dict) else []
    if not isinstance(leads, list):
        leads = []
    team_count = sum(
        1
        for key, member in users.items()
        if str(key).startswith("user::")
        and isinstance(member, dict)
        and _norm(member.get("org_id")) == email
        and _norm(key.replace("user::", "")) != email
    )
    trial_start = _parse_datetime(record.get("trial_start"))
    trial_end = (
        trial_start + datetime.timedelta(days=14) if trial_start else None
    )
    return {
        "email": email,
        "name": record.get("name") or "",
        "business": record.get("business") or record.get("businessName") or "",
        "business_type": record.get("businessType") or "",
        "status": record.get("status") or "unknown",
        "created_at": record.get("created_at") or record.get("trial_start") or "",
        "trial_ends_at": trial_end.isoformat() if trial_end else "",
        "last_login": record.get("last_login") or "",
        "plan": record.get("plan") or record.get("subscription_plan") or "Standard",
        "lead_count": len(leads),
        "team_count": team_count,
        "integrations": _integration_summary(record),
        "support_note": record.get("platform_support_note") or "",
    }


@owner_bp.get("/api/owner/access")
def owner_access():
    actor = _actor()
    return jsonify({"allowed": bool(actor and is_platform_owner(actor))}), 200


@owner_bp.get("/api/owner/overview")
def owner_overview():
    actor, error = _require_owner()
    if error:
        return error
    users = load_users() or {}
    leads = load_leads() or {}
    accounts = _owner_accounts(users)
    rows = [_account_row(email, record, leads, users) for email, record in accounts.items()]
    status_counts = Counter(row["status"] for row in rows)
    connected = Counter()
    for row in rows:
        for key, value in row["integrations"].items():
            if value:
                connected[key] += 1
    recent_cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    recent_signups = sum(
        1
        for row in rows
        if (_parse_datetime(row["created_at"]) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
        >= recent_cutoff
    )
    return jsonify(
        {
            "accounts_total": len(rows),
            "active_accounts": status_counts.get("active", 0),
            "trials": status_counts.get("trial", 0) + status_counts.get("pending_payment", 0),
            "past_due": status_counts.get("past_due", 0),
            "suspended": status_counts.get("suspended", 0),
            "recent_signups": recent_signups,
            "contacts_total": sum(row["lead_count"] for row in rows),
            "integrations": dict(connected),
            "estimated_mrr": sum(
                20 if row["status"] == "active" else 0 for row in rows
            ),
            "generated_at": int(time.time()),
        }
    ), 200


@owner_bp.get("/api/owner/accounts")
def owner_accounts():
    actor, error = _require_owner()
    if error:
        return error
    users = load_users() or {}
    leads = load_leads() or {}
    accounts = _owner_accounts(users)
    rows = [_account_row(email, record, leads, users) for email, record in accounts.items()]
    rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    return jsonify({"accounts": rows}), 200


@owner_bp.post("/api/owner/accounts/<path:email>/action")
def owner_account_action(email):
    actor, error = _require_owner()
    if error:
        return error
    target = _norm(email)
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip().lower()
    users = load_users() or {}
    account = users.get(target)
    if not isinstance(account, dict):
        return jsonify({"error": "account_not_found"}), 404

    details = {}
    if action == "suspend":
        account["status"] = "suspended"
    elif action == "reactivate":
        account["status"] = "active"
    elif action == "extend_trial":
        days = max(1, min(int(data.get("days") or 7), 90))
        account["trial_start"] = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14 - days)
        ).isoformat()
        account["status"] = "trial"
        details["days"] = days
    elif action == "support_note":
        note = str(data.get("note") or "").strip()[:1000]
        account["platform_support_note"] = note
        details["note_length"] = len(note)
    else:
        return jsonify({"error": "unsupported_action"}), 400

    users[target] = account
    save_users(users)
    _audit(actor, action, target, details)
    return jsonify({"ok": True, "status": account.get("status")}), 200


@owner_bp.get("/api/owner/support-queue")
def owner_support_queue():
    actor, error = _require_owner()
    if error:
        return error
    users = load_users() or {}
    leads = load_leads() or {}
    rows = [
        _account_row(email, record, leads, users)
        for email, record in _owner_accounts(users).items()
    ]
    queue = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for row in rows:
        reasons = []
        created = _parse_datetime(row.get("created_at"))
        last_login = _parse_datetime(row.get("last_login"))
        if row["status"] in {"past_due", "suspended"}:
            reasons.append("Account needs billing or access attention")
        if created and (now - created).days >= 2 and not last_login:
            reasons.append("Signed up but has not logged in")
        if row["lead_count"] == 0 and created and (now - created).days >= 2:
            reasons.append("No contacts imported")
        if not any(row["integrations"].values()):
            reasons.append("No integrations connected")
        if reasons:
            queue.append({**row, "reasons": reasons, "priority": len(reasons)})
    queue.sort(key=lambda item: item["priority"], reverse=True)
    return jsonify({"queue": queue}), 200


@owner_bp.get("/api/owner/health")
def owner_health():
    actor, error = _require_owner()
    if error:
        return error
    checks = {
        "database": True,
        "session_secret": bool(os.getenv("SESSION_SECRET") or os.getenv("FLASK_SECRET_KEY")),
        "whatsapp_token": bool(os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN")),
        "whatsapp_phone_id": bool(os.getenv("WHATSAPP_PHONE_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID")),
        "meta_app_secret": bool(os.getenv("APP_SECRET") or os.getenv("META_APP_SECRET")),
        "stripe": bool(os.getenv("STRIPE_SECRET_KEY")),
        "stripe_webhook": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
        "google_oauth": bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET")),
        "sendgrid": bool(os.getenv("SENDGRID_API_KEY")),
    }
    return jsonify(
        {
            "ok": all(checks.values()),
            "checks": checks,
            "deployment": os.getenv("RENDER_GIT_COMMIT", ""),
            "service": os.getenv("RENDER_SERVICE_NAME", ""),
            "checked_at": int(time.time()),
        }
    ), 200


@owner_bp.get("/api/owner/audit")
def owner_audit():
    actor, error = _require_owner()
    if error:
        return error
    rows = _load_json(AUDIT_FILE, [])
    return jsonify({"audit": rows[:250] if isinstance(rows, list) else []}), 200


@owner_bp.route("/api/owner/features", methods=["GET", "POST"])
def owner_features():
    actor, error = _require_owner()
    if error:
        return error
    flags = _load_json(FEATURE_FLAGS_FILE, {})
    if not isinstance(flags, dict):
        flags = {}
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        key = str(data.get("key") or "").strip()
        if not key or len(key) > 80:
            return jsonify({"error": "invalid_feature_key"}), 400
        flags[key] = bool(data.get("enabled"))
        _save_json(FEATURE_FLAGS_FILE, flags)
        _audit(actor, "feature_flag_changed", key, {"enabled": flags[key]})
    return jsonify({"features": flags}), 200

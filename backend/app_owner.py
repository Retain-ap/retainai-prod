import datetime
import hashlib
import json
import os
import sqlite3
import time
import zipfile
from collections import Counter
from uuid import uuid4

from flask import Blueprint, Response, jsonify, request, send_file, session
from werkzeug.security import generate_password_hash

from storage import DATA_ROOT, SQLITE_PATH, USE_SQLITE, load_leads, load_users, save_users


owner_bp = Blueprint("owner_bp", __name__)

AUDIT_FILE = os.path.join(DATA_ROOT, "platform_audit.json")
FEATURE_FLAGS_FILE = os.path.join(DATA_ROOT, "platform_features.json")
BACKUP_ROOT = os.path.join(DATA_ROOT, "backups")
OWNER_MODULE_STARTED_AT = time.time()
CANONICAL_PLATFORM_OWNER = "owner@retainai.ca"


def _norm(value):
    return str(value or "").strip().lower()


def platform_owner_emails():
    return {CANONICAL_PLATFORM_OWNER}


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


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_files():
    os.makedirs(BACKUP_ROOT, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = os.path.join(BACKUP_ROOT, f"retainai-backup-{stamp}.zip")
    staged_db = ""
    files = []
    try:
        if USE_SQLITE and os.path.isfile(SQLITE_PATH):
            staged_db = os.path.join(BACKUP_ROOT, f".snapshot-{uuid4().hex}.db")
            source = sqlite3.connect(SQLITE_PATH)
            destination = sqlite3.connect(staged_db)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            files.append((staged_db, "retainai.db"))
        for name in os.listdir(DATA_ROOT):
            path = os.path.join(DATA_ROOT, name)
            if os.path.isfile(path) and name.lower().endswith(".json"):
                files.append((path, f"json/{name}"))
        manifest = {
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "storage_mode": "sqlite" if USE_SQLITE else "json",
            "files": [
                {"name": arcname, "bytes": os.path.getsize(path), "sha256": _sha256(path)}
                for path, arcname in files
            ],
        }
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, arcname in files:
                archive.write(path, arcname)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        with zipfile.ZipFile(archive_path, "r") as archive:
            bad_file = archive.testzip()
            if bad_file:
                raise RuntimeError(f"backup_verification_failed:{bad_file}")
        with open(f"{archive_path}.sha256", "w", encoding="ascii") as checksum_file:
            checksum_file.write(_sha256(archive_path))
        retention = max(3, min(int(os.getenv("BACKUP_RETENTION_COUNT") or 14), 90))
        archives = sorted(
            (
                os.path.join(BACKUP_ROOT, name)
                for name in os.listdir(BACKUP_ROOT)
                if name.startswith("retainai-backup-") and name.endswith(".zip")
            ),
            key=os.path.getmtime,
            reverse=True,
        )
        for old_path in archives[retention:]:
            os.remove(old_path)
            checksum_path = f"{old_path}.sha256"
            if os.path.isfile(checksum_path):
                os.remove(checksum_path)
        return archive_path, manifest
    finally:
        if staged_db and os.path.isfile(staged_db):
            os.remove(staged_db)


def _backup_rows():
    if not os.path.isdir(BACKUP_ROOT):
        return []
    rows = []
    for name in os.listdir(BACKUP_ROOT):
        path = os.path.join(BACKUP_ROOT, name)
        if not name.startswith("retainai-backup-") or not name.endswith(".zip") or not os.path.isfile(path):
            continue
        checksum_path = f"{path}.sha256"
        checksum = ""
        try:
            with open(checksum_path, "r", encoding="ascii") as checksum_file:
                checksum = checksum_file.read().strip()
        except Exception:
            checksum = _sha256(path)
        rows.append({
            "name": name,
            "bytes": os.path.getsize(path),
            "created_at": datetime.datetime.fromtimestamp(
                os.path.getmtime(path), datetime.timezone.utc
            ).isoformat(),
            "sha256": checksum,
        })
    return sorted(rows, key=lambda row: row["created_at"], reverse=True)


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
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        # Legacy accounts used UTC timestamps without an explicit offset.
        # Normalize every value to aware UTC before trial/support calculations.
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc)
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
    if record.get("trial_eligible") is False:
        trial_end = None
    now = datetime.datetime.now(datetime.timezone.utc)
    trial_days_remaining = (
        max(0, (trial_end - now).days + (1 if trial_end > now else 0))
        if trial_end
        else 0
    )
    integrations = _integration_summary(record)
    onboarding_checks = {
        "profile": bool(
            record.get("business")
            or record.get("businessName")
        ),
        "contacts": bool(leads),
        "integration": any(integrations.values()),
        "team": team_count > 0,
    }
    onboarding_score = round(
        100 * sum(1 for complete in onboarding_checks.values() if complete)
        / len(onboarding_checks)
    )
    status = (
        "deletion_pending"
        if record.get("deletion_scheduled_for")
        else (record.get("status") or "unknown")
    )
    risk_reasons = []
    last_login = _parse_datetime(record.get("last_login"))
    created_at = _parse_datetime(record.get("created_at") or record.get("trial_start"))
    if status in {"past_due", "suspended", "inactive"}:
        risk_reasons.append("Account access or billing needs attention")
    if created_at and (now - created_at).days >= 2 and not last_login:
        risk_reasons.append("No successful login recorded")
    if not leads and created_at and (now - created_at).days >= 2:
        risk_reasons.append("No contacts imported")
    if not any(integrations.values()):
        risk_reasons.append("No integrations connected")
    return {
        "email": email,
        "platform_owner": is_platform_owner(email),
        "name": record.get("name") or "",
        "business": record.get("business") or record.get("businessName") or "",
        "business_type": record.get("businessType") or "",
        "status": status,
        "billing_status": record.get("billing_status") or status,
        "created_at": record.get("created_at") or record.get("trial_start") or "",
        "trial_ends_at": trial_end.isoformat() if trial_end else "",
        "trial_days_remaining": trial_days_remaining,
        "last_login": record.get("last_login") or "",
        "plan": record.get("plan") or record.get("subscription_plan") or "Standard",
        "lead_count": len(leads),
        "team_count": team_count,
        "integrations": integrations,
        "onboarding_score": onboarding_score,
        "onboarding_checks": onboarding_checks,
        "risk_reasons": risk_reasons,
        "risk_level": "high" if len(risk_reasons) >= 3 else ("medium" if risk_reasons else "healthy"),
        "email_verified": bool(record.get("email_verified") or record.get("google_sub")),
        "subscription_mrr": float(record.get("subscription_mrr") or 0),
        "subscription_currency": record.get("subscription_currency") or "",
        "security_version": int(record.get("security_version") or 0),
        "support_note": record.get("platform_support_note") or "",
        "deletion_requested_at": record.get("deletion_requested_at") or "",
        "deletion_scheduled_for": record.get("deletion_scheduled_for") or "",
        "complimentary": bool(record.get("billing_exempt") and record.get("complimentary_access")),
        "complimentary_expires_at": record.get("complimentary_expires_at") or "",
    }


def _safe_account_export(target, account, users, leads):
    blocked = {
        "password", "password_hash", "google_refresh_token", "meta_access_token",
        "whatsapp_token", "access_token", "refresh_token", "totp_secret",
        "two_factor_secret",
    }
    clean = lambda record: {
        key: value
        for key, value in record.items()
        if key not in blocked and "token" not in key.lower() and "secret" not in key.lower()
    }
    team = [
        clean(member)
        for member in users.values()
        if isinstance(member, dict) and _norm(member.get("org_id")) == target
    ]
    return {
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "workspace": target,
        "profile": clean(account),
        "team": team,
        "contacts": leads.get(target, []) if isinstance(leads, dict) else [],
        "notice": "Credentials, session data, encryption secrets and access tokens are excluded.",
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
    revenue_by_currency = {}
    for row in rows:
        currency = str(row.get("subscription_currency") or "").upper()
        amount = float(row.get("subscription_mrr") or 0)
        if currency and amount:
            revenue_by_currency[currency] = round(
                float(revenue_by_currency.get(currency) or 0) + amount, 2
            )
    return jsonify(
        {
            "accounts_total": len(rows),
            "active_accounts": status_counts.get("active", 0),
            "trials": sum(1 for row in rows if row["trial_days_remaining"] > 0),
            "past_due": status_counts.get("past_due", 0),
            "suspended": status_counts.get("suspended", 0),
            "recent_signups": recent_signups,
            "contacts_total": sum(row["lead_count"] for row in rows),
            "team_members_total": sum(row["team_count"] for row in rows),
            "at_risk_accounts": sum(1 for row in rows if row["risk_reasons"]),
            "onboarded_accounts": sum(1 for row in rows if row["onboarding_score"] >= 75),
            "average_onboarding": round(
                sum(row["onboarding_score"] for row in rows) / len(rows)
            ) if rows else 0,
            "status_breakdown": dict(status_counts),
            "recorded_mrr": revenue_by_currency,
            "integrations": dict(connected),
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


@owner_bp.post("/api/owner/accounts")
def owner_create_complimentary_account():
    actor, error = _require_owner()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    email = _norm(data.get("email"))
    password = str(data.get("password") or "")
    name = str(data.get("name") or "").strip()[:120]
    business = str(data.get("business") or "").strip()[:160]
    business_type = str(data.get("business_type") or "").strip()[:120]
    expires_on = str(data.get("expires_on") or "").strip()

    if not email or "@" not in email or len(email) > 254:
        return jsonify({"error": "valid_email_required"}), 400
    if len(password) < 12 or len(password) > 256:
        return jsonify({"error": "Password must contain between 12 and 256 characters."}), 400
    if is_platform_owner(email):
        return jsonify({"error": "platform_owner_account_locked"}), 403

    expires_at = ""
    if expires_on:
        try:
            expiry = datetime.datetime.strptime(expires_on, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=datetime.timezone.utc
            )
            if expiry <= datetime.datetime.now(datetime.timezone.utc):
                return jsonify({"error": "Access end date must be in the future."}), 400
            expires_at = expiry.isoformat().replace("+00:00", "Z")
        except ValueError:
            return jsonify({"error": "invalid_access_end_date"}), 400

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 503
    if email in users:
        return jsonify({"error": "account_already_exists"}), 409

    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    users[email] = {
        "email": email,
        "password": generate_password_hash(password),
        "name": name or email.split("@", 1)[0].replace(".", " ").title(),
        "business": business or "Launch Partner",
        "businessName": business or "Launch Partner",
        "businessType": business_type,
        "role": "owner",
        "org_id": email,
        "status": "active",
        "billing_status": "complimentary",
        "billing_exempt": True,
        "complimentary_access": True,
        "complimentary_expires_at": expires_at,
        "plan": "Complimentary",
        "trial_eligible": False,
        "email_verified": True,
        "email_verified_at": now,
        "created_at": now,
        "created_by_platform_owner": actor,
        "security_version": 0,
    }
    save_users(users)
    _audit(actor, "complimentary_account_created", email, {
        "expires_at": expires_at or "never",
        "business": business,
    })
    return jsonify({
        "ok": True,
        "account": _account_row(email, users[email], load_leads() or {}, users),
    }), 201


@owner_bp.get("/api/owner/accounts/<path:email>/export")
def owner_account_export(email):
    actor, error = _require_owner()
    if error:
        return error
    target = _norm(email)
    users = load_users() or {}
    account = users.get(target)
    if not isinstance(account, dict):
        return jsonify({"error": "account_not_found"}), 404
    payload = _safe_account_export(target, account, users, load_leads() or {})
    _audit(actor, "account_export", target, {"team_records": len(payload["team"])})
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="retainai-{target}-export.json"'},
    )


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
    if is_platform_owner(target):
        return jsonify({"error": "platform_owner_account_locked"}), 403
    if action == "suspend":
        account["status"] = "suspended"
    elif action == "archive":
        account["status"] = "archived"
        account["archived_at"] = (
            datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        )
    elif action == "reactivate":
        if account.get("billing_status") == "complimentary_revoked":
            return jsonify({"error": "Revoked complimentary access cannot be reactivated as a paid account."}), 409
        account["status"] = "active"
    elif action == "revoke_complimentary":
        if not account.get("billing_exempt"):
            return jsonify({"error": "account_is_not_complimentary"}), 400
        account["complimentary_access"] = False
        account["billing_exempt"] = False
        account["billing_status"] = "complimentary_revoked"
        account["status"] = "suspended"
        account["security_version"] = int(account.get("security_version") or 0) + 1
        details["access_revoked"] = True
    elif action == "restore_complimentary":
        if account.get("plan") != "Complimentary":
            return jsonify({"error": "account_was_not_created_as_complimentary"}), 400
        account["complimentary_access"] = True
        account["billing_exempt"] = True
        account["billing_status"] = "complimentary"
        account["status"] = "active"
        account["security_version"] = int(account.get("security_version") or 0) + 1
        details["access_restored"] = True
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
    elif action == "force_logout":
        account["security_version"] = int(account.get("security_version") or 0) + 1
        account["sessions_revoked_at"] = (
            datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        )
    elif action == "schedule_delete":
        now = datetime.datetime.now(datetime.timezone.utc)
        account["deletion_requested_at"] = now.isoformat().replace("+00:00", "Z")
        account["deletion_scheduled_for"] = (
            now + datetime.timedelta(days=14)
        ).isoformat().replace("+00:00", "Z")
        details["scheduled_for"] = account["deletion_scheduled_for"]
    elif action == "cancel_delete":
        if not account.get("deletion_scheduled_for"):
            return jsonify({"error": "deletion_not_pending"}), 400
        account.pop("status_before_deletion", None)
        account.pop("deletion_requested_at", None)
        account.pop("deletion_scheduled_for", None)
    elif action == "delete_now":
        confirmation = str(data.get("confirmation") or "").strip()
        if confirmation != f"DELETE {target}":
            return jsonify({"error": "email_confirmation_required"}), 400
        # Reuse the billing-safe account lifecycle implementation. It refuses
        # deletion when an active Stripe subscription cannot be cancelled.
        from app_account import _cancel_workspace_subscriptions, _purge_workspace
        try:
            details["subscriptions_cancelled"] = _cancel_workspace_subscriptions(account)
        except Exception:
            return jsonify({
                "error": "billing_cancellation_failed",
                "message": "The subscription could not be safely cancelled, so no customer data was deleted.",
            }), 409
        details["records_removed"] = _purge_workspace(target, users)
        _audit(actor, action, target, details)
        return jsonify({"ok": True, "deleted": True}), 200
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
    backup_rows = _backup_rows()
    latest_backup = backup_rows[0] if backup_rows else None
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
        "backup_available": bool(latest_backup),
    }
    return jsonify(
        {
            "ok": all(checks.values()),
            "checks": checks,
            "deployment": os.getenv("RENDER_GIT_COMMIT", ""),
            "service": os.getenv("RENDER_SERVICE_NAME", ""),
            "checked_at": int(time.time()),
            "uptime_seconds": int(time.time() - OWNER_MODULE_STARTED_AT),
            "latest_backup": latest_backup,
        }
    ), 200


@owner_bp.route("/api/owner/backups", methods=["GET", "POST"])
def owner_backups():
    actor, error = _require_owner()
    if error:
        return error
    if request.method == "POST":
        try:
            path, manifest = _backup_files()
        except Exception as exc:
            _audit(actor, "backup_failed", details={"error": type(exc).__name__})
            return jsonify({"error": "backup_failed"}), 500
        _audit(actor, "backup_created", details={
            "name": os.path.basename(path),
            "file_count": len(manifest["files"]),
        })
    return jsonify({"backups": _backup_rows()}), 200


@owner_bp.get("/api/owner/backups/<path:name>")
def owner_backup_download(name):
    actor, error = _require_owner()
    if error:
        return error
    safe_name = os.path.basename(name)
    if safe_name != name or not safe_name.startswith("retainai-backup-") or not safe_name.endswith(".zip"):
        return jsonify({"error": "invalid_backup_name"}), 400
    path = os.path.join(BACKUP_ROOT, safe_name)
    if not os.path.isfile(path):
        return jsonify({"error": "backup_not_found"}), 404
    _audit(actor, "backup_downloaded", details={"name": safe_name})
    return send_file(path, as_attachment=True, download_name=safe_name)


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

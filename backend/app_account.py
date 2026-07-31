import datetime
import json

from flask import Blueprint, Response, jsonify, request, session

from storage import load_leads, load_users, save_users


account_bp = Blueprint("account_bp", __name__)


def _norm(value):
    return str(value or "").strip().lower()


def _workspace():
    email = _norm(session.get("user_email"))
    if not email:
        return None, None, (jsonify({"error": "authentication_required"}), 401)
    users = load_users() or {}
    record = users.get(email)
    if not isinstance(record, dict):
        return None, None, (jsonify({"error": "account_not_found"}), 404)
    workspace = _norm(record.get("org_id")) or email
    owner = users.get(workspace)
    if not isinstance(owner, dict):
        owner = record
    return workspace, (users, owner), None


def _clean(record):
    blocked = {"password", "password_hash", "totp_secret", "two_factor_secret"}
    return {
        key: value
        for key, value in record.items()
        if key not in blocked and "token" not in key.lower() and "secret" not in key.lower()
    }


@account_bp.get("/api/account/export")
def account_export():
    workspace, context, error = _workspace()
    if error:
        return error
    users, owner = context
    actor = _norm(session.get("user_email"))
    if actor != workspace:
        return jsonify({"error": "workspace_owner_required"}), 403
    team = [
        _clean(member)
        for member in users.values()
        if isinstance(member, dict) and _norm(member.get("org_id")) == workspace
    ]
    leads = load_leads() or {}
    payload = {
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "workspace": workspace,
        "profile": _clean(owner),
        "team": team,
        "contacts": leads.get(workspace, []) if isinstance(leads, dict) else [],
        "notice": "Credentials, session data, encryption secrets and access tokens are excluded.",
    }
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="retainai-workspace-export.json"'},
    )


@account_bp.post("/api/account/deletion")
def account_deletion():
    workspace, context, error = _workspace()
    if error:
        return error
    users, owner = context
    actor = _norm(session.get("user_email"))
    if actor != workspace:
        return jsonify({"error": "workspace_owner_required"}), 403
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip().lower()
    if action == "schedule":
        if _norm(data.get("confirmation")) != workspace:
            return jsonify({"error": "email_confirmation_required"}), 400
        now = datetime.datetime.now(datetime.timezone.utc)
        owner["deletion_requested_at"] = now.isoformat().replace("+00:00", "Z")
        owner["deletion_scheduled_for"] = (
            now + datetime.timedelta(days=14)
        ).isoformat().replace("+00:00", "Z")
    elif action == "cancel":
        if not owner.get("deletion_scheduled_for"):
            return jsonify({"error": "deletion_not_pending"}), 400
        owner.pop("status_before_deletion", None)
        owner.pop("deletion_requested_at", None)
        owner.pop("deletion_scheduled_for", None)
    else:
        return jsonify({"error": "unsupported_action"}), 400
    users[workspace] = owner
    save_users(users)
    return jsonify(
        {
            "ok": True,
            "status": owner.get("status"),
            "deletion_scheduled_for": owner.get("deletion_scheduled_for", ""),
        }
    ), 200

import datetime
import json
import os
import time
from uuid import uuid4

import stripe
from flask import Blueprint, Response, jsonify, request, session

from storage import DATA_ROOT, delete_users, load_leads, load_users, save_leads, save_users


account_bp = Blueprint("account_bp", __name__)
_last_deletion_sweep = 0
_WORKSPACE_JSON_FILES = (
    "notifications.json",
    "appointments.json",
    "whatsapp_chats.json",
    "whatsapp_status.json",
    "whatsapp_webhook_events.json",
    "whatsapp_unmatched.json",
    "automations.json",
    "automations_state.json",
    "automation_users.json",
    "subscriptions.json",
    "invites.json",
)


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


def _atomic_json(path, value):
    temp_path = f"{path}.{uuid4().hex}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
    os.replace(temp_path, path)


def _purge_workspace_json(workspace):
    identity_fields = {"email", "user_email", "owner_email", "org_email", "org_id", "workspace"}
    for filename in _WORKSPACE_JSON_FILES:
        path = os.path.join(DATA_ROOT, filename)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            changed = False
            if isinstance(value, dict):
                for key in list(value):
                    if _norm(key) == workspace:
                        value.pop(key, None)
                        changed = True
            elif isinstance(value, list):
                kept = []
                for row in value:
                    belongs = isinstance(row, dict) and any(
                        _norm(row.get(field)) == workspace for field in identity_fields
                    )
                    changed = changed or belongs
                    if not belongs:
                        kept.append(row)
                value = kept
            if changed:
                _atomic_json(path, value)
        except Exception:
            continue


def _purge_workspace(workspace, users):
    removed = [
        key
        for key, record in users.items()
        if _norm(key) == workspace
        or (isinstance(record, dict) and _norm(record.get("org_id")) == workspace)
    ]
    delete_users(removed)
    leads = load_leads() or {}
    if isinstance(leads, dict) and workspace in leads:
        leads.pop(workspace, None)
        save_leads(leads)
    _purge_workspace_json(workspace)
    return len(removed)


def _cancel_workspace_subscriptions(owner):
    subscription_id = str(owner.get("stripe_subscription_id") or "").strip()
    customer_id = str(owner.get("stripe_customer_id") or "").strip()
    if not subscription_id and not customer_id:
        return 0
    secret = str(os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        raise RuntimeError("billing_cancellation_unavailable")
    stripe.api_key = secret
    subscriptions = []
    if subscription_id:
        subscriptions.append(subscription_id)
    elif customer_id:
        page = stripe.Subscription.list(customer=customer_id, status="all", limit=100)
        subscriptions.extend(
            item.get("id")
            for item in page.auto_paging_iter()
            if str(item.get("status") or "").lower()
            in {"active", "trialing", "past_due", "unpaid"}
        )
    cancelled = 0
    for current_id in filter(None, subscriptions):
        cancel_method = getattr(stripe.Subscription, "cancel", None)
        if callable(cancel_method):
            cancel_method(current_id)
        else:
            stripe.Subscription.delete(current_id)
        cancelled += 1
    return cancelled


def _purge_due_deletions():
    global _last_deletion_sweep
    now_epoch = time.time()
    if now_epoch - _last_deletion_sweep < 3600:
        return
    _last_deletion_sweep = now_epoch
    users = load_users() or {}
    if not isinstance(users, dict):
        return
    platform_owners = {
        _norm(value)
        for value in os.getenv(
            "PLATFORM_OWNER_EMAILS", "owner@retainai.ca,mateo.zuf23@gmail.com"
        ).split(",")
    }
    now = datetime.datetime.now(datetime.timezone.utc)
    due = []
    for email, record in users.items():
        if _norm(email) in platform_owners or not isinstance(record, dict):
            continue
        raw_due = record.get("deletion_scheduled_for")
        try:
            scheduled = datetime.datetime.fromisoformat(str(raw_due).replace("Z", "+00:00"))
        except Exception:
            continue
        if scheduled <= now:
            due.append(_norm(email))
    for workspace in due:
        owner = users.get(workspace) if isinstance(users.get(workspace), dict) else {}
        try:
            _cancel_workspace_subscriptions(owner)
        except Exception:
            # Never erase the account while its paid subscription might still
            # renew. The next hourly sweep will retry after billing recovers.
            continue
        _purge_workspace(workspace, users)


@account_bp.before_app_request
def sweep_due_account_deletions():
    _purge_due_deletions()


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
        if workspace in {
            _norm(value)
            for value in os.getenv(
                "PLATFORM_OWNER_EMAILS", "owner@retainai.ca,mateo.zuf23@gmail.com"
            ).split(",")
        }:
            return jsonify({"error": "platform_owner_account_locked"}), 403
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
    elif action == "delete_now":
        platform_owners = {
            _norm(value)
            for value in os.getenv(
                "PLATFORM_OWNER_EMAILS", "owner@retainai.ca,mateo.zuf23@gmail.com"
            ).split(",")
        }
        if workspace in platform_owners:
            return jsonify({"error": "platform_owner_account_locked"}), 403
        confirmation = str(data.get("confirmation") or "").strip()
        if confirmation != f"DELETE {workspace}":
            return jsonify({"error": "delete_confirmation_required"}), 400
        try:
            subscriptions_cancelled = _cancel_workspace_subscriptions(owner)
        except Exception:
            return jsonify({
                "error": "billing_cancellation_failed",
                "message": "RetainAI could not safely cancel the active subscription. Open the billing portal or contact support before deleting.",
            }), 409
        records_removed = _purge_workspace(workspace, users)
        session.clear()
        return jsonify({
            "ok": True,
            "deleted": True,
            "records_removed": records_removed,
            "subscriptions_cancelled": subscriptions_cancelled,
        }), 200
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

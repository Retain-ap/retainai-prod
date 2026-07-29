# backend/app_team.py
import os
import re
import json
import time
import secrets
import datetime
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from storage import load_users, save_users, DATA_ROOT

team_bp = Blueprint("team_bp", __name__)

INVITES_FILE = os.path.join(DATA_ROOT, "invites.json")
FRONTEND_BASE = (
    os.getenv("FRONTEND_URL")
    or os.getenv("FRONTEND_BASE")
    or "http://localhost:3000"
).rstrip("/")
SENDGRID_API_KEY = (os.getenv("SENDGRID_API_KEY") or "").strip()
SENDER_EMAIL = (os.getenv("SENDER_EMAIL") or "noreply@retainai.ca").strip()
INVITE_TTL_SECONDS = 7 * 24 * 60 * 60
VALID_ROLES = {"manager", "member"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ───────────────── storage/helpers ─────────────────

def _norm(email: str) -> str:
    return (email or "").strip().lower()


def _user_key(email: str) -> str:
    return f"user::{_norm(email)}"


def _utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _load_invites() -> Dict[str, Dict[str, Any]]:
    try:
        with open(INVITES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _save_invites(data: Dict[str, Dict[str, Any]]) -> None:
    os.makedirs(DATA_ROOT, exist_ok=True)
    tmp = INVITES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, INVITES_FILE)


def _current_user_email() -> str:
    # This matches the authentication convention already used throughout RetainAI.
    # Do not use ownerEmail from the request body/query as authorization.
    return _norm(
        request.headers.get("X-User-Email")
        or request.headers.get("X-Auth-Email")
        or ""
    )


def _resolve_actor(users: dict, email: str) -> Tuple[Optional[str], Optional[str], Optional[dict], Optional[dict]]:
    """Return (role, org_owner_email, owner_record, subject_record)."""
    email = _norm(email)
    if not email or not isinstance(users, dict):
        return None, None, None, None

    team_rec = users.get(_user_key(email))
    if isinstance(team_rec, dict):
        role = (team_rec.get("role") or "member").strip().lower()
        org_email = _norm(team_rec.get("org_id") or email)

        # Some older installs created a user::<owner> mirror record.
        if role == "owner" or org_email == email:
            owner = users.get(org_email) or users.get(email)
            if isinstance(owner, dict):
                return "owner", org_email, owner, team_rec
        else:
            owner = users.get(org_email)
            if isinstance(owner, dict):
                return role if role in VALID_ROLES else "member", org_email, owner, team_rec

    top_level = users.get(email)
    if isinstance(top_level, dict):
        top_role = (top_level.get("role") or "").strip().lower()
        top_org = _norm(top_level.get("org_id") or "")
        if top_org and top_org != email and top_role in VALID_ROLES:
            owner = users.get(top_org)
            if isinstance(owner, dict):
                return top_role, top_org, owner, top_level
        return "owner", email, top_level, top_level

    return None, None, None, None


def _require_actor(owner_only: bool = False):
    me = _current_user_email()
    if not me:
        return None, (jsonify({"error": "auth_required"}), 401)

    users = load_users() or {}
    if not isinstance(users, dict):
        return None, (jsonify({"error": "storage_not_ready"}), 500)

    role, org_email, owner, subject = _resolve_actor(users, me)
    if not role or not org_email or not owner:
        return None, (jsonify({"error": "user_not_found"}), 404)
    if owner_only and role != "owner":
        return None, (jsonify({"error": "forbidden"}), 403)

    return {
        "email": me,
        "role": role,
        "org_email": org_email,
        "owner": owner,
        "subject": subject or {},
        "users": users,
    }, None


def _member_payload(email: str, rec: dict, *, owner_email: str = "") -> dict:
    email = _norm(email or rec.get("email"))
    role = (rec.get("role") or ("owner" if email == owner_email else "member")).lower()
    if email == owner_email:
        role = "owner"

    return {
        "email": email,
        "name": (rec.get("name") or rec.get("business") or "").strip(),
        "role": role,
        "status": rec.get("team_status") or rec.get("status") or "active",
        "last_login": rec.get("last_login") or rec.get("lastLoginAt"),
        "joined_at": rec.get("joined_at") or rec.get("created_at") or rec.get("trial_start"),
        "avatar": rec.get("avatar") or rec.get("logo") or rec.get("picture") or "",
    }


def _all_members(users: dict, org_email: str) -> list:
    owner = users.get(org_email) or {}
    rows = [_member_payload(org_email, owner, owner_email=org_email)]
    seen = {org_email}

    for key, rec in users.items():
        if not (isinstance(key, str) and key.startswith("user::") and isinstance(rec, dict)):
            continue
        email = _norm(rec.get("email") or key.split("user::", 1)[-1])
        if not email or email in seen:
            continue
        if _norm(rec.get("org_id")) != org_email:
            continue
        role = (rec.get("role") or "member").lower()
        if role == "owner":
            continue
        rows.append(_member_payload(email, rec, owner_email=org_email))
        seen.add(email)

    # Compatibility for older records that only have a top-level member login.
    for key, rec in users.items():
        if not isinstance(key, str) or key.startswith("user::") or not isinstance(rec, dict):
            continue
        email = _norm(rec.get("email") or key)
        role = (rec.get("role") or "").lower()
        if email in seen or role not in VALID_ROLES:
            continue
        if _norm(rec.get("org_id")) != org_email:
            continue
        rows.append(_member_payload(email, rec, owner_email=org_email))
        seen.add(email)

    rows.sort(key=lambda m: (0 if m["role"] == "owner" else 1, (m.get("name") or m["email"]).lower()))
    return rows


def _invite_url(token: str) -> str:
    return f"{FRONTEND_BASE}/accept-invite?token={token}"


def _send_invite_email(*, to_email: str, inviter_name: str, business_name: str, role: str, accept_url: str) -> bool:
    if not SENDGRID_API_KEY:
        return False

    inviter = inviter_name or business_name or "A RetainAI workspace owner"
    workspace = business_name or "their RetainAI workspace"
    subject = f"You’re invited to join {workspace} on RetainAI"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;color:#202124">
      <h2 style="margin-bottom:8px">Join {workspace} on RetainAI</h2>
      <p>{inviter} invited you to join as a <strong>{role.title()}</strong>.</p>
      <p style="margin:28px 0">
        <a href="{accept_url}" style="background:#f7cb53;color:#111;padding:13px 20px;border-radius:8px;text-decoration:none;font-weight:700">
          Accept invitation
        </a>
      </p>
      <p style="color:#666;font-size:14px">This link expires in 7 days. If you were not expecting this invitation, you can ignore this email.</p>
    </div>
    """

    try:
        message = Mail(
            from_email=SENDER_EMAIL,
            to_emails=to_email,
            subject=subject,
            html_content=html,
        )
        response = SendGridAPIClient(SENDGRID_API_KEY).send(message)
        return response.status_code in (200, 201, 202)
    except Exception:
        return False


def _find_active_invite(invites: dict, email: str, org_email: str):
    now = int(time.time())
    for token, inv in invites.items():
        if not isinstance(inv, dict):
            continue
        if inv.get("accepted_at") or inv.get("cancelled_at"):
            continue
        if _norm(inv.get("email")) != email or _norm(inv.get("org_id")) != org_email:
            continue
        if int(inv.get("expires_at") or 0) > now:
            return token, inv
    return None, None


def _public_invite(token: str, inv: dict, include_url: bool = False) -> dict:
    out = {
        "token": token,
        "email": _norm(inv.get("email")),
        "role": inv.get("role") or "member",
        "created_at": inv.get("created_at"),
        "expires_at": inv.get("expires_at"),
        "email_sent": bool(inv.get("email_sent")),
    }
    if include_url:
        out["accept_url"] = _invite_url(token)
    return out


# ───────────────── routes ─────────────────

@team_bp.route("/api/team/members", methods=["GET"])
def team_members():
    actor, error = _require_actor()
    if error:
        return error

    return jsonify({
        "members": _all_members(actor["users"], actor["org_email"]),
        "current_role": actor["role"],
        "can_manage": actor["role"] == "owner",
        "org_id": actor["org_email"],
    }), 200


@team_bp.route("/api/team/invites", methods=["GET"])
def list_invites():
    actor, error = _require_actor(owner_only=True)
    if error:
        return error

    now = int(time.time())
    invites = _load_invites()
    rows = []
    for token, inv in invites.items():
        if not isinstance(inv, dict):
            continue
        if _norm(inv.get("org_id")) != actor["org_email"]:
            continue
        if inv.get("accepted_at") or inv.get("cancelled_at"):
            continue
        if int(inv.get("expires_at") or 0) <= now:
            continue
        rows.append(_public_invite(token, inv, include_url=True))

    rows.sort(key=lambda x: int(x.get("created_at") or 0), reverse=True)
    return jsonify({"invites": rows}), 200


@team_bp.route("/api/team/invite", methods=["POST"])
def invite_member():
    actor, error = _require_actor(owner_only=True)
    if error:
        return error

    body = request.get_json(silent=True) or {}
    email = _norm(body.get("email"))
    role = (body.get("role") or "member").strip().lower()

    if not email or not EMAIL_RE.match(email):
        return jsonify({"error": "valid_email_required"}), 400
    if role not in VALID_ROLES:
        return jsonify({"error": "invalid_role"}), 400
    if email == actor["org_email"]:
        return jsonify({"error": "cannot_invite_owner"}), 409

    users = actor["users"]
    existing_role, existing_org, _owner, _subject = _resolve_actor(users, email)
    if existing_role:
        if existing_org == actor["org_email"]:
            return jsonify({"error": "already_member"}), 409
        return jsonify({"error": "email_in_use"}), 409

    invites = _load_invites()
    existing_token, existing = _find_active_invite(invites, email, actor["org_email"])
    if existing:
        return jsonify({
            "ok": True,
            "existing": True,
            "invite": _public_invite(existing_token, existing, include_url=True),
        }), 200

    now = int(time.time())
    token = secrets.token_urlsafe(32)
    accept_url = _invite_url(token)
    owner = actor["owner"] or {}
    email_sent = _send_invite_email(
        to_email=email,
        inviter_name=(owner.get("name") or "").strip(),
        business_name=(owner.get("business") or owner.get("businessName") or "").strip(),
        role=role,
        accept_url=accept_url,
    )

    invites[token] = {
        "email": email,
        "role": role,
        "org_id": actor["org_email"],
        "created_at": now,
        "expires_at": now + INVITE_TTL_SECONDS,
        "accepted_at": None,
        "cancelled_at": None,
        "email_sent": email_sent,
        "last_sent_at": now if email_sent else None,
    }
    _save_invites(invites)

    return jsonify({
        "ok": True,
        "invite": _public_invite(token, invites[token], include_url=True),
    }), 201


@team_bp.route("/api/team/invite/resend", methods=["POST"])
def resend_invite():
    actor, error = _require_actor(owner_only=True)
    if error:
        return error

    body = request.get_json(silent=True) or {}
    old_token = (body.get("token") or "").strip()
    invites = _load_invites()
    old = invites.get(old_token)
    if not isinstance(old, dict) or _norm(old.get("org_id")) != actor["org_email"]:
        return jsonify({"error": "invite_not_found"}), 404
    if old.get("accepted_at") or old.get("cancelled_at"):
        return jsonify({"error": "invite_inactive"}), 409

    now = int(time.time())
    new_token = secrets.token_urlsafe(32)
    new_invite = dict(old)
    new_invite.update({
        "created_at": now,
        "expires_at": now + INVITE_TTL_SECONDS,
        "accepted_at": None,
        "cancelled_at": None,
    })

    owner = actor["owner"] or {}
    email_sent = _send_invite_email(
        to_email=_norm(new_invite.get("email")),
        inviter_name=(owner.get("name") or "").strip(),
        business_name=(owner.get("business") or owner.get("businessName") or "").strip(),
        role=new_invite.get("role") or "member",
        accept_url=_invite_url(new_token),
    )
    new_invite["email_sent"] = email_sent
    new_invite["last_sent_at"] = now if email_sent else None

    old["cancelled_at"] = now
    old["replaced_by"] = new_token
    invites[old_token] = old
    invites[new_token] = new_invite
    _save_invites(invites)

    return jsonify({
        "ok": True,
        "invite": _public_invite(new_token, new_invite, include_url=True),
    }), 200


@team_bp.route("/api/team/invite/cancel", methods=["POST"])
def cancel_invite():
    actor, error = _require_actor(owner_only=True)
    if error:
        return error

    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    invites = _load_invites()
    inv = invites.get(token)
    if not isinstance(inv, dict) or _norm(inv.get("org_id")) != actor["org_email"]:
        return jsonify({"error": "invite_not_found"}), 404
    if inv.get("accepted_at"):
        return jsonify({"error": "already_accepted"}), 409

    inv["cancelled_at"] = int(time.time())
    invites[token] = inv
    _save_invites(invites)
    return jsonify({"ok": True}), 200


@team_bp.route("/api/team/role", methods=["POST"])
def change_member_role():
    actor, error = _require_actor(owner_only=True)
    if error:
        return error

    body = request.get_json(silent=True) or {}
    email = _norm(body.get("email"))
    role = (body.get("role") or "").strip().lower()
    if not email or role not in VALID_ROLES:
        return jsonify({"error": "invalid_request"}), 400
    if email == actor["org_email"]:
        return jsonify({"error": "owner_role_locked"}), 409

    users = actor["users"]
    key = _user_key(email)
    member = users.get(key)
    if not isinstance(member, dict) or _norm(member.get("org_id")) != actor["org_email"]:
        return jsonify({"error": "member_not_found"}), 404

    member["role"] = role
    member["updated_at"] = _utc_iso()
    users[key] = member

    login_rec = users.get(email)
    if isinstance(login_rec, dict) and _norm(login_rec.get("org_id")) == actor["org_email"]:
        login_rec["role"] = role
        users[email] = login_rec

    save_users(users)
    return jsonify({"ok": True, "member": _member_payload(email, member, owner_email=actor["org_email"])}), 200


@team_bp.route("/api/team/remove", methods=["POST"])
def remove_member():
    actor, error = _require_actor(owner_only=True)
    if error:
        return error

    body = request.get_json(silent=True) or {}
    email = _norm(body.get("email"))
    if not email:
        return jsonify({"error": "email_required"}), 400
    if email == actor["org_email"]:
        return jsonify({"error": "cannot_remove_owner"}), 409

    users = actor["users"]
    key = _user_key(email)
    member = users.get(key)
    if not isinstance(member, dict) or _norm(member.get("org_id")) != actor["org_email"]:
        return jsonify({"error": "member_not_found"}), 404

    users.pop(key, None)

    # Remove only the teammate's login record. Organization data remains owned by the owner.
    login_rec = users.get(email)
    if isinstance(login_rec, dict) and _norm(login_rec.get("org_id")) == actor["org_email"]:
        users.pop(email, None)

    save_users(users)
    return jsonify({"ok": True}), 200


@team_bp.route("/api/team/invite/<token>", methods=["GET"])
def read_invite(token):
    invites = _load_invites()
    inv = invites.get(token)
    if not isinstance(inv, dict) or inv.get("cancelled_at"):
        return jsonify({"error": "not_found"}), 404
    if inv.get("accepted_at"):
        return jsonify({"error": "already_accepted"}), 409
    if int(inv.get("expires_at") or 0) <= int(time.time()):
        return jsonify({"error": "expired"}), 410

    users = load_users() or {}
    owner = users.get(_norm(inv.get("org_id"))) if isinstance(users, dict) else {}
    owner = owner or {}

    return jsonify({
        "invite": {
            "email": _norm(inv.get("email")),
            "role": inv.get("role") or "member",
            "org_id": _norm(inv.get("org_id")),
            "business": owner.get("business") or owner.get("businessName") or "RetainAI workspace",
            "inviter_name": owner.get("name") or "",
            "expires_at": inv.get("expires_at"),
            "requires_password": True,
        }
    }), 200


@team_bp.route("/api/team/accept", methods=["POST"])
def accept_invite():
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    name = (body.get("name") or "").strip()
    email = _norm(body.get("email"))
    password = str(body.get("password") or "")

    if not token or not email:
        return jsonify({"error": "bad_request"}), 400
    if len(password) < 8:
        return jsonify({"error": "password_too_short"}), 400

    invites = _load_invites()
    inv = invites.get(token)
    if not isinstance(inv, dict) or inv.get("cancelled_at"):
        return jsonify({"error": "not_found"}), 404
    if inv.get("accepted_at"):
        return jsonify({"error": "already_accepted"}), 409
    if int(inv.get("expires_at") or 0) <= int(time.time()):
        return jsonify({"error": "expired"}), 410
    if _norm(inv.get("email")) != email:
        return jsonify({"error": "email_mismatch", "invited": _norm(inv.get("email"))}), 400

    users = load_users() or {}
    if not isinstance(users, dict):
        return jsonify({"error": "storage_not_ready"}), 500

    org_email = _norm(inv.get("org_id"))
    owner = users.get(org_email)
    if not isinstance(owner, dict):
        return jsonify({"error": "org_not_found"}), 404

    existing_role, existing_org, _existing_owner, _subject = _resolve_actor(users, email)
    if existing_role and existing_org != org_email:
        return jsonify({"error": "email_in_use"}), 409

    role = (inv.get("role") or "member").lower()
    if role not in VALID_ROLES:
        role = "member"

    now_iso = _utc_iso()
    display_name = name or email.split("@", 1)[0].replace(".", " ").title()

    users[_user_key(email)] = {
        "email": email,
        "name": display_name,
        "role": role,
        "org_id": org_email,
        "team_status": "active",
        "joined_at": now_iso,
        "last_login": None,
    }

    # A teammate gets their own password. Organization-level data still comes from the owner.
    users[email] = {
        "email": email,
        "password": generate_password_hash(password),
        "name": display_name,
        "role": role,
        "org_id": org_email,
        "status": "active",
        "joined_at": now_iso,
    }
    save_users(users)

    inv["accepted_at"] = int(time.time())
    invites[token] = inv
    _save_invites(invites)

    return jsonify({
        "ok": True,
        "user": {
            "email": email,
            "name": display_name,
            "role": role,
            "orgOwnerEmail": org_email,
        },
    }), 200

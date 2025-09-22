# backend/app_team.py
import os, json, time, secrets, datetime
from flask import Blueprint, request, jsonify
from urllib.parse import urljoin

team_bp = Blueprint("team_bp", __name__)

USERS_FILE    = "users.json"
INVITES_FILE  = "invites.json"
FRONTEND_BASE = os.getenv("FRONTEND_BASE", "http://localhost:3000")

# ───────────────── helpers ─────────────────

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _norm(email: str) -> str:
    return (email or "").strip().lower()

def _user_key(email: str) -> str:
    return f"user::{_norm(email)}"

def _current_user_email() -> str:
    return _norm(request.headers.get("X-User-Email", ""))

def _users():
    return _load_json(USERS_FILE, {})

def _save_users(data):
    _save_json(USERS_FILE, data)

def _invites():
    return _load_json(INVITES_FILE, {})

def _save_invites(data):
    _save_json(INVITES_FILE, data)

def _get_any_user_view(users_dict: dict, email: str):
    """Prefer team record 'user::<email>' else legacy top-level '<email>'."""
    key = _user_key(email)
    return users_dict.get(key) or users_dict.get(email)

def _bootstrap_owner_if_missing(users_dict: dict, email: str) -> dict:
    """
    Ensure there's a 'user::<owner>' team record. Seed from legacy owner if needed.
    """
    key = _user_key(email)
    if key in users_dict:
        return users_dict

    legacy = users_dict.get(email) or {}
    users_dict[key] = {
        "email": email,
        "name": legacy.get("name") or legacy.get("business") or "",
        "role": "owner",
        "org_id": legacy.get("org_id") or email,  # single-tenant org by default
        "last_login": legacy.get("last_login"),
    }
    _save_users(users_dict)
    return users_dict

def _iter_team_members(users_dict: dict, org_id: str):
    """
    Yield team members from 'user::' namespace. If none, fall back to owner-only.
    """
    had_any = False
    for k, v in users_dict.items():
        if isinstance(k, str) and k.startswith("user::"):
            if (v.get("org_id") or v.get("email")) == org_id:
                had_any = True
                yield {
                    "email": v.get("email"),
                    "name": v.get("name") or "",
                    "role": v.get("role", "member"),
                    "last_login": v.get("last_login"),
                }
    if not had_any:
        owner = users_dict.get(_user_key(org_id)) or users_dict.get(org_id) or {"email": org_id}
        yield {
            "email": owner.get("email", org_id),
            "name": owner.get("name") or "",
            "role": owner.get("role", "owner"),
            "last_login": owner.get("last_login"),
        }

def _clone_owner_login_to_member(users: dict, owner_email: str, member_email: str, name: str, role: str):
    """
    Create/overwrite a TOP-LEVEL users[member_email] record that mirrors the owner's
    login fields so /api/login works for the teammate with the SAME PASSWORD.

    We copy: password, business fields, logo, and mark status=active.
    """
    owner_email = _norm(owner_email)
    member_email = _norm(member_email)
    owner_legacy = users.get(owner_email) or {}

    owner_pw = owner_legacy.get("password")
    if not owner_pw:
        # If owner has no legacy record with password, we cannot mirror credentials.
        raise ValueError("owner_password_missing")

    base = {
        "password": owner_pw,
        "businessType": owner_legacy.get("businessType", ""),
        "business": owner_legacy.get("business", ""),
        "teamSize": owner_legacy.get("teamSize", ""),
        "logo": owner_legacy.get("logo", "") or owner_legacy.get("picture", ""),
        "location": owner_legacy.get("location", ""),
        "stripe_account_id": owner_legacy.get("stripe_account_id"),
        "stripe_connected": owner_legacy.get("stripe_connected", False),
        "status": "active",
        "trial_start": owner_legacy.get("trial_start") or datetime.datetime.utcnow().isoformat(),
        "trial_ending_notice_sent": False,
        "name": name or owner_legacy.get("name", "") or member_email.split("@")[0].title(),
        "people": owner_legacy.get("people", ""),
        "org_id": owner_legacy.get("org_id") or owner_email,
        "role": role or "member",
    }

    current = users.get(member_email) or {}
    current.update(base)
    users[member_email] = current

# ───────────────── routes ─────────────────

@team_bp.route("/api/team/members", methods=["GET"])
def team_members():
    me = _current_user_email()
    if not me:
        return jsonify({"error": "auth"}), 401

    users_db = _users()
    users_db = _bootstrap_owner_if_missing(users_db, me)

    me_user = _get_any_user_view(users_db, me)
    if not me_user:
        return jsonify({"error": "no_user"}), 404

    org_id = me_user.get("org_id") or me
    out = list(_iter_team_members(users_db, org_id))
    return jsonify({"members": out})

@team_bp.route("/api/team/invite", methods=["POST"])
def invite_member():
    me = _current_user_email()
    if not me:
        return jsonify({"error":"auth"}), 401

    users_db = _users()
    users_db = _bootstrap_owner_if_missing(users_db, me)

    me_user = _get_any_user_view(users_db, me)
    if not me_user:
        return jsonify({"error":"no_user"}), 404
    if me_user.get("role", "owner") != "owner":
        return jsonify({"error":"forbidden"}), 403

    body  = request.get_json() or {}
    email = _norm(body.get("email"))
    role  = (body.get("role") or "member").lower()
    if not email:
        return jsonify({"error":"email_required"}), 400

    org_id = me_user.get("org_id") or me_user.get("email") or me

    # already a member in team namespace?
    existing_member_rec = users_db.get(_user_key(email))
    if existing_member_rec and (existing_member_rec.get("org_id") == org_id):
        return jsonify({"error": "already_member"}), 409

    # pending invite?
    invites = _invites()
    now = int(time.time())
    for t, inv in invites.items():
        if inv.get("accepted_at"):
            continue
        if _norm(inv.get("email")) == email and inv.get("org_id") == org_id and inv.get("expires_at", 0) > now:
            accept_url = urljoin(FRONTEND_BASE, f"/accept-invite?token={t}")
            return jsonify({"ok": True, "token": t, "accept_url": accept_url, "existing": True})

    # create new invite
    token = secrets.token_urlsafe(24)
    invites[token] = {
        "email": email,
        "role": role,
        "org_id": org_id,
        "created_at": now,
        "expires_at": now + 7*24*3600,
        "accepted_at": None
    }
    _save_invites(invites)

    accept_url = urljoin(FRONTEND_BASE, f"/accept-invite?token={token}")
    return jsonify({"ok": True, "token": token, "accept_url": accept_url})

@team_bp.route("/api/team/invite/<token>", methods=["GET"])
def read_invite(token):
    invs = _invites()
    inv = invs.get(token)
    if not inv:
        return jsonify({"error":"not_found"}), 404
    if inv["expires_at"] < int(time.time()):
        return jsonify({"error":"expired"}), 410
    return jsonify({"invite": {"email": inv["email"], "role": inv["role"], "org_id": inv["org_id"]}})

@team_bp.route("/api/team/accept", methods=["POST"])
def accept_invite():
    """
    On accept:
      1) Ensure org owner exists in team namespace.
      2) Create/overwrite team member in 'user::email'.
      3) Create/overwrite TOP-LEVEL users[email] with owner’s password and business fields.
      → Teammate can now log in at /api/login using the OWNER'S password.
    """
    body  = request.get_json() or {}
    token = body.get("token")
    name  = (body.get("name") or "").strip()
    email_input = _norm(body.get("email"))

    if not token or not email_input:
        return jsonify({"error":"bad_request"}), 400

    invites = _invites()
    inv = invites.get(token)
    if not inv:
        return jsonify({"error":"not_found"}), 404
    if inv["expires_at"] < int(time.time()):
        return jsonify({"error":"expired"}), 410
    if inv.get("accepted_at"):
        return jsonify({"error":"already_accepted"}), 409

    # must match invited email
    if _norm(inv["email"]) != email_input:
        return jsonify({"error":"email_mismatch", "invited": _norm(inv["email"])}), 400

    users_db = _users()

    # Ensure owner exists in team namespace
    org_owner_email = _norm(inv.get("org_id") or "")
    if not org_owner_email:
        return jsonify({"error":"org_invalid"}), 400
    users_db = _bootstrap_owner_if_missing(users_db, org_owner_email)

    # 1) Team namespace record
    key = _user_key(email_input)
    users_db[key] = {
        "email": email_input,
        "name": name,
        "role": inv["role"] or "member",
        "org_id": inv["org_id"],
        "last_login": None
    }

    # 2) TOP-LEVEL login record with SAME PASSWORD as owner
    try:
        _clone_owner_login_to_member(
            users_db,
            owner_email=org_owner_email,
            member_email=email_input,
            name=name,
            role=inv["role"] or "member",
        )
    except ValueError as e:
        if str(e) == "owner_password_missing":
            return jsonify({"error": "owner_has_no_password"}), 409
        raise

    # persist
    _save_users(users_db)

    # 3) mark invite accepted
    inv["accepted_at"] = int(time.time())
    invites[token] = inv
    _save_invites(invites)

    return jsonify({
        "ok": True,
        "login": {
            "email": email_input,
            "password_hint": "Use the same password as the account owner."
        }
    })

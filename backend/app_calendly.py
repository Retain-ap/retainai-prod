"""Owner-only, read-only Calendly connection and manual sync (primary booking link).

Unavailable unless the server has Calendly OAuth app credentials
(CALENDLY_CLIENT_ID, CALENDLY_CLIENT_SECRET, CALENDLY_REDIRECT_URI). Status
reports only what is stored; there is no simulated connection.
"""

import datetime as dt
import hashlib
import os
import uuid
from urllib.parse import urlencode

from flask import Blueprint, jsonify, redirect, request, session

import calendly_bookings as cal
import value_receipt as vr
from oauth_state import consume_oauth_state, issue_oauth_state
from secret_store import decrypt_secret, encrypt_secret
from storage import DATA_ROOT, load_user_leads

calendly_bp = Blueprint("calendly", __name__)
CONNECTIONS_FILE = os.path.join(DATA_ROOT, "calendly_connections.json")
STATE_PURPOSE = "calendly_bookings"
_PKCE_SESSION_KEY = "calendly_pkce"


def _config():
    client_id = str(os.getenv("CALENDLY_CLIENT_ID") or "").strip()
    secret = str(os.getenv("CALENDLY_CLIENT_SECRET") or "").strip()
    redirect_uri = str(os.getenv("CALENDLY_REDIRECT_URI") or "").strip()
    return {
        "configured": bool(client_id and secret and redirect_uri.startswith("https://") and os.getenv("DATA_ENCRYPTION_KEY")),
        "client_id": client_id, "secret": secret, "redirect_uri": redirect_uri,
    }


def _client(config):
    return cal.CalendlyClient(client_id=config["client_id"], client_secret=config["secret"], redirect_uri=config["redirect_uri"])


def _keys():
    return str(os.getenv("DATA_ENCRYPTION_KEY") or ""), str(os.getenv("PREVIOUS_DATA_ENCRYPTION_KEY") or "")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _owner():
    from app_value import _owner_context

    return _owner_context()


def _load(workspace):
    return (vr._read(CONNECTIONS_FILE).get(workspace) or {}) if workspace else {}


def _update(change, guard=None):
    """Read-modify-write under the file lock; ``guard`` re-checks inside the
    lock that the workspace still exists (see app_value.workspace_guard)."""
    with vr._locked(CONNECTIONS_FILE):
        if guard:
            guard()
        data = vr._read(CONNECTIONS_FILE)
        result = change(data)
        vr._write(CONNECTIONS_FILE, data)
        return result


def _store_tokens(connection, tokens, now):
    key, _ = _keys()
    connection["access_token_enc"] = encrypt_secret(tokens["access_token"], key)
    if tokens.get("refresh_token"):
        connection["refresh_token_enc"] = encrypt_secret(tokens["refresh_token"], key)
    try:
        lifetime = int(tokens.get("expires_in") or 7200)
    except (TypeError, ValueError):
        lifetime = 7200
    connection["expires_at"] = vr._iso(now + dt.timedelta(seconds=max(60, min(lifetime, 86400))))
    connection["token_refreshed_at"] = vr._iso(now)
    connection["status"] = "connected"


def _masked(user_uri):
    return f"…{cal.uuid_from_uri(user_uri)[-4:]}" if user_uri else ""


def _public(connection, config):
    if not connection.get("user_uri"):
        return {"configured": config["configured"], "connected": False}
    return {
        "configured": config["configured"],
        "connected": connection.get("status") == "connected",
        "needs_reconnect": connection.get("status") == "needs_reconnect",
        "account": _masked(connection.get("user_uri")),
        "connected_at": connection.get("connected_at") or "",
        "last_sync": connection.get("last_sync") or None,
        "sync_in_progress": bool(connection.get("sync_cursor")),
        "scopes": list(cal.REQUIRED_SCOPES),
    }


def _state_key(state):
    return hashlib.sha256(str(state).encode("utf-8")).hexdigest()[:32]


@calendly_bp.get("/api/calendly/status")
def calendly_status():
    ctx, error = _owner()
    if error:
        return error
    try:
        return jsonify(_public(_load(ctx["workspace"]), _config())), 200
    except vr.EvidenceStoreError:
        return jsonify({"error": "Calendly connection details can't be read right now."}), 503


@calendly_bp.post("/api/calendly/connect")
def calendly_connect():
    ctx, error = _owner()
    if error:
        return error
    config = _config()
    if not config["configured"]:
        return jsonify({"error": "Calendly isn't available yet: RetainAI's Calendly app credentials are not configured."}), 503
    state = issue_oauth_state(STATE_PURPOSE, f"{ctx['workspace']}|{ctx['email']}")
    verifier, challenge = cal.pkce_pair()
    # The verifier stays in the owner's signed session; only the challenge leaves.
    pending = dict(session.get(_PKCE_SESSION_KEY) or {})
    pending[_state_key(state)] = verifier
    session[_PKCE_SESSION_KEY] = dict(list(pending.items())[-4:])
    session.modified = True
    return jsonify({"url": cal.authorize_url(config["client_id"], config["redirect_uri"], state, challenge)}), 200


def _back(**params):
    base = str(os.getenv("FRONTEND_URL") or "https://www.retainai.ca").rstrip("/")
    return redirect(f"{base}/app/import?{urlencode(params)}")


@calendly_bp.get("/api/calendly/oauth/callback")
def calendly_callback():
    state = request.args.get("state")
    pending = dict(session.get(_PKCE_SESSION_KEY) or {})
    verifier = pending.pop(_state_key(state), None) if state else None
    session[_PKCE_SESSION_KEY] = pending
    session.modified = True
    record = consume_oauth_state(STATE_PURPOSE, state)
    if not record:
        return _back(calendly_error="expired")
    workspace, _, actor = str(record.get("subject") or "").partition("|")
    ctx, error = _owner()
    if error or not verifier or ctx["workspace"] != workspace or ctx["email"] != actor or vr._email(session.get("user_email")) != actor:
        return _back(calendly_error="session_mismatch")
    if request.args.get("error"):
        return _back(calendly_error="denied" if request.args.get("error") == "access_denied" else "failed")
    config = _config()
    code = str(request.args.get("code") or "")
    if not code or not config["configured"]:
        return _back(calendly_error="failed")
    client = _client(config)
    try:
        tokens = client.exchange_code(code, verifier)
    except cal.CalendlyError:
        return _back(calendly_error="failed")
    # The token response names the connecting user, so users:read isn't needed.
    user_uri = str(tokens.get("owner") or "")
    problem = ""
    if not tokens.get("access_token") or not user_uri.startswith(cal.USER_URI_PREFIX):
        problem = "failed"
    elif not cal.granted_scopes_ok(tokens):
        problem = "missing_scope"
    now = _now()

    def save(data):
        for other, connection in data.items():
            if other != workspace and isinstance(connection, dict) and connection.get("user_uri") == user_uri:
                return "account_linked_elsewhere"
        current = data.get(workspace) or {}
        if current.get("user_uri") and current["user_uri"] != user_uri:
            return "different_account"
        connection = {**current, "user_uri": user_uri, "organization_uri": str(tokens.get("organization") or "")[:200],
                      "granted_scope": str(tokens.get("scope") or "")[:200],
                      # A new generation on every connect: a sync started under an
                      # earlier connection can never write after a reconnect.
                      "connection_id": uuid.uuid4().hex,
                      "connected_by": actor, "connected_at": current.get("connected_at") or vr._iso(now)}
        connection.pop("sync_cursor", None)
        _store_tokens(connection, tokens, now)
        data[workspace] = connection
        return ""

    if not problem:
        try:
            problem = _update(save, ctx["guard"])
        except (vr.EvidenceStoreError, vr.WorkspaceGone):
            problem = "failed"
    if problem:
        for token in (tokens.get("refresh_token"), tokens.get("access_token")):
            if token:
                try:  # don't keep an authorization RetainAI won't use
                    client.revoke(token)
                except cal.CalendlyError:
                    pass
        return _back(calendly_error=problem)
    return _back(calendly="connected")


class ConnectionChanged(RuntimeError):
    """Calendly was disconnected or reconnected while a sync was running."""


def _access_token(workspace, config, *, guard=None, force_refresh=False, connection_id=None):
    """A valid access token. Renewal happens under the file lock so two syncs
    never spend the same single-use refresh token."""
    key, previous = _keys()

    def renew(data):
        connection = data.get(workspace) or {}
        if not connection.get("user_uri"):
            raise LookupError("not_connected")
        if connection_id is not None and connection.get("connection_id") != connection_id:
            raise ConnectionChanged()
        if connection.get("status") != "connected":
            raise cal.CalendlyAuthError("needs_reconnect")
        expires = vr._utc(connection.get("expires_at"))
        if not force_refresh and expires and expires - _now() > cal.REFRESH_MARGIN:
            return decrypt_secret(connection.get("access_token_enc"), key, previous), False
        try:
            tokens = _client(config).refresh(decrypt_secret(connection.get("refresh_token_enc"), key, previous))
        except cal.CalendlyAuthError:
            connection["status"] = "needs_reconnect"
            return None, True
        if not tokens.get("access_token"):
            connection["status"] = "needs_reconnect"
            return None, True
        _store_tokens(connection, tokens, _now())
        return tokens["access_token"], False

    token, refused = _update(renew, guard)
    if refused:
        raise cal.CalendlyAuthError("needs_reconnect")
    return token


@calendly_bp.post("/api/calendly/sync")
def calendly_sync():
    """One bounded step of a pass over the owner's Calendly window.

    Reads at most SYNC_REQUEST_BUDGET requests / SYNC_TIME_BUDGET_SECONDS,
    never sleeps for a rate limit, and saves a server-side cursor so the next
    Sync continues. Everything read in this step is written in one commit that
    first re-checks, under the connection and appointment locks, that the same
    Calendly connection is still in place.
    """
    import app as core

    ctx, error = _owner()
    if error:
        return error
    config = _config()
    if not config["configured"]:
        return jsonify({"error": "Calendly isn't available: credentials are not configured."}), 503
    workspace, now = ctx["workspace"], _now()
    client = _client(config)
    changed = (jsonify({"error": "Calendly was disconnected or reconnected during this sync. Nothing from it was saved."}), 409)
    try:
        connection = _load(workspace)
    except vr.EvidenceStoreError:
        return jsonify({"error": "Calendly connection details can't be read right now."}), 503
    user_uri, connection_id = connection.get("user_uri"), connection.get("connection_id") or ""
    if not user_uri:
        return jsonify({"error": "Calendly isn't connected."}), 400
    cursor, continuing = cal.cursor_for(connection.get("sync_cursor"), connection_id, user_uri, now)
    budget = cal.Budget()
    held = {"token": None, "renewed": False}

    def call(request_with):
        if held["token"] is None:
            held["token"] = _access_token(workspace, config, guard=ctx["guard"], connection_id=connection_id)
        try:
            return request_with(held["token"])
        except cal.CalendlyAuthError:
            if held["renewed"]:
                raise
            held["renewed"] = True  # one forced renewal per sync
            held["token"] = _access_token(workspace, config, guard=ctx["guard"], connection_id=connection_id, force_refresh=True)
            return request_with(held["token"])

    try:
        step = cal.fetch_step(client, call, cursor, budget)
    except ConnectionChanged:
        return changed
    except LookupError:
        return jsonify({"error": "Calendly isn't connected."}), 400
    except cal.CalendlyAuthError:
        return jsonify({"error": "Calendly no longer accepts RetainAI's access. Reconnect Calendly to continue."}), 409
    except cal.CalendlyError as exc:
        return jsonify({"error": f"Calendly could not be read: {exc} Nothing from this sync was saved."}), 502
    except vr.EvidenceStoreError:
        return jsonify({"error": "Calendly connection details can't be read right now."}), 503

    index = cal.email_index(load_user_leads(workspace))
    timezone_name = ctx["owner"].get("timezone") or "UTC"
    finished = step["state"] in ("complete", "truncated")
    results = {"events": step["events"], "invitees": len(step["pairs"]), "imported": 0, "updated": 0, "unchanged": 0,
               "unmatched": 0, "skipped": 0, "cancelled": 0, "rescheduled": 0,
               "pass_complete": finished, "continued": continuing,
               "truncated": step["state"] == "truncated", "notes": step["notes"],
               "stopped": step["state"] if not finished else None, "retry_after": step["retry_after"],
               "pass_events": step["cursor"]["events_seen"]}
    mapped = []
    for event, invitee in step["pairs"]:
        status, rescheduled = cal.map_status(event, invitee, now)
        if not status:
            results["skipped"] += 1
            continue
        matches = index.get(str(invitee.get("email") or "").strip().lower()) or []
        if len(matches) != 1:
            # Only one existing contact may match; nobody is added from Calendly.
            results["unmatched"] += 1
            continue
        results["cancelled"] += status == "cancelled"
        results["rescheduled"] += rescheduled
        mapped.append(cal.to_appointment(event, invitee, matches[0], workspace=workspace, timezone_name=timezone_name,
                                         status=status, rescheduled=rescheduled))
    results["at"] = vr._iso(now)
    appointments_path = os.path.join(DATA_ROOT, "appointments.json")
    fields = ("status", "appointment_time", "duration", "calendly_status", "calendly_invitee_status",
              "calendly_rescheduled", "lead_id", "title", "timezone")

    def commit(data):
        current = data.get(workspace) or {}
        if current.get("connection_id", "") != connection_id or current.get("user_uri") != user_uri:
            raise ConnectionChanged()
        with vr._locked(appointments_path):
            ctx["guard"]()  # deleted while Calendly was being read: write nothing
            all_appointments = core.load_appointments() or {}
            rows = list(all_appointments.get(workspace) or [])
            positions = {str(row.get("id")): i for i, row in enumerate(rows)
                         if isinstance(row, dict) and str(row.get("id") or "").startswith("calendly:")}
            for appointment in mapped:
                position = positions.get(appointment["id"])
                if position is None:
                    rows.append(appointment)
                    positions[appointment["id"]] = len(rows) - 1
                    results["imported"] += 1
                elif all(rows[position].get(field) == appointment.get(field) for field in fields):
                    results["unchanged"] += 1
                else:
                    rows[position] = {**rows[position], **appointment}
                    results["updated"] += 1
            if mapped:
                all_appointments[workspace] = rows
                core.save_appointments(all_appointments)
        if finished:
            current.pop("sync_cursor", None)  # the next Sync starts a fresh pass
        else:
            current["sync_cursor"] = step["cursor"]
        current["last_sync"] = results
        data[workspace] = current

    try:
        _update(commit, ctx["guard"])
    except ConnectionChanged:
        return changed
    except vr.EvidenceStoreError:
        return jsonify({"error": "Calendly connection details can't be read right now."}), 503
    return jsonify({"ok": True, **results}), 200


def revoke_workspace(workspace):
    """Revoke at Calendly (best effort) and delete the stored tokens."""
    config = _config()
    connection = _load(workspace)
    revoked = False
    if config["configured"] and connection.get("user_uri"):
        key, previous = _keys()
        client = _client(config)
        for field in ("refresh_token_enc", "access_token_enc"):
            token = decrypt_secret(connection.get(field), key, previous)
            if not token:
                continue
            try:
                client.revoke(token)
                revoked = True
            except cal.CalendlyError:
                pass
    _update(lambda data: data.pop(workspace, None))
    return revoked


@calendly_bp.post("/api/calendly/disconnect")
def calendly_disconnect():
    ctx, error = _owner()
    if error:
        return error
    try:
        if not _load(ctx["workspace"]).get("user_uri"):
            return jsonify({"ok": True, "revoked": False, "was_connected": False}), 200
        revoked = revoke_workspace(ctx["workspace"])
    except vr.EvidenceStoreError:
        return jsonify({"error": "Calendly connection details can't be read right now."}), 503
    return jsonify({"ok": True, "revoked": revoked, "was_connected": True,
                    "message": "" if revoked else "RetainAI deleted its Calendly access, but Calendly couldn't confirm the revoke. You can also remove RetainAI in Calendly's integrations settings."}), 200

"""Owner-only, read-only Square Bookings connection and manual sync.

Unavailable unless the server has Square application credentials
(SQUARE_APPLICATION_ID, SQUARE_APPLICATION_SECRET). There is no simulated
connected state: status reports exactly what is stored.
"""

import datetime as dt
import os

from flask import Blueprint, jsonify, redirect, request, session

import square_bookings as sq
import value_receipt as vr
from oauth_state import consume_oauth_state, issue_oauth_state
from secret_store import decrypt_secret, encrypt_secret
from storage import DATA_ROOT, load_user_leads

square_bp = Blueprint("square", __name__)
CONNECTIONS_FILE = os.path.join(DATA_ROOT, "square_connections.json")
STATE_PURPOSE = "square_bookings"


def _config():
    client_id = str(os.getenv("SQUARE_APPLICATION_ID") or "").strip()
    secret = str(os.getenv("SQUARE_APPLICATION_SECRET") or "").strip()
    environment = "sandbox" if str(os.getenv("SQUARE_ENVIRONMENT") or "").strip().lower() == "sandbox" else "production"
    return {
        "configured": bool(client_id and secret and os.getenv("DATA_ENCRYPTION_KEY")),
        "client_id": client_id,
        "secret": secret,
        "environment": environment,
        "base": sq.BASE_URLS[environment],
    }


def _client(config, **kwargs):
    return sq.SquareClient(config["base"], client_id=config["client_id"], client_secret=config["secret"], **kwargs)


def _keys():
    return str(os.getenv("DATA_ENCRYPTION_KEY") or ""), str(os.getenv("PREVIOUS_DATA_ENCRYPTION_KEY") or "")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _frontend(path):
    base = str(os.getenv("FRONTEND_URL") or "https://www.retainai.ca").rstrip("/")
    return f"{base}{path}"


# ------------------------------------------------------------------ store

def _load(workspace):
    return (vr._read(CONNECTIONS_FILE).get(workspace) or {}) if workspace else {}


def _update(workspace, change, guard=None):
    """Read-modify-write one workspace's connection under the file lock.
    ``guard`` re-checks inside the lock that the workspace still exists."""
    with vr._locked(CONNECTIONS_FILE):
        if guard:
            guard()
        data = vr._read(CONNECTIONS_FILE)
        result = change(data)
        vr._write(CONNECTIONS_FILE, data)
        return result


def _public(connection, config):
    if not connection.get("merchant_id"):
        return {"configured": config["configured"], "connected": False, "environment": config["environment"]}
    return {
        "configured": config["configured"],
        "connected": connection.get("status") == "connected",
        "needs_reconnect": connection.get("status") == "needs_reconnect",
        "environment": connection.get("environment") or config["environment"],
        "merchant": f"…{str(connection['merchant_id'])[-4:]}",
        "connected_at": connection.get("connected_at") or "",
        "token_refreshed_at": connection.get("token_refreshed_at") or "",
        "last_sync": connection.get("last_sync") or None,
        "scopes": list(sq.SCOPES),
    }


def _store_tokens(connection, tokens, now):
    key, _ = _keys()
    connection["access_token_enc"] = encrypt_secret(tokens["access_token"], key)
    if tokens.get("refresh_token"):
        connection["refresh_token_enc"] = encrypt_secret(tokens["refresh_token"], key)
    connection["expires_at"] = str(tokens.get("expires_at") or "")
    connection["token_refreshed_at"] = vr._iso(now)
    connection["status"] = "connected"


def _owner():
    from app_value import _owner_context

    return _owner_context()


# ----------------------------------------------------------------- routes

@square_bp.get("/api/square/status")
def square_status():
    ctx, error = _owner()
    if error:
        return error
    try:
        return jsonify(_public(_load(ctx["workspace"]), _config())), 200
    except vr.EvidenceStoreError:
        return jsonify({"error": "Square connection details can't be read right now."}), 503


@square_bp.post("/api/square/connect")
def square_connect():
    ctx, error = _owner()
    if error:
        return error
    config = _config()
    if not config["configured"]:
        return jsonify({"error": "Square isn't available yet: RetainAI's Square app credentials are not configured."}), 503
    state = issue_oauth_state(STATE_PURPOSE, f"{ctx['workspace']}|{ctx['email']}")
    return jsonify({"url": sq.authorize_url(config["base"], config["client_id"], state, config["environment"])}), 200


@square_bp.get("/api/square/oauth/callback")
def square_callback():
    def back(**params):
        from urllib.parse import urlencode

        return redirect(_frontend("/app/import?" + urlencode(params)))

    record = consume_oauth_state(STATE_PURPOSE, request.args.get("state"))
    if not record:
        return back(square_error="expired")
    workspace, _, actor = str(record.get("subject") or "").partition("|")
    # The callback must land in the same signed-in owner session that started it.
    ctx, error = _owner()
    if error or ctx["workspace"] != workspace or ctx["email"] != actor or vr._email(session.get("user_email")) != actor:
        return back(square_error="session_mismatch")
    if request.args.get("error"):
        return back(square_error="denied" if request.args.get("error") == "access_denied" else "failed")
    code = str(request.args.get("code") or "")
    config = _config()
    if not code or not config["configured"]:
        return back(square_error="failed")
    try:
        tokens = _client(config).exchange_code(code)
    except sq.SquareError:
        return back(square_error="failed")
    merchant = str(tokens.get("merchant_id") or "")
    if not merchant or not tokens.get("access_token"):
        return back(square_error="failed")
    now = _now()

    def save(data):
        for other, connection in data.items():
            if other != workspace and isinstance(connection, dict) and connection.get("merchant_id") == merchant:
                return "merchant_linked_elsewhere"
        current = data.get(workspace) or {}
        if current.get("merchant_id") and current["merchant_id"] != merchant:
            return "different_merchant"
        connection = {**current, "merchant_id": merchant, "environment": config["environment"],
                      "connected_by": actor, "connected_at": current.get("connected_at") or vr._iso(now)}
        _store_tokens(connection, tokens, now)
        data[workspace] = connection
        return ""

    try:
        problem = _update(workspace, save, ctx["guard"])
    except (vr.EvidenceStoreError, vr.WorkspaceGone):
        problem = "failed"
    if problem:
        try:  # don't keep an authorization RetainAI won't use
            _client(config).revoke(tokens["access_token"])
        except sq.SquareError:
            pass
        return back(square_error=problem)
    return back(square="connected")


def _access_token(workspace, config, *, guard=None, force_refresh=False):
    connection = _load(workspace)
    if not connection.get("merchant_id"):
        raise LookupError("not_connected")
    if connection.get("status") != "connected":
        raise sq.SquareAuthError("needs_reconnect")
    key, previous = _keys()
    refreshed = vr._utc(connection.get("token_refreshed_at"))
    expires = vr._utc(connection.get("expires_at"))
    stale = not refreshed or _now() - refreshed >= sq.REFRESH_AFTER or (expires and expires - _now() < dt.timedelta(days=8))
    if force_refresh or stale:
        refresh_token = decrypt_secret(connection.get("refresh_token_enc"), key, previous)
        try:
            tokens = _client(config).refresh(refresh_token)
        except sq.SquareAuthError:
            _update(workspace, lambda data: data.get(workspace, {}).update(status="needs_reconnect"), guard)
            raise
        if not tokens.get("access_token"):
            raise sq.SquareError("Square returned no access token.")
        now = _now()

        def save(data):
            current = data.get(workspace) or {}
            if current.get("merchant_id") != connection.get("merchant_id"):
                return  # disconnected meanwhile: never resurrect
            _store_tokens(current, tokens, now)
            data[workspace] = current

        _update(workspace, save, guard)
        return tokens["access_token"]
    return decrypt_secret(connection.get("access_token_enc"), key, previous)


@square_bp.post("/api/square/sync")
def square_sync():
    import app as core

    ctx, error = _owner()
    if error:
        return error
    config = _config()
    if not config["configured"]:
        return jsonify({"error": "Square isn't available: credentials are not configured."}), 503
    workspace, now = ctx["workspace"], _now()
    client = _client(config)
    try:
        token = _access_token(workspace, config, guard=ctx["guard"])
        try:
            bookings, truncated = sq.fetch_bookings(client, token, now)
        except sq.SquareAuthError:
            token = _access_token(workspace, config, guard=ctx["guard"], force_refresh=True)
            bookings, truncated = sq.fetch_bookings(client, token, now)
    except LookupError:
        return jsonify({"error": "Square isn't connected."}), 400
    except sq.SquareAuthError:
        return jsonify({"error": "Square no longer accepts RetainAI's access. Reconnect Square to continue."}), 409
    except sq.SquareError as exc:
        return jsonify({"error": f"Square could not be read: {exc}"}), 502
    except vr.EvidenceStoreError:
        return jsonify({"error": "Square connection details can't be read right now."}), 503

    by_email, by_phone = sq.contact_index(load_user_leads(workspace))
    customers, lookups = {}, 0
    results = {"read": len(bookings), "imported": 0, "updated": 0, "unchanged": 0, "unmatched": 0,
               "skipped": 0, "lookup_limit": 0, "truncated": truncated}
    mapped = []
    for booking in bookings:
        start = sq._utc(booking.get("start_at"))
        status = sq.map_status(booking.get("status"), start, now) if start else None
        if not status:
            results["skipped"] += 1
            continue
        customer_id = str(booking.get("customer_id") or "")
        if customer_id and customer_id not in customers:
            if lookups >= sq.MAX_CUSTOMER_LOOKUPS:
                results["lookup_limit"] += 1
                continue
            lookups += 1
            try:
                customers[customer_id] = client.get_customer(token, customer_id)
            except sq.SquareError:
                customers[customer_id] = {}
        lead = sq.match_contact(customers.get(customer_id) or {}, by_email, by_phone)
        if not lead:
            # Only existing contacts are updated; nobody is added from Square.
            results["unmatched"] += 1
            continue
        mapped.append(sq.to_appointment(booking, lead, workspace=workspace, timezone_name=ctx["owner"].get("timezone"), status=status))

    appointments_path = os.path.join(DATA_ROOT, "appointments.json")
    with vr._locked(appointments_path):
        ctx["guard"]()  # deleted while Square was being read: write nothing
        all_appointments = core.load_appointments() or {}
        rows = list(all_appointments.get(workspace) or [])
        index = {str(row.get("square_booking_id")): i for i, row in enumerate(rows) if isinstance(row, dict) and row.get("square_booking_id")}
        for appointment in mapped:
            position = index.get(appointment["square_booking_id"])
            if position is None:
                rows.append(appointment)
                index[appointment["square_booking_id"]] = len(rows) - 1
                results["imported"] += 1
                continue
            existing = rows[position]
            fields = ("status", "appointment_time", "duration", "square_version", "square_status", "lead_id")
            if all(existing.get(field) == appointment.get(field) for field in fields):
                results["unchanged"] += 1
                continue
            rows[position] = {**existing, **appointment}
            results["updated"] += 1
        all_appointments[workspace] = rows
        core.save_appointments(all_appointments)

    results["at"] = vr._iso(now)

    def remember(data):
        if workspace in data and data[workspace].get("merchant_id"):
            data[workspace]["last_sync"] = results

    _update(workspace, remember, ctx["guard"])
    return jsonify({"ok": True, **results}), 200


def revoke_workspace(workspace):
    """Revoke at Square (best effort) and delete the stored tokens."""
    config = _config()
    connection = _load(workspace)
    revoked = False
    if connection.get("access_token_enc") and config["configured"]:
        key, previous = _keys()
        try:
            _client(config).revoke(decrypt_secret(connection["access_token_enc"], key, previous))
            revoked = True
        except sq.SquareError:
            revoked = False
    _update(workspace, lambda data: data.pop(workspace, None))
    return revoked


@square_bp.post("/api/square/disconnect")
def square_disconnect():
    ctx, error = _owner()
    if error:
        return error
    try:
        if not _load(ctx["workspace"]).get("merchant_id"):
            return jsonify({"ok": True, "revoked": False, "was_connected": False}), 200
        revoked = revoke_workspace(ctx["workspace"])
    except vr.EvidenceStoreError:
        return jsonify({"error": "Square connection details can't be read right now."}), 503
    return jsonify({"ok": True, "revoked": revoked, "was_connected": True,
                    "message": "" if revoked else "RetainAI deleted its Square access, but Square couldn't confirm the revoke. You can also remove RetainAI in your Square Dashboard."}), 200

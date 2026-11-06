"""Value Receipt API: verified paid revenue linked to recorded follow-ups.

Owner-only. Every request is scoped to the signed-in session's workspace; no
caller-supplied identity is trusted. Reading Stripe is on demand and read-only,
against the business's own connected account. RetainAI's platform (membership)
billing account is never queried here.
"""

import datetime as dt
import os

from flask import Blueprint, Response, jsonify, request

import value_receipt as vr
from storage import DATA_ROOT, load_user_leads

value_bp = Blueprint("value_receipt", __name__)

REVENUE_FILE = os.path.join(DATA_ROOT, "revenue_evidence.json")
FOLLOWUP_FILE = os.path.join(DATA_ROOT, "followup_log.json")
MAX_SYNC_INVOICES = 1000

revenue_store = vr.RevenueStore(REVENUE_FILE)
followup_log = vr.FollowupLog(FOLLOWUP_FILE)


def record_followup(workspace, *, lead_id="", lead_email="", channel, source):
    """Called by send paths right after a provider accepted a message."""
    try:
        return followup_log.record(workspace, lead_id=lead_id, lead_email=lead_email, channel=channel, source=source)
    except Exception:  # never let bookkeeping break a successful send
        return None


def _store_unavailable():
    import app as core

    core.app.logger.error("[VALUE RECEIPT] Evidence store unreadable; refusing to read or write")
    return jsonify({"error": "Revenue records can't be read right now. Nothing was changed."}), 503


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _owner_context():
    import app as core

    email = core._session_email()
    if not email:
        return None, (jsonify({"error": "authentication_required"}), 401)
    role, workspace, owner, account_id = core._connected_acct_for(email)
    if not role:
        return None, (jsonify({"error": "authentication_required"}), 401)
    if role != "owner":
        # Revenue is the owner's business information, like invoices.
        return None, (jsonify({"error": "owner_required"}), 403)
    return {"email": email, "workspace": vr._email(workspace), "owner": owner or {}, "account_id": account_id or ""}, None


def _receipt_for(ctx):
    import app as core

    args = request.args
    window_days = vr.parse_window(args.get("window_days"))
    start, end, since, until, zone = vr.parse_period(
        args.get("since"), args.get("until"), ctx["owner"].get("timezone"), _now()
    )
    workspace = ctx["workspace"]
    notifications = (core.load_notifications() or {}).get(workspace) or []
    chats = (core.load_chats() or {}).get(workspace) or {}
    followups = vr.collect_followups(
        workspace, log_entries=followup_log.entries(workspace), notifications=notifications, chats=chats
    )
    appointments = (core.load_appointments() or {}).get(workspace) or []
    receipt = vr.build_receipt(
        last_sync=revenue_store.meta(workspace)["last_sync"],
        records=revenue_store.records(workspace),
        leads=load_user_leads(workspace),
        followups=followups,
        appointments=appointments,
        start=start,
        end=end,
        window_days=window_days,
    )
    receipt["period"] = {"since": since, "until": until, "timezone": zone}
    receipt["stripe_connected"] = bool(ctx["account_id"])
    receipt["currencies"] = sorted(vr.CURRENCY_EXPONENTS)
    return receipt


@value_bp.get("/api/value-receipt")
def get_value_receipt():
    ctx, error = _owner_context()
    if error:
        return error
    try:
        return jsonify(_receipt_for(ctx)), 200
    except vr.EvidenceError as exc:
        return jsonify({"error": str(exc)}), 400
    except vr.EvidenceStoreError:
        return _store_unavailable()


@value_bp.get("/api/value-receipt/export.csv")
def export_value_receipt():
    ctx, error = _owner_context()
    if error:
        return error
    try:
        receipt = _receipt_for(ctx)
    except vr.EvidenceError as exc:
        return jsonify({"error": str(exc)}), 400
    except vr.EvidenceStoreError:
        return _store_unavailable()
    name = f"retainai-value-receipt-{receipt['period']['since']}-to-{receipt['period']['until']}.csv"
    return Response(
        vr.receipt_csv(receipt),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


@value_bp.post("/api/value-receipt/sync")
def sync_value_receipt():
    """Read paid invoices from the business's own connected Stripe account."""
    import app as core

    ctx, error = _owner_context()
    if error:
        return error
    if not ctx["account_id"]:
        return jsonify({"error": "stripe_not_connected"}), 400
    since = int((_now() - dt.timedelta(days=vr.MAX_PERIOD_DAYS)).timestamp())
    records, seen = [], 0
    try:
        listing = core.stripe.Invoice.list(
            status="paid", created={"gte": since}, limit=100,
            expand=["data.charge"], stripe_account=ctx["account_id"],
            stripe_version=vr.STRIPE_API_VERSION,
        )
        for invoice in listing.auto_paging_iter():
            seen += 1
            if seen > MAX_SYNC_INVOICES:
                break
            record = vr.stripe_invoice_record(invoice, ctx["account_id"])
            if record:
                records.append(record)
    except Exception as exc:
        core.app.logger.warning("[VALUE RECEIPT] Stripe read failed: %s", type(exc).__name__)
        return jsonify({"error": "stripe_read_failed"}), 502
    truncated = seen > MAX_SYNC_INVOICES
    try:
        result = revenue_store.upsert_stripe(ctx["workspace"], records, vr._iso(_now()), complete=not truncated)
    except vr.EvidenceStoreError:
        return _store_unavailable()
    return jsonify({"ok": True, "read": len(records), **result, "truncated": truncated}), 200


@value_bp.post("/api/value-receipt/payments")
def record_payment():
    ctx, error = _owner_context()
    if error:
        return error
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Send the payment as a JSON object."}), 400
    lead_id = str(body.get("lead_id") or "").strip()
    lead = next((row for row in load_user_leads(ctx["workspace"]) if isinstance(row, dict) and str(row.get("id") or "") == lead_id), None)
    if not lead:
        return jsonify({"error": "Choose a customer from this workspace."}), 400
    try:
        import app as core

        record, created = revenue_store.add_manual(
            ctx["workspace"], body, lead=lead, recorded_by=ctx["email"], now=_now(),
            timezone_name=ctx["owner"].get("timezone") or "UTC",
            bookings=(core.load_appointments() or {}).get(ctx["workspace"]) or [],
        )
    except vr.EvidenceError as exc:
        return jsonify({"error": str(exc)}), 409 if "idempotency key was already used" in str(exc) else 400
    except vr.EvidenceStoreError:
        return _store_unavailable()
    return jsonify({"ok": True, "record": record, "created": created}), 201 if created else 200


@value_bp.post("/api/value-receipt/payments/<record_id>/refund")
def record_refund(record_id):
    ctx, error = _owner_context()
    if error:
        return error
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Send the refund as a JSON object."}), 400
    try:
        record = revenue_store.set_manual_refund(ctx["workspace"], record_id, body.get("refunded_amount", ""), _now())
    except KeyError:
        return jsonify({"error": "Only owner-recorded payments can be changed here."}), 404
    except vr.EvidenceError as exc:
        return jsonify({"error": str(exc)}), 400
    except vr.EvidenceStoreError:
        return _store_unavailable()
    return jsonify({"ok": True, "record": record}), 200


@value_bp.delete("/api/value-receipt/payments/<record_id>")
def delete_payment(record_id):
    ctx, error = _owner_context()
    if error:
        return error
    try:
        revenue_store.delete_manual(ctx["workspace"], record_id)
    except KeyError:
        return jsonify({"error": "Only owner-recorded payments can be removed."}), 404
    except vr.EvidenceStoreError:
        return _store_unavailable()
    return jsonify({"ok": True}), 200

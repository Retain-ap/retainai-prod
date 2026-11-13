"""Owner-reviewed referral accounting. No payment transfers are performed here."""
import calendar
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import closing, contextmanager

import requests
from flask import Blueprint, current_app, g, jsonify, redirect, request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from storage import SQLITE_PATH, load_users
from app_owner import _require_owner

partners_bp = Blueprint("partners", __name__)
COOKIE = "retainai_partner"
WINDOW = 60 * 86400
HOLD = 30 * 86400


def blank():
    return {"partners": [], "referrals": [], "invoices": [], "payouts": []}


def needs_refund_refresh(row):
    return row.get("reason") == "Refund adjusted" and row.get("refundAllocationVersion") != 1


def hold_legacy_refunds(state):
    # Old snapshots lack line-allocation evidence. Normalize reads as well as
    # writes so owner screens/exports cannot present stale amounts as payable.
    for row in state["invoices"]:
        if needs_refund_refresh(row):
            row.update({"previousCommissionMinor": row["commissionMinor"], "commissionMinor": 0,
                "status": "review", "reason": "Refund allocation needs refresh"})
    return state


@contextmanager
def state_write():
    # Share the already-backed-up application database; BEGIN IMMEDIATE also
    # serializes the two gunicorn workers. Never hold this lock across Stripe.
    with closing(sqlite3.connect(SQLITE_PATH, timeout=15)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS partner_ledger (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT value FROM partner_ledger WHERE id=1").fetchone()
        state = hold_legacy_refunds(json.loads(row[0]) if row else blank())
        yield state
        connection.execute("INSERT OR REPLACE INTO partner_ledger VALUES (1, ?)", (json.dumps(state),))


def read_state():
    with closing(sqlite3.connect(SQLITE_PATH, timeout=15)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS partner_ledger (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        row = connection.execute("SELECT value FROM partner_ledger WHERE id=1").fetchone()
        return hold_legacy_refunds(json.loads(row[0]) if row else blank())


def identity(email):
    local, _, domain = str(email).strip().lower().partition("@")
    local = local.split("+", 1)[0]
    if domain in {"gmail.com", "googlemail.com"}:
        domain, local = "gmail.com", local.replace(".", "")
    return hashlib.sha256(f"{local}@{domain}".encode()).hexdigest()


def signer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="partner-referral-v1")


def read_cookie():
    try:
        return signer().loads(request.cookies.get(COOKIE, ""), max_age=WINDOW)
    except (BadSignature, SignatureExpired):
        return None


def signup_partner(email):
    code = read_cookie()
    if not isinstance(code, str):
        return ""
    state = read_state()
    partner = next((p for p in state["partners"] if p["code"] == code and p["active"]), None)
    if not partner or identity(email) in {identity(partner["email"]), identity("owner@retainai.ca")}:
        return ""
    if any(r["accountKey"] == identity(email) for r in state["referrals"]):
        return ""
    return code


@partners_bp.get("/api/partners/r/<code>")
def referral_link(code):
    state = read_state()
    valid = any(p["code"] == code and p["active"] for p in state["partners"])
    response = redirect("https://www.retainai.ca/signup" if valid else "https://www.retainai.ca/partners")
    if valid and not read_cookie():
        response.set_cookie(COOKIE, signer().dumps(code), max_age=WINDOW, httponly=True, secure=True, samesite="Lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def bind_customer(email, customer, code, created_at, live):
    if not re.fullmatch(r"cus_[A-Za-z0-9]+", str(customer)) or not code:
        return
    with state_write() as state:
        partner = next((p for p in state["partners"] if p["code"] == code), None)
        key = identity(email)
        if not partner or key == identity(partner["email"]):
            return
        existing = next((r for r in state["referrals"] if r["accountKey"] == key and r["livemode"] == live), None)
        if existing:
            # A recreated account / new Stripe customer never restarts the term.
            return
        if any(r["customerId"] == customer and r["livemode"] == live for r in state["referrals"]):
            return
        state["referrals"].append({"accountKey": key, "code": code, "customerId": customer,
            "createdAt": created_at, "livemode": live, "firstPaidAt": 0, "syncedAt": 0, "error": "Not synced yet",
            "basePriceIds": [os.environ["STRIPE_PRICE_ID"]] if os.environ.get("STRIPE_PRICE_ID") else []})


def mode():
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if re.match(r"^(sk|rk)_live_", key):
        return True
    if re.match(r"^(sk|rk)_test_", key):
        return False
    raise ValueError("Stripe is not configured")


def stripe_get(path):
    # Isolated read-only accounting client; existing checkout API stays pinned.
    response = requests.get("https://api.stripe.com/v1/" + path,
        auth=(os.environ.get("STRIPE_SECRET_KEY", ""), ""),
        headers={"Stripe-Version": "2025-06-30.basil"}, timeout=8)
    if not response.ok:
        raise ValueError("Stripe reconciliation unavailable; retry before recording a payout")
    return response.json()


def anniversary(stamp):
    date = dt.datetime.fromtimestamp(stamp, dt.timezone.utc)
    return int(date.replace(year=date.year + 1, day=min(date.day, calendar.monthrange(date.year + 1, date.month)[1])).timestamp())


def base_amount(invoice, price):
    prices = {price} if isinstance(price, str) else set(price)
    lines = (invoice.get("lines") or {})
    if not isinstance(lines.get("data"), list) or lines.get("has_more") is not False:
        raise ValueError("Invoice lines need manual review")
    amount = 0
    for line in lines.get("data", []):
        details = (line.get("parent") or {}).get("subscription_item_details") or {}
        if ((line.get("pricing") or {}).get("price_details") or {}).get("price") not in prices:
            continue
        if not details.get("subscription") or details.get("proration") or line.get("quantity") != 1 or line.get("amount", 0) < 0:
            raise ValueError("Proration or quantity needs manual review")
        amount += line["amount"] - sum(d["amount"] for d in line.get("discount_amounts") or []) - sum(t["amount"] for t in line.get("taxes") or [] if t.get("tax_behavior") == "inclusive")
    return max(0, amount)


def calculate(invoice, charge, base, first_paid, now, base_prices=()):
    """Pure calculation, all amounts in Stripe minor units. Fail closed."""
    paid_at = (invoice.get("status_transitions") or {}).get("paid_at") or 0
    result = {"invoiceId": invoice["id"], "currency": invoice.get("currency", ""), "paidAt": paid_at,
        "baseMinor": base, "commissionMinor": 0, "holdUntil": paid_at + HOLD, "reason": "", "status": "excluded", "refundAllocationVersion": 1}
    if invoice.get("status") != "paid" or invoice.get("amount_paid", 0) <= 0 or base <= 0:
        result["reason"] = "No paid base membership"
        return result
    if not first_paid or not paid_at or paid_at >= anniversary(first_paid):
        result["reason"] = "Outside the first 12 months"
        return result
    total = invoice.get("total", 0)
    valid = (isinstance(total, int) and total > 0 and invoice.get("amount_paid") == total
        and invoice.get("total_excluding_tax") is not None and 0 <= base <= invoice["total_excluding_tax"]
        and not invoice.get("paid_out_of_band") and not invoice.get("post_payment_credit_notes_amount")
        and not invoice.get("pre_payment_credit_notes_amount") and charge and charge.get("paid")
        and charge.get("captured") and charge.get("status") == "succeeded" and charge.get("amount") == total
        and charge.get("customer") == invoice.get("customer") and charge.get("currency") == invoice.get("currency")
        and charge.get("livemode") == invoice.get("livemode") and isinstance(charge.get("amount_refunded"), int)
        and 0 <= charge["amount_refunded"] <= total)
    if not valid:
        return {**result, "status": "review", "reason": "Payment or credit allocation needs review"}
    if charge.get("disputed") or (charge.get("fraud_details") or {}).get("stripe_report") == "fraudulent" or (charge.get("fraud_details") or {}).get("user_report") == "fraudulent":
        return {**result, "status": "review", "reason": "Dispute or fraud hold"}
    # Stripe reports charge-wide refunds, not which subscription line was
    # refunded. Base-only invoices may include tax without including add-ons.
    lines = invoice.get("lines") or {}
    base_only = (base == invoice.get("total_excluding_tax") and lines.get("has_more") is False
        and isinstance(lines.get("data"), list)
        and any(line.get("amount", 0) > 0 and ((line.get("pricing") or {}).get("price_details") or {}).get("price") in base_prices for line in lines["data"])
        and all(line.get("amount") == 0
            or ((line.get("pricing") or {}).get("price_details") or {}).get("price") in base_prices
            for line in lines["data"]))
    if 0 < charge["amount_refunded"] < total and not base_only:
        return {**result, "status": "review", "reason": "Partial refund allocation needs review"}
    remaining = max(0, total - charge["amount_refunded"])
    commission = (base * remaining * 30 + total * 50) // (total * 100)
    return {**result, "commissionMinor": commission, "status": "available" if now >= result["holdUntil"] else "pending", "reason": "Refund adjusted" if remaining < total else ""}


def sync_customer(customer):
    live = mode()
    referral = next((r for r in read_state()["referrals"] if r["customerId"] == customer and r["livemode"] == live), None)
    if not referral:
        return
    prices = sorted(set(referral.get("basePriceIds", [])) | {os.environ.get("STRIPE_PRICE_ID", "")})
    prices = [price for price in prices if price]
    if not prices:
        raise ValueError("Base membership price is not configured")
    with state_write() as state:
        current = next(r for r in state["referrals"] if r["customerId"] == customer and r["livemode"] == live)
        if current.get("syncUntil", 0) > time.time():
            raise ValueError("A refresh is already running; retry shortly")
        current.update({"syncUntil": int(time.time()) + 300, "syncedAt": 0})
    try:
        invoices, cursor = [], ""
        for _ in range(5):
            page = stripe_get(f"invoices?customer={customer}&limit=100" + (f"&starting_after={cursor}" if cursor else ""))
            if not isinstance(page.get("data"), list) or not isinstance(page.get("has_more"), bool):
                raise ValueError("Invoice list incomplete")
            invoices.extend(page["data"])
            if not page["has_more"]:
                break
            cursor = page["data"][-1]["id"]
        else:
            raise ValueError("Invoice history needs manual review")
        rows, first = [], referral["firstPaidAt"]
        for invoice in sorted(invoices, key=lambda i: (i.get("status_transitions") or {}).get("paid_at") or 0):
            if invoice.get("customer") != customer or invoice.get("livemode") != live:
                raise ValueError("Invoice ownership mismatch")
            if invoice.get("status") != "paid" or invoice.get("amount_paid", 0) <= 0:
                continue
            stamp = (invoice.get("status_transitions") or {}).get("paid_at") or 0
            if stamp and any(((line.get("pricing") or {}).get("price_details") or {}).get("price") in prices for line in (invoice.get("lines") or {}).get("data", [])):
                first = min(first or stamp, stamp)
            try:
                base = base_amount(invoice, prices)
                if not base:
                    continue
                if stamp:
                    first = min(first or stamp, stamp)
                if first and stamp >= anniversary(first):
                    rows.append({**calculate(invoice, None, base, first, int(time.time())), "customerId": customer, "code": referral["code"], "livemode": live})
                    continue
                payments = stripe_get(f"invoice_payments?invoice={invoice['id']}&status=paid&limit=100")
                charge = None
                if payments.get("has_more") is False and len(payments.get("data", [])) == 1:
                    payment = payments["data"][0]
                    pi = (payment.get("payment") or {}).get("payment_intent", "")
                    if payment.get("invoice") == invoice["id"] and payment.get("livemode") == live and payment.get("amount_paid") == invoice["amount_paid"] and re.fullmatch(r"pi_[A-Za-z0-9]+", str(pi)):
                        intent = stripe_get(f"payment_intents/{pi}?expand[]=latest_charge")
                        charge = intent.get("latest_charge") if isinstance(intent.get("latest_charge"), dict) else None
                row = calculate(invoice, charge, base, first, int(time.time()), prices)
            except ValueError as error:
                # API errors must block the entire refresh, not silently drop debt.
                if "unavailable" in str(error):
                    raise
                row = {"invoiceId": invoice["id"], "currency": invoice.get("currency", ""), "paidAt": stamp,
                    "commissionMinor": 0, "status": "review", "reason": str(error), "holdUntil": 0, "baseMinor": 0}
            rows.append({**row, "customerId": customer, "code": referral["code"], "livemode": live})
        with state_write() as state:
            current = next(r for r in state["referrals"] if r["customerId"] == customer and r["livemode"] == live)
            current.update({"firstPaidAt": first, "syncedAt": int(time.time()), "error": "", "syncUntil": 0, "basePriceIds": prices})
            state["invoices"] = [i for i in state["invoices"] if not (i["customerId"] == customer and i["livemode"] == live)] + rows
    except Exception:
        with state_write() as state:
            for row in state["referrals"]:
                if row["customerId"] == customer and row["livemode"] == live:
                    row["error"] = "Stripe refresh failed. Payout recording is blocked until a successful refresh."
                    row["syncUntil"] = 0
        raise


def bind_known_customers():
    live = mode()
    known = {(r["accountKey"], r["livemode"]) for r in read_state()["referrals"]}
    for email, user in (load_users() or {}).items():
        if isinstance(user, dict) and user.get("partner_code") and (identity(email), live) not in known:
            checkout_id = user.get("stripe_checkout_session_id", "")
            if not re.fullmatch(r"cs_[A-Za-z0-9_]+", str(checkout_id)):
                continue
            checkout = stripe_get(f"checkout/sessions/{checkout_id}")
            metadata = checkout.get("metadata") or {}
            if checkout.get("status") == "complete" and checkout.get("livemode") == live and metadata.get("user_email") == email and metadata.get("partner_code") == user["partner_code"]:
                bind_customer(email, checkout.get("customer"), user["partner_code"], user.get("terms_accepted_at", ""), live)


@partners_bp.after_app_request
def reconcile_signed_webhook(response):
    event = getattr(g, "partner_stripe_event", None)
    if not event or response.status_code >= 300 or event.get("account") or not isinstance(event.get("livemode"), bool):
        return response
    if event.get("type") not in {"checkout.session.completed", "invoice.paid", "invoice.payment_succeeded", "charge.refunded"}:
        return response
    try:
        if event["livemode"] != mode():
            return response
        obj = event["data"]["object"]
        customer = str(obj.get("customer") or "")
        if event["type"] == "checkout.session.completed":
            metadata = obj.get("metadata") or {}
            email = str(metadata.get("user_email") or "").strip().lower()
            user = (load_users() or {}).get(email) or {}
            if user.get("partner_code") and obj.get("id") == user.get("stripe_checkout_session_id") and metadata.get("partner_code") == user["partner_code"]:
                bind_customer(email, customer, user["partner_code"], user.get("terms_accepted_at", ""), mode())
        sync_customer(customer)
        return response
    except Exception:
        # Billing has already committed. A retry reconciles accounting even if
        # the billing handler correctly deduplicates the original event.
        current_app.logger.exception("Partner commission reconciliation failed")
        return current_app.response_class("", status=503)


def available(state, code, currency, live, now):
    earned = sum(i["commissionMinor"] for i in state["invoices"] if i["code"] == code and i["currency"] == currency and i["livemode"] == live and not needs_refund_refresh(i) and i["status"] in {"available", "pending"} and i["holdUntil"] <= now)
    paid = sum(p["amountMinor"] for p in state["payouts"] if p["code"] == code and p["currency"] == currency and p["livemode"] == live)
    return earned - paid


@partners_bp.route("/api/owner/partners", methods=["GET", "POST"])
def owner_partners():
    _, error = _require_owner()
    if error:
        return error
    try:
        bind_known_customers()
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                raise ValueError("Invalid request")
            op = body.get("op")
            if op == "sync":
                customer = body.get("customerId", "")
                if not re.fullmatch(r"cus_[A-Za-z0-9]+", str(customer)):
                    raise ValueError("Choose a referred customer")
                sync_customer(customer)
            else:
                with state_write() as state:
                    code = str(body.get("code", "")).strip().lower()
                    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,39}", code):
                        raise ValueError("Use a 3–40 character partner code")
                    if op == "create":
                        name, email = str(body.get("name", "")).strip(), str(body.get("email", "")).strip().lower()
                        if not name or len(name) > 120 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254 or body.get("accepted") is not True:
                            raise ValueError("Confirm the partner accepted the written terms and provide their name and email")
                        if any(p["code"] == code or identity(p["email"]) == identity(email) for p in state["partners"]):
                            raise ValueError("Partner code or email already exists")
                        state["partners"].append({"code": code, "name": name, "email": email, "active": True, "createdAt": int(time.time()), "terms": "30-percent-12-months-v1"})
                    elif op == "toggle":
                        partner = next((p for p in state["partners"] if p["code"] == code), None)
                        if not partner:
                            raise ValueError("Partner not found")
                        partner["active"] = body.get("active") is True
                    elif op == "record":
                        now, live = int(time.time()), mode()
                        currency, reference = str(body.get("currency", "")).lower(), str(body.get("reference", "")).strip()
                        referrals = [r for r in state["referrals"] if r["code"] == code and r["livemode"] == live]
                        if not referrals or any(r["error"] or now - r["syncedAt"] > 300 for r in referrals):
                            raise ValueError("Refresh every customer for this partner immediately before recording payment")
                        if any(i["code"] == code and i["livemode"] == live and i["status"] == "review" for i in state["invoices"]):
                            raise ValueError("Resolve invoice review holds before recording payment")
                        amount = available(state, code, currency, live, now)
                        if amount <= 0 or not reference or len(reference) > 120 or any(p["reference"] == reference for p in state["payouts"]):
                            raise ValueError("No payable balance, or payment reference is missing/duplicate")
                        if body.get("amountMinor") != amount:
                            raise ValueError("Balance changed. Review the current amount before recording payment")
                        state["payouts"].append({"code": code, "currency": currency, "amountMinor": amount, "reference": reference, "livemode": live, "recordedAt": now})
                    else:
                        raise ValueError("Unknown action")
        state = read_state()
        live, now = mode(), int(time.time())
        for key in ("referrals", "invoices", "payouts"):
            state[key] = [r for r in state[key] if r["livemode"] == live]
        state["livemode"] = live
        state["balances"] = [{"code": p["code"], "currency": currency, "amountMinor": available(state, p["code"], currency, live, now)}
            for p in state["partners"] for currency in sorted({i["currency"] for i in state["invoices"] if i["code"] == p["code"]} | {i["currency"] for i in state["payouts"] if i["code"] == p["code"]})]
        return jsonify(state), 200, {"Cache-Control": "no-store"}
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        current_app.logger.exception("Partner ledger operation failed")
        return jsonify({"error": "Partner ledger unavailable. No payout was recorded; retry after refreshing."}), 503

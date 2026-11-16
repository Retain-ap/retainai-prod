"""Durable subscription Checkout attempts; tax stays off until explicitly enabled.

Only the existing Checkout create/retrieve APIs are used. This module never
changes a subscription, customer, registration or remotely expires a session.
"""

import copy
import datetime as dt
import hashlib
import json
import os
from urllib.parse import urlsplit

from storage import DATA_ROOT
from value_receipt import _locked, _read, _write, workspace_generation

ATTEMPTS_FILE = os.path.join(DATA_ROOT, "billing_checkout_attempts.json")
FLAG = "RETAINAI_STRIPE_AUTOMATIC_TAX"
PAUSE_FLAG = "RETAINAI_STRIPE_CHECKOUT_PAUSED"
SCHEMA = 1
RETRY_WINDOW = dt.timedelta(hours=24)


class CheckoutPolicyError(RuntimeError):
    """A safe, non-sensitive explanation that may be shown to the account owner."""


class CheckoutPaused(CheckoutPolicyError):
    """Only new/reopened checkouts are paused; membership and portal stay open."""


def checkout_paused():
    # Invalid configuration fails closed without breaking authenticated status.
    return str(os.getenv(PAUSE_FLAG) or "").strip().lower() not in {"", "0", "false", "no", "off"}


def _check_pause():
    if checkout_paused():
        raise CheckoutPaused("New checkouts are temporarily paused. Please try again later; existing memberships and billing management remain available.")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def tax_enabled():
    raw = str(os.getenv(FLAG) or "").strip().lower()
    if raw in {"", "0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    raise CheckoutPolicyError("Billing configuration needs review. Please contact support before trying again.")


def _policy(price_id, enabled):
    return {"version": SCHEMA, "price_id": price_id, "automatic_tax": enabled}


def _key(email, generation, policy):
    # Preserve the old key/arguments for tax-off attempts. This also fails closed
    # (Stripe's parameter comparison) if an unrecorded legacy attempt differed.
    namespace = "retainai-subscription-checkout"
    if policy["automatic_tax"]:
        namespace += f":automatic-tax-v{SCHEMA}"
    return hashlib.sha256(f"{namespace}:{email}:{generation}".encode()).hexdigest()


def _digest(params):
    return hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _valid_attempt(email, value):
    if not isinstance(value, dict):
        raise CheckoutPolicyError("A previous checkout needs review. Please contact support; do not start another payment.")
    policy, params = value.get("policy"), value.get("params")
    generation = value.get("generation")
    if (value.get("schema") != SCHEMA or not isinstance(policy, dict)
            or policy.get("version") != SCHEMA
            or not isinstance(policy.get("price_id"), str) or not policy["price_id"]
            or type(policy.get("automatic_tax")) is not bool
            or type(generation) is not int or generation < 0
            or not isinstance(value.get("account_generation"), str)
            or not isinstance(params, dict)
            or (params.get("metadata") or {}).get("user_email") != email
            or value.get("params_sha256") != _digest(params)
            or value.get("idempotency_key") != _key(email, generation, policy)):
        raise CheckoutPolicyError("A previous checkout needs review. Please contact support; do not start another payment.")
    return copy.deepcopy(value)


def _load(email):
    with _locked(ATTEMPTS_FILE):
        record = _read(ATTEMPTS_FILE).get(email)
        return None if record is None else _valid_attempt(email, record)


def _claim(email, policy, params, generation, load_users, account_generation, replace_key=None):
    """Atomically choose one immutable request before contacting Stripe."""
    with _locked(ATTEMPTS_FILE):
        _check_pause()
        data = _read(ATTEMPTS_FILE)
        current = data.get(email)
        if current is not None:
            current = _valid_attempt(email, current)
            if replace_key is None or current["idempotency_key"] != replace_key:
                return current
            generation = max(generation, current["generation"] + 1)
        owner = (load_users() or {}).get(email)
        if not isinstance(owner, dict) or workspace_generation(owner) != account_generation:
            raise CheckoutPolicyError("This account is no longer available. Please contact support.")
        attempt = {
            "schema": SCHEMA, "policy": copy.deepcopy(policy),
            "generation": generation, "idempotency_key": _key(email, generation, policy),
            "params": copy.deepcopy(params), "created_at": _now().isoformat(),
            "session_id": "", "account_generation": workspace_generation(owner),
        }
        attempt["params"]["metadata"]["checkout_generation"] = str(generation)
        attempt["params"]["subscription_data"]["metadata"]["checkout_generation"] = str(generation)
        attempt["params_sha256"] = _digest(attempt["params"])
        data[email] = attempt
        _write(ATTEMPTS_FILE, data)
        return copy.deepcopy(attempt)


def _record_session(email, attempt, session_id, load_users):
    with _locked(ATTEMPTS_FILE):
        data = _read(ATTEMPTS_FILE)
        current = _valid_attempt(email, data.get(email))
        owner = (load_users() or {}).get(email)
        if (current["idempotency_key"] != attempt["idempotency_key"]
                or current["account_generation"] != attempt["account_generation"]
                or not isinstance(owner, dict)
                or workspace_generation(owner) != current["account_generation"]):
            raise CheckoutPolicyError("Checkout changed while it was opening. Please contact support before trying again.")
        if current.get("session_id") not in ("", session_id):
            raise CheckoutPolicyError("A previous checkout needs review. Please contact support.")
        current["session_id"] = session_id
        data[email] = current
        _write(ATTEMPTS_FILE, data)


def _check_pending(attempt, policy):
    if attempt["policy"] != policy:
        raise CheckoutPolicyError("A previous checkout uses different billing settings. Please contact support to resolve it before starting another payment.")
    try:
        created = dt.datetime.fromisoformat(attempt["created_at"])
        if created.tzinfo is None:
            raise ValueError
        age = _now() - created
    except (KeyError, TypeError, ValueError):
        raise CheckoutPolicyError("A previous checkout needs review. Please contact support.") from None
    if age < dt.timedelta(0) or age >= RETRY_WINDOW:
        raise CheckoutPolicyError("A previous checkout could not be confirmed. Please contact support before starting another payment.")


def _livemode(secret_key):
    if secret_key.startswith(("sk_live_", "rk_live_")):
        return True
    if secret_key.startswith(("sk_test_", "rk_test_")):
        return False
    raise CheckoutPolicyError("Billing configuration needs review. Please contact support.")


def _object_id(value):
    return value.get("id") if isinstance(value, dict) else value


def _check_customer_location(stripe, params, livemode):
    customer_id = params.get("customer")
    if not customer_id:
        return
    customer = stripe.Customer.retrieve(customer_id)
    if (not isinstance(customer, dict) or customer.get("id") != customer_id
            or customer.get("livemode") is not livemode):
        raise CheckoutPolicyError("Your billing account could not be confirmed. Please contact support.")
    shipping = (customer or {}).get("shipping") or {}
    if (customer or {}).get("deleted") or not isinstance(shipping, dict) or shipping.get("address"):
        raise CheckoutPolicyError("Your saved billing location needs review. Please contact support before paying so tax uses the correct address.")


def _check_session(session, email, params, livemode, expected_id=None, tax=None, require_url=False):
    if (not isinstance(session, dict) or not str(session.get("id") or "").startswith("cs_")
            or (expected_id and session.get("id") != expected_id)
            or session.get("livemode") is not livemode or session.get("mode") != "subscription"
            or (session.get("metadata") or {}).get("user_email") != email):
        raise CheckoutPolicyError("Your checkout could not be confirmed. Please contact support before starting another payment.")
    expected_customer = params.get("customer")
    if expected_customer and _object_id(session.get("customer")) != expected_customer:
        raise CheckoutPolicyError("Your checkout account could not be confirmed. Please contact support.")
    if not expected_customer:
        # Stripe creates the Customer on completion; null is normal while open.
        if str(session.get("customer_email") or "").strip().lower() != email:
            raise CheckoutPolicyError("Your checkout account could not be confirmed. Please contact support.")
    if tax is not None and (session.get("automatic_tax") or {}).get("enabled") is not tax:
        raise CheckoutPolicyError("Your checkout tax settings could not be confirmed. Please contact support.")
    if require_url:
        try:
            parsed = urlsplit(str(session.get("url") or ""))
            valid = (parsed.scheme == "https" and parsed.hostname == "checkout.stripe.com"
                     and not parsed.username and not parsed.password and parsed.port in (None, 443))
        except ValueError:
            valid = False
        if not valid:
            raise CheckoutPolicyError("Your checkout link could not be confirmed. Please contact support.")


def _save_billing_fields(email, original, changes, load_users, save_users, administratively_blocked):
    """Refresh after provider I/O; never write the earlier whole users snapshot."""
    latest = load_users() or {}
    current = latest.get(email)
    if not isinstance(current, dict) or workspace_generation(current) != workspace_generation(original):
        raise CheckoutPolicyError("This account is no longer available. Please contact support.")
    current.update(changes)
    if changes.get("billing_status") in {"active", "trialing"} and not administratively_blocked(current):
        current["status"] = "active"
    save_users(latest)


def create_or_reuse(*, email, user, cancel_url, trial_days, recovery, stripe,
                   secret_key, price_id, frontend_url, load_users, save_users,
                   complimentary_access_active, find_existing_subscription,
                   administratively_blocked, blocking_statuses):
    _check_pause()
    if complimentary_access_active(user):
        return {"state": "complimentary_access", "url": f"{frontend_url}/app", "subscriptionStatus": "complimentary"}
    if not secret_key or not price_id:
        raise RuntimeError("Billing is not configured.")
    livemode = _livemode(secret_key)
    price = stripe.Price.retrieve(price_id)
    if price.get("id") != price_id or price.get("livemode") is not livemode:
        raise CheckoutPolicyError("The billing plan could not be confirmed. Please contact support.")
    if not bool((price or {}).get("active", True)):
        raise RuntimeError("The configured RetainAI price is inactive.")
    if str(((price or {}).get("recurring") or {}).get("interval") or "").lower() != "month":
        raise RuntimeError("The configured RetainAI price must renew monthly.")

    users = load_users() or {}
    if not isinstance(users.get(email), dict):
        raise CheckoutPolicyError("This account is no longer available. Please contact support.")
    user = copy.deepcopy(users[email])
    original = copy.deepcopy(user)
    existing = find_existing_subscription(email, user)
    if existing is not None:
        _save_billing_fields(email, original, {key: user[key] for key in (
            "stripe_customer_id", "stripe_subscription_id", "billing_status", "stripe_duplicate_subscription_count"
        ) if key in user}, load_users, save_users, administratively_blocked)
        return {"state": "existing_subscription", "url": f"{frontend_url}/login?billing=already_active",
                "subscriptionStatus": str(existing.get("status") or "")}

    enabled = tax_enabled()
    if enabled and price.get("tax_behavior") != "exclusive":
        raise CheckoutPolicyError("The billing plan's tax settings need review. Please contact support.")
    policy = _policy(price_id, enabled)
    for _ in range(3):
        attempt = _load(email)
        if attempt and attempt["account_generation"] != workspace_generation(original):
            raise CheckoutPolicyError("A previous account checkout needs review. Please contact support.")
        previous_id = str((attempt.get("session_id") if attempt else user.get("stripe_checkout_session_id")) or "").strip()
        terminal = False
        if previous_id:
            # A retrieval failure is not evidence that an old payment vanished.
            previous = stripe.checkout.Session.retrieve(previous_id, expand=["subscription"])
            previous_params = attempt["params"] if attempt else {
                "customer": user["stripe_customer_id"]
            } if user.get("stripe_customer_id") else {"customer_email": email}
            _check_session(previous, email, previous_params, livemode, expected_id=previous_id)
            status = str(previous.get("status") or "")
            subscription = previous.get("subscription")
            subscription_status = str(subscription.get("status") or "") if isinstance(subscription, dict) else ""
            if subscription_status in blocking_statuses:
                if not str(subscription.get("id") or "").startswith("sub_"):
                    raise CheckoutPolicyError("Your subscription is still being confirmed. Please contact support before starting another payment.")
                changes = {"stripe_subscription_id": subscription["id"], "billing_status": subscription_status}
                if _object_id(previous.get("customer")):
                    changes["stripe_customer_id"] = _object_id(previous["customer"])
                _save_billing_fields(email, original, changes, load_users, save_users, administratively_blocked)
                return {"state": "existing_subscription", "url": f"{frontend_url}/login?billing=already_active",
                        "subscriptionStatus": subscription_status}
            if status == "open":
                actual_tax = bool((previous.get("automatic_tax") or {}).get("enabled"))
                if actual_tax != enabled or (attempt and attempt["policy"] != policy) or (enabled and not attempt):
                    raise CheckoutPolicyError("An open checkout uses different billing settings. Please contact support to resolve it before starting another payment.")
                if enabled:
                    _check_customer_location(stripe, attempt["params"], livemode)
                _check_session(previous, email, previous_params, livemode, tax=enabled, require_url=True)
                _check_pause()
                return {"state": "open_checkout", "url": previous.get("url")}
            if status not in {"expired", "complete"}:
                raise CheckoutPolicyError("Your previous checkout could not be confirmed. Please contact support.")
            if status == "complete" and (subscription_status not in {"canceled", "incomplete_expired"}
                                         or not str((subscription or {}).get("id") or "").startswith("sub_")):
                raise CheckoutPolicyError("Your completed checkout is still being confirmed. Please contact support before starting another payment.")
            terminal = True

        if attempt is None or terminal:
            generation = max(int(user.get("stripe_checkout_generation") or 0), (attempt or {}).get("generation", 0))
            if previous_id:
                generation += 1
            params = {
                # Preserve the deployed payment-method/API contract for this tax-only change.
                "payment_method_types": ["card"], "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": f"{frontend_url}/login?paid=1&session_id={{CHECKOUT_SESSION_ID}}",
                "cancel_url": cancel_url,
                "metadata": {"user_email": email, "recovery": "true" if recovery else "false", "checkout_generation": str(generation)},
                "subscription_data": {"metadata": {"user_email": email, "checkout_generation": str(generation)}},
            }
            if user.get("partner_code"):
                params["metadata"]["partner_code"] = user["partner_code"]
                params["subscription_data"]["metadata"]["partner_code"] = user["partner_code"]
            if user.get("stripe_customer_id"):
                params["customer"] = user["stripe_customer_id"]
            else:
                params["customer_email"] = email
            if int(trial_days or 0) > 0:
                params["subscription_data"]["trial_period_days"] = int(trial_days)
            if enabled:
                params["automatic_tax"] = {"enabled": True}
                if params.get("customer"):
                    params["billing_address_collection"] = "required"
                    params["customer_update"] = {"address": "auto"}
            attempt = _claim(email, policy, params, generation, load_users, workspace_generation(original),
                             replace_key=attempt["idempotency_key"] if attempt and terminal else None)
            if attempt.get("session_id"):
                continue  # another request already completed this exact attempt

        _check_pending(attempt, policy)
        owner = (load_users() or {}).get(email)
        if (not isinstance(owner, dict) or workspace_generation(owner) != attempt["account_generation"]
                or attempt["account_generation"] != workspace_generation(original)):
            raise CheckoutPolicyError("This account is no longer available. Please contact support.")
        if enabled:
            _check_customer_location(stripe, attempt["params"], livemode)
        _check_pause()
        checkout = stripe.checkout.Session.create(**copy.deepcopy(attempt["params"]), idempotency_key=attempt["idempotency_key"])
        _check_session(checkout, email, attempt["params"], livemode)
        _record_session(email, attempt, checkout["id"], load_users)
        _check_session(checkout, email, attempt["params"], livemode, tax=enabled, require_url=True)
        _save_billing_fields(email, original, {
            "stripe_checkout_session_id": checkout["id"], "stripe_checkout_generation": attempt["generation"],
            "stripe_checkout_created_at": _now().isoformat().replace("+00:00", "Z")
        }, load_users, save_users, administratively_blocked)
        return {"state": "new_checkout", "url": checkout["url"]}
    raise CheckoutPolicyError("Another checkout request is finishing. Please try again in a moment.")

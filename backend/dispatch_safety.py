"""Durable, conservative delivery claims for automatic email.

A claim is saved before calling the provider. A crash or ambiguous provider
failure leaves the attempt held for review; it must not cause an automatic
resend. This provides at-most-one provider attempt, not guaranteed delivery.
Receipts are partitioned by workspace for deletion. Event/run identifiers are
hashed; receipts contain timestamps and status, never recipients or bodies.
"""

import datetime
import fcntl
import hashlib
import json
import os
import uuid
from contextlib import contextmanager


class DeliveryHeld(RuntimeError):
    pass


@contextmanager
def exclusive(path, *, blocking=False):
    """Use the same .lock/flock convention as the existing evidence stores."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(f"{path}.lock", "a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Automatic delivery state is unreadable; no email was attempted.")
    return data


def write_state(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _digest(identity):
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def _receipt_state(path):
    data = read_state(path)
    if not data:
        return {"schema_version": 1, "workspaces": {}}
    if data.get("schema_version") != 1 or not isinstance(data.get("workspaces"), dict):
        raise ValueError("Automatic delivery receipt ownership is unknown; delivery is held for review.")
    return data


def held_reason(path, workspace, identity_prefix):
    with exclusive(path, blocking=True):
        bucket = _receipt_state(path)["workspaces"].get(str(workspace).strip().lower(), {})
        if not isinstance(bucket, dict):
            raise ValueError("Automatic delivery state is unreadable.")
        scope = _digest(identity_prefix)
        if any(item.get("scope") == scope and item.get("status") != "sent" for item in bucket.values()):
            return "Email delivery is held: an earlier attempt may have reached the provider. No retry was queued. Ask support to review provider delivery before any further attempt."
    return None


def dispatch_once(path, identity, send, *, is_eligible=None):
    """Return True for a new accepted send whose workspace still exists.

    False means already accepted, or its workspace became inactive / its claim
    was purged while in flight;
    callers must not recreate owner notifications for a purged claim.

    Provider rejection and transport ambiguity are both held because the
    existing mail adapter returns only a boolean, not proof of non-delivery.
    A pending claim survives process death and is never silently retried.
    """
    if len(identity) < 2 or not str(identity[1]).strip():
        raise ValueError("Automatic delivery workspace is required.")
    workspace = str(identity[1]).strip().lower()
    key = _digest(identity)
    claim_id = uuid.uuid4().hex
    with exclusive(path, blocking=True):
        receipts = _receipt_state(path)
        if is_eligible is not None and not is_eligible():
            raise DeliveryHeld("Automatic delivery stopped because the workspace is no longer active. No email was attempted.")
        bucket = receipts["workspaces"].setdefault(workspace, {})
        previous = bucket.get(key)
        if previous:
            if previous.get("status") == "sent":
                return False
            raise DeliveryHeld("Email delivery needs review: an earlier attempt may have reached the provider. Automatic resend is held to avoid a duplicate.")
        bucket[key] = {"status": "pending", "claimed_at": _stamp(), "claim_id": claim_id, "scope": _digest(identity[:4])}
        write_state(path, receipts)

    try:
        accepted = send() is True
    except Exception:
        accepted = False
    with exclusive(path, blocking=True):
        receipts = _receipt_state(path)
        previous = receipts["workspaces"].get(workspace, {}).get(key)
        # Account deletion may remove this claim while the provider is in
        # flight. Never recreate a purged workspace or overwrite another claim.
        retained_claim = bool(previous and previous.get("claim_id") == claim_id)
        if retained_claim:
            previous["status"] = "sent" if accepted else "unconfirmed"
            previous["finished_at"] = _stamp()
            write_state(path, receipts)
        # Account purge removes notifications before this journal. Recheck
        # access so callers cannot recreate notices after that earlier purge.
        still_eligible = is_eligible is None or is_eligible()
    if not accepted:
        raise DeliveryHeld("Email delivery could not be confirmed. Check the provider before retrying; automatic resend is held to avoid a duplicate.")
    return retained_claim and still_eligible

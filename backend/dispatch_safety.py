"""Durable, conservative delivery claims for automatic email.

A claim is saved before calling the provider. A crash or ambiguous provider
failure leaves the attempt held for review; it must not cause an automatic
resend. This provides at-most-one provider attempt, not guaranteed delivery.
Receipts contain only a hashed event key, timestamps and status, never bodies.
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


def dispatch_once(path, identity, send):
    """Return True for a new accepted send, False for an already-sent event.

    Provider rejection and transport ambiguity are both held because the
    existing mail adapter returns only a boolean, not proof of non-delivery.
    A pending claim survives process death and is never silently retried.
    """
    key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    with exclusive(path, blocking=True):
        receipts = read_state(path)
        previous = receipts.get(key)
        if previous:
            if previous.get("status") == "sent":
                return False
            raise DeliveryHeld("Email delivery needs review: an earlier attempt may have reached the provider. Automatic resend is held to avoid a duplicate.")
        receipts[key] = {"status": "pending", "claimed_at": _stamp()}
        write_state(path, receipts)

    try:
        accepted = bool(send())
    except Exception:
        accepted = False
    with exclusive(path, blocking=True):
        receipts = read_state(path)
        receipts[key]["status"] = "sent" if accepted else "unconfirmed"
        receipts[key]["finished_at"] = _stamp()
        write_state(path, receipts)
    if not accepted:
        raise DeliveryHeld("Email delivery could not be confirmed. Check the provider before retrying; automatic resend is held to avoid a duplicate.")
    return True

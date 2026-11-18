"""Read-only evidence of the existing scheduler's Linux process lock.

Never acquire a probe lock: even a momentary acquisition can make scheduler
bootstrap mistake the health request for another scheduler. /proc/locks is a
kernel snapshot of current ownership, so stale PID text in the file is ignored.
See https://man7.org/linux/man-pages/man5/proc_locks.5.html.
"""

import os
import sys


MAX_LOCK_BYTES = 1024 * 1024


def _exclusive_flock_present(text, identity):
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) > 1 and fields[1] == "->":
            continue  # A waiter does not own its requested lock.
        if len(fields) != 8:
            return None
        if fields[1:4] != ["FLOCK", "ADVISORY", "WRITE"]:
            continue
        try:
            major, minor, inode = fields[5].split(":")
            candidate = (int(major, 16), int(minor, 16), int(inode))
        except (ValueError, TypeError):
            return None
        if candidate == identity and fields[6:] == ["0", "EOF"]:
            return True
    return False


def _file_identity(path):
    info = os.stat(path)
    return os.major(info.st_dev), os.minor(info.st_dev), info.st_ino


def scheduler_lock_held(lock_path):
    """True/False for observed Linux ownership, None when it is unavailable.

    Does not open the scheduler file, read its PID, acquire locks, create
    files, or start jobs. File identity is rechecked to reject replacement.
    """
    if not sys.platform.startswith("linux"):
        return None
    try:
        identity = _file_identity(lock_path)
    except FileNotFoundError:
        return False
    except OSError:
        return None
    try:
        with open("/proc/locks", encoding="ascii") as handle:
            text = handle.read(MAX_LOCK_BYTES + 1)
        if len(text) > MAX_LOCK_BYTES or _file_identity(lock_path) != identity:
            return None
        return _exclusive_flock_present(text, identity)
    except (OSError, UnicodeError):
        return None


def scheduler_status(enabled, local_running, owner_present, bootstrap_done):
    """Describe availability evidence without claiming a job was delivered."""
    running = bool(enabled and (local_running or owner_present is True))
    if not enabled:
        status = "scheduler_disabled"
    elif local_running:
        status = "operational"
    elif owner_present is True:
        status = "owned_by_another_worker"
    elif owner_present is None:
        status = "scheduler_status_unknown"
    else:
        status = "scheduler_offline" if bootstrap_done else "scheduler_waiting"
    return {
        "ok": running, "status": status, "scheduler_enabled": bool(enabled),
        "scheduler_running": running, "local_scheduler_running": bool(local_running),
        "scheduler_owner_present": (bool(local_running) or owner_present) if enabled else False,
        "evaluation_interval_minutes": 10,
    }

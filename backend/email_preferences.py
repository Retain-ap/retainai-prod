"""Owner email preferences, independent of browser notification settings."""

STATE_FILE = "email_preferences.json"


def lead_reminders_enabled_record(record):
    if record is None:
        return True
    if not isinstance(record, dict):
        raise ValueError("Email preference state is invalid.")
    value = record.get("lead_reminder_emails", True)
    if not isinstance(value, bool):
        raise ValueError("Email preference state is invalid.")
    return value


def lead_reminders_enabled(path, workspace):
    from value_receipt import _locked, _read
    with _locked(path):
        return lead_reminders_enabled_record(_read(path).get(workspace))


def get_preferences(path, authorize):
    from value_receipt import _locked, _read
    with _locked(path):
        workspace = authorize()  # Fresh owner/access check inside the lock.
        return {"lead_reminder_emails": lead_reminders_enabled_record(_read(path).get(workspace))}


def set_preferences(path, reminder_state_path, authorize, enabled):
    from value_receipt import _locked, _read, _write
    if not isinstance(enabled, bool):
        raise ValueError("A boolean preference is required.")
    # Same order as the sender: reminder claim -> preferences. A completed
    # disable is observed before any later provider attempt. An already
    # in-flight send may finish before this save can acquire the reminder lock.
    with _locked(reminder_state_path), _locked(path):
        workspace = authorize()
        state = _read(path)
        existing = state.get(workspace)
        lead_reminders_enabled_record(existing)  # Fail closed on damaged state.
        state[workspace] = {**(existing or {}), "lead_reminder_emails": enabled}
        _write(path, state)
        return {"lead_reminder_emails": enabled}

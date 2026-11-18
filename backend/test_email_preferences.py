"""Owner preference tests using synthetic accounts and no live mail."""
import ast
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import email_preferences as preferences
import lead_reminders


def definitions(names, namespace):
    source = ast.parse(Path(__file__).with_name("app.py").read_text(encoding="utf-8"))
    selected = []
    for node in source.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            selected.append(node)
    assert len(selected) == len(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), "app.py", "exec"), namespace)


class PreferencePolicyTests(unittest.TestCase):
    def setUp(self):
        self.actor = "owner@example.test"
        self.users = {
            self.actor: {"status": "active", "role": "owner"},
            "other@example.test": {"status": "active", "role": "owner"},
            "member@example.test": {"status": "active", "role": "member", "org_id": self.actor},
        }
        self.request = types.SimpleNamespace(method="GET", get_json=lambda **_: None)
        self.ns = {
            "os": os, "DATA_ROOT": "unused-test-path", "request": self.request,
            "jsonify": lambda value: value, "_session_email": lambda: self.actor,
            "_norm_email": lambda value: str(value or "").strip().lower(),
            "load_users": lambda: self.users,
            "_account_has_access": lambda user: isinstance(user, dict) and user.get("status") == "active",
        }
        definitions({"_resolve_org_and_role", "_owner_email_preference_workspace", "owner_email_preferences"}, self.ns)

    def test_existing_workspace_defaults_to_enabled_and_false_is_explicit(self):
        self.assertTrue(preferences.lead_reminders_enabled_record(None))
        self.assertTrue(preferences.lead_reminders_enabled_record({}))
        self.assertFalse(preferences.lead_reminders_enabled_record({"lead_reminder_emails": False}))
        for record in [[], {"lead_reminder_emails": "false"}, {"lead_reminder_emails": None}]:
            with self.assertRaises(ValueError):
                preferences.lead_reminders_enabled_record(record)

    def test_only_current_active_owner_is_authorized(self):
        self.assertEqual(self.ns["_owner_email_preference_workspace"](), self.actor)
        for actor in ["member@example.test", "missing@example.test"]:
            self.actor = actor
            with self.assertRaises(PermissionError):
                self.ns["_owner_email_preference_workspace"]()
        self.actor = "owner@example.test"
        self.users[self.actor]["status"] = "suspended"
        with self.assertRaises(PermissionError):
            self.ns["_owner_email_preference_workspace"]()

    def test_endpoint_rejects_identity_fields_and_nonboolean_values(self):
        self.request.method = "POST"
        for body in [{"lead_reminder_emails": False, "owner_email": "other@example.test"}, {"lead_reminder_emails": "false"}, {}]:
            self.request.get_json = lambda **_: body
            with patch.object(preferences, "set_preferences") as writer:
                self.assertEqual(self.ns["owner_email_preferences"]()[1], 400)
                writer.assert_not_called()

    def test_endpoint_uses_fresh_session_identity_and_truthful_storage_errors(self):
        def get(_path, authorize):
            return {"lead_reminder_emails": authorize() == "other@example.test"}
        with patch.object(preferences, "get_preferences", side_effect=get):
            self.assertFalse(self.ns["owner_email_preferences"]()[0]["preferences"]["lead_reminder_emails"])
            self.actor = "other@example.test"
            self.assertTrue(self.ns["owner_email_preferences"]()[0]["preferences"]["lead_reminder_emails"])
            self.actor = "member@example.test"
            self.assertEqual(self.ns["owner_email_preferences"]()[1], 403)
        with patch.object(preferences, "get_preferences", side_effect=RuntimeError("synthetic damaged store")):
            response, status = self.ns["owner_email_preferences"]()
            self.assertEqual(status, 503)
            self.assertNotIn("synthetic", json.dumps(response))

    def test_valid_save_uses_authorized_owner_and_returns_confirmed_value(self):
        self.request.method = "POST"
        self.request.get_json = lambda **_: {"lead_reminder_emails": False}
        def save(path, claim_path, authorize, enabled):
            self.assertTrue(path.endswith(preferences.STATE_FILE))
            self.assertTrue(claim_path.endswith(lead_reminders.STATE_FILE))
            self.assertEqual(authorize(), "owner@example.test")
            self.assertIs(enabled, False)
            return {"lead_reminder_emails": False}
        with patch.object(preferences, "set_preferences", side_effect=save):
            result, status = self.ns["owner_email_preferences"]()
        self.assertEqual(status, 200)
        self.assertEqual(result, {"ok": True, "preferences": {"lead_reminder_emails": False}})

    def test_scheduler_rechecks_preference_before_eligibility_or_send(self):
        self.ns.update({"app": types.SimpleNamespace(logger=Mock()), "datetime": dt,
                        "load_user_profile": Mock(return_value={}), "in_quiet_hours": Mock(return_value=False),
                        "load_user_leads": Mock(return_value=[]), "BUSINESS_TYPE_INTERVALS": {},
                        "send_warning_summary_email": Mock(return_value=True)})
        definitions({"check_for_lead_reminders"}, self.ns)
        prepare_results = []
        def attempt(_path, _owner, *, now, prepare, send):
            prepare_results.append(prepare(dt.datetime(2026, 11, 18, 12, tzinfo=dt.timezone.utc)))
        with patch.object(lead_reminders, "send_if_due", side_effect=attempt), patch.object(preferences, "lead_reminders_enabled", return_value=False):
            self.ns["check_for_lead_reminders"]()
        self.assertTrue(prepare_results)
        self.assertTrue(all(result is None for result in prepare_results))
        self.ns["load_user_profile"].assert_not_called()
        self.ns["send_warning_summary_email"].assert_not_called()


@unittest.skipUnless(os.name == "posix", "Uses production POSIX locking; run in Linux CI")
class PreferencePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, preferences.STATE_FILE)
        self.claim_path = os.path.join(self.temp.name, lead_reminders.STATE_FILE)
        self.owner = "owner@example.test"
        self.now = dt.datetime(2026, 11, 18, 12, tzinfo=dt.timezone.utc)
        self.sender = Mock(return_value=True)

    def prepare(self, _now):
        if not preferences.lead_reminders_enabled(self.path, self.owner):
            return None
        return ([{"id": "lead", "createdAt": "2026-10-01T12:00:00Z"}], 14, ZoneInfo("UTC"))

    def send(self):
        return lead_reminders.send_if_due(self.claim_path, self.owner, now=self.now, prepare=self.prepare, send=self.sender)

    def test_disabled_survives_reload_and_isolated_from_other_workspace(self):
        self.assertTrue(preferences.lead_reminders_enabled(self.path, self.owner))
        self.assertFalse(Path(self.path).exists())
        preferences.set_preferences(self.path, self.claim_path, lambda: self.owner, False)
        self.assertFalse(self.send())
        self.sender.assert_not_called()
        self.assertFalse(Path(self.claim_path).exists())
        self.assertTrue(preferences.lead_reminders_enabled(self.path, "other@example.test"))

    def test_reenable_preserves_existing_claim_cooldown(self):
        self.assertTrue(self.send())
        before = Path(self.claim_path).read_bytes()
        for enabled in [False, True]:
            preferences.set_preferences(self.path, self.claim_path, lambda: self.owner, enabled)
        self.assertEqual(Path(self.claim_path).read_bytes(), before)
        self.assertFalse(self.send())
        self.sender.assert_called_once()

    def test_save_waits_for_existing_send_and_all_later_attempts_observe_disable(self):
        entered, release, saved = (threading.Event() for _ in range(3))
        def provider(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return True
        self.sender.side_effect = provider
        send_thread = threading.Thread(target=self.send)
        def disable():
            preferences.set_preferences(self.path, self.claim_path, lambda: self.owner, False)
            saved.set()
        disable_thread = threading.Thread(target=disable)
        send_thread.start()
        try:
            self.assertTrue(entered.wait(5))
            disable_thread.start()
            self.assertFalse(saved.wait(0.05))
        finally:
            release.set()
            send_thread.join(5)
            if disable_thread.ident:
                disable_thread.join(5)
        self.assertTrue(saved.is_set())
        self.now += dt.timedelta(days=8)
        self.assertFalse(self.send())
        self.sender.assert_called_once()

    def test_deleted_owner_cannot_recreate_preferences_and_file_is_purged(self):
        def removed():
            raise PermissionError("Deleted")
        with self.assertRaises(PermissionError):
            preferences.set_preferences(self.path, self.claim_path, removed, False)
        self.assertFalse(Path(self.path).exists())
        source = ast.parse(Path(__file__).with_name("app_account.py").read_text())
        files = next(ast.literal_eval(node.value) for node in source.body if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "_WORKSPACE_JSON_FILES" for target in node.targets))
        self.assertIn(preferences.STATE_FILE, files)

    def test_damaged_state_never_enables_sending_or_overwrites_preferences(self):
        from value_receipt import EvidenceStoreError
        Path(self.path).write_text("broken")
        with self.assertRaises(EvidenceStoreError):
            self.send()
        self.sender.assert_not_called()
        with self.assertRaises(EvidenceStoreError):
            preferences.set_preferences(self.path, self.claim_path, lambda: self.owner, True)
        self.assertEqual(Path(self.path).read_text(), "broken")


if __name__ == "__main__":
    unittest.main()

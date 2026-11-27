"""No-provider tests using real OS locks, receipts, and selected app functions.

Extracting the function definitions avoids importing the production app or its
environment/provider clients. Their executed code is the actual app source.
Run on Linux (the production platform): python3 -m unittest test_dispatch_safety.
"""
import ast
import copy
import datetime
import functools
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import automation_state
try:
    import dispatch_safety as delivery
except ModuleNotFoundError as error:
    if error.name != "fcntl":
        raise
    delivery = None


def _hold_lock(path, ready, release):
    with delivery.exclusive(path) as acquired:
        ready.put(acquired)
        release.wait(5)


def _definitions(names, namespace, filename="app.py"):
    parsed = ast.parse(Path(__file__).with_name(filename).read_text(encoding="utf-8"))
    selected = []
    for node in parsed.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            selected.append(node)
    assert len(selected) == len(names), names
    tree = ast.Module(body=selected, type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), "app.py", "exec"), namespace)


@unittest.skipIf(delivery is None, "Requires production POSIX file locks")
class DispatchReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "receipts.json")

    def test_os_lock_excludes_another_process_without_waiting(self):
        context = multiprocessing.get_context("fork")
        ready, release = context.Queue(), context.Event()
        process = context.Process(target=_hold_lock, args=(self.path, ready, release))
        process.start()
        try:
            self.assertTrue(ready.get(timeout=5))
            with delivery.exclusive(self.path) as acquired:
                self.assertFalse(acquired)
        finally:
            release.set()
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join()
        self.assertEqual(process.exitcode, 0)
        with delivery.exclusive(self.path) as acquired:
            self.assertTrue(acquired)

    def test_accepted_send_is_not_repeated_and_receipt_has_no_recipient_or_body(self):
        sender = Mock(return_value=True)
        identity = ["automation", "owner@example.com", "flow", "lead", 0]
        self.assertTrue(delivery.dispatch_once(self.path, identity, sender))
        self.assertFalse(delivery.dispatch_once(self.path, identity, sender))
        sender.assert_called_once()
        raw = Path(self.path).read_text()
        self.assertNotIn('"lead"', raw)
        self.assertEqual(next(iter(json.loads(raw)["workspaces"]["owner@example.com"].values()))["status"], "sent")

    def test_timeout_and_false_result_are_held_after_restart(self):
        for identity, sender in [(["timeout", "owner@example.com"], Mock(side_effect=TimeoutError)), (["false", "owner@example.com"], Mock(return_value=False))]:
            with self.assertRaises(delivery.DeliveryHeld):
                delivery.dispatch_once(self.path, identity, sender)
            with self.assertRaisesRegex(delivery.DeliveryHeld, "needs review"):
                delivery.dispatch_once(self.path, identity, sender)
            sender.assert_called_once()

    def test_claim_must_persist_before_provider_and_failed_completion_stays_pending(self):
        sender = Mock(return_value=True)
        with patch.object(delivery, "write_state", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                delivery.dispatch_once(self.path, ["before", "owner@example.com"], sender)
        sender.assert_not_called()
        real_write = delivery.write_state
        writes = []
        def fail_second(path, data):
            writes.append(True)
            if len(writes) == 2:
                raise OSError("completion write failed")
            real_write(path, data)
        with patch.object(delivery, "write_state", side_effect=fail_second):
            with self.assertRaises(OSError):
                delivery.dispatch_once(self.path, ["after", "owner@example.com"], sender)
        with self.assertRaises(delivery.DeliveryHeld):
            delivery.dispatch_once(self.path, ["after", "owner@example.com"], sender)
        sender.assert_called_once()

    def test_corrupt_journal_fails_closed(self):
        Path(self.path).write_text("invalid json")
        sender = Mock()
        with self.assertRaises(ValueError):
            delivery.dispatch_once(self.path, ["event", "owner@example.com"], sender)
        sender.assert_not_called()

    def test_purge_during_provider_call_never_resurrects_claim(self):
        def send():
            with delivery.exclusive(self.path, blocking=True):
                data = delivery.read_state(self.path)
                data["workspaces"].pop("owner@example.com")
                delivery.write_state(self.path, data)
            return True
        self.assertFalse(delivery.dispatch_once(self.path, ["event", "owner@example.com"], send))
        self.assertNotIn("owner@example.com", delivery.read_state(self.path)["workspaces"])

    def test_inactive_workspace_cannot_recreate_purged_receipts(self):
        sender = Mock(return_value=True)
        with self.assertRaises(delivery.DeliveryHeld):
            delivery.dispatch_once(self.path, ["event", "owner@example.com"], sender, is_eligible=lambda: False)
        sender.assert_not_called()
        self.assertFalse(Path(self.path).exists())

    def test_account_deletion_after_acceptance_suppresses_new_owner_notices(self):
        eligible = Mock(side_effect=[True, False])
        sender = Mock(return_value=True)
        self.assertFalse(delivery.dispatch_once(self.path, ["event", "owner@example.com"], sender, is_eligible=eligible))
        sender.assert_called_once()
        self.assertEqual(next(iter(delivery.read_state(self.path)["workspaces"]["owner@example.com"].values()))["status"], "sent")

    def test_same_event_ids_are_isolated_per_workspace(self):
        sender = Mock(return_value=True)
        for owner in ["a@example.com", "b@example.com"]:
            delivery.dispatch_once(self.path, ["automation", owner, "flow", "lead", 0], sender)
        self.assertEqual(sender.call_count, 2)
        self.assertEqual(set(delivery.read_state(self.path)["workspaces"]), {"a@example.com", "b@example.com"})

    def test_legacy_unowned_receipts_fail_closed(self):
        delivery.write_state(self.path, {"oldhash": {"status": "sent"}})
        sender = Mock()
        with self.assertRaisesRegex(ValueError, "ownership"):
            delivery.dispatch_once(self.path, ["event", "owner@example.com"], sender)
        sender.assert_not_called()

    def test_truthy_unconfirmed_provider_result_is_held(self):
        with self.assertRaises(delivery.DeliveryHeld):
            delivery.dispatch_once(self.path, ["event", "owner@example.com"], lambda: "not-confirmed")

    def test_account_purge_removes_only_its_receipts_and_scoped_progress(self):
        source = ast.parse(Path(__file__).with_name("app_account.py").read_text())
        files = next(ast.literal_eval(node.value) for node in source.body
                     if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "_WORKSPACE_JSON_FILES" for target in node.targets))
        self.assertIn("automatic_email_dispatch.json", files)
        namespace = {"os": os, "json": json, "uuid4": uuid4, "DATA_ROOT": self.temp.name,
                     "_WORKSPACE_JSON_FILES": files, "_norm": lambda value: str(value or "").strip().lower(),
                     "_file_lock": lambda path: delivery.exclusive(path, blocking=True)}
        _definitions({"_purge_workspace_json", "_scrub_file", "_atomic_json"}, namespace, "app_account.py")
        receipts = os.path.join(self.temp.name, "automatic_email_dispatch.json")
        state_path = os.path.join(self.temp.name, "automations_state.json")
        state = automation_state.scoped_state({}, {"users": {}})
        for owner in ["a@example.com", "b@example.com"]:
            delivery.dispatch_once(receipts, ["automation", owner, "same-flow", "same-lead", 0], lambda: True)
            automation_state.workspace_state(state, owner)["same-flow"] = {"same-lead": {"step": 1}}
        delivery.write_state(state_path, state)
        namespace["_purge_workspace_json"]("a@example.com")
        self.assertEqual(set(delivery.read_state(receipts)["workspaces"]), {"b@example.com"})
        self.assertEqual(set(delivery.read_state(state_path)["workspaces"]), {"b@example.com"})


@unittest.skipIf(delivery is None, "Requires production POSIX file locks")
class AutomaticEmailIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime.datetime(2026, 11, 18, 15, tzinfo=datetime.timezone.utc)
        self.users = {"a@example.com": {"status": "active"}, "b@example.com": {"status": "active"}}
        self.appointments = {}
        self.flows = {"users": {owner: [{"id": owner[0] + "-flow", "enabled": True,
            "steps": [{"type": "send_email", "subject": "Hello", "html": "Hello"}],
            "caps": {"per_lead_per_day": 1, "respect_quiet_hours": False}}] for owner in self.users}}
        self.leads = {owner: [{"id": "lead", "owner": owner, "email": owner[0] + "-customer@example.com"}] for owner in self.users}
        self.sent = Mock(return_value=True)
        self.state = os.path.join(self.temp.name, "state.json")
        self.receipts = os.path.join(self.temp.name, "receipts.json")
        self.ns = {
            "Dict": dict, "Any": object, "Optional": __import__("typing").Optional,
            "datetime": datetime, "_td": datetime.timedelta, "uuid4": uuid4, "functools": functools,
            "dispatch_safety": delivery, "automation_state": automation_state, "app": types.SimpleNamespace(logger=Mock()),
            "FILE_STATE": self.state, "FILE_EMAIL_DISPATCH": self.receipts, "FILE_AUTOMATIONS": "flows",
            "now_utc": lambda: self.now, "ensure_files": lambda: None,
            "read_json": lambda *args: copy.deepcopy(self.flows),
            "load_state": lambda: automation_state.scoped_state(delivery.read_state(self.state), self.flows),
            "save_state": lambda value: delivery.write_state(self.state, value),
            "load_leads": lambda: copy.deepcopy(self.leads),
            "load_users": lambda: copy.deepcopy(self.users),
            "_account_has_access": lambda user: user.get("status") == "active",
            "load_appointments": lambda: copy.deepcopy(self.appointments),
            "load_user_profile": lambda owner: {"business_name": "Example"},
            "_workspace_sender_details": lambda user, fallback="": {"address": "1 Main St, Toronto ON", "contact": fallback},
            "create_notification": Mock(),
            "trigger_met": lambda *args: True, "should_auto_stop": lambda *args: False,
            "render_text": lambda text, *args: text, "contains_blockers": lambda text: False,
            "in_quiet_hours": lambda *args: False, "_email_unsubscribe_url": lambda *args: "",
            "send_email_sendgrid_auto": self.sent, "record_followup": Mock(), "add_notification": Mock(),
            "CHANNEL_EMAIL": "email", "CHANNEL_WHATSAPP": "whatsapp",
            "user_from_request": lambda: "a@example.com", "jsonify": lambda result: result,
            "load_user_flows": lambda owner: copy.deepcopy(self.flows["users"].get(owner, [])),
            "save_user_flows": lambda owner, flows: self.flows["users"].__setitem__(owner, flows),
        }
        _definitions({"engine_tick", "_engine_tick_locked", "automations_run_once_route", "get_run", "advance",
                      "automation_event", "execute_step", "can_send", "mark_sent", "_record_automation_action",
                      "retry_automation_run", "delete_flow_route", "_automation_history_for_user"}, self.ns)

    def test_manual_run_only_dispatches_callers_workspace(self):
        result, status = self.ns["automations_run_once_route"]()
        self.assertEqual((result["ok"], status), (True, 200))
        self.assertEqual(self.sent.call_count, 1)
        self.assertEqual(self.sent.call_args.args[0], "a-customer@example.com")
        self.assertEqual(set(delivery.read_state(self.state)["workspaces"]["a@example.com"]), {"a-flow"})
        self.ns["add_notification"].assert_not_called()

    def test_concurrent_scheduler_and_manual_run_dispatch_once(self):
        entered, finish = threading.Event(), threading.Event()
        def send(*args, **kwargs):
            entered.set()
            self.assertTrue(finish.wait(5))
            return True
        self.sent.side_effect = send
        results = []
        thread = threading.Thread(target=lambda: results.append(self.ns["engine_tick"]("a@example.com")))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            response, status = self.ns["automations_run_once_route"]()
            self.assertEqual(status, 409)
            self.assertTrue(response["in_progress"])
        finally:
            finish.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(results[0]["ok"])
        self.sent.assert_called_once()

    def test_provider_ambiguity_survives_run_retries_and_is_visible_in_history(self):
        self.sent.side_effect = TimeoutError("provider timed out")
        for _ in range(2):
            self.ns["engine_tick"]("a@example.com")
        self.sent.assert_called_once()
        run = delivery.read_state(self.state)["workspaces"]["a@example.com"]["a-flow"]["lead"]
        self.assertEqual(run["step"], 0)
        self.assertIn("review", run["error"])
        self.assertTrue(any(event["type"] == "failed" for event in run["events"]))

    def test_state_save_failure_reports_failure_and_successful_delivery_is_recovered_without_resend(self):
        real_save = self.ns["save_state"]
        writes = []
        def fail_completion(value):
            writes.append(True)
            if len(writes) > 1:
                raise OSError("disk error")
            real_save(value)
        self.ns["save_state"] = fail_completion
        result, status = self.ns["automations_run_once_route"]()
        self.assertFalse(result["ok"])
        self.assertEqual(status, 503)
        self.ns["save_state"] = real_save
        self.assertTrue(self.ns["engine_tick"]("a@example.com")["ok"])
        self.sent.assert_called_once()
        self.assertEqual(delivery.read_state(self.state)["workspaces"]["a@example.com"]["a-flow"]["lead"]["step"], 1)

    def test_corrupt_automation_state_never_starts_fresh_sends(self):
        Path(self.state).write_text("{")
        self.assertFalse(self.ns["engine_tick"]()["ok"])
        self.sent.assert_not_called()

    def _appointment_job(self):
        fixed_now = self.now
        class Clock(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now if tz else fixed_now.replace(tzinfo=None)
        def parse(value, zone):
            parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo(zone))
        self.ns.update({
            "datetime": types.SimpleNamespace(datetime=Clock, timezone=datetime.timezone, timedelta=datetime.timedelta),
            "_account_has_access": lambda user: user.get("status") == "active",
            "_workspace_appointment_timezone": lambda *args: "America/Toronto",
            "_parse_appointment_datetime": parse,
            "send_post_appointment_update_email": self.sent, "log_notification": Mock(),
            "save_appointments": Mock(side_effect=AssertionError("Never overwrite a calendar snapshot")),
        })
        _definitions({"send_post_appointment_update_prompts"}, self.ns)
        return self.ns["send_post_appointment_update_prompts"]

    def test_appointment_eligibility_and_local_timezone_no_snapshot_write(self):
        self.users["b@example.com"]["status"] = "suspended"
        recent = {"appointment_time": "2026-11-18T08:00:00", "status": "completed"}
        self.appointments = {"a@example.com": [
            {**recent, "id": "recent"}, {**recent, "id": "cancelled", "status": "cancelled"},
            {**recent, "id": "no-show", "status": "no_show"},
            {**recent, "id": "historical", "appointment_time": "2026-05-22T08:00:00"},
            {**recent, "id": "future", "appointment_time": "2026-11-18T12:00:00"},
            {**recent, "id": "legacy-sent", "post_appt_update_sent": True}],
            "b@example.com": [{**recent, "id": "inactive"}]}
        job = self._appointment_job()
        def send(**kwargs):
            self.appointments["a@example.com"].append({**recent, "id": "new-edit", "status": "cancelled"})
            return True
        self.sent.side_effect = send
        job(); job()
        self.sent.assert_called_once()
        self.assertEqual(self.sent.call_args.kwargs["appointment_time"], recent["appointment_time"])
        self.assertTrue(any(row["id"] == "new-edit" for row in self.appointments["a@example.com"]))
        self.ns["save_appointments"].assert_not_called()
        self.ns["log_notification"].assert_not_called()

    def test_failed_appointment_provider_is_held_without_success_notification(self):
        self.appointments = {"a@example.com": [{"id": "recent", "appointment_time": "2026-11-18T08:00:00", "status": "completed"}]}
        self.sent.return_value = False
        job = self._appointment_job()
        job(); job()
        self.sent.assert_called_once()
        self.ns["log_notification"].assert_not_called()
        self.assertEqual(next(iter(delivery.read_state(self.receipts)["workspaces"]["a@example.com"].values()))["status"], "unconfirmed")

    def test_colliding_flow_and_lead_ids_remain_independent_and_delete_is_scoped(self):
        self.flows["users"]["b@example.com"][0]["id"] = "a-flow"
        self.assertTrue(self.ns["engine_tick"]()["ok"])
        self.assertEqual(self.sent.call_count, 2)
        state = delivery.read_state(self.state)
        self.assertEqual(state["workspaces"]["a@example.com"]["a-flow"]["lead"]["step"], 1)
        self.assertEqual(state["workspaces"]["b@example.com"]["a-flow"]["lead"]["step"], 1)
        rows = self.ns["_automation_history_for_user"]("a@example.com")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("b-customer@example.com", json.dumps(rows))
        self.ns["delete_flow_route"]("a-flow")
        state = delivery.read_state(self.state)
        self.assertNotIn("a-flow", state["workspaces"]["a@example.com"])
        self.assertIn("a-flow", state["workspaces"]["b@example.com"])
        response, status = self.ns["delete_flow_route"]("a-flow")
        self.assertEqual(status, 404)
        self.assertIn("a-flow", delivery.read_state(self.state)["workspaces"]["b@example.com"])

    def test_held_retry_does_not_clear_error_or_claim_queued(self):
        self.sent.return_value = False
        self.ns["engine_tick"]("a@example.com")
        before = Path(self.state).read_bytes()
        response, status = self.ns["retry_automation_run"]("a-flow", "lead")
        self.assertEqual(status, 409)
        self.assertTrue(response["delivery_held"])
        self.assertIn("No retry was queued", response["error"])
        self.assertEqual(Path(self.state).read_bytes(), before)
        self.sent.assert_called_once()

    def test_legacy_unique_completion_preserved_and_ambiguous_flows_quarantined(self):
        self.flows["users"]["b@example.com"][0]["id"] = "a-flow"
        self.flows["users"]["b@example.com"].append({"id": "safe-flow", "enabled": True, "steps": [{"type": "send_email"}], "caps": {"respect_quiet_hours": False}})
        delivery.write_state(self.state, {"a-flow": {"lead": {"step": 0, "events": [{"html": "private-other-tenant"}]}}, "orphan": {"old": {"done": True}}})
        self.assertTrue(self.ns["engine_tick"]()["ok"])
        self.sent.assert_called_once()
        self.assertEqual(self.sent.call_args.args[0], "b-customer@example.com")
        rows = self.ns["_automation_history_for_user"]("a@example.com")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["delivery_held"])
        self.assertNotIn("private-other-tenant", json.dumps(rows))
        self.assertIn("orphan", delivery.read_state(self.state)["legacy_unresolved"])

    def test_unique_legacy_done_run_is_not_resent(self):
        delivery.write_state(self.state, {"a-flow": {"lead": {"step": 1, "done": True}}})
        self.assertTrue(self.ns["engine_tick"]("a@example.com")["ok"])
        self.sent.assert_not_called()
        self.assertTrue(delivery.read_state(self.state)["workspaces"]["a@example.com"]["a-flow"]["lead"]["done"])

    def test_purge_waits_for_engine_save_then_removes_workspace_without_resurrection(self):
        entered, release, purging, purged = (threading.Event() for _ in range(4))
        def send(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return True
        self.sent.side_effect = send
        namespace = {"os": os, "json": json, "uuid4": uuid4, "DATA_ROOT": self.temp.name,
                     "_WORKSPACE_JSON_FILES": ("state.json", "receipts.json"),
                     "_norm": lambda value: str(value or "").strip().lower(),
                     "_file_lock": lambda path: delivery.exclusive(path, blocking=True)}
        _definitions({"_purge_workspace_json", "_scrub_file", "_atomic_json"}, namespace, "app_account.py")
        def purge():
            self.users.pop("a@example.com")
            purging.set()
            namespace["_purge_workspace_json"]("a@example.com")
            purged.set()
        engine = threading.Thread(target=lambda: self.ns["engine_tick"]("a@example.com"))
        deletion = threading.Thread(target=purge)
        engine.start()
        try:
            self.assertTrue(entered.wait(5))
            deletion.start()
            self.assertTrue(purging.wait(5))
            self.assertFalse(purged.wait(0.05))
        finally:
            release.set()
            engine.join(5)
            if deletion.ident:
                deletion.join(5)
        self.assertFalse(engine.is_alive())
        self.assertFalse(deletion.is_alive())
        self.assertTrue(purged.is_set())
        self.assertNotIn("a@example.com", delivery.read_state(self.state)["workspaces"])
        self.assertNotIn("a@example.com", delivery.read_state(self.receipts)["workspaces"])


@unittest.skipIf(delivery is None, "Requires production POSIX file locks")
class FlowPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "automations.json")
        self.state = os.path.join(self.temp.name, "state.json")
        self.users = {"a@example.com": {"status": "active"}, "b@example.com": {"status": "active"}}
        delivery.write_state(self.path, {"users": {"a@example.com": [{"id": "a"}], "b@example.com": [{"id": "b"}]}})
        delivery.write_state(self.state, automation_state.scoped_state({}, {"users": {}}))
        self.ns = {
            "List": list, "Dict": dict, "Any": object, "functools": functools,
            "dispatch_safety": delivery, "automation_state": automation_state,
            "FILE_AUTOMATIONS": self.path, "FILE_STATE": self.state,
            "read_json": lambda path, default: delivery.read_state(path),
            "write_json": delivery.write_state,
            "load_users": lambda: copy.deepcopy(self.users),
            "_account_has_access": lambda user: user.get("status") == "active",
            "jsonify": lambda value: value, "app": types.SimpleNamespace(logger=Mock()),
        }
        _definitions({"save_user_flows", "_serialized_automation_state"}, self.ns)

    def _save_response(self):
        def view():
            self.ns["save_user_flows"]("a@example.com", [{"id": "changed"}])
            return {"ok": True}, 200
        return self.ns["_serialized_automation_state"](view)()

    def test_active_save_preserves_other_workspace(self):
        self.assertEqual(self._save_response()[1], 200)
        self.assertEqual(delivery.read_state(self.path)["users"], {
            "a@example.com": [{"id": "changed"}], "b@example.com": [{"id": "b"}],
        })

    def test_missing_or_inactive_owner_returns_403_without_recreating_flows(self):
        for owner in [None, {"status": "suspended"}]:
            if owner is None:
                self.users.pop("a@example.com", None)
            else:
                self.users["a@example.com"] = owner
            delivery.write_state(self.path, {"users": {"b@example.com": [{"id": "b"}]}})
            before = Path(self.path).read_bytes()
            response, status = self._save_response()
            self.assertEqual(status, 403)
            self.assertIn("not saved", response["error"])
            self.assertEqual(Path(self.path).read_bytes(), before)

    def test_purge_lock_returns_409_then_fresh_owner_check_refuses_late_save(self):
        with delivery.exclusive(self.path, blocking=True):
            response, status = self._save_response()
            self.assertEqual(status, 409)
            self.assertTrue(response["in_progress"])
            # Production purge deletes users before taking this JSON lock.
            self.users.pop("a@example.com")
            delivery.write_state(self.path, {"users": {"b@example.com": [{"id": "b"}]}})
        self.assertEqual(self._save_response()[1], 403)
        self.assertNotIn("a@example.com", delivery.read_state(self.path)["users"])


if __name__ == "__main__":
    unittest.main()

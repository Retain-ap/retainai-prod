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

import dispatch_safety as delivery


def _hold_lock(path, ready, release):
    with delivery.exclusive(path) as acquired:
        ready.put(acquired)
        release.wait(5)


def _definitions(names, namespace):
    parsed = ast.parse(Path(__file__).with_name("app.py").read_text(encoding="utf-8"))
    selected = []
    for node in parsed.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            selected.append(node)
    assert len(selected) == len(names), names
    tree = ast.Module(body=selected, type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), "app.py", "exec"), namespace)


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
        self.assertNotIn("example.com", raw)
        self.assertEqual(next(iter(json.loads(raw).values()))["status"], "sent")

    def test_timeout_and_false_result_are_held_after_restart(self):
        for identity, sender in [(["timeout"], Mock(side_effect=TimeoutError)), (["false"], Mock(return_value=False))]:
            with self.assertRaises(delivery.DeliveryHeld):
                delivery.dispatch_once(self.path, identity, sender)
            with self.assertRaisesRegex(delivery.DeliveryHeld, "needs review"):
                delivery.dispatch_once(self.path, identity, sender)
            sender.assert_called_once()

    def test_claim_must_persist_before_provider_and_failed_completion_stays_pending(self):
        sender = Mock(return_value=True)
        with patch.object(delivery, "write_state", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                delivery.dispatch_once(self.path, ["before"], sender)
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
                delivery.dispatch_once(self.path, ["after"], sender)
        with self.assertRaises(delivery.DeliveryHeld):
            delivery.dispatch_once(self.path, ["after"], sender)
        sender.assert_called_once()

    def test_corrupt_journal_fails_closed(self):
        Path(self.path).write_text("invalid json")
        sender = Mock()
        with self.assertRaises(ValueError):
            delivery.dispatch_once(self.path, ["event"], sender)
        sender.assert_not_called()


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
            "dispatch_safety": delivery, "app": types.SimpleNamespace(logger=Mock()),
            "FILE_STATE": self.state, "FILE_EMAIL_DISPATCH": self.receipts, "FILE_AUTOMATIONS": "flows",
            "now_utc": lambda: self.now, "ensure_files": lambda: None,
            "read_json": lambda *args: copy.deepcopy(self.flows),
            "load_state": lambda: delivery.read_state(self.state),
            "save_state": lambda value: delivery.write_state(self.state, value),
            "load_leads": lambda: copy.deepcopy(self.leads),
            "load_users": lambda: copy.deepcopy(self.users),
            "load_appointments": lambda: copy.deepcopy(self.appointments),
            "load_user_profile": lambda owner: {"business_name": "Example"},
            "trigger_met": lambda *args: True, "should_auto_stop": lambda *args: False,
            "render_text": lambda text, *args: text, "contains_blockers": lambda text: False,
            "in_quiet_hours": lambda *args: False, "_email_unsubscribe_url": lambda *args: "",
            "send_email_sendgrid_auto": self.sent, "record_followup": Mock(), "add_notification": Mock(),
            "CHANNEL_EMAIL": "email", "CHANNEL_WHATSAPP": "whatsapp",
            "user_from_request": lambda: "a@example.com", "jsonify": lambda result: result,
        }
        _definitions({"engine_tick", "_engine_tick_locked", "automations_run_once_route", "get_run", "advance",
                      "automation_event", "execute_step", "can_send", "mark_sent", "_record_automation_action"}, self.ns)

    def test_manual_run_only_dispatches_callers_workspace(self):
        result, status = self.ns["automations_run_once_route"]()
        self.assertEqual((result["ok"], status), (True, 200))
        self.assertEqual(self.sent.call_count, 1)
        self.assertEqual(self.sent.call_args.args[0], "a-customer@example.com")
        self.assertEqual(set(delivery.read_state(self.state)), {"a-flow"})

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
        run = delivery.read_state(self.state)["a-flow"]["lead"]
        self.assertEqual(run["step"], 0)
        self.assertIn("review", run["error"])
        self.assertTrue(any(event["type"] == "failed" for event in run["events"]))

    def test_state_save_failure_reports_failure_and_successful_delivery_is_recovered_without_resend(self):
        real_save = self.ns["save_state"]
        self.ns["save_state"] = Mock(side_effect=OSError("disk error"))
        result, status = self.ns["automations_run_once_route"]()
        self.assertFalse(result["ok"])
        self.assertEqual(status, 503)
        self.ns["save_state"] = real_save
        self.assertTrue(self.ns["engine_tick"]("a@example.com")["ok"])
        self.sent.assert_called_once()
        self.assertEqual(delivery.read_state(self.state)["a-flow"]["lead"]["step"], 1)

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

    def test_failed_appointment_provider_is_held_without_success_notification(self):
        self.appointments = {"a@example.com": [{"id": "recent", "appointment_time": "2026-11-18T08:00:00", "status": "completed"}]}
        self.sent.return_value = False
        job = self._appointment_job()
        job(); job()
        self.sent.assert_called_once()
        self.ns["log_notification"].assert_not_called()
        self.assertEqual(next(iter(delivery.read_state(self.receipts).values()))["status"], "unconfirmed")


if __name__ == "__main__":
    unittest.main()

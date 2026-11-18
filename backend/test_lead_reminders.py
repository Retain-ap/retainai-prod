"""No real provider calls. POSIX integration cases exercise production file locks."""

import datetime as dt
import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import lead_reminders as reminders


NOW = dt.datetime(2026, 11, 18, 14, tzinfo=dt.timezone.utc)  # 09:00 Toronto
ZONE = ZoneInfo("America/Toronto")
OWNER = "owner@example.invalid"
LEADS = [{"id": "lead-1", "name": "Synthetic contact", "createdAt": "2026-10-01T12:00:00Z"}]


class FixedDateTime(dt.datetime):
    moment = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.moment.astimezone(tz) if tz else cls.moment.replace(tzinfo=None)


def prepared(_now):
    return LEADS, 14, ZONE


def record_at(now=NOW, leads=LEADS):
    return {"attempted_at": now.isoformat(), "attempted_fingerprint": reminders.reminder_fingerprint(leads, 14)}


def concurrent_sender(path, ready, results):
    ready.wait(5)
    sent = reminders.send_if_due(path, OWNER, now=NOW, prepare=prepared, send=lambda *_: True)
    results.put(sent)


class LeadReminderPolicyTests(unittest.TestCase):
    def test_first_send_waits_for_local_daytime(self):
        fp = reminders.reminder_fingerprint(LEADS, 14)
        self.assertFalse(reminders.reminder_due({}, fp, NOW - dt.timedelta(minutes=1), ZONE))
        self.assertTrue(reminders.reminder_due({}, fp, NOW, ZONE))
        self.assertTrue(reminders.reminder_due({}, fp, NOW + dt.timedelta(minutes=59), ZONE))
        self.assertTrue(reminders.reminder_due({}, fp, NOW + dt.timedelta(hours=7, minutes=59), ZONE))
        self.assertFalse(reminders.reminder_due({}, fp, NOW + dt.timedelta(hours=8), ZONE))

    def test_timezone_prefers_profile_then_account_and_falls_back_to_utc(self):
        self.assertEqual(str(reminders.reminder_timezone({"timezone": "Asia/Tokyo"}, {"timezone": "Europe/London"})), "Asia/Tokyo")
        self.assertEqual(str(reminders.reminder_timezone({}, {"time_zone": "Europe/London"})), "Europe/London")
        for profile in ({}, {"timezone": "Not/AZone"}):
            self.assertEqual(str(reminders.reminder_timezone(profile, {})), "UTC")

    def test_daylight_saving_still_starts_at_nine_local(self):
        fp = reminders.reminder_fingerprint(LEADS, 14)
        summer = dt.datetime(2026, 7, 3, 13, tzinfo=dt.timezone.utc)
        self.assertTrue(reminders.reminder_due({}, fp, summer, ZONE))
        self.assertFalse(reminders.reminder_due({}, fp, summer - dt.timedelta(minutes=1), ZONE))
        self.assertFalse(reminders.reminder_due({}, fp, summer + dt.timedelta(hours=8), ZONE))

    def test_unchanged_set_waits_seven_days_across_restarts(self):
        record = json.loads(json.dumps(record_at()))
        fp = reminders.reminder_fingerprint(LEADS, 14)
        for days in range(7):
            self.assertFalse(reminders.reminder_due(record, fp, NOW + dt.timedelta(days=days), ZONE))
        self.assertTrue(reminders.reminder_due(record, fp, NOW + dt.timedelta(days=7), ZONE))

    def test_material_change_waits_until_another_local_day(self):
        changed = LEADS + [{"id": "lead-2", "createdAt": "2026-10-02T00:00:00Z"}]
        fp = reminders.reminder_fingerprint(changed, 14)
        self.assertFalse(reminders.reminder_due(record_at(), fp, NOW + dt.timedelta(minutes=30), ZONE))
        self.assertTrue(reminders.reminder_due(record_at(), fp, NOW + dt.timedelta(days=1), ZONE))

    def test_fingerprint_ignores_aging_order_and_notes_but_detects_contact_changes(self):
        lead = LEADS[0]
        fp = reminders.reminder_fingerprint([lead], 14)
        self.assertEqual(fp, reminders.reminder_fingerprint([{**lead, "days_since_contact": 99, "notes": "changed", "name": "Edited name"}], 14))
        two = [lead, {"id": "lead-2", "createdAt": "2026-10-02T00:00:00Z"}]
        self.assertEqual(reminders.reminder_fingerprint(two, 14), reminders.reminder_fingerprint(two[::-1], 14))
        self.assertNotEqual(fp, reminders.reminder_fingerprint([{**lead, "last_contacted": "2026-10-31T00:00:00Z"}], 14))
        self.assertNotEqual(fp, reminders.reminder_fingerprint(two, 14))
        self.assertNotEqual(fp, reminders.reminder_fingerprint([lead], 30))

    def test_overdue_selection_keeps_weekly_eligibility_and_does_not_mutate_contacts(self):
        before = json.dumps(LEADS)
        leads = LEADS + [{"id": "new", "createdAt": NOW.isoformat()}, {"id": "broken", "last_contacted": "invalid"}, None]
        selected = reminders.overdue_leads(leads, 14, NOW)
        self.assertEqual([item["id"] for item in selected], ["lead-1"])
        self.assertGreater(selected[0]["days_since_contact"], 16)
        self.assertEqual(json.dumps(LEADS), before)

    def test_offset_timestamps_are_compared_as_instants(self):
        when = NOW - dt.timedelta(days=14)
        selected = reminders.overdue_leads([{"id": "offset", "createdAt": when.astimezone(ZONE).isoformat()}], 14, NOW)
        self.assertEqual(selected[0]["days_since_contact"], 14)

    def test_invalid_or_future_state_cannot_trigger_a_send(self):
        fp = reminders.reminder_fingerprint(LEADS, 14)
        with self.assertRaises(ValueError):
            reminders.reminder_due({"attempted_at": "broken"}, fp, NOW, ZONE)
        self.assertFalse(reminders.reminder_due(record_at(NOW + dt.timedelta(days=1)), fp, NOW, ZONE))


@unittest.skipUnless(os.name == "posix", "Production file-lock integration requires POSIX; run in Linux CI")
class LeadReminderStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, reminders.STATE_FILE)

    def send(self, **kwargs):
        return reminders.send_if_due(self.path, OWNER, now=kwargs.pop("now", NOW), prepare=kwargs.pop("prepare", prepared), **kwargs)

    def state(self):
        return json.loads(Path(self.path).read_text())[OWNER]

    def test_accepted_marker_persists_and_independent_call_does_not_repeat(self):
        provider = Mock(return_value=True)
        self.assertTrue(self.send(send=provider))
        self.assertEqual(self.state()["last_sent_at"], NOW.isoformat())
        self.assertFalse(self.send(send=provider, now=NOW + dt.timedelta(days=1)))
        self.assertEqual(provider.call_count, 1)

    def test_two_real_processes_cannot_both_claim_one_briefing(self):
        context = multiprocessing.get_context("fork")
        ready, results = context.Event(), context.Queue()
        workers = [context.Process(target=concurrent_sender, args=(self.path, ready, results)) for _ in range(2)]
        for worker in workers:
            worker.start()
        try:
            ready.set()
            outcomes = [results.get(timeout=10) for _ in workers]
            for worker in workers:
                worker.join(10)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(sorted(outcomes), [False, True])
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join()
            results.close()

    def test_rejected_provider_is_not_recorded_as_sent_and_is_not_hammered(self):
        provider = Mock(return_value=False)
        self.assertFalse(self.send(send=provider))
        self.assertNotIn("last_sent_at", self.state())
        self.assertFalse(self.send(send=provider, now=NOW + dt.timedelta(days=1)))
        self.assertEqual(provider.call_count, 1)
        self.assertFalse(self.send(send=provider, now=NOW + dt.timedelta(days=7)))
        self.assertEqual(provider.call_count, 2)

    def test_lost_provider_response_keeps_claim_without_success_receipt(self):
        provider = Mock(side_effect=TimeoutError("synthetic uncertain outcome"))
        with self.assertRaises(TimeoutError):
            self.send(send=provider)
        self.assertNotIn("last_sent_at", self.state())
        self.assertFalse(self.send(send=provider, now=NOW + dt.timedelta(minutes=15)))
        self.assertEqual(provider.call_count, 1)

    def test_failure_after_provider_acceptance_does_not_repeat_after_restart(self):
        import value_receipt as store
        real_write = store._write
        writes = 0

        def interrupted_write(path, state):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("synthetic disk failure")
            real_write(path, state)

        provider = Mock(return_value=True)
        with patch.object(store, "_write", side_effect=interrupted_write), self.assertRaises(OSError):
            self.send(send=provider)
        self.assertNotIn("last_sent_at", self.state())
        self.assertFalse(self.send(send=provider, now=NOW + dt.timedelta(days=1)))
        self.assertEqual(provider.call_count, 1)

    def test_corrupt_store_or_failed_claim_never_calls_provider(self):
        import value_receipt as store
        provider = Mock(return_value=True)
        Path(self.path).write_text("broken json")
        with self.assertRaises(store.EvidenceStoreError):
            self.send(send=provider)
        Path(self.path).unlink()
        with patch.object(store, "_write", side_effect=OSError("synthetic disk failure")), self.assertRaises(OSError):
            self.send(send=provider)
        provider.assert_not_called()

    def test_guard_runs_inside_claim_and_can_refuse_removed_account(self):
        provider = Mock(return_value=True)
        self.assertFalse(self.send(send=provider, prepare=lambda _now: None))
        provider.assert_not_called()
        self.assertFalse(os.path.exists(self.path))

    def test_claims_are_per_account_and_material_changes_wait_until_tomorrow(self):
        provider = Mock(return_value=True)
        self.assertTrue(self.send(send=provider))
        self.assertTrue(reminders.send_if_due(self.path, "other@example.invalid", now=NOW, prepare=prepared, send=provider))
        changed = LEADS + [{"id": "lead-2", "createdAt": "2026-10-01T12:00:00Z"}]
        prepare_changed = lambda _now: (changed, 14, ZONE)
        self.assertFalse(self.send(send=provider, prepare=prepare_changed, now=NOW + dt.timedelta(minutes=30)))
        self.assertTrue(self.send(send=provider, prepare=prepare_changed, now=NOW + dt.timedelta(days=1)))
        self.assertEqual(provider.call_count, 3)


@unittest.skipUnless(os.name == "posix", "Flask/storage integration requires POSIX; run in Linux CI")
class LeadReminderSchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.TemporaryDirectory()
        os.environ.setdefault("DATA_ROOT", cls.data.name)
        os.environ.setdefault("RUN_SCHEDULER", "0")
        os.environ.setdefault("SESSION_SECRET", "test-only-lead-reminder-session-secret-long-enough")
        os.environ.setdefault("DATA_ENCRYPTION_KEY", "test-only-independent-lead-reminder-data-key-long-enough")
        import app
        cls.core = app

    @classmethod
    def tearDownClass(cls):
        cls.data.cleanup()

    def test_existing_mailer_propagates_acceptance(self):
        with patch.object(self.core, "load_users", return_value={}), patch.object(self.core, "send_email_with_template", return_value=False):
            self.assertFalse(self.core.send_warning_summary_email(OWNER, LEADS, 14))
        with patch.object(self.core, "load_users", return_value={}), patch.object(self.core, "send_email_with_template", return_value=True):
            self.assertTrue(self.core.send_warning_summary_email(OWNER, LEADS, 14))

    def test_inactive_account_quiet_hours_and_current_guard_block_sends(self):
        core = self.core
        active = {"email": OWNER, "org_id": OWNER, "role": "owner", "status": "active"}
        for current_users, profile in (({}, {}), ({OWNER: {**active, "status": "suspended"}}, {}), ({OWNER: active}, {"timezone": "America/Toronto", "quiet_hours_start": "08:00", "quiet_hours_end": "10:00"})):
            with self.subTest(current_users=bool(current_users), quiet=bool(profile)), tempfile.TemporaryDirectory() as directory:
                with patch.object(core, "DATA_ROOT", directory), patch.object(core.datetime, "datetime", FixedDateTime), \
                     patch.object(core, "load_users", side_effect=[{OWNER: active}, current_users]), \
                     patch.object(core, "load_user_profile", return_value=profile), \
                     patch.object(core, "send_warning_summary_email") as provider:
                    core.check_for_lead_reminders()
                provider.assert_not_called()

    def test_scheduler_repeated_ticks_send_and_log_once(self):
        core = self.core
        active = {"email": OWNER, "org_id": OWNER, "role": "owner", "status": "active"}
        with tempfile.TemporaryDirectory() as directory, patch.object(core, "DATA_ROOT", directory), \
             patch.object(core.datetime, "datetime", FixedDateTime), \
             patch.object(core, "load_users", return_value={OWNER: active}), \
             patch.object(core, "load_user_profile", return_value={"timezone": "America/Toronto"}), \
             patch.object(core, "load_user_leads", return_value=LEADS), \
             patch.object(core, "log_notification") as notification, \
             patch.object(core, "send_warning_summary_email", return_value=True) as provider:
            core.check_for_lead_reminders()
            core.check_for_lead_reminders()
            provider.assert_called_once()
            notification.assert_called_once()

    def test_scheduler_waits_until_quiet_hours_end_during_daytime(self):
        core = self.core
        active = {"email": OWNER, "org_id": OWNER, "role": "owner", "status": "active"}
        class LaterClock(FixedDateTime):
            moment = NOW + dt.timedelta(hours=2)
        with tempfile.TemporaryDirectory() as directory, patch.object(core, "DATA_ROOT", directory), \
             patch.object(core, "load_users", return_value={OWNER: active}), \
             patch.object(core, "load_user_profile", return_value={"timezone": "America/Toronto", "quiet_hours_start": "22:00", "quiet_hours_end": "11:00"}), \
             patch.object(core, "load_user_leads", return_value=LEADS), \
             patch.object(core, "log_notification"), \
             patch.object(core, "send_warning_summary_email", return_value=True) as provider:
            with patch.object(core.datetime, "datetime", FixedDateTime):
                core.check_for_lead_reminders()
            provider.assert_not_called()
            with patch.object(core.datetime, "datetime", LaterClock):
                core.check_for_lead_reminders()
            provider.assert_called_once()

    def test_account_purge_includes_reminder_state(self):
        import app_account
        with tempfile.TemporaryDirectory() as directory, patch.object(app_account, "DATA_ROOT", directory):
            path = Path(directory) / reminders.STATE_FILE
            path.write_text(json.dumps({OWNER: record_at(), "other@example.invalid": record_at()}))
            app_account._purge_workspace_json(OWNER)
            self.assertEqual(set(json.loads(path.read_text())), {"other@example.invalid"})


if __name__ == "__main__":
    unittest.main()

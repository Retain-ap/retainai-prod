"""Scheduler status tests without app startup, jobs, providers, or env files."""
import ast
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, mock_open, patch

import scheduler_health as health


def _hold_scheduler_lock(path, ready, release):
    import fcntl
    with open(path, "a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        ready.put(True)
        release.wait(5)


class SchedulerStatusTests(unittest.TestCase):
    def test_local_running_and_other_worker_are_distinguished(self):
        local = health.scheduler_status(True, True, True, True)
        other = health.scheduler_status(True, False, True, True)
        self.assertTrue(local["ok"] and other["ok"])
        self.assertEqual(local["status"], "operational")
        self.assertEqual(other["status"], "owned_by_another_worker")
        self.assertFalse(other["local_scheduler_running"])
        self.assertTrue(other["scheduler_owner_present"])
        self.assertNotIn("pid", other)

    def test_disabled_waiting_offline_and_unknown_are_not_online(self):
        cases = [
            ((False, False, True, True), "scheduler_disabled"),
            ((True, False, False, False), "scheduler_waiting"),
            ((True, False, False, True), "scheduler_offline"),
            ((True, False, None, True), "scheduler_status_unknown"),
        ]
        for args, expected in cases:
            result = health.scheduler_status(*args)
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], expected)

    def test_only_exact_file_exclusive_flock_is_an_owner(self):
        identity = (0, 47, 32388)
        self.assertTrue(health._exclusive_flock_present("3: FLOCK ADVISORY WRITE 1568 00:2f:32388 0 EOF", identity))
        for line in [
            "3: FLOCK ADVISORY WRITE 1568 00:2f:32389 0 EOF",
            "3: FLOCK ADVISORY READ 1568 00:2f:32388 0 EOF",
            "3: POSIX ADVISORY WRITE 1568 00:2f:32388 0 EOF",
            "3: -> FLOCK ADVISORY WRITE 1568 00:2f:32388 0 EOF",
        ]:
            self.assertFalse(health._exclusive_flock_present(line, identity))

    def test_unrecognized_kernel_format_is_unknown(self):
        self.assertIsNone(health._exclusive_flock_present("unexpected format", (1, 2, 3)))

    def test_proc_read_failure_is_unknown(self):
        with patch.object(health.sys, "platform", "linux"), patch.object(health, "_file_identity", return_value=(1, 2, 3)), patch("builtins.open", side_effect=PermissionError):
            self.assertIsNone(health.scheduler_lock_held("scheduler.lock"))

    def test_probe_is_read_only_and_rejects_replaced_file(self):
        opened = mock_open(read_data="1: FLOCK ADVISORY WRITE 123 01:02:3 0 EOF\n")
        with patch.object(health.sys, "platform", "linux"), patch.object(health, "_file_identity", side_effect=[(1, 2, 3), (1, 2, 4)]), patch("builtins.open", opened):
            self.assertIsNone(health.scheduler_lock_held("scheduler.lock"))
        opened.assert_called_once_with("/proc/locks", encoding="ascii")
        opened().read.assert_called_once_with(health.MAX_LOCK_BYTES + 1)
        opened().write.assert_not_called()

    def test_oversized_proc_snapshot_is_unknown(self):
        with patch.object(health.sys, "platform", "linux"), patch.object(health, "_file_identity", return_value=(1, 2, 3)), patch("builtins.open", mock_open(read_data="x" * (health.MAX_LOCK_BYTES + 1))):
            self.assertIsNone(health.scheduler_lock_held("scheduler.lock"))

    def test_missing_lock_is_offline_and_does_not_create_it(self):
        with patch.object(health.sys, "platform", "linux"), patch.object(health, "_file_identity", side_effect=FileNotFoundError), patch("builtins.open") as opened:
            self.assertFalse(health.scheduler_lock_held("scheduler.lock"))
            opened.assert_not_called()

    def test_unsupported_platform_is_unknown(self):
        with patch.object(health.sys, "platform", "win32"), patch("builtins.open") as opened:
            self.assertIsNone(health.scheduler_lock_held("scheduler.lock"))
            opened.assert_not_called()

    def test_route_reports_other_owner_without_starting_or_reading_local_schedule(self):
        parsed = ast.parse(Path(__file__).with_name("app.py").read_text(encoding="utf-8"))
        node = next(item for item in parsed.body if isinstance(item, ast.FunctionDef) and item.name == "automations_health")
        node.decorator_list = []
        scheduler = types.SimpleNamespace(running=False, start=Mock(), get_job=Mock())
        namespace = {"scheduler": scheduler, "SCHEDULER_ENABLED": True,
                     "app": types.SimpleNamespace(config={"BOOTSTRAP_DONE": True}),
                     "_scheduler_process_lock_path": lambda: "scheduler.lock", "jsonify": lambda value: value}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
        with patch.object(health, "scheduler_lock_held", return_value=True):
            result = namespace["automations_health"]()
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "owned_by_another_worker")
        self.assertIsNone(result["next_evaluation"])
        scheduler.start.assert_not_called()
        scheduler.get_job.assert_not_called()


@unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux /proc/locks and process locks")
class LinuxSchedulerOwnershipTests(unittest.TestCase):
    def test_other_process_owner_is_live_and_stale_pid_after_exit_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "scheduler.lock")
            context = multiprocessing.get_context("fork")
            ready, release = context.Queue(), context.Event()
            process = context.Process(target=_hold_scheduler_lock, args=(path, ready, release))
            process.start()
            try:
                self.assertTrue(ready.get(timeout=5))
                self.assertTrue(health.scheduler_lock_held(path))
                self.assertTrue(health.scheduler_status(True, False, health.scheduler_lock_held(path), True)["ok"])
            finally:
                release.set()
                process.join(5)
                if process.is_alive():
                    process.terminate()
                    process.join()
            self.assertEqual(process.exitcode, 0)
            self.assertTrue(Path(path).read_text().isdigit())
            self.assertFalse(health.scheduler_lock_held(path))
            # The status probe never takes a lock that could fool bootstrap.
            import fcntl
            with open(path, "rb") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def test_probe_does_not_create_missing_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "scheduler.lock")
            self.assertFalse(health.scheduler_lock_held(path))
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()

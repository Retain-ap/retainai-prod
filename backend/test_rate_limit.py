"""Regression tests for rate limits shared across backend workers."""

import multiprocessing
import os
import sqlite3
import tempfile
import unittest


_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402
import rate_limit  # noqa: E402


def _signup_attempt(_):
    # Each call runs in a separate process, like a separate gunicorn worker.
    import rate_limit as worker_limits

    return worker_limits.hit([("signup_email", "shared@example.com", 4)], 3600)


class SharedRateLimitTests(unittest.TestCase):
    def setUp(self):
        rate_limit.reset()

    def test_limit_is_shared_between_processes(self):
        with multiprocessing.get_context("spawn").Pool(4) as pool:
            results = pool.map(_signup_attempt, range(12))
        self.assertEqual(results.count(False), 4)
        self.assertEqual(results.count(True), 8)

    def test_keys_are_stored_as_digests_only(self):
        rate_limit.record("login", "person@example.com:198.51.100.7")
        with sqlite3.connect(rate_limit.RATE_LIMIT_DB) as conn:
            stored = " ".join(row[0] for row in conn.execute("SELECT k FROM rate_events"))
        self.assertNotIn("person@example.com", stored)
        self.assertNotIn("198.51.100.7", stored)

    def test_login_lockout_and_clear(self):
        with retainai.app.test_request_context("/api/login", headers={"CF-Connecting-IP": "198.51.100.7"}):
            for _ in range(retainai.LOGIN_MAX_ATTEMPTS):
                self.assertFalse(retainai._login_is_limited("person@example.com"))
                retainai._record_login_failure("person@example.com")
            self.assertTrue(retainai._login_is_limited("person@example.com"))
            retainai._clear_login_failures("person@example.com")
            self.assertFalse(retainai._login_is_limited("person@example.com"))

    def test_spoofed_forwarded_for_does_not_reset_ip_limit(self):
        for attempt in range(retainai.SIGNUP_MAX_PER_IP):
            with retainai.app.test_request_context(
                "/api/auth/signup",
                headers={"CF-Connecting-IP": "198.51.100.9", "X-Forwarded-For": f"10.0.0.{attempt}"},
            ):
                self.assertFalse(retainai._signup_rate_limited(f"user{attempt}@example.com"))
        with retainai.app.test_request_context(
            "/api/auth/signup",
            headers={"CF-Connecting-IP": "198.51.100.9", "X-Forwarded-For": "10.0.0.250"},
        ):
            self.assertTrue(retainai._signup_rate_limited("another@example.com"))

    def test_falls_back_to_memory_when_database_is_unusable(self):
        original = rate_limit.RATE_LIMIT_DB
        # A directory cannot be opened as a database file.
        rate_limit.RATE_LIMIT_DB = _TEST_DATA.name
        try:
            keys = [("password_reset", "fallback@example.com", 2)]
            self.assertFalse(rate_limit.hit(keys, 60))
            self.assertFalse(rate_limit.hit(keys, 60))
            self.assertTrue(rate_limit.hit(keys, 60))
        finally:
            rate_limit.RATE_LIMIT_DB = original


if __name__ == "__main__":
    unittest.main()

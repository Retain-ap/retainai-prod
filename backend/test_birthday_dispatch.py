"""Birthday adapter checks; no app startup, provider calls or production data.

The shared dispatch journal has its own persistence/concurrency tests. Here a
contract fake verifies event identity, fresh eligibility and no notification writes.
"""

import ast
import copy
import datetime
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class DeliveryHeld(RuntimeError):
    pass


class BirthdayDispatchTests(unittest.TestCase):
    def setUp(self):
        self.owner = "owner@example.test"
        self.now = datetime.datetime(2026, 1, 2, 9, 5)
        self.users = {self.owner: {"status": "active", "name": "Owner", "business": "Studio", "mailingAddress": "1 Main St, Toronto ON"}}
        self.leads = {self.owner: [
            {"id": "today", "name": "Avery", "email": "avery@example.test", "birthday": "1990-01-02"},
            {"id": "tomorrow", "name": "Blake", "email": "blake@example.test", "birthday": "1990-01-03"},
        ]}
        self.receipts = {}
        self.identities = []
        self.before_check = None

        def dispatch_once(path, identity, send, *, is_eligible=None):
            self.identities.append(identity)
            key = tuple(identity)
            if key in self.receipts:
                if self.receipts[key] == "accepted":
                    return False
                raise DeliveryHeld("Held")
            if self.before_check:
                self.before_check()
            if is_eligible is not None and not is_eligible():
                raise DeliveryHeld("No longer eligible")
            self.receipts[key] = "claimed"
            try:
                accepted = send() is True
            except Exception:
                accepted = False
            if not accepted:
                raise DeliveryHeld("Unconfirmed")
            self.receipts[key] = "accepted"
            return True

        fake = types.SimpleNamespace(dispatch_once=dispatch_once, DeliveryHeld=DeliveryHeld)
        self.module_patch = patch.dict(sys.modules, {"dispatch_safety": fake})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        clock = Mock(wraps=datetime.datetime)
        clock.utcnow.side_effect = lambda: self.now
        clock.now.side_effect = lambda: self.now
        self.send = Mock(return_value=True)
        self.log = Mock()
        self.scope = {
            "datetime": types.SimpleNamespace(datetime=clock, timedelta=datetime.timedelta),
            "load_users": lambda: copy.deepcopy(self.users),
            "load_leads": lambda: copy.deepcopy(self.leads),
            "_account_has_access": lambda user: user.get("status") == "active",
            "_workspace_business_name": lambda user: user.get("business", ""),
            "_workspace_sender_details": lambda user, fallback="": {"address": user.get("mailingAddress", ""), "contact": fallback},
            "imported_without_consent": lambda lead: lead.get("email_consent_status") == "unknown",
            "_email_unsubscribe_url": lambda owner, lead: "https://example.test/unsubscribe",
            "send_email_with_template": self.send,
            "log_notification": self.log,
            "platform_email_sender": lambda: "platform@example.test",
            "SG_TEMPLATE_BIRTHDAY": "birthday",
            "SG_TEMPLATE_BDAY_REMINDER_USER": "birthday-owner",
            "FRONTEND_URL": "https://example.test",
            "FILE_EMAIL_DISPATCH": "isolated-journal.json",
            "app": types.SimpleNamespace(logger=Mock()),
        }
        names = {"send_birthday_email", "send_birthday_reminder_to_user", "_birthday_contact_key", "_dispatch_birthday_email", "send_birthday_greetings"}
        source = pathlib.Path(__file__).with_name("app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in selected}, names)
        exec(compile(ast.Module(body=selected, type_ignores=[]), "birthday-adapter", "exec"), self.scope)

    def run_job(self):
        self.scope["send_birthday_greetings"]()

    def test_repeat_job_sends_each_type_once_without_notification_writes(self):
        self.run_job()
        self.run_job()
        self.assertEqual(self.send.call_count, 2)
        self.log.assert_not_called()
        self.assertEqual(set(self.receipts), {
            ("birthday_customer_greeting", self.owner, "id:today", "2026-01-02"),
            ("birthday_owner_reminder", self.owner, "id:tomorrow", "2026-01-03"),
        })

    def test_same_contact_id_in_other_workspace_is_independent(self):
        self.leads[self.owner] = [self.leads[self.owner][0]]
        other = "other@example.test"
        self.users[other] = dict(self.users[self.owner])
        self.leads[other] = copy.deepcopy(self.leads[self.owner])
        self.run_job()
        self.run_job()
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual({key[1] for key in self.receipts}, {self.owner, other})

    def test_year_rollover_separates_reminder_greeting_and_next_year(self):
        self.leads[self.owner] = [{"id": "new-year", "name": "Avery", "email": "avery@example.test", "birthday": "1990-01-01"}]
        self.now = datetime.datetime(2026, 12, 31, 9, 5)
        self.run_job()
        self.now = datetime.datetime(2027, 1, 1, 9, 5)
        self.run_job()
        self.now = datetime.datetime(2028, 1, 1, 9, 5)
        self.run_job()
        self.assertEqual(self.send.call_count, 3)
        self.assertEqual({key[3] for key in self.receipts}, {"2027-01-01", "2028-01-01"})

    def test_rechecks_access_consent_contact_and_destination_before_claim(self):
        source = copy.deepcopy(self.leads[self.owner][0])
        mutations = {
            "access": lambda: self.users[self.owner].update(status="inactive"),
            "opt-out": lambda: self.leads[self.owner][0].update(email_opt_out=True),
            "import-consent": lambda: self.leads[self.owner][0].update(email_consent_status="unknown"),
            "deleted": lambda: self.leads[self.owner].clear(),
            "address-changed": lambda: self.leads[self.owner][0].update(email="new@example.test"),
            "birthday-changed": lambda: self.leads[self.owner][0].update(birthday="1990-03-01"),
            "business-removed": lambda: self.users[self.owner].update(business=""),
            "mailing-address-removed": lambda: self.users[self.owner].update(mailingAddress=""),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.users[self.owner] = {"status": "active", "business": "Studio", "mailingAddress": "1 Main St, Toronto ON"}
                self.leads[self.owner] = [copy.deepcopy(source)]
                self.before_check = mutate
                self.assertFalse(self.scope["_dispatch_birthday_email"](self.owner, source, self.now.date()))
        self.send.assert_not_called()
        self.assertEqual(self.receipts, {})

    def test_false_none_or_exception_never_logs_success_or_retries(self):
        for outcome in [False, None, RuntimeError("Provider unavailable")]:
            with self.subTest(outcome=type(outcome).__name__):
                self.receipts.clear()
                self.send.reset_mock(side_effect=True)
                self.send.return_value = outcome
                if isinstance(outcome, Exception):
                    self.send.side_effect = outcome
                self.run_job()
                self.run_job()
                self.assertEqual(self.send.call_count, 2, "Each event gets one provider attempt")
                self.log.assert_not_called()

    def test_owner_reminder_rechecks_contact_and_owner_access(self):
        lead = copy.deepcopy(self.leads[self.owner][1])
        self.before_check = lambda: self.users[self.owner].update(status="inactive")
        self.assertFalse(self.scope["_dispatch_birthday_email"](self.owner, lead, self.now.date() + datetime.timedelta(days=1), owner_reminder=True))
        self.send.assert_not_called()

    def test_journal_error_prevents_provider_send_and_success_log(self):
        fake = sys.modules["dispatch_safety"]
        with patch.object(fake, "dispatch_once", side_effect=OSError("Journal unavailable")):
            self.run_job()
        self.send.assert_not_called()
        self.log.assert_not_called()

    def test_purge_after_dispatch_return_cannot_recreate_notifications(self):
        def completed_then_purged(path, identity, send, *, is_eligible=None):
            self.users.clear()
            self.leads.clear()
            return True

        fake = sys.modules["dispatch_safety"]
        with patch.object(fake, "dispatch_once", side_effect=completed_then_purged):
            self.run_job()
        self.log.assert_not_called()

    def test_legacy_email_fallback_is_normalized_and_anonymous_contact_is_skipped(self):
        lead = {"name": "Legacy", "email": "LEGACY@example.test", "birthday": "1990-01-02"}
        self.leads[self.owner] = [lead, {"name": "No identity", "birthday": "1990-01-03"}]
        self.run_job()
        lead["name"] = "Renamed"
        lead["email"] = "legacy@example.test"
        self.run_job()
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(next(iter(self.receipts))[2], "email:legacy@example.test")


    def test_no_mailing_address_pauses_customer_greetings_and_tells_the_owner_once(self):
        self.users[self.owner]["mailingAddress"] = ""
        self.scope["SENDER_DETAILS_MESSAGE"] = "Add your business mailing address in Settings."
        self.run_job()
        sent_to = [call.kwargs.get("to_email") for call in self.send.call_args_list]
        self.assertNotIn("avery@example.test", sent_to, "no customer greeting without the sender's address")
        paused = [call for call in self.log.call_args_list if call.args[1:2] == ("Birthday emails paused",)]
        self.assertEqual(len(paused), 1)
        self.assertIn("1 birthday email today", paused[0].args[2])


if __name__ == "__main__":
    unittest.main()

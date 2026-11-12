"""Contact file parsing, validated import, tenant isolation and safe undo."""

import io
import os
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch


_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402
import app_imports  # noqa: E402
import contact_import as ci  # noqa: E402


APPLE_VCARD = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nPRODID:-//Apple Inc.//iPhone OS 18.0//EN\r\n"
    "N:Rivera;Jordan;;;\r\nFN:Jordan Rivera\r\nORG:North Star Studio;\r\nTITLE:Owner\r\n"
    "item1.EMAIL;type=INTERNET;type=pref:jordan@example.com\r\n"
    "TEL;type=CELL;type=VOICE;type=pref:(416) 555-0101\r\nTEL;type=WORK:416 555 0199\r\n"
    "NOTE:Prefers mornings\\, no lavender\r\nBDAY:1990-04-12\r\nEND:VCARD\r\n"
    "BEGIN:VCARD\r\nVERSION:4.0\r\nFN:Avery Chen\r\nN:Chen;Avery;;;\r\n"
    "EMAIL;TYPE=work:avery@\r\n example.com\r\nTEL;TYPE=cell;VALUE=uri:tel:+44-20-7946-0958\r\nEND:VCARD\r\n"
)
ANDROID_VCARD_21 = (
    "BEGIN:VCARD\nVERSION:2.1\nN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Dubois;=C3=89mile;;;\n"
    "FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=C3=89mile Dubois\nTEL;CELL:+33 6 12 34 56 78\nEND:VCARD\n"
)


def _csv(headers, *rows, sep=","):
    lines = [sep.join(headers)] + [sep.join(row) for row in rows]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


class ParserTests(unittest.TestCase):
    def test_apple_and_icloud_vcards(self):
        parsed = ci.parse_file("Contacts.vcf", APPLE_VCARD.encode("utf-8"))
        self.assertEqual(parsed["format"], "vcard")
        self.assertEqual(len(parsed["rows"]), 2)
        jordan, _ = ci.build_contact(parsed["rows"][0], parsed["mapping"])
        self.assertEqual(jordan["name"], "Jordan Rivera")
        self.assertEqual(jordan["email"], "jordan@example.com")
        self.assertEqual(jordan["phone"], "+14165550101")  # mobile wins over work
        self.assertEqual(jordan["company"], "North Star Studio")
        self.assertEqual(jordan["notes"], "Prefers mornings, no lavender")
        self.assertEqual(jordan["birthday"], "1990-04-12")
        avery, _ = ci.build_contact(parsed["rows"][1], parsed["mapping"])
        self.assertEqual(avery["email"], "avery@example.com")  # folded line joined
        self.assertEqual(avery["phone"], "+442079460958")

    def test_android_and_whatsapp_shared_vcard_21_quoted_printable(self):
        parsed = ci.parse_file("whatsapp-contact.vcf", ANDROID_VCARD_21.encode("utf-8"))
        contact, _ = ci.build_contact(parsed["rows"][0], parsed["mapping"])
        self.assertEqual(contact["name"], "Émile Dubois")
        self.assertEqual(contact["phone"], "+33612345678")

    def test_crm_presets_are_detected_and_mapped(self):
        cases = {
            "hubspot": (["Record ID", "First Name", "Last Name", "Email", "Phone Number", "Company Name"],
                        ["1", "Sam", "Lee", "sam@example.com", "4165550111", "Acme"]),
            "salesforce": (["Contact ID", "First Name", "Last Name", "Account Name", "Email", "Mobile", "Title"],
                           ["003x", "Sam", "Lee", "Acme", "sam@example.com", "4165550111", "CEO"]),
            "pipedrive": (["Person - Name", "Person - Email", "Person - Phone", "Person - Organization"],
                          ["Sam Lee", "sam@example.com", "4165550111", "Acme"]),
            "zoho": (["Contact Owner", "First Name", "Last Name", "Account Name", "Email", "Mobile"],
                     ["me", "Sam", "Lee", "Acme", "sam@example.com", "4165550111"]),
            "google": (["First Name", "Last Name", "E-mail 1 - Value", "Phone 1 - Value", "Organization Name"],
                       ["Sam", "Lee", "sam@example.com", "4165550111", "Acme"]),
            "outlook": (["First Name", "Last Name", "E-mail Address", "Mobile Phone", "Company"],
                        ["Sam", "Lee", "sam@example.com", "4165550111", "Acme"]),
        }
        for preset, (headers, row) in cases.items():
            with self.subTest(preset=preset):
                parsed = ci.parse_file(f"{preset}.csv", _csv(headers, row))
                self.assertEqual(parsed["preset"]["key"], preset)
                contact, problem = ci.build_contact(parsed["rows"][0], parsed["mapping"])
                self.assertEqual(problem, "")
                self.assertEqual(contact["name"], "Sam Lee")
                self.assertEqual(contact["email"], "sam@example.com")
                self.assertEqual(contact["phone"], "+14165550111")
                self.assertEqual(contact["company"], "Acme")

    def test_semicolon_tab_utf16_and_quoted_csv(self):
        text = 'Name;Email;Phone\r\n"Lee, Sam";sam@example.com;+1 416 555 0111\r\n'
        parsed = ci.parse_file("export.csv", text.encode("utf-16"))
        contact, _ = ci.build_contact(parsed["rows"][0], parsed["mapping"])
        self.assertEqual(contact["name"], "Lee, Sam")
        tab = ci.parse_file("export.tsv", _csv(["Name", "Email"], ["Sam", "sam@example.com"], sep="\t"))
        self.assertEqual(tab["mapping"]["email"], "Email")

    def test_validation_and_limits(self):
        self.assertEqual(ci.build_contact({"E": "not-an-email"}, {"email": "E"})[1], "invalid_email")
        self.assertEqual(ci.build_contact({"N": "Name only"}, {"name": "N"})[1], "missing_email_or_phone")
        kept, warning = ci.build_contact({"E": "bad@", "P": "4165550111"}, {"email": "E", "phone": "P"})
        self.assertEqual((kept["email"], warning), ("", "invalid_email"))
        self.assertEqual(ci.build_contact({"P": "12"}, {"phone": "P"})[1], "invalid_phone")
        self.assertEqual(ci.build_contact({"P": "+1 (416) 555-0111 ext. 22"}, {"phone": "P"})[0]["phone"], "+14165550111")
        long_notes = ci.build_contact({"E": "a@b.co", "N": "x" * 9000}, {"email": "E", "notes": "N"})[0]
        self.assertEqual(len(long_notes["notes"]), ci.MAX_FIELD_CHARS["notes"])
        with self.assertRaises(ci.ContactImportError):
            ci.parse_file("big.csv", b"x" * (ci.MAX_FILE_BYTES + 1))
        with self.assertRaises(ci.ContactImportError):
            ci.parse_file("contacts.xlsx", b"PK\x03\x04")
        many = _csv(["Email"], *[[f"p{i}@example.com"] for i in range(ci.MAX_ROWS + 5)])
        parsed = ci.parse_file("many.csv", many)
        self.assertEqual(len(parsed["rows"]), ci.MAX_ROWS)
        self.assertTrue(parsed["truncated"])


class ImportApiTests(unittest.TestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        self.users = {self.owner: {"email": self.owner, "role": "owner", "org_id": self.owner, "status": "active", "security_version": 0}}
        self.patch = patch.object(retainai, "load_users", side_effect=lambda: self.users)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = self._client(self.owner)

    def _client(self, email):
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = email
            signed["org_email"] = email
            signed["security_version"] = 0
        return client

    def _preview(self, name, content, client=None):
        response = (client or self.client).post(
            "/api/import/file/preview",
            data={"file": (io.BytesIO(content), name)},
            content_type="multipart/form-data",
            headers={"Origin": "http://localhost:3000"},
        )
        return response

    def _commit(self, preview, client=None, **options):
        body = {"rows": preview["rows"], "mapping": preview["mapping"], "source": preview["format"], **options}
        return (client or self.client).post("/api/import/file/commit", json=body, headers={"Origin": "http://localhost:3000"})

    def _leads(self, email=None):
        return retainai.load_leads().get(email or self.owner, [])

    def test_preview_reports_outcomes_and_commit_saves_without_consent_or_automation(self):
        content = _csv(["Name", "Email", "Phone"],
                       ["Sam Lee", "sam@example.com", "4165550111"],
                       ["Sam Again", "SAM@example.com", ""],
                       ["No Contact", "", ""],
                       ["Bad Email", "nope@", "4165550122"])
        preview = self._preview("leads.csv", content).get_json()
        self.assertEqual([o["status"] for o in preview["outcomes"]], ["imported", "skipped", "invalid", "imported"])
        self.assertEqual(preview["outcomes"][1]["reason"], "duplicate_in_file")
        self.assertEqual(preview["outcomes"][0]["contact"]["phone"], "+14165550111")
        self.assertEqual(self._leads(), [])  # preview never writes

        result = self._commit(preview, tag="Spring list").get_json()
        self.assertEqual(result["summary"]["imported"], 2)
        self.assertEqual(result["summary"]["invalid"], 1)
        self.assertEqual(result["summary"]["warnings"], 1)
        leads = self._leads()
        self.assertEqual(len(leads), 2)
        for lead in leads:
            self.assertEqual(lead["tags"], ["Spring list"])
            self.assertTrue(lead["imported_at"])
            self.assertNotIn("email_consent_status", lead)
            self.assertNotIn("email_opt_out", lead)
            self.assertFalse(retainai.trig_new_lead(lead))
        self.assertTrue(retainai.trig_new_lead({"createdAt": datetime.now(timezone.utc).isoformat()}))

    def test_imported_contacts_get_no_automated_email_until_consent_is_recorded(self):
        # Consent is the variable under test; the workspace must also have a
        # real sender name before any customer birthday email is eligible.
        self.users[self.owner]["businessName"] = "Sample Studio"
        old = "2020-01-01T00:00:00Z"
        today = datetime.utcnow().strftime("%m-%d")
        imported = {"id": "i1", "name": "Imported", "email": "imp@example.com", "birthday": f"1990-{today}",
                    "createdAt": old, "imported_at": old, "source": "vcard"}
        manual = {"id": "m1", "name": "Manual", "email": "man@example.com", "createdAt": old}
        self.assertFalse(retainai.trig_no_reply(imported, 3))
        self.assertTrue(retainai.trig_no_reply(manual, 3))
        self.assertTrue(retainai.trig_no_reply({**imported, "email_consent_status": "confirmed"}, 3))
        with patch.object(retainai, "load_leads", return_value={self.owner: [imported]}), \
                patch.object(retainai, "send_birthday_email", return_value=True) as greet, \
                patch.object(retainai, "send_birthday_reminder_to_user"), patch.object(retainai, "log_notification"):
            retainai.send_birthday_greetings()
            greet.assert_not_called()
        with patch.object(retainai, "load_leads", return_value={self.owner: [{**imported, "email_consent_status": "confirmed"}]}), \
                patch.object(retainai, "send_birthday_email", return_value=True) as greet, \
                patch.object(retainai, "send_birthday_reminder_to_user"), patch.object(retainai, "log_notification"), \
                patch.object(retainai, "_email_unsubscribe_url", return_value="https://example.test/u"):
            retainai.send_birthday_greetings()
            greet.assert_called_once()
            self.assertEqual(greet.call_args.args[:3], ("imp@example.com", "Imported", "Sample Studio"))

    def test_duplicate_modes_and_dry_run(self):
        first = self._preview("a.csv", _csv(["Name", "Email", "Company"], ["Sam", "sam@example.com", ""])).get_json()
        self._commit(first)
        update = self._preview("b.csv", _csv(["Name", "Email", "Company"], ["Samuel", "sam@example.com", "Acme"])).get_json()
        self.assertEqual(update["outcomes"][0]["reason"], "already_in_crm")
        dry = self._commit(update, duplicate_mode="update", dry_run=True).get_json()
        self.assertEqual(dry["summary"]["updated"], 1)
        self.assertEqual(self._leads()[0]["name"], "Sam")  # dry run saved nothing
        self._commit(update, duplicate_mode="merge")
        self.assertEqual((self._leads()[0]["name"], self._leads()[0]["company"]), ("Sam", "Acme"))
        self._commit(update, duplicate_mode="update")
        self.assertEqual(self._leads()[0]["name"], "Samuel")
        self.assertEqual(len(self._leads()), 1)

    def test_commit_revalidates_client_rows_and_enforces_limits(self):
        forged = [{"raw": {"Email": "x" * 500 + "@example.com", "Name": "<script>" * 100}, "selected": True}]
        response = self.client.post("/api/import/file/commit", json={"rows": forged, "mapping": {"email": "Email", "name": "Name"}},
                                    headers={"Origin": "http://localhost:3000"})
        self.assertEqual(response.get_json()["summary"]["invalid"], 1)  # truncated email no longer valid
        too_many = [{"raw": {"Email": "a@b.co"}}] * (ci.MAX_ROWS + 1)
        response = self.client.post("/api/import/file/commit", json={"rows": too_many, "mapping": {"email": "Email"}},
                                    headers={"Origin": "http://localhost:3000"})
        self.assertEqual(response.status_code, 413)
        no_channel = self.client.post("/api/import/file/commit", json={"rows": [{"raw": {"Name": "x"}}], "mapping": {"name": "Name"}},
                                      headers={"Origin": "http://localhost:3000"})
        self.assertEqual(no_channel.status_code, 400)

    def test_imports_are_scoped_to_the_signed_in_workspace(self):
        other = f"other-{uuid.uuid4().hex[:8]}@example.com"
        self.users[other] = {"email": other, "role": "owner", "org_id": other, "status": "active", "security_version": 0}
        preview = self._preview("a.csv", _csv(["Email"], ["sam@example.com"])).get_json()
        self._commit(preview, client=self._client(other))
        self.assertEqual(self._leads(), [])
        self.assertEqual(len(self._leads(other)), 1)
        anonymous = retainai.app.test_client().post("/api/import/file/preview",
                                                     data={"file": (io.BytesIO(b"Email\na@b.co\n"), "a.csv")},
                                                     content_type="multipart/form-data")
        self.assertEqual(anonymous.status_code, 401)

    def test_undo_removes_only_that_import_and_restores_changed_contacts(self):
        self._commit(self._preview("a.csv", _csv(["Name", "Email"], ["Sam", "sam@example.com"])).get_json())
        second = self._preview("b.csv", _csv(["Name", "Email"], ["Samuel", "sam@example.com"], ["Pat", "pat@example.com"])).get_json()
        import_id = self._commit(second, duplicate_mode="update").get_json()["import"]["id"]
        retainai.save_user_leads(self.owner, self._leads() + [{"id": "manual", "name": "Added later", "email": "later@example.com"}])
        undone = self.client.post(f"/api/import/{import_id}/undo", headers={"Origin": "http://localhost:3000"}).get_json()
        self.assertEqual(undone["removed_contacts"], 1)
        names = sorted(lead["name"] for lead in self._leads())
        self.assertEqual(names, ["Added later", "Sam"])

    def test_rejects_unsupported_and_oversized_files(self):
        self.assertEqual(self._preview("contacts.xlsx", b"PK\x03\x04").status_code, 400)
        self.assertEqual(self._preview("big.csv", b"Email\n" + b"a" * ci.MAX_FILE_BYTES).status_code, 413)

    def _undo(self, import_id):
        return self.client.post(f"/api/import/{import_id}/undo", headers={"Origin": "http://localhost:3000"})

    def _by_email(self):
        return {lead["email"]: lead for lead in self._leads()}

    def test_undo_keeps_contacts_edited_after_the_import_and_reports_conflicts(self):
        self._commit(self._preview("a.csv", _csv(["Name", "Email"], ["Sam", "sam@example.com"], ["Kim", "kim@example.com"])).get_json())
        second = self._preview("b.csv", _csv(["Name", "Email"], ["Samuel", "sam@example.com"], ["Kimberly", "kim@example.com"],
                                             ["Pat", "pat@example.com"], ["Lee", "lee@example.com"])).get_json()
        import_id = self._commit(second, duplicate_mode="update").get_json()["import"]["id"]
        leads = self._leads()
        for lead in leads:
            if lead["email"] == "sam@example.com":
                lead["notes"] = "Called after the import"  # updated by the import, then edited
            if lead["email"] == "pat@example.com":
                lead["phone"] = "+14165550199"  # created by the import, then edited
        retainai.save_user_leads(self.owner, leads)

        undone = self._undo(import_id)
        self.assertEqual(undone.status_code, 200)
        body = undone.get_json()
        self.assertEqual((body["removed_contacts"], body["restored_contacts"], body["kept_contacts"]), (1, 1, 2))
        self.assertEqual({c["reason"] for c in body["conflicts"]}, {"edited_since_import"})
        after = self._by_email()
        self.assertNotIn("lee@example.com", after)  # untouched new contact removed
        self.assertEqual(after["kim@example.com"]["name"], "Kim")  # untouched update reverted
        self.assertEqual((after["sam@example.com"]["name"], after["sam@example.com"]["notes"]), ("Samuel", "Called after the import"))
        self.assertEqual(after["pat@example.com"]["phone"], "+14165550199")
        self.assertEqual(self._undo(import_id).status_code, 404)  # one undo per import

    def test_undo_still_works_after_the_contact_list_is_opened(self):
        # The import page reloads contacts right after a commit, and GET /api/leads
        # stores each contact's computed status. That is not an edit.
        self._commit(self._preview("a.csv", _csv(["Name", "Email"], ["Sam", "sam@example.com"])).get_json())
        second = self._preview("b.csv", _csv(["Name", "Email"], ["Samuel", "sam@example.com"], ["Pat", "pat@example.com"])).get_json()
        import_id = self._commit(second, duplicate_mode="update").get_json()["import"]["id"]
        listed = self.client.get("/api/leads", headers={"Origin": "http://localhost:3000"})
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(all(lead.get("status") for lead in self._leads()), "opening contacts stores a computed status")

        body = self._undo(import_id).get_json()
        self.assertEqual((body["removed_contacts"], body["restored_contacts"], body["kept_contacts"]), (1, 1, 0))
        self.assertEqual({lead["email"]: lead["name"] for lead in self._leads()}, {"sam@example.com": "Sam"})

    def test_a_real_edit_after_opening_contacts_is_still_kept(self):
        preview = self._preview("a.csv", _csv(["Name", "Email"], ["Pat", "pat@example.com"], ["Lee", "lee@example.com"])).get_json()
        import_id = self._commit(preview).get_json()["import"]["id"]
        self.client.get("/api/leads", headers={"Origin": "http://localhost:3000"})
        pat = self._by_email()["pat@example.com"]
        marked = self.client.post("/api/leads/contacted", json={"leadId": pat["id"]}, headers={"Origin": "http://localhost:3000"})
        self.assertEqual(marked.status_code, 200)

        body = self._undo(import_id).get_json()
        self.assertEqual((body["removed_contacts"], body["kept_contacts"]), (1, 1))
        self.assertEqual(list(self._by_email()), ["pat@example.com"])

    def test_unreadable_birthdays_are_reported_and_impossible_dates_rejected(self):
        self.assertEqual(ci.normalize_birthday("1990-02-14"), "1990-02-14")
        self.assertEqual(ci.normalize_birthday("19900214"), "1990-02-14")
        self.assertEqual(ci.normalize_birthday("--02-29"), "0000-02-29")
        for unreadable in ("2/14/1990", "14/02/1990", "1990-02-31", "1990-13-01", "0/0/00"):
            self.assertEqual(ci.normalize_birthday(unreadable), "", unreadable)

        preview = self._preview("outlook.csv", _csv(["First Name", "Last Name", "E-mail Address", "Birthday"],
                                                     ["Ava", "Example", "ava@example.com", "2/14/1990"],
                                                     ["Ben", "Sample", "ben@example.com", "1990-02-14"])).get_json()
        self.assertEqual([o["reason"] for o in preview["outcomes"]], ["invalid_birthday", ""])
        self.assertIn("YYYY-MM-DD", preview["reasons"]["invalid_birthday"])
        summary = self._commit(preview).get_json()["summary"]
        self.assertEqual((summary["imported"], summary["warnings"]), (2, 1))
        saved = self._by_email()
        self.assertEqual((saved["ava@example.com"]["birthday"], saved["ben@example.com"]["birthday"]), ("", "1990-02-14"))

    def test_legacy_full_list_undo_is_refused_without_touching_contacts(self):
        retainai.save_user_leads(self.owner, [{"id": "kept", "name": "Added after", "email": "after@example.com"}])
        history = app_imports._load_json_file(app_imports.IMPORT_HISTORY_FILE, {})
        history[self.owner] = [{"id": "legacy1", "created_at": 1, "label": "old.csv", "before": [], "summary": {}}]
        app_imports._save_json_file(app_imports.IMPORT_HISTORY_FILE, history)
        listed = self.client.get("/api/import/history").get_json()["imports"][0]
        self.assertFalse(listed["undo_available"])
        self.assertNotIn("before", listed)
        self.assertEqual(self._undo("legacy1").status_code, 409)
        self.assertEqual([lead["id"] for lead in self._leads()], ["kept"])

    def test_row_matching_two_different_contacts_is_skipped_as_identity_conflict(self):
        retainai.save_user_leads(self.owner, [
            {"id": "a", "name": "A", "email": "a@example.com", "phone": "+14165550111"},
            {"id": "b", "name": "B", "email": "b@example.com", "phone": "+14165550222"},
        ])
        before = self._leads()
        preview = self._preview("x.csv", _csv(["Name", "Email", "Phone"], ["Mixed", "a@example.com", "4165550222"])).get_json()
        self.assertEqual((preview["outcomes"][0]["status"], preview["outcomes"][0]["reason"]), ("skipped", "identity_conflict"))
        result = self._commit(preview, duplicate_mode="update").get_json()
        self.assertEqual((result["summary"]["updated"], result["summary"]["skipped"]), (0, 1))
        self.assertIsNone(result["import"])
        self.assertEqual(self._leads(), before)

    def test_updated_contacts_are_reindexed_so_old_identities_do_not_match(self):
        retainai.save_user_leads(self.owner, [{"id": "a", "name": "A", "email": "old@example.com", "phone": "+14165550111"}])
        preview = self._preview("x.csv", _csv(["Name", "Email", "Phone"],
                                              ["A moved", "new@example.com", "4165550111"],
                                              ["Someone else", "old@example.com", "4165550333"])).get_json()
        result = self._commit(preview, duplicate_mode="update").get_json()
        self.assertEqual([o["status"] for o in result["outcomes"]], ["updated", "imported"])
        after = self._by_email()
        self.assertEqual(after["new@example.com"]["id"], "a")
        self.assertEqual(after["old@example.com"]["name"], "Someone else")

    def test_malformed_requests_and_files_return_400(self):
        post = lambda body: self.client.post("/api/import/file/commit", json=body, headers={"Origin": "http://localhost:3000"})
        for body in ([{"raw": {"Email": "a@b.co"}}], "rows", 7, None):
            with self.subTest(body=body):
                self.assertEqual(post(body).status_code, 400)
        for rows in ([["a@b.co"]], ["a@b.co"], [{"raw": ["a@b.co"]}], [{"raw": {"Email": {"x": 1}}}]):
            with self.subTest(rows=rows):
                self.assertEqual(post({"rows": rows, "mapping": {"email": "Email"}}).status_code, 400)
        self.assertEqual(post({"rows": [{"raw": {"Email": "a@b.co"}}], "mapping": ["email"]}).status_code, 400)
        huge_field = b'Name,Email\n"' + b"a" * 200000 + b'",x@example.com\n'
        response = self._preview("big-field.csv", huge_field)
        self.assertEqual(response.status_code, 400)
        self.assertIn("could not be read", response.get_json()["error"])
        self.assertEqual(self._leads(), [])

    def test_merging_into_an_existing_contact_keeps_its_consent_and_automations(self):
        old = "2020-01-01T00:00:00Z"
        confirmed = {"id": "c", "name": "Client", "email": "client@example.com", "createdAt": old,
                     "email_consent_status": "confirmed", "email_consent_source": "workspace_user"}
        legacy_import = {"id": "l", "name": "Legacy", "email": "legacy@example.com", "createdAt": old, "source": "csv"}
        retainai.save_user_leads(self.owner, [confirmed, legacy_import])
        preview = self._preview("x.csv", _csv(["Name", "Email", "Company"], ["Client", "client@example.com", "Acme"])).get_json()
        self._commit(preview, duplicate_mode="merge")
        after = self._by_email()["client@example.com"]
        self.assertEqual((after["company"], after["email_consent_status"]), ("Acme", "confirmed"))
        self.assertNotIn("imported_at", after)
        self.assertTrue(retainai.trig_no_reply(after, 3))
        # Contacts imported before imports were marked keep their existing behaviour.
        self.assertTrue(retainai.trig_no_reply(legacy_import, 3))

    def test_simultaneous_commits_and_undo_do_not_overwrite_each_other(self):
        real_load = app_imports._load_leads_bucket

        def slow_load(user_email):
            leads = real_load(user_email)
            time.sleep(0.15)  # widen the read-modify-write window
            return leads

        first = self._preview("a.csv", _csv(["Email"], ["one@example.com"])).get_json()
        second = self._preview("b.csv", _csv(["Email"], ["two@example.com"])).get_json()
        seed = self._commit(self._preview("c.csv", _csv(["Email"], ["three@example.com"])).get_json()).get_json()["import"]["id"]
        results = []
        with patch.object(app_imports, "_load_leads_bucket", side_effect=slow_load):
            jobs = [
                threading.Thread(target=lambda: results.append(self._commit(first, client=self._client(self.owner)).status_code)),
                threading.Thread(target=lambda: results.append(self._commit(second, client=self._client(self.owner)).status_code)),
                threading.Thread(target=lambda: results.append(self._client(self.owner).post(
                    f"/api/import/{seed}/undo", headers={"Origin": "http://localhost:3000"}).status_code)),
            ]
            for job in jobs:
                job.start()
            for job in jobs:
                job.join()
        self.assertEqual(sorted(results), [200, 200, 200])
        self.assertEqual(sorted(self._by_email()), ["one@example.com", "two@example.com"])
        self.assertEqual(len(app_imports._load_json_file(app_imports.IMPORT_HISTORY_FILE, {})[self.owner]), 2)


if __name__ == "__main__":
    unittest.main()

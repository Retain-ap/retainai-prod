"""Contact file parsing, validated import, tenant isolation and safe undo."""

import io
import os
import tempfile
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


if __name__ == "__main__":
    unittest.main()

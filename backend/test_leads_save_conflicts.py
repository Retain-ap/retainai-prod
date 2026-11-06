"""Whole-list contact saves must never silently overwrite a concurrent change."""

import io
import os
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch


_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402
import app_imports  # noqa: E402
import storage  # noqa: E402

ORIGIN = {"Origin": "http://localhost:3000"}


class LeadSaveConflictTests(unittest.TestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        users = {self.owner: {"email": self.owner, "role": "owner", "org_id": self.owner, "status": "active", "security_version": 0}}
        patcher = patch.object(retainai, "load_users", side_effect=lambda: users)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.seed = [
            {"id": "a", "name": "Ana", "email": "ana@example.com", "createdAt": "2026-01-01T00:00:00Z", "last_contacted": "2026-11-01T00:00:00Z"},
            {"id": "b", "name": "Ben", "email": "ben@example.com", "createdAt": "2026-01-02T00:00:00Z", "last_contacted": "2026-11-01T00:00:00Z"},
        ]
        storage.save_user_leads(self.owner, self.seed)

    def client(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = self.owner
            signed["org_email"] = self.owner
            signed["security_version"] = 0
        return client

    def load(self, client=None):
        body = (client or self.client()).get("/api/leads", headers=ORIGIN).get_json()
        return body["leads"], body["revision"]

    def save(self, leads, revision=None, client=None):
        body = {"leads": leads}
        if revision is not None:
            body["base_revision"] = revision
        return (client or self.client()).post("/api/leads", json=body, headers=ORIGIN)

    def stored(self):
        return storage.load_user_leads(self.owner)

    def test_normal_save_returns_the_stored_list_and_its_revision(self):
        leads, revision = self.load()
        self.assertEqual(revision, storage.leads_revision(self.stored()))
        edited = [dict(leads[0], name="Ana Edited"), leads[1]]
        response = self.save(edited, revision)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual((body["ok"], body["count"]), (True, 2))
        self.assertEqual(body["revision"], self.load()[1])
        self.assertEqual(self.stored()[0]["name"], "Ana Edited")
        self.assertEqual(body["leads"], self.stored())  # exactly what was stored

    def test_unversioned_whole_list_save_is_refused_so_old_pages_cannot_erase_an_import(self):
        leads, _ = self.load()
        storage.save_user_leads(self.owner, self.stored() + [{"id": "c", "name": "Cara", "email": "cara@example.com", "imported_at": "2026-11-06T00:00:00Z"}])
        for revision in (None, ""):
            with self.subTest(revision=revision):
                body = {"leads": [dict(leads[0], name="Old page"), leads[1]]}
                if revision is not None:
                    body["base_revision"] = revision
                response = self.client().post("/api/leads", json=body, headers=ORIGIN)
                self.assertEqual(response.status_code, 428)
                self.assertEqual(response.get_json()["code"], "revision_required")
                self.assertIn("Reload", response.get_json()["error"])
        self.assertEqual([lead["name"] for lead in self.stored()], ["Ana", "Ben", "Cara"])

    def test_save_returns_the_stored_list_with_a_customer_unsubscribe_kept(self):
        withdrawn = dict(self.seed[1], email_opt_out=True, email_consent_status="withdrawn",
                         email_consent_updated_at="2026-11-05T00:00:00+00:00", email_consent_source="customer_unsubscribe_link")
        storage.save_user_leads(self.owner, [self.seed[0], withdrawn])
        leads, revision = self.load()
        # A page that still shows Ben before his unsubscribe edits his name.
        stale_ben = {key: value for key, value in leads[1].items() if not key.startswith("email_") or key == "email"}
        response = self.save([leads[0], dict(stale_ben, name="Benjamin")], revision)
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        returned = body["leads"][1]
        self.assertEqual((returned["name"], returned["email_opt_out"], returned["email_consent_source"]),
                         ("Benjamin", True, "customer_unsubscribe_link"))
        self.assertEqual(body["revision"], storage.leads_revision(self.stored()))
        self.assertEqual(body["leads"], self.stored())
        # The returned list and revision are a consistent base for the next save.
        self.assertEqual(self.save(body["leads"], body["revision"]).status_code, 200)

    def test_automation_add_tag_merges_into_the_current_contact_only(self):
        storage.save_user_leads(self.owner, [
            dict(self.seed[0], name="Ana Renamed Later", tags=["VIP"]),
            {"id": "x", "name": "No email", "email": ""},
            {"id": "y", "name": "Also no email", "email": ""},
        ])
        stale_run_copy = dict(self.seed[0], tags=[])
        retainai.execute_step({"owner": self.owner}, {"type": "add_tag", "tag": "Follow-up"}, stale_run_copy,
                              {"events": []}, {}, {})
        stored = {lead["id"]: lead for lead in self.stored()}
        self.assertEqual(stored["a"]["name"], "Ana Renamed Later")
        self.assertEqual(stored["a"]["tags"], ["Follow-up", "VIP"])
        self.assertNotIn("tags", stored["x"])
        # A contact without id is matched by a real email only, never by "" == "".
        retainai.execute_step({"owner": self.owner}, {"type": "add_tag", "tag": "Nope"}, {"email": "", "name": "Ghost"},
                              {"events": []}, {}, {})
        self.assertNotIn("tags", self.stored()[1])
        self.assertNotIn("tags", self.stored()[2])

    def test_stale_full_list_save_after_an_import_is_refused_and_keeps_imported_contacts(self):
        leads, revision = self.load()
        upload = self.client().post(
            "/api/import/file/preview", data={"file": (io.BytesIO(b"Name,Email\nCara,cara@example.com\n"), "c.csv")},
            content_type="multipart/form-data", headers=ORIGIN,
        ).get_json()
        committed = self.client().post("/api/import/file/commit", json={
            "rows": upload["rows"], "mapping": upload["mapping"], "source": "csv"}, headers=ORIGIN)
        self.assertEqual(committed.get_json()["summary"]["imported"], 1)

        stale = [dict(leads[0], name="Ana Edited"), leads[1]]  # built before the import
        response = self.save(stale, revision)
        self.assertEqual(response.status_code, 409)
        body = response.get_json()
        self.assertEqual(body["error"], "leads_changed")
        self.assertEqual(sorted(lead["email"] for lead in body["leads"]), ["ana@example.com", "ben@example.com", "cara@example.com"])
        self.assertEqual(body["revision"], storage.leads_revision(self.stored()))
        self.assertEqual(len(self.stored()), 3)  # imported contact survived
        self.assertEqual(self.stored()[0]["name"], "Ana")
        # The client re-applies its edit onto the current list and saves again.
        merged = [dict(lead, name="Ana Edited") if lead["id"] == "a" else lead for lead in body["leads"]]
        self.assertEqual(self.save(merged, body["revision"]).status_code, 200)
        self.assertEqual(sorted(lead["name"] for lead in self.stored()), ["Ana Edited", "Ben", "Cara"])

    def test_second_of_two_saves_from_the_same_revision_is_refused(self):
        leads, revision = self.load()
        first = self.save([dict(leads[0], name="From tab one"), leads[1]], revision)
        second = self.save([leads[0], dict(leads[1], name="From tab two")], revision)
        self.assertEqual((first.status_code, second.status_code), (200, 409))
        self.assertEqual(self.stored()[0]["name"], "From tab one")
        self.assertEqual(self.stored()[1]["name"], "Ben")

    def test_simultaneous_saves_are_checked_and_written_atomically(self):
        leads, revision = self.load()
        real_load = retainai.load_user_leads

        def slow_load(email):
            current = real_load(email)
            time.sleep(0.15)  # widen the check-then-write window
            return current

        results = {}

        def run(name, payload):
            results[name] = self.save(payload, revision).status_code

        with patch.object(retainai, "load_user_leads", side_effect=slow_load):
            jobs = [
                threading.Thread(target=run, args=("one", [dict(leads[0], name="One"), leads[1]])),
                threading.Thread(target=run, args=("two", [leads[0], dict(leads[1], name="Two")])),
            ]
            for job in jobs:
                job.start()
            for job in jobs:
                job.join()
        self.assertEqual(sorted(results.values()), [200, 409])
        names = sorted(lead["name"] for lead in self.stored())
        self.assertIn(names, (["Ben", "One"], ["Ana", "Two"]))

    def test_import_running_during_a_save_is_never_lost(self):
        leads, revision = self.load()
        upload = self.client().post(
            "/api/import/file/preview", data={"file": (io.BytesIO(b"Name,Email\nCara,cara@example.com\n"), "c.csv")},
            content_type="multipart/form-data", headers=ORIGIN,
        ).get_json()
        real_bucket = app_imports._load_leads_bucket

        def slow_bucket(email):
            current = real_bucket(email)
            time.sleep(0.15)
            return current

        results = {}
        with patch.object(app_imports, "_load_leads_bucket", side_effect=slow_bucket):
            importer = threading.Thread(target=lambda: results.setdefault("import", self.client().post(
                "/api/import/file/commit", json={"rows": upload["rows"], "mapping": upload["mapping"]}, headers=ORIGIN).status_code))
            importer.start()
            time.sleep(0.05)  # the import holds the lock and is mid-way
            results["save"] = self.save([dict(leads[0], name="Ana Edited"), leads[1]], revision).status_code
            importer.join()
        self.assertEqual((results["import"], results["save"]), (200, 409))
        self.assertIn("cara@example.com", [lead["email"] for lead in self.stored()])

    def test_server_side_writers_change_the_revision(self):
        leads, revision = self.load()
        marked = self.client().post("/api/leads/contacted", json={"leadId": "b"}, headers=ORIGIN)
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(self.save([dict(leads[0], name="Stale"), leads[1]], revision).status_code, 409)

    def test_malformed_save_requests_return_400(self):
        client = self.client()
        self.assertEqual(client.post("/api/leads", json=[{"id": "a"}], headers=ORIGIN).status_code, 400)
        self.assertEqual(self.save(self.seed, revision=123).status_code, 400)
        self.assertEqual(len(self.stored()), 2)

    def test_lock_is_reentrant_within_a_thread(self):
        done = threading.Event()

        def nested():
            with storage.leads_lock():
                with storage.leads_lock():
                    storage.save_user_leads(self.owner, self.seed[:1])
            done.set()

        worker = threading.Thread(target=nested)
        worker.start()
        worker.join(timeout=5)
        self.assertTrue(done.is_set())
        self.assertEqual(len(self.stored()), 1)


if __name__ == "__main__":
    unittest.main()

"""Off-Render backup tools: verify, seal, open and restore-drill a real archive."""

import json
import os
import sqlite3
import tempfile
import unittest
import uuid
import zipfile
from unittest.mock import patch

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import app as retainai  # noqa: E402
import app_owner  # noqa: E402
import backup_tools as bt  # noqa: E402

PASSPHRASE = "correct horse battery staple"


def make_archive(folder, *, with_db=True, extra=None):
    """Build an archive exactly like app_owner._backup_files does, on test data."""
    data_root = os.path.join(folder, "data")
    os.makedirs(data_root)
    with open(os.path.join(data_root, "users.json"), "w") as handle:
        json.dump({"owner@example.com": {"email": "owner@example.com"}, "b@example.com": {"email": "b@example.com"}}, handle)
    with open(os.path.join(data_root, "leads.json"), "w") as handle:
        json.dump({"owner@example.com": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}, handle)
    sqlite_path = os.path.join(data_root, "retainai.db")
    if with_db:
        connection = sqlite3.connect(sqlite_path)
        connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
        connection.execute("INSERT INTO notes (body) VALUES ('x')")
        connection.commit()
        connection.close()
    backups = os.path.join(data_root, "backups")
    with patch.object(app_owner, "BACKUP_ROOT", backups), patch.object(app_owner, "DATA_ROOT", data_root), \
            patch.object(app_owner, "SQLITE_PATH", sqlite_path if with_db else os.path.join(data_root, "missing.db")):
        path, _ = app_owner._backup_files()
    if extra:
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr(*extra)
    return path


class BackupToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["RETAINAI_BACKUP_PASSPHRASE"] = PASSPHRASE
        self.addCleanup(os.environ.pop, "RETAINAI_BACKUP_PASSPHRASE", None)

    def test_verifies_the_real_backup_format_and_reports_only_counts(self):
        path = make_archive(self.tmp.name)
        with open(f"{path}.sha256") as handle:
            checksum = handle.read().strip()
        report = bt.verify_archive(path, checksum)
        self.assertEqual(report["archive_sha256"], checksum)
        self.assertEqual(report["sqlite"], {"integrity": "ok", "tables": {"notes": 1}})
        self.assertEqual(report["json_records"], {"json/leads.json": 1, "json/users.json": 2})
        self.assertNotIn("owner@example.com", json.dumps(report))
        with self.assertRaisesRegex(bt.BackupError, "does not match"):
            bt.verify_archive(path, "0" * 64)

    def test_rejects_tampered_unlisted_and_unsafe_entries(self):
        path = make_archive(self.tmp.name)
        tampered = os.path.join(self.tmp.name, "tampered.zip")
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(tampered, "w") as target:
            for item in source.infolist():
                data = source.read(item.filename)
                target.writestr(item, data.replace(b'"3"', b'"9"') if item.filename == "json/leads.json" else data)
        with self.assertRaisesRegex(bt.BackupError, "Digest mismatch for json/leads.json"):
            bt.verify_archive(tampered)
        with self.assertRaisesRegex(bt.BackupError, "Unexpected entries"):
            bt.verify_archive(make_archive(os.path.join(self.tmp.name, "b"), extra=("../evil.json", "{}")))
        with self.assertRaisesRegex(bt.BackupError, "Manifest mismatch"):
            bt.verify_archive(make_archive(os.path.join(self.tmp.name, "c"), extra=("json/extra.json", "{}")))
        not_zip = os.path.join(self.tmp.name, "nope.zip")
        with open(not_zip, "wb") as handle:
            handle.write(b"plain text")
        with self.assertRaisesRegex(bt.BackupError, "Not a valid zip"):
            bt.verify_archive(not_zip)

    def test_seal_and_open_round_trip_and_detect_wrong_passphrase_or_damage(self):
        path = make_archive(self.tmp.name)
        sealed = os.path.join(self.tmp.name, "copy.rbk")
        digest = bt.seal(path, sealed, PASSPHRASE)
        with open(sealed, "rb") as handle:
            blob = handle.read()
        self.assertTrue(blob.startswith(bt.MAGIC))
        self.assertNotIn(b"owner@example.com", blob)
        restored = os.path.join(self.tmp.name, "restored.zip")
        self.assertEqual(bt.unseal(sealed, restored, PASSPHRASE), digest)
        self.assertEqual(bt.verify_archive(restored)["archive_sha256"], digest)
        with self.assertRaisesRegex(bt.BackupError, "Wrong passphrase"):
            bt.unseal(sealed, os.path.join(self.tmp.name, "x.zip"), "wrong passphrase here")
        damaged = os.path.join(self.tmp.name, "damaged.rbk")
        with open(damaged, "wb") as handle:
            handle.write(blob[:-1] + bytes([blob[-1] ^ 1]))
        with self.assertRaisesRegex(bt.BackupError, "changed or damaged"):
            bt.unseal(damaged, os.path.join(self.tmp.name, "y.zip"), PASSPHRASE)
        with self.assertRaisesRegex(bt.BackupError, "already exists"):
            bt.seal(path, sealed, PASSPHRASE)

    def test_restore_drill_reads_the_backup_back_with_retainai_storage(self):
        path = make_archive(self.tmp.name, with_db=False)
        sealed = os.path.join(self.tmp.name, "copy.rbk")
        bt.seal(path, sealed, PASSPHRASE)
        result = bt.restore_drill(sealed, os.path.join(self.tmp.name, "drill"), PASSPHRASE)
        self.assertEqual((result["users"], result["workspaces_with_contacts"], result["contacts"]), (2, 1, 3))
        self.assertEqual(result["storage_mode"], "json")
        with self.assertRaisesRegex(bt.BackupError, "new folder"):
            bt.restore_drill(sealed, os.path.join(self.tmp.name, "drill"), PASSPHRASE)
        drill = os.path.join(self.tmp.name, "drill")
        self.assertEqual(os.stat(drill).st_mode & 0o777, 0o700)
        for name in os.listdir(drill):
            self.assertEqual(os.stat(os.path.join(drill, name)).st_mode & 0o777, 0o600, name)

    def test_rejects_duplicate_link_and_bomb_entries_before_reading(self):
        path = make_archive(self.tmp.name)
        duplicate = os.path.join(self.tmp.name, "dup.zip")
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(duplicate, "w") as target:
            for item in source.infolist():
                target.writestr(item, source.read(item.filename))
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                target.writestr("json/users.json", "{}")
        with self.assertRaisesRegex(bt.BackupError, "Duplicate entry"):
            bt.verify_archive(duplicate)
        link = os.path.join(self.tmp.name, "link.zip")
        with zipfile.ZipFile(link, "w") as target:
            info = zipfile.ZipInfo("json/users.json")
            info.external_attr = (0o120777 << 16)
            target.writestr(info, "/etc/passwd")
        with self.assertRaisesRegex(bt.BackupError, "non-file entry"):
            bt.verify_archive(link)
        bomb = os.path.join(self.tmp.name, "bomb.zip")
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as target:
            target.writestr("json/users.json", b"0" * (64 * 1024 * 1024))
        with self.assertRaisesRegex(bt.BackupError, "expands suspiciously"):
            bt.verify_archive(bomb)
        with patch.object(bt, "MAX_TOTAL_BYTES", 10):
            with self.assertRaisesRegex(bt.BackupError, "too large when uncompressed"):
                bt.verify_archive(path)

    def test_outputs_are_owner_only_new_files_and_never_follow_links(self):
        path = make_archive(self.tmp.name)
        sealed = os.path.join(self.tmp.name, "copy.rbk")
        bt.seal(path, sealed, PASSPHRASE)
        self.assertEqual(os.stat(sealed).st_mode & 0o777, 0o600)
        target = os.path.join(self.tmp.name, "elsewhere.zip")
        trap = os.path.join(self.tmp.name, "trap.zip")
        os.symlink(target, trap)
        with self.assertRaisesRegex(bt.BackupError, "already exists"):
            bt.unseal(sealed, trap, PASSPHRASE)
        self.assertFalse(os.path.exists(target))
        restored = os.path.join(self.tmp.name, "restored.zip")
        bt.unseal(sealed, restored, PASSPHRASE)
        self.assertEqual(os.stat(restored).st_mode & 0o777, 0o600)
        linked_dir = os.path.join(self.tmp.name, "linked-dir")
        os.symlink(self.tmp.name, linked_dir)
        with self.assertRaisesRegex(bt.BackupError, "new folder"):
            bt.restore_drill(sealed, linked_dir, PASSPHRASE)

    def test_cli_never_takes_a_passphrase_argument_and_enforces_length(self):
        path = make_archive(self.tmp.name)
        os.environ["RETAINAI_BACKUP_PASSPHRASE"] = "short"
        self.assertEqual(bt.main(["seal", path, "--out", os.path.join(self.tmp.name, "s.rbk")]), 1)
        with self.assertRaises(SystemExit):
            bt.main(["seal", path, "--out", "x.rbk", "--passphrase", PASSPHRASE])
        with patch("sys.stdout"):
            self.assertEqual(bt.main(["verify", path]), 0)


class OwnerVerifyEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = make_archive(self.tmp.name)
        self.owner = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        users = {self.owner: {"email": self.owner, "role": "owner", "status": "active", "security_version": 0}}
        for patcher in (
            patch.object(retainai, "load_users", return_value=users),
            patch.object(app_owner, "BACKUP_ROOT", os.path.dirname(self.archive)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def client(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = self.owner
            signed["org_email"] = self.owner
            signed["security_version"] = 0
        return client

    def post(self, name, owner=True):
        with patch.object(app_owner, "is_platform_owner", return_value=owner):
            return self.client().post(f"/api/owner/backups/{name}/verify", headers={"Origin": "http://localhost:3000"})

    def test_platform_owner_can_verify_a_stored_backup(self):
        name = os.path.basename(self.archive)
        response = self.post(name)
        body = response.get_json()
        self.assertEqual(response.status_code, 200, body)
        self.assertEqual((body["ok"], body["checksum_file_matched"], body["sqlite_integrity"]), (True, True, "ok"))
        self.assertEqual(self.post(name, owner=False).status_code, 403)
        self.assertEqual(self.post("not-a-backup.zip").status_code, 400)

    def test_a_damaged_stored_backup_fails_verification(self):
        with open(f"{self.archive}.sha256", "w") as handle:
            handle.write("0" * 64)
        response = self.post(os.path.basename(self.archive))
        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()

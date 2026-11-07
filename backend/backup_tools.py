"""Verify, encrypt and restore-test RetainAI backups away from Render.

The daily backup (``app_owner._backup_files``) is a zip of the SQLite database
and JSON data files with a SHA-256 manifest. It lives on the same Render disk
as the data, so it does not protect against losing that disk or service.

This tool runs on the owner's own computer after downloading a backup through
the Owner Console (which requires owner sign-in and MFA):

    python backup_tools.py verify retainai-backup-....zip
    python backup_tools.py seal   retainai-backup-....zip --out backup.rbk
    python backup_tools.py open   backup.rbk --out restored.zip
    python backup_tools.py drill  backup.rbk --into ./restore-test

``open`` and ``drill`` write decrypted customer data, so they run only on Linux
and macOS, where the output is created owner-only (0600 files, 0700 folder) and
checked after creation. On native Windows, POSIX mode bits do not set a private
ACL, so those two commands refuse to run; use WSL or a Linux/macOS machine.
``verify`` and ``seal`` write no plaintext and work everywhere.

Output is limited to file names, sizes, digests and record counts: never
customer data. Passphrases come from RETAINAI_BACKUP_PASSPHRASE or a hidden
prompt, never from the command line.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"RAIBK1\n"
SALT_BYTES, NONCE_BYTES = 16, 12
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
MAX_ARCHIVE_BYTES = 2 * 1024 ** 3
MAX_ENTRY_BYTES = 2 * 1024 ** 3        # uncompressed, per file
MAX_TOTAL_BYTES = 4 * 1024 ** 3        # uncompressed, whole archive
MAX_JSON_BYTES = 256 * 1024 ** 2
MAX_RATIO = 200                        # compression ratio above this is treated as a zip bomb
MAX_ENTRIES = 200
MIN_PASSPHRASE = 12


class BackupError(Exception):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(name: str) -> bool:
    return (
        bool(name)
        and not name.startswith(("/", "\\"))
        and ".." not in name.replace("\\", "/").split("/")
        and (name in ("manifest.json", "retainai.db") or (name.startswith("json/") and name.endswith(".json") and name.count("/") == 1))
    )


def _check_entries(infos):
    """Reject zip bombs, duplicates, links and directories before reading."""
    if len(infos) > MAX_ENTRIES:
        raise BackupError("The archive has too many entries.")
    seen, total = set(), 0
    for info in infos:
        name = info.filename
        if name in seen:
            raise BackupError(f"Duplicate entry in archive: {name}")
        seen.add(name)
        mode = (info.external_attr >> 16) & 0o170000
        if info.is_dir() or mode in (stat.S_IFLNK, stat.S_IFDIR) or (mode and mode != stat.S_IFREG):
            raise BackupError(f"Unexpected non-file entry in archive: {name}")
        if info.file_size > MAX_ENTRY_BYTES:
            raise BackupError(f"{name} is too large when uncompressed.")
        if info.compress_size and info.file_size > 10 * 1024 ** 2 and info.file_size / info.compress_size > MAX_RATIO:
            raise BackupError(f"{name} expands suspiciously far; refusing to read it.")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise BackupError("The archive is too large when uncompressed.")


def _stream_digest(archive, name):
    digest, size = hashlib.sha256(), 0
    with archive.open(name) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            if size > MAX_ENTRY_BYTES:
                raise BackupError(f"{name} is larger than its header says.")
            digest.update(chunk)
    return size, digest.hexdigest()


def _read_bounded(archive, name, limit):
    with archive.open(name) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise BackupError(f"{name} is too large to inspect.")
    return data


def _posix_permissions() -> bool:
    """True where mode bits are the real access control (Linux, macOS)."""
    return os.name == "posix"


def _require_private_plaintext_output():
    if not _posix_permissions():
        raise BackupError(
            "Decrypting or restoring a backup is supported only on Linux and macOS, where the output can be made "
            "owner-only. On Windows, file mode bits don't set a private access list, so RetainAI won't write "
            "decrypted customer data here. Use WSL or a Linux/macOS computer."
        )


def _check_private(fd_or_path, mode):
    info = os.fstat(fd_or_path) if isinstance(fd_or_path, int) else os.lstat(fd_or_path)
    if info.st_mode & 0o077 or (hasattr(os, "geteuid") and info.st_uid != os.geteuid()) or info.st_mode & 0o777 != mode:
        raise BackupError("The output could not be made owner-only; nothing was written.")


def _new_private_file(path, *, plaintext=True):
    """Create a new owner-only file; never follow or replace an existing path."""
    if plaintext:
        _require_private_plaintext_output()
    if os.path.lexists(path):
        raise BackupError("The output file already exists; choose a new name.")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise BackupError("The output file already exists; choose a new name.") from None
    if _posix_permissions():
        try:
            _check_private(fd, 0o600)
        except BackupError:
            os.close(fd)
            os.remove(path)
            raise
    return os.fdopen(fd, "wb")


def _extract_private(archive, name, target):
    with archive.open(name) as src, _new_private_file(target) as dst:
        written = 0
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            written += len(chunk)
            if written > MAX_ENTRY_BYTES:
                raise BackupError(f"{name} is larger than its header says.")
            dst.write(chunk)


def verify_archive(path: str, expected_sha256: str = "") -> dict:
    """Check structure, manifest digests, SQLite integrity and JSON parsing."""
    if not os.path.isfile(path):
        raise BackupError("Backup file not found.")
    if os.path.getsize(path) > MAX_ARCHIVE_BYTES:
        raise BackupError("Backup is larger than 2 GB; check it is the right file.")
    archive_sha = _sha256_file(path)
    if expected_sha256 and archive_sha != expected_sha256.strip().lower():
        raise BackupError("The archive's SHA-256 does not match the expected checksum.")
    report = {"archive_sha256": archive_sha, "files": [], "sqlite": None, "json_records": {}}
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise BackupError("Not a valid zip archive.") from None
    with archive:
        infos = archive.infolist()
        _check_entries(infos)
        bad = archive.testzip()
        if bad:
            raise BackupError(f"Corrupted entry in archive: {bad}")
        names = [info.filename for info in infos]
        unsafe = [name for name in names if not _safe_member(name)]
        if unsafe:
            raise BackupError(f"Unexpected entries in archive: {', '.join(sorted(unsafe)[:5])}")
        if "manifest.json" not in names:
            raise BackupError("manifest.json is missing.")
        manifest = json.loads(_read_bounded(archive, "manifest.json", MAX_JSON_BYTES))
        listed = {row["name"]: row for row in manifest.get("files") or []}
        missing = sorted(set(listed) - set(names))
        extra = sorted(set(names) - set(listed) - {"manifest.json"})
        if missing or extra:
            raise BackupError(f"Manifest mismatch. Missing: {missing[:5]} Extra: {extra[:5]}")
        for name, row in sorted(listed.items()):
            size, digest = _stream_digest(archive, name)
            if size != int(row.get("bytes", -1)) or digest != row.get("sha256"):
                raise BackupError(f"Digest mismatch for {name}.")
            report["files"].append({"name": name, "bytes": size, "sha256": row["sha256"]})
            if name.endswith(".json"):
                try:
                    value = json.loads(_read_bounded(archive, name, MAX_JSON_BYTES))
                except ValueError:
                    raise BackupError(f"{name} is not valid JSON.") from None
                report["json_records"][name] = len(value) if isinstance(value, (dict, list)) else 1
            if name == "retainai.db":
                with tempfile.TemporaryDirectory() as scratch:
                    db_path = os.path.join(scratch, "check.db")
                    _extract_private(archive, name, db_path)
                    connection = sqlite3.connect(db_path)
                    try:
                        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                        tables = {
                            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                            for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                        }
                    finally:
                        connection.close()
                if result != "ok":
                    raise BackupError("SQLite integrity check failed.")
                report["sqlite"] = {"integrity": result, "tables": tables}
        report["created_at"] = manifest.get("created_at", "")
        report["storage_mode"] = manifest.get("storage_mode", "")
    return report


def _passphrase(confirm: bool) -> str:
    value = os.environ.get("RETAINAI_BACKUP_PASSPHRASE")
    if value is None:
        value = getpass.getpass("Backup passphrase: ")
        if confirm and getpass.getpass("Repeat passphrase: ") != value:
            raise BackupError("Passphrases do not match.")
    if len(value) < MIN_PASSPHRASE:
        raise BackupError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters.")
    return value


def _key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).derive(passphrase.encode("utf-8"))


def seal(archive_path: str, out_path: str, passphrase: str) -> str:
    """Verify, then encrypt the archive. The digest is authenticated too."""
    report = verify_archive(archive_path)
    with open(archive_path, "rb") as handle:
        plaintext = handle.read()
    salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
    header = MAGIC + salt + nonce
    ciphertext = AESGCM(_key(passphrase, salt)).encrypt(nonce, plaintext, header)
    with _new_private_file(out_path, plaintext=False) as handle:  # ciphertext only
        handle.write(header + ciphertext)
    return report["archive_sha256"]


def unseal(sealed_path: str, out_path: str, passphrase: str) -> str:
    _require_private_plaintext_output()
    with open(sealed_path, "rb") as handle:
        blob = handle.read()
    if not blob.startswith(MAGIC):
        raise BackupError("Not a sealed RetainAI backup.")
    salt = blob[len(MAGIC):len(MAGIC) + SALT_BYTES]
    nonce = blob[len(MAGIC) + SALT_BYTES:len(MAGIC) + SALT_BYTES + NONCE_BYTES]
    header = blob[:len(MAGIC) + SALT_BYTES + NONCE_BYTES]
    try:
        plaintext = AESGCM(_key(passphrase, salt)).decrypt(nonce, blob[len(header):], header)
    except InvalidTag:
        raise BackupError("Wrong passphrase, or the file was changed or damaged.") from None
    with _new_private_file(out_path) as handle:
        handle.write(plaintext)
    return _sha256_bytes(plaintext)


def restore_drill(source: str, into: str, passphrase: str | None = None) -> dict:
    """Restore into an empty folder and start the app's storage layer on it.

    Never touches production. Proves the backup can be read back by RetainAI's
    own code, reporting only counts.
    """
    _require_private_plaintext_output()
    if os.path.lexists(into):
        raise BackupError("Restore into a new folder that does not exist yet.")
    os.makedirs(into, mode=0o700)
    os.chmod(into, 0o700)  # makedirs applies the umask; make the folder exactly owner-only
    _check_private(into, 0o700)
    with tempfile.TemporaryDirectory() as scratch:  # mkdtemp: owner-only on POSIX
        archive = source
        if not zipfile.is_zipfile(source):
            archive = os.path.join(scratch, "restored.zip")
            unseal(source, archive, passphrase if passphrase is not None else _passphrase(False))
        report = verify_archive(archive)
        with zipfile.ZipFile(archive) as opened:
            for row in report["files"]:
                _extract_private(opened, row["name"], os.path.join(into, row["name"].split("/", 1)[-1]))
    use_sqlite = os.path.isfile(os.path.join(into, "retainai.db"))
    probe = (
        "import storage, json;"
        "users = storage.load_users() or {}; leads = storage.load_leads() or {};"
        "print(json.dumps({'users': len(users), 'workspaces_with_contacts': len(leads),"
        " 'contacts': sum(len(v) for v in leads.values() if isinstance(v, list))}))"
    )
    # A minimal environment: no provider keys, no scheduler, so the drill can't
    # send messages, refresh tokens or reach any service with restored data.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "RUN_SCHEDULER": "0",
        "DATA_ROOT": into,
        "USE_SQLITE": "true" if use_sqlite else "false",
        "SQLITE_PATH": os.path.join(into, "retainai.db"),
    }
    completed = subprocess.run(
        [sys.executable, "-c", probe], cwd=os.path.dirname(os.path.abspath(__file__)),
        env=env, capture_output=True, text=True, timeout=120,
    )
    if completed.returncode != 0:
        raise BackupError("RetainAI's storage layer could not read the restored data.")
    counts = json.loads(completed.stdout.strip().splitlines()[-1])
    return {"archive_sha256": report["archive_sha256"], "restored_files": len(report["files"]), "storage_mode": "sqlite" if use_sqlite else "json", **counts}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="check a downloaded .zip backup")
    verify.add_argument("archive")
    verify.add_argument("--sha256", default="", help="expected checksum shown in the Owner Console")
    sealer = sub.add_parser("seal", help="verify and encrypt a .zip backup")
    sealer.add_argument("archive")
    sealer.add_argument("--out", required=True)
    opener = sub.add_parser("open", help="decrypt a sealed backup to a .zip")
    opener.add_argument("sealed")
    opener.add_argument("--out", required=True)
    drill = sub.add_parser("drill", help="restore into an empty folder and read it back")
    drill.add_argument("source")
    drill.add_argument("--into", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            result = verify_archive(args.archive, args.sha256)
        elif args.command == "seal":
            result = {"sealed": args.out, "archive_sha256": seal(args.archive, args.out, _passphrase(True))}
        elif args.command == "open":
            result = {"restored": args.out, "archive_sha256": unseal(args.sealed, args.out, _passphrase(False))}
        else:
            result = restore_drill(args.source, args.into)
    except BackupError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

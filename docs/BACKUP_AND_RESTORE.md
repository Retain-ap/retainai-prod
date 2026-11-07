# RetainAI backups: off-Render copy and restore

## What exists today (checked November 6, 2026, read-only)

- The backend scheduler creates
  `/var/retainai/backups/retainai-backup-<UTC time>.zip` at 03:20 UTC every day.
  Render logs show one archive of 15 files every day from October 31 to
  November 6.
- Each archive holds the SQLite database (copied with SQLite's online backup)
  and every JSON data file, plus `manifest.json` with each file's size and
  SHA-256. A `.sha256` file stores the archive's own checksum. The last 14 are
  kept (`BACKUP_RETENTION_COUNT`).
- The server archives still sit on the same Render disk and are not encrypted
  there. A real production archive was downloaded, encrypted and independently
  restored on the owner's computer on November 7 UTC (details below).
  A second private cloud copy and recurring off-site retention remain open.

## What a backup contains and needs

- It holds customer contact data, so treat every copy as confidential. Never
  put it in Git, chat, email or a shared folder.
- Secrets stored in the data (Google tokens, MFA secrets) are encrypted with
  `DATA_ENCRYPTION_KEY`. A restore is only fully usable together with that key,
  and with `PREVIOUS_DATA_ENCRYPTION_KEY` if keys were rotated. Keep the keys
  in the owner's password manager, **separate from the backup copies**.

## Weekly off-Render copy (owner, about 5 minutes)

Run these steps on the owner's own computer, from a checkout of this
repository, with Python 3.11 or 3.12 and `pip install -r backend/requirements.txt`.

**Platforms.** Use Linux or macOS for the complete procedure. Verifying a
SQLite archive extracts a temporary database for its integrity check; `seal`
also performs that verification. Plaintext output is supported **only on Linux
and macOS**: there the tool creates the output owner-only (files 0600, folder 0700)
and checks it after creating it. On native Windows, mode bits don't set a
private access list (DACL), so `open` and `drill` refuse to run instead of
claiming private output. Use WSL's Linux filesystem (not `/mnt/c`) or a
Linux/macOS computer for temporary and restored files until a
Windows wrapper that sets and checks a private ACL exists. The downloaded
`.zip` from step 3 is plaintext on any platform: keep it in a private folder
and delete it after sealing.

1. Sign in to RetainAI as the platform owner (MFA required). Open
   **Owner Console > Backups**.
2. Press **Verify** on the newest backup. It must say that the files match the
   manifest and the stored checksum, and that the database is `ok`.
3. Press **Download**. Note the SHA-256 shown in the list.
4. Check the download:
   ```
   python backend/backup_tools.py verify ~/Downloads/retainai-backup-<time>.zip --sha256 <checksum from step 3>
   ```
5. Encrypt it with a passphrase of at least 12 characters. The tool asks for it
   twice and never shows it.
   ```
   python backend/backup_tools.py seal ~/Downloads/retainai-backup-<time>.zip --out retainai-<date>.rbk
   ```
   The `.rbk` file uses AES-256-GCM with a scrypt-derived key. Any change to the
   file makes decryption fail.
6. Store `retainai-<date>.rbk` in **two places the owner controls** that are not
   Render, for example an encrypted USB drive and the owner's existing cloud
   drive. Store the passphrase in the password manager.
7. Delete the unencrypted `.zip` from Downloads.

Keep at least the last 4 weekly copies and one from each month.

## Restore drill (quarterly, and after any storage change, Linux/macOS)

The drill restores into an empty folder on the owner's computer and has
RetainAI's own storage code read it back. It never touches production.

```
python backend/backup_tools.py drill retainai-<date>.rbk --into ./restore-test-<date>
```

It prints only counts (users, workspaces with contacts, contacts) and the
archive checksum. Compare the counts with the Owner Console. Then delete the
`restore-test-<date>` folder.

### What has and hasn't been proven

- **Proven on a fixture only.** In PR37 the `verify`, `seal` and `drill` steps
  ran end to end on a **local test archive built from seed data** (1 user,
  12 contacts) in a disposable folder, plus the automated tests in
  `backend/test_backup_tools.py`. That shows the tool works on the real backup
  format. It is **not** evidence that a production backup has been copied off
  Render or restored.
- **Production drill completed by Codex, November 7 UTC:** the owner signed
  into the MFA-protected Owner Console. A fresh archive,
  `retainai-backup-20261107T021411Z.zip`, passed the server checksum/manifest
  check and SQLite integrity check, then was downloaded and sealed with
  scrypt/AES-256-GCM. An independent restore using the app's own storage layer
  recovered **5 users, 1 workspace with contacts, 5 contacts and 15 files**,
  matching the observed Owner Console totals. SQLite integrity was `ok`.
  The restore ran inside a mode-0700 directory on WSL Ubuntu's Linux
  filesystem, with no provider credentials or scheduler loaded. The restored
  plaintext and the original downloaded ZIP were removed after verification.
  The encrypted archive remains in the owner's private Windows recovery
  folder, with its new passphrase protected separately by current-user DPAPI.
  - Original archive SHA-256:
    `5c9ac60ff0a13716b279dda663641979ff751f2f57eaeaa4aeae48d2f194976e`
  - Encrypted `.rbk` SHA-256:
    `4b2327823e551be496720ef1b2304e768db4c7c8234e365f7e310e12da39e480`
  - **Still open:** private cloud upload and round-trip verification,
    independent password-manager recovery-key custody, production
    `DATA_ENCRYPTION_KEY` escrow and recurring off-site copies. Do not describe
    this local drill as proof of those separate requirements.

## Restoring production (only in a real data loss)

1. Pick the newest `.rbk` whose drill passed. Run `open` to recover the `.zip`,
   then `verify` it.
2. On Render, take a fresh backup of whatever is left first, and stop
   background jobs (set `RUN_SCHEDULER=0`).
3. Copy the archive's files back to `DATA_ROOT` (`/var/retainai`):
   `retainai.db` at the root, and `json/*.json` as `*.json` at the root. This
   needs owner access to the service's shell through the Render dashboard.
4. Make sure `DATA_ENCRYPTION_KEY` is the key that was in use when the backup
   was made, restart the service, sign in, and check contacts and settings.
   Then set `RUN_SCHEDULER=1` again.

Do not restore by any route that skips owner MFA or weakens access.

## Blockers needing owner credentials (not done by Claude)

- **Owner Console access worked for the November 7 local copy and drill.**
  Future copies still require owner MFA or authorized service-shell access.
  Do not bypass MFA or weaken SSH authentication to automate them.
- **Automatic off-site copies** (for example to object storage) would need the
  owner to choose a storage provider and create a write-only credential for it.
  Nothing was chosen or bought. Until then the weekly manual copy above is the
  off-Render backup.
- **Encryption keys:** the owner must confirm `DATA_ENCRYPTION_KEY` (and any
  previous key) is stored in their password manager. It is visible only to the
  owner in Render's environment settings.

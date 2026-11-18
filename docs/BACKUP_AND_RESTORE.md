# RetainAI backups: off-Render copy and restore

## Current evidence (November 18, 2026)

- The backend scheduler creates
  `/var/retainai/backups/retainai-backup-<UTC time>.zip` at 03:20 UTC every day.
  Scheduled runs were observed in Render logs on November 16 and 17. These
  server snapshots alone are not off-site copies.
- Each archive holds the SQLite database (copied with SQLite's online backup)
  and every JSON data file, plus `manifest.json` with each file's size and
  SHA-256. A `.sha256` file stores the archive's own checksum. The last 14 are
  kept (`BACKUP_RETENTION_COUNT`).
- The server archives still sit on the same Render disk and are not encrypted
  there. The November 18 recovery point has a verified encrypted local copy
  and a private OneDrive copy that was downloaded again, decrypted and checked.
  The downloaded cloud copy also passed an isolated application startup and
  storage check (details below). Historical encrypted archives were preserved.
- The existing OneDrive **RetainAI Backups** folder is visible through the
  owner's signed-in desktop sync client. A new cloud credential is not required
  to stage encrypted files there. A successful local copy alone does not prove
  that an upload completed; retain separate cloud verification evidence.
- The existing weekly local recovery task checks an already-downloaded
  encrypted archive. It does not capture, download or upload fresh snapshots.
  **Unattended fresh off-site copying is not configured.** Independent recovery
  key custody and production integration-token decryption remain unverified.

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
Linux/macOS computer for temporary and restored files. Separately reviewed
owner-local Windows helpers now check private ACLs and pass the existing
DPAPI-protected key through stdin for sealing and verification. Those helpers
are not part of this repository's CLI and do not remove its platform guard.
The downloaded
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
6. Preserve a private local encrypted copy and upload only the `.rbk` to the
   existing private OneDrive **RetainAI Backups** folder. Never upload the ZIP
   or recovery key. Download the cloud copy separately, compare its encrypted
   checksum, then decrypt and verify the complete archive. Desktop sync can
   transport the file, but a queued/local file is not cloud round-trip proof.
   Keep the recovery passphrase independently in the owner's password manager.
7. After the encrypted cloud round trip passes, delete the exact temporary
   unencrypted `.zip`. Preserve the encrypted archives and verification receipts.

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

- **Historical fixture check.** In PR37 the `verify`, `seal` and `drill` steps
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
  - This November 7 drill established local recovery. Later cloud and startup
    verification is recorded below; independent key custody and recurring
    fresh off-site copying remain separate requirements.
- **Cloud round trip and actual application startup, November 18 UTC:**
  `retainai-backup-20261118T085556Z.zip` was captured at 08:55:56 UTC and sealed
  with the existing recovery key as `retainai-backup-20261118T085556Z.rbk`.
  The encrypted file was uploaded to the existing private OneDrive folder,
  downloaded again, hash-matched, decrypted, and verified against its complete
  manifest and SQLite integrity/foreign-key checks. It recovered **6 users,
  8 contacts, 3 workspaces with contacts and 18 files**. The key was neither
  uploaded nor rotated, and the temporary plaintext download was removed.
  - Original archive SHA-256:
    `9eb4632373dc20b41a13cdb3f61b420699822a2a47b54dd7ffa3c4366c6bba72`
  - Encrypted `.rbk` SHA-256:
    `924fa84e8e96449c7d0750fcf4a347fded6a7adc96ce19df461f5537c01c3499`
  - At 09:16:58 UTC the downloaded cloud copy passed the unchanged backend at
    `15994c007e535cd0a38d4ad9fc4275f52fda9df3`: actual storage startup returned
    matching counts, `/api/health` returned 200, and storage readiness passed.
    The probe used real Linux `fcntl` locks and an owner-only RAM filesystem
    inside an isolated network namespace. Restored JSON remained unchanged
    and RAM cleanup was independently verified.
  - No network requests, scheduler jobs, workers or production environment
    credentials were used. One urllib3 import-time IPv6 capability probe was
    blocked before socket creation and counted separately. Temporary
    process-only keys allowed startup without retrieving production keys.
  - This does **not** verify customer login, provider readiness, integration-token
    decryption, independent recovery-key custody, or startup of later commits.
    The operator retains the sanitized receipts
    `retainai-onedrive-backup-proof-20261118.json` and
    `retain-app-restore-production-proof-20261118.json`; archive data, private
    account identifiers and credentials are not included in this repository.
  - This recovery point contains `automations_state.json`. The lazily created
    `lead_reminder_state.json` and `automatic_email_dispatch.json` were absent.
    It also predates the owner reminder preference introduced in PR86
    (`6319addfde19dd77cecafe32a5af31a2f417a4a2`). Do not treat absent state as
    permission to send or fabricate delivery markers during restoration.

## Restoring production (only in a real data loss)

1. Pick the newest `.rbk` whose drill passed. Run `open` to recover the `.zip`,
   then `verify` it.
2. On Render, take a fresh backup of whatever is left first, and stop
   background jobs (set `RUN_SCHEDULER=0`).
3. Copy the archive's files back to `DATA_ROOT` (`/var/retainai`):
   `retainai.db` at the root, and `json/*.json` as `*.json` at the root. This
   needs owner access to the service's shell through the Render dashboard.
4. Restore the original `DATA_ENCRYPTION_KEY` and any required
   `PREVIOUS_DATA_ENCRYPTION_KEY` through the authorized secret-management path.
   Restart with `RUN_SCHEDULER=0`, sign in, and check contacts, settings and
   required encrypted integrations. A readable database does not prove that
   its encrypted tokens can be recovered.
5. Before enabling any background sending, reconcile `email_preferences.json`,
   `lead_reminder_state.json`, `automatic_email_dispatch.json` and
   `automations_state.json` with surviving newer state and provider history,
   including attempts after the archive's recovery point. Preserve pending or
   uncertain claims and quarantined history; do not clear them to force retries.
   Missing reminder preferences default to enabled, so restore the owner's
   current choice explicitly. See [owner reminder recovery behavior](LEAD_REMINDER_FREQUENCY.md).
6. Set `RUN_SCHEDULER=1` only after the recovered preferences and delivery state
   are consistent and required application checks pass. Leave scheduling
   disabled if delivery history or consent/preferences remain uncertain.

Do not restore by any route that skips owner MFA or weakens access.

## Remaining recovery and automation gaps

- **Owner Console access was used for the verified November 18 recovery point.**
  Future copies still require owner MFA or authorized service-shell access.
  Do not bypass MFA or weaken SSH authentication to automate them.
- **Unattended source retrieval is the missing component.** The encrypted
  destination, local sealing key and local verifier already exist. Backup
  endpoints require an authenticated, MFA-assured owner session; no working
  noninteractive server-download route has been established. The previously
  tested SSH key was rejected. The existing OneDrive client can carry encrypted
  files once captured, but neither sync nor the weekly verification task makes
  capture unattended. Do not extract browser tokens or weaken MFA/SSH checks.
- **Independent key custody and token recovery remain unverified.** Confirm
  separate password-manager custody of both the outer archive recovery
  passphrase and the original production `DATA_ENCRYPTION_KEY` (plus any required
  previous key), accessible without this computer/Windows account. A working
  local DPAPI envelope and a private cloud archive do not establish that
  independence. No production encryption key was retrieved for the startup drill.

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
- **Gap:** the archives sit on the same Render disk as the data and are not
  encrypted there. Losing the disk or the service loses the backups too. Until
  this procedure is followed, no off-Render copy and no restore drill exist.

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

## Restore drill (quarterly, and after any storage change)

The drill restores into an empty folder on the owner's computer and has
RetainAI's own storage code read it back. It never touches production.

```
python backend/backup_tools.py drill retainai-<date>.rbk --into ./restore-test-<date>
```

It prints only counts (users, workspaces with contacts, contacts) and the
archive checksum. Compare the counts with the Owner Console. Then delete the
`restore-test-<date>` folder.

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

- **Copying backups off Render** needs the owner's MFA-protected Owner Console
  sign-in, or owner access to the service shell. Claude has neither, by design.
  Codex's Render SSH attempt was refused with `publickey`, and the right fix is
  the owner adding their own SSH key, not weakening access.
- **Automatic off-site copies** (for example to object storage) would need the
  owner to choose a storage provider and create a write-only credential for it.
  Nothing was chosen or bought. Until then the weekly manual copy above is the
  off-Render backup.
- **Encryption keys:** the owner must confirm `DATA_ENCRYPTION_KEY` (and any
  previous key) is stored in their password manager. It is visible only to the
  owner in Render's environment settings.

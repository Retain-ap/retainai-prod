# Contact import and safe contact saves: November 6, 2026

Mateo asked, through Codex, for an easier contact import. The import work then
turned up places where saving the contact list could lose data. Claude wrote and
tested each pull request against a disposable local backend; Codex reviewed, merged
and checked Render. No production data was written by Claude, and no customer was
emailed.

## Shipped to `deploy`

| PR | Merged as | What it does |
| --- | --- | --- |
| [#33](https://github.com/Retain-ap/retainai-prod/pull/33) | `4c80df5` | One Import screen for CSV and vCard (.vcf) files: Apple, iCloud, Outlook, Android and WhatsApp-shared contact cards, plus HubSpot, Salesforce, Pipedrive, Zoho, Google and Outlook CSV presets. It has editable column matching, row review with reasons, limits of 5 MB and 5,000 rows, server-side re-validation, duplicate and identity-conflict handling, and an undo that keeps later edits (older imports refuse undo with 409). Imported contacts are never marked as consenting, and get no automated emails until consent is confirmed on their profile. WhatsApp has no contact export; only contact cards or the phone's address book are imported, never chats. |
| [#34](https://github.com/Retain-ap/retainai-prod/pull/34) | `c74b3a3` | Whole-list contact saves can no longer overwrite imports, other tabs or webhook updates. `GET /api/leads` returns a revision. `POST` requires `base_revision`: a missing one gets **428** (reload required) and a stale one gets **409** with the current list. Every contact writer shares one lock across both gunicorn workers. The dashboard, Appointments and the contact drawer all save through `frontend/src/leadSync.js`: the confirmed list plus the user's own field changes, re-applied after a 409. Failed saves stay on the device with a Retry button. |
| [#35](https://github.com/Retain-ap/retainai-prod/pull/35) | open, not merged | Fixes appointments stored on a contact without a `_localKey`. Done, edit, reschedule, delete and visit notes matched nothing, so nothing was saved. Identical appointments now stay distinct. |

## Things to know

- **Old tabs after #34:** pages opened before the #34 deploy get "reload required"
  when saving contacts. Their immediate saves show the message; their debounced
  saves (for example "mark contacted") keep the edit only in that tab until it is
  reloaded. Nothing on the server is overwritten.
- **Unsaved edits** are kept in memory for the session only.
- **Same field edited twice at once:** the later save wins, and the user isn't told.

## Closet Muse and Apple (status relayed by Codex, not checked by Claude)

- Live at `628b36e`.
- Native build 2 (from `2f31f69`) is valid and in TestFlight beta testing, with the
  owner group assigned.
- Apple disclosures are published. One new screenshot was still processing before
  the version is added back to the unsubmitted review draft.
- **No public App Review submission has been made.**

## Open

- Codex is verifying the Render deploys of #33 and #34.
- PR #35 needs review and merge.
- The earlier open items in [Joint launch completion](2026-11-06-joint-launch-completion.md)
  are unchanged: Google verification replies, Apple tax and banking, device and
  purchase acceptance, and off-Render backups.

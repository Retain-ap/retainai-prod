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
| [#35](https://github.com/Retain-ap/retainai-prod/pull/35) | `a4dcd17` | Fixes appointments stored on a contact without a `_localKey`. Done, edit, reschedule, delete and visit notes matched nothing, so nothing was saved. Identical appointments now stay distinct. |

## Validation

- Frontend `srv-d4n4hna4d50c73f5u2v0` is live at `a4dcd170800a1b3493b9d13aff006b54a75bf2c3`:
  deployment `dep-dbmr3kbm8hqs73b7irp0`, finished `2026-11-06T10:55:11.776Z`.
  PR #35's squash message inherited a documentation skip phrase, so Codex
  explicitly deployed the latest commit after confirming no automatic deploy
  had started. Automatic deployment remains enabled.
- Backend `srv-d3co8ul6ubrc73evtrj0` is live at
  `c74b3a3bf9980a2aff8c386c55033ca64003ca4c`, deployment
  `dep-dbmquq5g1s2s73d9r8e0`, finished `2026-11-06T10:44:54.682Z`.
  PR #35 changes no backend files, so no additional backend restart was needed.
- Post-release checks at 10:55 UTC returned 200 for the website and backend
  health endpoint, and 401 for anonymous import history. No error-level backend
  application logs appeared between the backend deploy and this check.
- Final RetainAI checks: 114 backend tests, 77 frontend tests, lint, build,
  dependency audits and secret scanning passed. All three PR #35 CI jobs passed
  on reviewed head `02b562898e2a7bf7ea7f7650784b9a06b74389bf`.
- Disposable real-backend browser checks covered an import racing with a stale
  dashboard save, initial-load failure recovery, rejection of unversioned saves,
  and completing the second of two identical legacy appointments while keeping a
  concurrent import. No live customer contact was changed for these tests.
- These are file imports, not continuous OAuth synchronization with each CRM.
  WhatsApp support means shared contact cards/address-book contacts, not chat
  history. New imported contacts require confirmed consent before automation;
  updating an existing contact preserves its consent and history.

## Things to know

- **Old tabs after #34:** pages opened before the #34 deploy get "reload required"
  when saving contacts. Their immediate saves show the message; their debounced
  saves (for example "mark contacted") keep the edit only in that tab until it is
  reloaded. Nothing on the server is overwritten.
- **Unsaved edits** are kept in memory for the session only.
- **Same field edited twice at once:** the later save wins, and the user isn't told.

## Closet Muse and Apple (verified by Codex)

- Web community is live at `628b36e`, Render deployment
  `dep-dbmqf77avr4c73924ra0`, completed `2026-11-06T10:12:33.978Z`.
  Friends, accepted-friend text messaging, outfit sharing/saves and inspiration
  feeds are available. Existing private closets remain private until shared.
  The community is opt-in and 18+; public posts are visible within the member
  community, not an anonymous public website.
- Native build 2 (from `2f31f69`) is valid and in TestFlight beta testing, with the
  owner group assigned.
- Updated Apple privacy disclosures are published; 13 listing screenshots are
  processed. Build 2 is selected and the three-item review draft is
  `READY_FOR_REVIEW` with `submittedDate: null`. An optional stalled iPhone inbox
  screenshot reservation was removed; its original file is retained locally.
- Closet Muse checks: 612 tests passed (6 platform skips), 112 built-server HTTP
  checks, lint/typecheck/build, and 48 native unit/UI test executions on iPhone
  and iPad simulators. All 17 production smoke checks passed on the live web SHA.
- Current complete community handoff:
  [COMMUNITY.md](https://github.com/Retain-ap/closet-muse/blob/main/docs/COMMUNITY.md),
  merged through [PR #21](https://github.com/Retain-ap/closet-muse/pull/21).
- **No public App Review submission has been made.**

## Remaining owner/provider work

- Reload RetainAI tabs opened before this release before making more edits; first
  copy any unsaved work because session-memory changes do not survive a reload.
- Test Closet Muse build 2 on a physical iPhone, including camera/photo access,
  friend messaging and sandbox purchase/restore. Simulator tests do not substitute
  for this acceptance. Existing Canadian Apple business/tax requirements remain;
  no banking or tax action was performed during this feature release.
- Check Owner Studio > Community daily. All outfit submissions require owner
  approval before publication; reports and suspensions are handled there.
- Earlier Google review, independent-backup and provider gates are documented in
  [Joint launch completion](2026-11-06-joint-launch-completion.md). That document
  is a historical snapshot, not a fresh verification of every provider status;
  completed Apple tax/contact steps in the later session must not be repeated.

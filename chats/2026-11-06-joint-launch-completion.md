# Joint launch completion pass — November 6, 2026

Mateo asked Codex and Claude to work together on remaining fixes, testing and
release preparation while he was away. Claude owned RetainAI's code audit; Codex
owned Closet Muse/Apple setup, independently reviewed the RetainAI diff and CI,
then merged and checked production. No new charge, payout, tax filing or customer
message was made in this pass.

## RetainAI changes and validation

[PR #31](https://github.com/Retain-ap/retainai-prod/pull/31) merged reviewed head
`765c06cbbd4fada3d61ae32d3b5418dea3b7bfa1` as
`004ac88f87705f3c43360be58671eb010ec36fd8`:

- Calendar, Insights, the contact drawer and Google-contact import now use the
  shared API origin. A build without the duplicate build-time variable previously
  sent those requests to the frontend origin. Production's old build happened to
  contain the right variable; this was a reproduced configuration-dependent bug.
- The final signup terms checkbox is fixed at 18px instead of stretching across
  the row on phones. Signup errors are announced as alerts.
- Three unreferenced components were removed; Codex checked that no source imports
  them. Two regression checks cover the default API origin and duplicate env logic.

[All three CI jobs passed](https://github.com/Retain-ap/retainai-prod/actions/runs/42167212341):
84 backend tests, 47 frontend tests, lint, build, dependency audits and secret
scanning. Claude also exercised a real local backend and built frontend at five
viewport widths; contact, appointment and profile workflows passed. Logout passed
on phone/iPad after correcting the test's menu and timing assumptions.

Frontend deployment `dep-dbmm53m8bjmc73dqvfe0` is **live**, finished
`2026-11-06T05:17:03Z`, at merge commit `004ac88`. Backend code did not change;
its observed live revision remains `7c96ded7710215126f43c7905cfec0bb19dab4ce`.
Codex reloaded the authenticated production session and verified Calendar,
Insights and the fictional Alex Maple contact drawer. No customer data was edited
and no email was sent. Nine anonymous HTTP checks passed: health, readiness,
signed-out session response, private-leads guard, home/login/signup/partners and
the apex-to-www redirect. A first probe expected 401 for `/api/session`; source
and response confirmed its documented signed-out behavior is 200 with
`authenticated:false,user:null`. The private `/api/leads` guard returns 401.

## Closet Muse and Apple

[Current handoff](https://github.com/Retain-ap/closet-muse/blob/main/docs/LAUNCH_READINESS_2026-11-06.md)
was merged through docs-only [PR #14](https://github.com/Retain-ap/closet-muse/pull/14)
as `c14bfc33b17b14026c58a32ec5903be508891a39` with `[skip render]`.
Render still runs `c66d02ee87c305d0a01c1badfdd7b63f5d82e250`; no runtime change
required another deploy. Fresh release gate: 604 automated tests, 81 normal and
91 capture HTTP checks, lint/build/audit/secret scans passed. Native gate: 40
unit/UI test executions passed on iPhone/iPad simulators. Production: 17/17 smoke
checks passed and no error-level logs appeared in the checked period.

Apple sign-in worked after Mateo's handoff. The signed version 1.0 (1), ten listing
screenshots, subscription review screenshot, privacy declaration, listing metadata,
Canada-only CA$9.99 monthly product and subscription/group review draft are ready.
The app version is not submitted. Fresh TestFlight usage showed one invitation,
zero installs and zero sessions; no physical-device acceptance is claimed.

Actual remaining Apple requirements: banking, Canadian GST/HST Form 506 and U.S.
Tax Questionnaire; a reachable App Review contact phone; verification of the
dedicated standard reviewer email; physical iPhone/iPad and sandbox purchase/
restore acceptance. Owner mailbox sign-in requested Microsoft Authenticator
approval, so Codex did not bypass it. The Paid Apps Agreement was already accepted;
do not buy another developer membership or recreate the configured keys.

## Provider and recovery items still open

- Google verification: both review videos were submitted November 2. RetainAI's
  complete AI-service reply and dedicated reviewer account are still required.
  [Verified AI-service facts](2026-11-06-google-ai-review-facts.md) now record the
  exact endpoint, dynamic routing, Google-derived inputs and fresh account controls;
  a reply and public disclosure clarification are prepared but not sent/published.
  Public Closet Muse Calendar is **off**: Codex directly checked
  `GOOGLE_CALENDAR_ENABLED=false` in Render on November 6. This resolves Claude's
  concern about an earlier November 2 temporary enablement; no flag changed today.
- RetainAI Owner Console needs an owner sign-in and MFA. Do not weaken it to create
  a reviewer account or obtain backups. Its daily backup exists on the same Render
  disk (Claude observed `retainai-backup-20261106T032000Z.zip`, 15 files, at 03:20 UTC).
  No verified independent copy or restore drill is recorded. Download through the
  authorized owner workflow, verify the digest and keep an off-Render copy weekly.
- Closet Muse's independent encrypted archive needs its original v2 key and real
  quarantine verification. No protected local key/real restore receipt was found.
  A new key does not decrypt the existing archive. Regular independent retention
  and recovery acceptance remain unfinished.
- Stripe Connect's callback URI is saved, but the full account-connection round
  trip remains deferred. Non-owner Google sign-in/physical-device checks also remain.
- November 2 real web signup/payment/cancellation tests and the Closet Muse refund
  are already recorded; don't repeat live charges merely to satisfy this checklist.
- The 30% first-year web commission tracking is implemented. Public partner posts
  await app-account publishing identities. Apple sales require financial-report
  reconciliation before commission payouts are approved. Unapproved shopping and
  Calendar features stay hidden.

No claim is made that every possible production action was tested, that Google or
Apple approved either review, or that only marketing remains. Continue with the
specific owner/provider/recovery gates rather than repeating completed setup.

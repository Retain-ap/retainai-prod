# Service-business value, Calendly and inspired looks — November 6, 2026

Mateo chose service businesses using Calendly as RetainAI's first audience and
approved a new Closet Muse recovery key, a fresh encrypted production backup,
private OneDrive storage and a separate restore check. Claude implemented the
RetainAI changes; Codex independently reviewed, requested regression fixes and
merged the final revision. Codex implemented and released Closet Muse's changes.

## RetainAI release

[PR37](https://github.com/Retain-ap/retainai-prod/pull/37) merged as
`cbcb7b79ed5c59205335711f267e4ac114c5a902` after all checks passed on reviewed
head `ffd9fc4bfc21b003548ed8ed25b079fb530eed03`.

- A Value Receipt separates provider-verified business payments, owner-entered
  payments and estimates. It exposes evidence and CSV export, keeps currencies
  separate, subtracts refunds and rejects unconfirmed, uncaptured, disputed or
  mismatched charges. RetainAI's own membership billing is never business revenue.
- Follow-up/payment links require that payment's own invoice or an explicitly
  selected valid booking. They show sequence, not proof of causation. Date-only
  same-day payments cannot establish event order.
- Rebooking uses completed-visit intervals, with explained fallback values and
  exclusions for future, cancelled, no-show or already-booked visits.
- General service-business setup is the default; the salon/barber preset is
  optional. Checklist progress reflects real setup and activation, not invented
  time saved or revenue.
- Calendly is the primary read-only booking integration. Square remains optional.
  Both report unavailable until their app credentials are configured. See
  [booking setup](../docs/BOOKING_INTEGRATION_ASSESSMENT.md).
- Calendly requests only `scheduled_events:read` with PKCE S256. It matches
  existing contacts by one email, creates no consent and sends no messages.
  Sync steps are bounded and resumable, report caps/rate limits, skip malformed
  or unknown states, and recheck account/connection generations before writing.
  A revision comparison rejects an older sync after a newer one has committed.
- Invoice retries preserve Stripe idempotency. New stores participate in export
  and account deletion, and stale writes cannot restore a deleted workspace.
- Backup tools verify, encrypt and restore to isolated private directories.
  Native Windows plaintext restore fails closed; use supported POSIX recovery.
  The RetainAI restore test used **local fictional SQLite data**, not a real
  production archive or durable off-site copy. See [backup guide](../docs/BACKUP_AND_RESTORE.md).
- The privacy policy names OpenRouter and accurately explains Google-derived
  data in AI requests, dynamic upstream routing, training restrictions and the
  fact that zero-data-retention routing is not enabled.

### Validation and live evidence

[Final reviewed CI](https://github.com/Retain-ap/retainai-prod/actions/runs/42317846728)
passed **202 backend tests**, **111 frontend tests in 28 suites**, compilation,
lint, production build, both dependency audit gates and secret scanning. The
31 Calendly tests use fake providers. Mutation checks showed deletion,
disconnect and out-of-order sync tests fail without the safeguards. Disposable
real-backend browser QA covered phone, iPad and desktop; no customer messages or
live payments were created.

Both Render services are live at `cbcb7b79ed5c59205335711f267e4ac114c5a902`:

- Backend `srv-d3co8ul6ubrc73evtrj0`, deploy `dep-dbn6vam7bikc738f8v60`,
  live 2026-11-07 00:25:20 UTC.
- Frontend `srv-d4n4hna4d50c73f5u2v0`, deploy `dep-dbn6vam7bikc738f8v2g`,
  live 2026-11-07 00:25:15 UTC.
- [Merged-source CI](https://github.com/Retain-ap/retainai-prod/actions/runs/42318000083)
  also passed. Both services retain automatic deployments from `deploy`.
- All **15/15** anonymous production GET checks passed: health/readiness/session,
  public pages and the apex redirect, plus access guards on leads, imports,
  Value Receipt/export and Calendly/Square status. The public `/privacy-policy`
  page was separately read in the browser and shows the new disclosures.
- No error-level backend app logs appeared in the initial post-live check.
  This is a short observation window, not proof of absence of all runtime errors.
- The controlled live browser session is signed out. Authenticated feature
  journeys were tested with the disposable real backend, not claimed as new
  production-account tests. No real Calendly/Square authorization was performed.

## Closet Muse release and recovery

Authoritative [Closet Muse handoff](https://github.com/Retain-ap/closet-muse/blob/main/docs/INSPIRED_RELEASE_2026-11-06.md)
records the details. Web/API is live at `e778fcf3687969dc0861d7b653c50a019d1fbf85`;
TestFlight **build 3** uses `64c72e471d0e0a8b4f32737ba85afa1108bf3ef1` and is VALID,
assigned internally and selected for the App Store version.

Inspired looks match wardrobe labels, not image recognition. Members can send
selected pieces to one accepted friend for styling after moderation. The web
adds batch setup, optional explicit-consent photo labels, a clearly fictional
public sample gallery and aggregate owner milestones. Private closets stay private.
Checks passed: 628 tests, 120/130 built-server HTTP checks, 52 native simulator
test executions and 17/17 exact-release production smoke checks.

The new real encrypted production backup contains 21 files and 2 media references.
It was uploaded to the owner's private OneDrive folder and independently downloaded
again; its digest matched and a separate private quarantine restore passed with
credentials, learning and sharing inactive. The new key is Windows DPAPI-protected.
Independent Bitwarden/offline key escrow and recurring off-site retention remain
open. The new key does not recover the old October archive.

Google's Closet Muse homepage, functionality, branding and minimum-scope checks
were complete; privacy data-protection disclosure remained. The policy fix was
deployed and the existing Google email thread was replied to successfully.
Approval is pending, so public Calendar remains disabled. Apple review notes and
listing copy match build 3; the three-item review draft is still unsubmitted.

## What remains

- RetainAI: register/configure its Calendly OAuth application and test a real
  connection and import. Square is optional. Do not describe either as live-connected.
- RetainAI: Google still needs the dedicated reviewer login and AI-service details.
  Owner MFA was deferred. Current OpenRouter routing has no fixed upstream list;
  answering Google's demand for a closed provider/model list needs an intentional
  routing decision and validation, not a guessed list. The factual reply remains
  a draft; the existing replacement video is already in the review thread.
- RetainAI: complete the deferred Stripe Connect round trip, and verify a real
  production backup off Render with its own recovery-key custody and restore.
- Closet Muse: save the new key independently, arrange recurring backup retention,
  test TestFlight 3 on a physical iPhone (including sandbox purchase/restore), and
  resolve Apple's Canadian tax/account requirements before public App Review.
  Both approved U.S. forms were already Active; do not repeat them or invent a GST ID.
- Both: provider approval is separate from code/test completion. Existing web
  signup/cancellation/refund checks from November 2 need not be repeated.
- Marketing: the 30% first-twelve-month partner offer is implemented; public posts
  await the chosen app-account identity. Payouts remain reviewed manually, and Apple
  commissions need financial-report reconciliation. Monitor community moderation daily.

This handoff is documentation-only and uses `[skip render]`; it changes no runtime
or secrets. No public App Review submission, physical-device acceptance, new live
purchase, production Calendly import or Google approval is claimed.

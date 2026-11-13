# Follow-up workflow, supported runtime and partner outreach — November 13

## Shipped product changes

[PR66](https://github.com/Retain-ap/retainai-prod/pull/66) merged at `a33646fd5d50a95ee1b9f0a8a5e9dbcf0f4bcde8`. Backend deploy `dep-dbrb5r942hec73bdkgh0` became Live at 06:50:19 UTC; frontend deploy `dep-dbrb5r942hec73bdkhcg` at 06:50:15 UTC. Health/readiness and all 27 public route/metadata checks passed.

Due-customer actions now open the matching customer and factual context in AI Studio. The user still reviews and chooses whether to send. Real contacted/sent events drive a seven-local-day waiting group; failed or refused sends do not record outreach. Invented C$75 customer values and default potential-revenue totals were removed. Cadence copy distinguishes recorded visit evidence from owner/default intervals.

Independent review caught and fixed five edge cases: stale held drafts overriding the selected customer, UTC versus workspace-local dates, unsupported "usually" claims, deleted customers restoring another draft, and same-day follow-up status. The final checks passed **286 backend tests, 266 frontend tests in 38 suites, lint, production build, production audit and secret scan**. No live customer email was sent to test this feature.

The initial `/partners` HTML now carries the exact 30%/first-12-month offer, 30-day hold and implemented product capabilities. A shared source keeps React and prerendered copy aligned. The live phone layout was inspected without horizontal overflow.

## Node runtime

[PR67](https://github.com/Retain-ap/retainai-prod/pull/67), merged at `ef14e1f5b026816b04362c2d44016e455bc050f6`, pins frontend Node 24.19.0 in `.node-version`, package engines and CI. No dependency versions changed in that PR. Fresh Node24 validation passed the 266 frontend tests, lint, build and a zero-vulnerability production audit; GitHub run `43382297785` was green.

Claude changed only the frontend Render `NODE_VERSION` using merge mode, preserving other variables. The connector automatically started deploy `dep-dbrbbqlckfvc73dpd0c0` from `a33646f`; it was Live at 07:02:59 UTC with Node24.19.0 in its build log. The 27 public route checks passed again. This establishes the supported runtime independently of the later source-pin merge. The post-merge deployment receipt is tracked separately; a pushed commit is not automatically treated as proof of a live deployment.

## Actual marketing execution

Five tailored proposals received website acknowledgements: Shawn Mynar, Forrest & Company, Next Level Coaching, Clarity Business Academy and WhizQueen. They responded to current explicit partnership/collaboration invitations with the approved 30%/first-12-month offer. Sources, exact copy and acknowledgements are in the private overnight ledger. No partnership has accepted, no payment is due, and no automatic follow-up was enabled.

The narrow solicited-response assessment and the unchanged gate for general cold outreach are in `docs/SELLING_PLAN_14_DAY.md`. App-owned social identities remain unavailable; posts are drafts. HeyCatch's public audit was used and its implemented fixes remain documented, but its paid workspace is signed out with an unknown login identity. No marketing automation is claimed.

## Remaining boundaries

Calendly Sandbox's nonempty owner-only lifecycle passed November 13: one marked QA booking matched its existing QA contact, repeated sync produced no duplicate, and cancellation propagated. The booking is cancelled and no sample time remains reserved. Production OAuth approval remains separate. The test exposed timezone and cancelled-label defects fixed by PR74 below; its post-release browser re-sync was blocked before identity or sync, so no new live acceptance is claimed. The existing event type also reported Zoom disconnected. Stripe Connect remains deferred at the owner's request. Independent backup-key custody and a recurring off-host routine remain separate from the already verified encrypted backup/restore.

Closet Muse's web partner form is live; its native build6 and public App Review gates are recorded in that repository. No CRA registration or tax declaration was fabricated for either app.

The private `outputs/night-20261113` directory holds screenshots, exact deployment IDs, outreach receipts and the combined 25-check public-service report. Later Edge controls stalled and the Render connector required reauthentication; neither condition was treated as deployment success.

## Latest verified release — November 13, 15:11 UTC

[PR74](https://github.com/Retain-ap/retainai-prod/pull/74) merged at `21a54df490ab0467fd87c47a1dfb18ef77a7606b`. Backend `dep-dbrigqe1egvs73ftmpsg` became Live at **15:11:40 UTC**, and frontend `dep-dbrigqe1egvs73ftmpp0` at **15:11:30 UTC**. These exact-source receipts came from Claude's authenticated Render connector and were read in its UI; root's direct Render connector remained unavailable. Anonymous health/readiness, authentication guards and the combined 25 public-service checks passed separately. Loaded main asset: `main.44fe432e.js`.

The final tested source `1c1210a42988b69c7939097d1042154e3efa9833` passed **297 full Linux backend tests, 303 frontend tests in 42 suites, lint, 14-route build, dependency audits and secret scan**. Required GitHub run `43449421608` passed. The merge tree matches the tested tree. Claude's independent review caught a legacy Square status refresh problem; it was fixed with a regression test before merge.

Calendly, Square, receipt periods and manual payments now use the saved workspace timezone. Imported booking instants and identities remain stable; provider cancellation is authoritative and owner edits are preserved. The UI distinguishes Cancelled, No-show and Completed, separates History from Active, saves explicit no-show outcomes and shows each appointment's timezone. Ambiguous legacy Square terminal states without a provider baseline are conservatively preserved. Existing historical mirrored rows with incompatible identities are not silently rewritten.

[PR73](https://github.com/Retain-ap/retainai-prod/pull/73), merge `9227d89653063fd415a5375dcdb71e4545001654`, was already live at 08:29:02 UTC in frontend deploy `dep-dbrck4qvcj2c73ep7h6g`. It guards import/file/recount races, locks the accepted import plan during commitment, suppresses stale workspace responses and preserves the latest appointment load. Failed recounts keep Import disabled until a successful retry. Its 285 frontend tests included 19 component-level deferred-response regressions. PR74 includes that work.

PR70's mixed/unknown partial-refund guard is also included. Unprovable commission allocations are held for review, excluded from payable exports and cannot be paid through the normal action. Existing paid history is not rewritten. Base-only allocations can reconcile on a successful re-sync; mixed invoices still require audited reconciliation. No live payout or refund was created by the synthetic regression tests.

## Security and unshipped work

PR71 adds a fail-closed Linux resolved-requirements audit; it found no known vulnerabilities. This is not a frozen inventory of running Render packages. PR72 enables dependency alerts and reviewed security-update proposals, without automatic merging. At the November 13 checkpoint, the current CRA development tree has 34 npm findings (16 low, 5 moderate, 13 high, zero critical); production npm audit is zero. GitHub's 21 advisory alerts are a different metric and must not be equated with affected-package counts.

[Draft PR75](https://github.com/Retain-ap/retainai-prod/pull/75) prepares a Vite/Vitest toolchain migration without changing application source or production package versions. It is **unmerged and not deployed**; final browser, lazy-CSS, service-worker and compatibility acceptance remain separate from automated parity checks. No incompatible forced dependency override was shipped.

## Audit reconciliation

The complete current public HeyCatch report and all 13 actions were read again November 13. All 22 below-maximum scores match November 11, including the inapplicable D4.B bonus. The 21 applicable findings are mapped in `docs/HEYCATCH_EVIDENCE.md`; the exact changelog remains in the November 11 release note. All 27 current initial-HTML route checks passed at 15:09 UTC. No audit rerun or improved score is claimed. Approved real quotes, sourced production usage, the owner's story/portrait/profile and a real dated external mention are still needed; their slots remain safely unpublished.

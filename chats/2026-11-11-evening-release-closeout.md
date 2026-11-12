# Evening release closeout — 11 November 2026

Codex and Claude reviewed each other's changes. This entry records deployment evidence; it does not claim all provider or marketing gates are complete.

## Deployed

- PR59 merged as `f3ca3e5c3e4ae935f84fc804ee727b723f2e41a9`: current-subscription invoice guards, accessible login labels/password controls, and an acquisition plan based on free public posts and inbound interest.
- PR60 merged as `8513ea9c509f6b5e6cebcdda2244758028200cf8`: `/find-customers-who-stopped-rebooking`, sitemap/metadata and navigation links. Frontend deploy `dep-dbqguaivcj2c73eucagg` went live at 2026-11-12 00:59:22 UTC.
- PR61 merged as `288f2f42b3ea08d5c4c20e736a5378a884949555`: match subscription/customer IDs before mutable billing email; ignore tested replaced-subscription and late-invoice events; remember deleted subscription IDs so same-second deliveries cannot reopen them. A genuinely new subscription still activates. Backend deploy `dep-dbqh3shsrm7s738hq6d0` went live at 01:11:23 UTC.
- PR62 adds `tools/check-public-route-html.cjs` and the hosting instructions. It changes no production runtime; its commit deliberately skips Render.

## Evidence

- PR61 exact-head CI `43132336257` and merged CI `43132595723` succeeded. Backend: 278 tests, including 17 invoice/subscription regressions. Frontend: 229 tests. Billing fixtures did not send signed production webhooks or change actual payments.
- The two new guide rewrites were saved in Render above the SPA fallback. All 17 prior exact rules and the final catch-all were preserved. Both URL forms now serve the guide's own initial HTML.
- The reusable verifier passed 27 live URL forms. A local server intentionally returning the homepage for every path produced exit 1 and the expected 26 route failures. This guards against client-side hydration hiding incorrect server metadata.
- Phone layout at 375px and desktop layout were visually checked; no horizontal overflow. The mobile navigation opens and closes.
- Post-deploy anonymous checks passed 16/16 at 01:18 UTC: process/readiness, public pages, apex redirect and private API guards. An unsigned webhook was rejected with HTTP400.

These checks establish the named behaviours, not every possible Stripe lifecycle permutation or a new live checkout/refund acceptance.

## Remaining boundaries

Google Contacts/Calendar verification is approved. Calendly remains Sandbox with an empty sync acceptance; separate production credentials/authorization and nonempty booking/reschedule/cancel acceptance remain. The owner explicitly deferred the Stripe Connect round trip.

The 30% first-12-month partner offer and acquisition materials are prepared. The public guide is live; no social post, cold outreach or accepted partnership is claimed. App-owned social identities and legitimate sender details are still needed for their respective publishing channels. Real customer proof must not be fabricated.

Existing encrypted-backup evidence does not establish independent key custody or a recurring offsite routine. GitHub uptime scheduling remains best effort rather than dependable 15-minute coverage.

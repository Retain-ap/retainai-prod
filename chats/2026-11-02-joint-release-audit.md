# Joint release audit — November 2, 2026

Codex and the existing Claude Code desktop session worked together under the owner's
authorization to find and fix launch issues, push reviewed changes, and deploy them.
Claude owned backend/security checks; Codex owned frontend flows, production configuration,
merge/deployment verification and this record. They reviewed each other's changes and
avoided duplicate test sweeps. This entry supersedes the open release items in the earlier
[security pass](2026-11-02-security-pass.md), while preserving that historical record.

## Shipped

| Change | Evidence |
| --- | --- |
| Backend dependency upgrades and local debugger disabled by default | [PR #16](https://github.com/Retain-ap/retainai-prod/pull/16), merged and deployed as `a052ae7`; 74 backend tests and Claude's pip-audit passed |
| Dashboard navigation preserves browser Back, Calendar/Appointments, owner landing page and shortcut destinations | [PR #17](https://github.com/Retain-ap/retainai-prod/pull/17); eight regression tests, including five failures demonstrated against the old code |
| React Router production advisories fixed | [PR #19](https://github.com/Retain-ap/retainai-prod/pull/19); `react-router` 7.18.5, zero production npm findings |
| Owner Console explains its existing MFA requirement and links to Security settings | [PR #20](https://github.com/Retain-ap/retainai-prod/pull/20); two regression tests; live desktop, 820px tablet and 390px phone checked |
| Compatible development-tool security patches | [PR #21](https://github.com/Retain-ap/retainai-prod/pull/21); zero critical findings, production dependencies unchanged |
| Settings tabs and Help shortcuts update the URL and survive Back/reload | [PR #22](https://github.com/Retain-ap/retainai-prod/pull/22), frontend deployed as `ab9e3af`; two regression tests and live verification |
| WhatsApp appointment creation rejects missing or other-workspace lead references before writing | [PR #23](https://github.com/Retain-ap/retainai-prod/pull/23), merged and backend live as `787e1e4`; three regression tests; valid workspace leads and general appointments without a lead remain supported |
| Closet Muse readiness stops exposing filesystem paths | Commit `b70fcdb66554af4dd93394fd7d86ba5d957022df`, live; regression coverage and 17/17 production smoke checks |

RetainAI's static site now sends six response headers on `/*`: HSTS, frame denial via
X-Frame-Options and CSP `frame-ancestors`, nosniff, strict-origin-when-cross-origin referrer
policy, and a permissions policy disabling camera/location while preserving same-origin
microphone access for voice notes. Actual GET responses on `/`, `/login` and a deep app route
were verified. The Render connector cannot edit these headers; they were saved in its UI.

Closet Muse's public Apple sign-in gate was restored to `APPLE_SIGN_IN_ENABLED=false`, as
required by the existing launch plan pending device acceptance. Other environment keys and
owner linking/review settings were preserved. Its resulting Render deployment is live and
public Apple availability is false; Google sign-in remains available. Public Calendar remains
off pending Google's review.

## Verification and limits

- Combined RetainAI CI at `ab9e3af`: **74 backend tests, 45 frontend tests**, lint/build and
  both audit gates passed. [CI run](https://github.com/Retain-ap/retainai-prod/actions/runs/41450260145).
- The final appointment fix raises the backend suite to **77 passing tests**; all 45 frontend
  tests and both PR checks also passed, along with [deploy CI](https://github.com/Retain-ap/retainai-prod/actions/runs/41452307765).
  Codex independently reviewed Claude's exact PR head
  `699a842` before merging it; no customer/provider writes were used in these tests.
- Production npm audit: **zero**. The full frontend dependency tree still has **75 findings**:
  0 critical, 13 high, 51 moderate, 11 low. These remain in development/build tooling and
  require a separately planned migration; this is not a clean full audit. No forced,
  destructive `react-scripts` downgrade was used.
- Claude's security pass covered 145 RetainAI and 99 Closet Muse anonymous route/method
  pairs, 22 cross-account refusals, owner guards, CSRF/CORS and 13 redirect payloads. It
  also reported 365 Closet Muse unit tests and 77 HTTP security checks passing. Codex
  independently verified the deployed Closet Muse release with its 17-check smoke script.
- Live Settings validation used the current `main.e6d520c2.js` bundle: Security → Help →
  Integrations → browser Back → reload preserved both URL and displayed tab. Render's
  300-second CDN cache briefly returned the prior bundle immediately after deployment;
  a normal reload after propagation loaded the current release.
- Seven live health/readiness/site checks passed at 13:15 UTC. Queried application-error
  and HTTP 5xx logs were empty from 13:08:38 through approximately 13:16 UTC. These are
  point-in-time checks, not a guarantee that every provider or device workflow is complete.
- After the appointment backend deployment finished at 13:22:45 UTC, all seven checks
  passed again at 13:24 UTC. Error/5xx queries were empty for 13:23:15–13:24:14 UTC.
- No real customer data was modified by the regression fixtures. Provider sends and new
  charge/refund operations were not repeated during the security pass.

## Launch and Google review status

The previously verified launch signups remain cancelled for renewal. Closet Muse's CA$9.99
payment was refunded. RetainAI's checkout started a CA$0 trial, so it did **not** prove a
captured charge/refund. Its dashboard access was verified. The SendGrid unsubscribe footers
remain saved and active; this session did not send another delivery test.

Both approved videos are published Unlisted and the Google requests remain under review:
[Closet Muse](https://youtube.com/shorts/9ottxjqNpmE) and
[RetainAI](https://youtube.com/shorts/OTybHt9uPO0). RetainAI's replacement link was saved and
the existing reviewer thread was notified. No new duplicate request was created. See the
[submission record](2026-11-02-google-review-submissions.md).

RetainAI still needs the complete AI-provider response, dedicated reviewer account and any
additional OAuth-client coverage requested by Google. The owner deferred authenticator and
reviewer-account setup. No owner credentials were shared. Dynamic OpenRouter routing and
no-training controls must not be represented as a verified fixed provider list or zero retention.

## Still open

- Urgent owner credential revocation identified in the earlier security pass. Details are
  kept in the private owner handoff; credentials were never copied into this log. Changing
  repository visibility is an owner decision and does not replace revocation.
- Owner authenticator setup; full Stripe Connect round trip (callback URI is registered);
  Closet Muse non-owner Google sign-in and physical iPhone home-screen/photo acceptance.
- Reconcile RetainAI's advertised monthly amount with the earlier checkout evidence before
  committing affiliate offers. Billing prices and financial terms were not changed.
- Closet Muse backup-key verification; off-site RetainAI backups; provider/network approvals.
- Development-tool dependency backlog described above. Affiliate proposals are drafts only;
  no outreach, commission commitments or additional paid services were created.

The owner's private output report contains deployment IDs, screenshots, launch evidence and
the remaining owner actions. Application changes are deployed through green-CI PRs; this
documentation-only update uses `[skip render]`.

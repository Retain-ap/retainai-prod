# Urgent follow-up — November 2, 2026

The owner asked Codex to handle the urgent remaining items. Codex and Claude split the
credential verification, prevention work, pricing correction and independent reviews.
This entry corrects the earlier unverified token warning and closes the pricing discrepancy.

## Historical credential: verified inactive

The historical WhatsApp token was checked directly with Meta using a read-only identity
request. Meta rejected it with OAuthException 190 / subcode 463 and explicitly reported that
it expired on **August 10, 2025**. The prior description of a token needing urgent revocation
was too strong before its validity was checked.

Codex compared the historical credential with the backend's configured `WHATSAPP_TOKEN`
in memory: they are different. No credential value was printed, committed or written into
the evidence files. The configured credential was hidden again in Render; no environment
settings or credentials were changed. This comparison does not claim a full WhatsApp
message-delivery test. The reported historical token does not need an emergency replacement.

Claude ran a redacted Gitleaks scan over the local history and a temporary GitHub copy
including pull-request refs: 274 commits and 28 PR refs. There were two findings: the
already-expired Meta token and an old Google Calendar `sync_token` cursor, not a login
credential. No other recognized credentials were found by this scan. Current tracked
files passed. This is scanner coverage, not a guarantee that arbitrary secrets can never
exist. No broad ignore or allowlist was added.

## Prevention now enforced

[PR #26](https://github.com/Retain-ap/retainai-prod/pull/26), merged as `9630f63`, adds:

- Official Gitleaks 8.30.1, pinned to the independently verified release checksum.
- All default rules plus Meta EAA-token coverage missing from the provider-specific rule.
- A scan of new commits and the current tracked tree. A token committed and then deleted
  still fails the change's scan. Ignored local files are not read.
- Redacted reports, including synthetic Meta, Stripe and private-key checks. All 12 scanner
  checks passed, including new branches, missing old tips, PR ranges and clean pushes.

GitHub protection on `deploy` now requires an up-to-date pull request and these three
GitHub Actions checks, including for administrators:

1. Backend security and regression tests.
2. Frontend tests, lint, build, and production audit.
3. Secret scan of new commits and tracked files.

Force pushes and branch deletion are disabled. A separate approving reviewer is not
required, so the owner's normal single-maintainer PR workflow still works. PR #25 was
updated onto the scanner commit, passed all three checks and merged normally under the
new protection; no administrator bypass was used. Repository visibility was not changed.

## Pricing corrected

Codex inspected the exact `STRIPE_PRICE_ID` used by the backend and the matching live Stripe
price page. It is **CAD 20.00 per month** for RetainAI SaaS Subscription. The public page's
CA$30 amount did not match the configured checkout.

[PR #25](https://github.com/Retain-ap/retainai-prod/pull/25), merged as `636518a`, shows CA$20
and says it is the current launch price. Claude independently reviewed the two-line copy
change. No Stripe prices, subscriptions, taxes or payment behavior were modified.

The frontend automatically deploys this application change. The scanner/workflow change
used `[skip render]`; backend application source remains at the already-verified `787e1e4`.
Final live pricing, health and deployment evidence is in the owner's private output report.

## Remaining work

Owner MFA/reviewer-account setup, the Google verification follow-up, Stripe Connect,
physical-device/non-owner sign-in tests and backup tasks remain as recorded in the
[joint release audit](2026-11-02-joint-release-audit.md). RetainAI's CA$0 trial did not test
a captured payment/refund. The known development-tool dependency backlog remains; the
production npm audit is zero. The owner no longer needs to resolve the historical token
warning or the website/checkout price discrepancy described in that earlier handoff.

# RetainAI tax checkout preparation — November 15, 2026

Prepared in an isolated branch; production activation remains a separate operator action.

- Added a default-off automatic-tax option for new subscription Checkout Sessions. Existing subscriptions are not migrated.
- Added a durable locked attempt ledger, exact idempotent retries, mode/account/URL/tax response verification, completed-session duplicate-payment guards, and deletion/recreation checks.
- Added the default-off purchase-only pause switch and authenticated billing usage status. Member access, customer billing management, and webhooks remain available.
- Returning customers supply a fresh billing address; saved shipping addresses stop checkout for support because Stripe gives shipping precedence. No tax IDs are collected by this patch.
- Account deletion purges the attempt ledger; export includes only non-sensitive attempt status. Signup now says applicable taxes are additional.
- Added a read-only, sanitized server preflight and the activation/legacy-session drain/rollback procedure in [STRIPE_TAX_ROLLOUT.md](../docs/STRIPE_TAX_ROLLOUT.md).

Validation: 340 backend tests and all 303 frontend tests across 42 suites passed. Final frontend build/audit and secret scan receipts are recorded with the PR. The independent source review found no remaining blocking issue after the generation, late-pause, and federal-registration checks were added. All new payment/preflight tests use mocked providers; no live charge, customer update, tax registration, or subscription mutation was performed by these checks.

The owner approved normal Canadian GST registration effective November 15, Tax Basic at 0.5% for new checkouts, and RetainAI business SaaS tax code txcd_10103001. The coordinating operator owns applying and verifying the Stripe settings. The actual configured plan, live registration and pending-session inventory still must pass the runbook gates before new-checkout tax activation. Existing renewals (including the observed November 16 invoice) need a separate decision and are excluded from this patch.

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

Calendly Sandbox read-only authorization and an empty sync passed earlier. Production app approval and a nonempty booking lifecycle still need evidence. Stripe Connect remains deferred at the owner's request. Independent backup-key custody and a recurring off-host routine remain separate from the already verified encrypted backup/restore.

Closet Muse's web partner form is live; its native build6 and public App Review gates are recorded in that repository. No CRA registration or tax declaration was fabricated for either app.

The private `outputs/night-20261113` directory holds screenshots, exact deployment IDs, outreach receipts and the combined 25-check public-service report. Later Edge controls stalled and the Render connector required reauthentication; neither condition was treated as deployment success.

# Commission release, Calendly Production preparation and provider gates — November 15

This is the latest verified checkpoint for the November 15 Toronto session. Deployment times below fall on **November 16 UTC**. Older logs preserve their original evidence; a local commit or provider setting alone is not proof of a live end-to-end flow.

## Backend release is live; frontend is unchanged

[PR77](https://github.com/Retain-ap/retainai-prod/pull/77) merged as `54f4e7244f4a9eb20796cda45fd70045b7214efc`. Backend Render deploy `dep-dbt5mju8bjmc73f925p0` became Live at **2026-11-16 01:25:43 UTC**. The merge and tested PR head have the same tree. The frontend remains Live from `21a54df490ab0467fd87c47a1dfb18ef77a7606b`; its entire frontend tree matches the new merge, so this backend-only change did not require a frontend redeployment.

Partner commissions now hold at zero for review when a negative invoice line has no established allocation between qualifying base membership revenue and excluded charges. Normal exclusive/inclusive tax, discounts and supported refunds retain their covered behavior. Reconciliation persists the hold, and owner payout recording refuses it. No production invoice, refund, ledger adjustment or payout was created by synthetic tests.

Validation passed **300 Linux backend tests and 303 frontend tests**, frontend lint/build, dependency checks and secret scanning. Exact-merge GitHub release gate [43786093361](https://github.com/Retain-ap/retainai-prod/actions/runs/43786093361) is green. After deployment, **42 public checks and 27 initial-HTML/route checks passed**. The private `outputs/retainai-postmerge-smoke-20261115.json` and public-HTML log preserve the results. Production dependency results remain distinct from the previously recorded development-toolchain advisories and unmerged PR75 migration.

## Calendly Production app is prepared, not live-verified

The Production OAuth app was created under the owner account with read-only scheduled-event access; the local credential copy is Windows DPAPI-encrypted. A fresh Render readback still showed the Sandbox client after an earlier save attempt. Production environment configuration is therefore not yet verified. No credential value, token or private identifier belongs in this repository.

The existing connected owner account still syncs using its prior **Sandbox authorization**. This proves that connection continues to work, not that the Production environment was saved or a new Production consent/token exchange succeeds. Production configuration/readback, deployment, fresh authorization and a booking lifecycle check remain outstanding. Do not label Production OAuth fully tested or discard the existing connection merely to make the status appear complete. Historical Sandbox booking, duplicate prevention and cancellation evidence is in [the November 13 log](2026-11-13-followup-release.md).

## Google and tax state

RetainAI's approval for `calendar.events.readonly` and `contacts.readonly` is recorded in [the November 11 closeout](2026-11-11-evening-release-closeout.md). Closet Muse's separate `calendar.events.owned.readonly` approval was freshly confirmed in its Google email thread this session; there is no outstanding reply or review video for that existing scope. No additional sensitive scope is inferred to be approved.

The owner's CRA registration is now complete, but **Stripe Tax is not enabled**. Registration, Apple tax records and Stripe checkout tax configuration are separate. Stripe Tax setup and validation remain outstanding; the commission fix does not enable or certify tax collection. No tax identifier or address is committed.

## Cross-app release boundaries

Closet Muse PR51 is Live at `fcadf35b322df00bfd52d87e971ef0e5c803c10d`, Render `dep-dbt5phqjnfac73d0i3jg`, at 2026-11-16 01:32:50 UTC. Its full Linux gate passed 682 tests and 430 HTTP checks, followed by 17 public smoke checks.

Its signed build6 remains VALID and selected, with three ready App Review items **unsubmitted**. The Apple-generated GST506 election date predates GST/HST registration; Finance clarification is pending and the bank remains Processing. Native draft PR50 combines the pending PR41/45/48 work and a logout guard. Its 30 Node contracts pass, but its Mac compilation, new XCTest/UI tests and physical-device acceptance have not run. It is not in TestFlight. See [Closet Muse's matching session log](https://github.com/Retain-ap/closet-muse/blob/main/chats/2026-11-15-release-closeout.md).

## Remaining operating and marketing work

- Save and verify Calendly Production configuration, deployment, fresh authorization and its real lifecycle without contacting customers as a test.
- Configure Stripe Tax separately using verified registration and product facts; preserve the approved 30%/first-12-month partner terms.
- Stripe Connect remains deferred at the owner's request. Independent recovery-key custody and a recurring off-host restore routine remain separate from prior encrypted backup/restore success.
- Existing proposal acknowledgements are not accepted partnerships or sales. App-owned social publishing still needs the intended authenticated identity; no automatic follow-up was enabled.
- HeyCatch's sourced testimonial, usage, owner-profile and external-mention gaps remain evidence-dependent. No invented proof or improved audit score is claimed.

This documentation commit uses `[skip render]`; it changes no application code, private settings or deployment.

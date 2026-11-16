# Live website tax and Apple build 7 — November 15 evening

This supersedes the tax and Apple status in earlier November 15 checkpoints. Times below are **November 16 UTC**; the session was still November 15 in Toronto. Provider settings, unpaid previews, automated tests and actual purchases are separate evidence.

## Both websites: tax enabled, purchases reopened

[RetainAI PR79](https://github.com/Retain-ap/retainai-prod/pull/79) merged as `82dc7b8c248846dd4bc72afd3f07facc34aace72`; its tree exactly matches tested head `812285d`. Both backend and frontend deployed. Validation passed **340 backend tests, 303 frontend tests**, lint/build, production dependency checks and secret scanning; required GitHub checks were green. New checkout attempts preserve their exact parameters and idempotency key, reject conflicting tax policies and support a purchase-only pause. Existing subscriptions are not migrated by this code.

With the owner's specific approval, both live Stripe accounts received the normal Canadian GST/HST registration and approved [product tax classifications](https://docs.stripe.com/tax/tax-codes). RetainAI uses business SaaS `txcd_10103001`; Closet Muse membership and Style Memory use personal SaaS `txcd_10103100`. The approved Tax Basic charge is 0.5% of qualifying new Checkout/Billing volume. Prices remain tax-exclusive: CA$20, CA$9.99 and CA$5. No private registration identifiers are stored here.

Three anonymous, unpaid hosted Checkout previews used a fictional Ontario location:

| Product | Subtotal | HST | Total |
| --- | ---: | ---: | ---: |
| RetainAI | CA$20.00 | CA$2.60 | CA$22.60 |
| Closet Muse membership | CA$9.99 | CA$1.30 | CA$11.29 |
| Style Memory | CA$5.00 | CA$0.65 | CA$5.65 |

No card was entered and Subscribe was not clicked. All three exact test sessions were subsequently confirmed **expired and unpaid**, with no Customer, Subscription or Invoice created. No standalone live Tax Calculations API call was made; [Stripe documents no tax fee for abandoned Checkout sessions](https://docs.stripe.com/tax/how-tax-works#pricing). These previews do **not** prove an application signup, address persistence, paid invoice, renewal, purchase, restore or webhook lifecycle.

The controlled rollout paused purchases, verified authenticated pause status, drained the old instances and inspected complete provider lists plus local pending records. There were **zero open sessions and zero unresolved local attempts**; the latest non-preview sessions were November 2 and completed. Tax was enabled while purchases remained paused. The first attempted unpause did not persist, which both live API and server checks caught; it was corrected before reporting completion.

Final verified state at **03:21–03:22 UTC**:

- RetainAI backend: `82dc7b8`, Render `dep-dbt7bj7f3r2c73c4t880`, Live **03:18:06**. Tax true; purchase pause false. Its frontend remains the PR79 release, `dep-dbt6odc9v7es73clm7a0`, with `main.41443fba.js`.
- Closet Muse: `5d08d6d0e1c425d198d810e1d6d47eab60e917bf`, Render `dep-dbt7bjlg1s2s738vt670`, Live **03:17:56**. Tax true; purchase pause false.
- Both authenticated billing-status responses confirm purchases reopened. Signed-in RetainAI Owner Console and Closet Muse Daily Edit remain accessible. **12 final public health/readiness/auth checks passed**; RetainAI's earlier **27 public HTML/route checks** also passed.
- RetainAI's public Stripe business name was corrected to **RetainAI** in the Dashboard and verified by API readback. An earlier own-account API update was rejected and was not bypassed. Legal identity, bank details and statement descriptors were not changed by this task.

Local sanitized receipts include `stripe-tax-final-runtime-20261116.json`, `stripe-tax-final-public-smoke-20261116.json`, `stripe-tax-postpause-inventory-20261116.json` and `stripe-tax-preview-expiry-20261116.json`. Checkout URLs and session receipts remain private and outside Git.

## Closet Muse Apple release: prepared, not submitted

Native build **7**, from exact source `5d08d6d`, uploaded successfully, is **VALID**, is assigned to the private testing group and is selected in the unsubmitted App Review draft. The **703-test** Linux application gate, **430 HTTP checks** and both Mac test jobs passed. The Mac result is **270 XCTest tests: 194 unit and 76 UI, zero failures**. This does not establish physical-device build 7 acceptance or an Apple purchase/restore flow. Public App Review has **not** been submitted and public App Store availability is not claimed.

The temporary Actions cap was restored to **US$0**. Recorded spend is **US$4.66**, an increase of **US$1.88** for this attempt. No further paid Actions run is authorized by this session record.

All **13 App Store screenshots** are refreshed and processed: seven iPhone and six iPad, comprising nine new images and four identical images safely reused. The same app version was restored to the same review draft; original subscription and group review items were preserved. The draft has exactly **three READY_FOR_REVIEW items**, `submittedDate: null`, and build 7 selected. Local evidence is in `apple-build7-screenshot-refresh-receipt.json` and `apple-build7-draft-screenshot-transaction.json`.

Apple Business items now show Active. The GST506 election-date discrepancy still has an unresolved Apple Finance request, **case 23542198**; Active status does not answer that date question.

## Still open

- Existing untaxed Stripe subscriptions were not changed: RetainAI's read-only inventory had two active and one trialing subscription. Existing renewal tax, customer locations and any migration need a separate reviewed decision. No retroactive tax adjustment was made.
- Complete physical build 7 photo, Planner and Account checks plus Apple purchase/restore from a non-complimentary account, resolve or obtain Apple's guidance on the GST506 date, then complete the App Review submission and await Apple's decision.
- RetainAI Calendly Production configuration is live, but fresh Production consent, callback, sync and later refresh remain unverified. Stripe Connect is still deferred. Prior Google approval is not a substitute for these separate integrations.
- Backup-key custody/recurring restore operations and genuine marketing proof/partner replies remain separate from release tests. No new outreach, invented testimonial or new audit score is claimed here.

This documentation-only change uses `[skip render]`; it must not trigger a new application deployment.

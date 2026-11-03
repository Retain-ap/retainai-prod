# Partner commission operations — 2026-11-02

The owner approved **30% for the first 12 months for both apps**. This supersedes earlier proposed Closet Muse flat rewards and non-final partner-page copy.

## Owner workflow

1. Agree the public `/partners` offer and payment details with the partner in writing. Retain that acceptance; a prospect list is not an enrollment or consent record.
2. Open the owner Partners & commissions screen. Enter the business name, public/business email and a unique lowercase link code; confirm written acceptance. Share the generated `/r/code` link with that accepted partner.
3. The first valid signed referral cookie lasts 60 days and is attached only when a new account is created. The existing account stores the code; Stripe Checkout and subscription metadata receive it server-side. Existing members cannot add a partner later. Cookies require the same browser; no cross-device attribution is promised.
4. Verified billing webhooks reconcile paid invoices. The 12-month window starts at the first paid base membership invoice. Renewals before its calendar anniversary can earn; cancellation/rejoining does not restart the term. Self-referrals and normalized email aliases are excluded. A different identity cannot be detected perfectly: review suspicious referrals before payment.
5. Each month, choose **Refresh from Stripe**. Review customer errors, invoice holds, refunds and negative balances. The 30-day hold must have elapsed. Payment recording requires all the partner's customer histories refreshed within five minutes, no review holds, and an exact current positive balance.
6. Send the approved payment separately using the agreed method. Record its unique external reference and the amount already sent. The application does **not** transfer funds. Never use the record button as a payment instruction. Download the accounting snapshot for your records.

## Accounting rules

- Base membership only; 30% after discounts and before tax, rounded half-up to Stripe minor units for each invoice. Add-ons, unpaid invoices and free trial invoices earn nothing. No reward is issued merely for registering.
- A 30-day hold applies from each successful invoice payment. Payments are reviewed monthly, with method/details agreed in writing. There is no automatic payout or partner self-service dashboard in this release.
- Full and partial cash refunds reduce commission proportionately to the refunded charge. Refunds after an external payment can create a negative balance carried against later earnings.
- Credit notes, prorations, unusual quantities, split/partial payments, disputes/fraud and incomplete Stripe histories are held for review. Do not manually edit the store to clear a hold. Resolve the provider allocation or request an audited reconciliation fix first. A won dispute may still need that review because Stripe can retain the disputed marker.
- First-touch attribution is signed, HttpOnly and secure. Pausing a partner link stops new attribution; it does not erase earned commissions or existing referrals.
- Customer identity is hashed in the commission ledger; Stripe customer/invoice IDs remain for reconciliation. Partners are not given members' private information. The owner can see their accounting records.
- Test/live transactions and currencies remain separate. Webhook retries replace invoice records instead of adding duplicate earnings. Stored base-price history preserves prior invoice eligibility when configuration changes.
- Current full-price examples: RetainAI CA$20 → CA$6 per qualifying monthly payment; Closet Muse CA$9.99 → CA$3 after rounding. Twelve unchanged, full-price payments would total CA$72 and CA$36 respectively, before refunds. These are arithmetic examples, not earnings promises.

## Maintenance and limits

The existing verified Stripe invoice/checkout webhook handles accounting. `charge.refunded` is handled if the Stripe endpoint subscribes to it; delivery of that additional event has not been verified in the provider dashboard. The mandatory pre-payment Stripe refresh retrieves current refunds and disputes regardless of refund-event delivery. Do not pay solely from an old balance.

No external referral SaaS, paid plan, payment transfers, new live purchases, bulk outreach or prospect enrollment was added. Tests use isolated storage and provider fixtures; they do not prove a live partner sale or renewal occurred.

Keep price configuration and webhook signing secrets intact. Review logs if a webhook returns 503: billing is processed first, and accounting retries safely. Histories above 500 invoices require manual engineering review. Retain this ledger through account deletion/recreation so the earning period cannot restart.

## RetainAI implementation

- UI: Owner Console → Partners; the existing canonical-owner and authenticator/MFA rules apply. No MFA bypass was added. If setup is still deferred, finish it before enrolling partners.
- Ledger: `partner_ledger` table in the existing `SQLITE_PATH` database, transactional writes shared by Gunicorn workers. Owner backup includes that database even when users are stored as JSON. Copy backups off the server as in the existing operations plan.
- Email and Google-assisted signup use the same signup endpoint. Google sign-in alone cannot create an account or change attribution.
- Backend financial regression tests include taxes/discounts/add-ons, hold/anniversary boundaries, signature/self-referral protections, repeat delivery, price changes, refund clawbacks, owner authorization and provider outages. Existing billing tests also check referral metadata.
- Release through a PR into `deploy` after all three existing CI checks pass; verify both Render services and live public/owner guards afterward.

## Closet Muse companion change

The separate Closet Muse repository has matching terms and owner accounting, documented in `docs/PARTNER_COMMISSIONS_2026-11-02.md`. Its release must pass the Linux Node 24.19 gate before merging into `main`. No app credentials or member data are shared between the two programs.

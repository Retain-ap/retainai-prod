# Launch polish and marketing desk — 7 November 2026

Coordinated with Claude; root reviewed, merged, deployed and checked production.

## Shipped

- RetainAI [PR48](https://github.com/Retain-ap/retainai-prod/pull/48): route-specific initial metadata, correct CAD20 structured price, removal of placeholder install screenshots, visible phone wordmark/login, and an honest Example label on fictional preview data. Trailing slashes keep the route's metadata. All three final release jobs passed on `80dd5f1280d7759fb5fa694f212f39219d2b3000`.
- Runtime commit `cbc6616c75f50f7237eb9485540c632d096af452`, frontend deployment `dep-dbncu9o473hc739h2050`, live at 07:12:40 UTC.
- ClosetMuse [PR26](https://github.com/Retain-ap/closet-muse/pull/26): sitemap/robots, canonical and social metadata, utility/private noindex, stable existing icon, 1200x630 branded share card, phone sample CTA and Google button/consent layout. Linux release run `42349818926` passed. Runtime `2bb2b28af182f9f4b5dfa52b79ea50358c5100b6`, deployment `dep-dbncstnb9u1s73ci9kf0`, live at 07:10:28 UTC.
- Live checks at 07:17 UTC passed 18 public metadata/icon/sitemap checks. RetainAI legal/invitation and trailing-slash routes also passed. Mobile layouts were inspected; signup tests did not create accounts or start payment/OAuth flows.
- Search Console accepted both first sitemap submissions on 7 November: RetainAI Success, 6 discovered pages; ClosetMuse Success, 10. These are discovered pages, not a claim of immediate indexing or ranking. Existing icons are valid; Google controls refresh timing.

## Required Render routing configuration

Render's existing catch-all continued serving homepage HTML for short paths even though each generated `index.html` file was deployed. Root saved these **Rewrite** rules in order on frontend service `srv-d4n4hna4d50c73f5u2v0`:

| Source | Destination |
| --- | --- |
| /partners | /partners/index.html |
| /signup | /signup/index.html |
| /privacy-policy | /privacy-policy/index.html |
| /terms-of-service | /terms-of-service/index.html |
| /refund-policy | /refund-policy/index.html |
| /login | /login/index.html |
| /accept-invite | /accept-invite/index.html |
| /* | /index.html |

Preserve these rules when recreating the service. The catch-all remains last for app/referral/client routes. Production `/partners` now returns 200 and its own canonical before JavaScript. No backend/environment/secret change was needed.

## Marketing deliverable

Local `outputs/marketing-desk.html` provides a free operator workspace: 14 drafts for Nov 8–14 Toronto, 10 historical prospects with explicit requalification status, approved brand assets, public campaign URL builder, separate existing referral-link checks, sourced manual metrics, and owner checklist. Browser save/reload, clipboard, export/import, assets and responsive forms passed; 30 validation checks passed. No posting, outreach, enrollment, payouts or account connection occurred.

UTM tags are not captured at signup. This desk does not claim automated analytics. Existing app partner attribution/commission ledgers remain authoritative: 30% of qualifying paid base membership for the first 12 months, with exclusions/refund adjustment and manual payout review. Historical email drafts remain unsent/address-blocked. Publishing awaits app-owned social accounts.

## Remaining owner/provider gates

- Calendly ordinary account is owner@retainai.ca; separate developer login still required before scoped OAuth app setup and real sync/disconnect testing.
- Google technical AI response was already sent. Sending the dedicated standard review credential still awaits specific approval; no owner credential will be shared. Both Google verification decisions remain external gates.
- Apple build 3 remains VALID and selected; review draft READY_FOR_REVIEW, submittedDate null. Physical iPhone acceptance, Apple Business Canadian tax/account resolution and bank processing remain. Owner confirmed personal CRA only, not GST/HST registration. Never invent a number or resubmit Active US forms.
- RetainAI encrypted production backup passed local restore; private OneDrive transfer approval remains pending. ClosetMuse encrypted cloud round-trip/restore passed. Both recovery keys need independent owner custody; recurring off-site retention remains.
- App-owned publishing profiles/logins needed for public posts. A valid business mailing address is still needed before cold email; never fabricate it. RetainAI Stripe Connect round trip was deferred by owner. Optional shopping affiliation/native Apple sign-in remain gated.

Do not describe either service as universally perfect or App Store approved. This checkpoint is evidence for the changes above, not a substitute for physical-device/provider acceptance.

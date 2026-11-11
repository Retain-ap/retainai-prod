# Audit release and launch gates — November 11, 2026

The owner asked for the complete public HeyCatch audit to be implemented, local/GitHub/Render history to be reconciled, and independent work on both apps to continue with Claude while they were away. Findings at full marks were left alone. Missing customer proof was not invented.

## Verified releases

- **Current application release:** [PR53](https://github.com/Retain-ap/retainai-prod/pull/53), `79965ac0ef230866ffb8709686c1f82385e598a9`. Backend Render `dep-dbq1ea0473hc73ccjkd0` became live at **02:21:22 EST**; frontend `dep-dbq1ea0473hc73ccjk9g` became live at **02:21:19 EST**. All three [release checks](https://github.com/Retain-ap/retainai-prod/actions/runs/42978423141) passed on reviewed head `3cb2b1d8c0697d3f04f9b924824f5b208bd5dbdf`: **255 backend tests**, **190 frontend tests**, lint, build and required dependency audits. The frontend production dependency audit reports zero findings; existing frontend development-only high findings remain below the configured critical-development gate. All **21** final route/metadata/bundle checks and all 13 API readiness checks passed. The loaded main asset is `main.3d39a20b.js`; the new guard is present in its lazy-loaded application chunk.
- PR53 closes a regression made reachable by optional business details: customer drafts and manual sends now require a saved nonblank business name before any AI/email provider call. The UI links to Settings and preserves the latest unsent draft, isolated by workspace and signed-in person and restored only after the matching customer loads. A 4,500-character round-trip regression covers the 5,000-character send limit. No signup steps were added. Independent review caught and corrected early consumption, cross-account storage scope and stale-input capture before release.
- [PR51](https://github.com/Retain-ap/retainai-prod/pull/51): backend `a31bbb7761b4cdb427622298cb519866e85afa67`, Render `dep-dbq0lft9el5s7391eflg`, live **01:28:21 EST**. It preserves owner edits during Calendly refresh, closes the disconnect/refresh race, persists a provider baseline, and supports the shorter verified signup. All **250 backend tests** passed; health and all 13 readiness checks passed.
- [PR52](https://github.com/Retain-ap/retainai-prod/pull/52): frontend `9ad36f0396d851f675e1902ed588b627accc1478`, Render `dep-dbq0nl2jnfac739m1o0g`, live **01:32:54 EST**. All **168 frontend tests**, lint, build and required dependency audits passed. Email signup now has four steps; Google skips the password step. Business setup follows login.
- Exact Render rewrites for the five new public pages and trailing-slash variants were added after the built files were live; the SPA catch-all remains last. **20/20** production route/metadata checks passed. Mobile home and every email-signup stage were checked at 375×812 with no horizontal overflow. Actual product imagery contains clearly labelled fictional example data.
- Older local feature branches were reconciled using exact-tree and patch comparisons against their squash merges. Their work was already present. The primary checkout was fast-forwarded; no feature commits were discarded or reapplied.
- Closet Muse's separate billing release `3e53d5b9a1b0c762647e693bf9b895b8ad2d7c6d` became live at **02:04:03 EST** with 17/17 production checks. It preserves verified Apple entitlement independently of new-sales availability and prevents duplicate website subscriptions. Its private repository holds the detailed release record.

## Exact HeyCatch change log

The audit's original scores are retained below for a later rerun. Stubbed proof slots remain unpublished until their evidence is supplied.

- D3.2 (was 0/5): Added guarded testimonial cards between features and pricing; they stay unpublished until real customer quotes and photos are approved.
- D3.3 (was 0/4): Added Mateo’s name, owner role and direct contact above the homepage FAQ, in the footer and on /about.
- D3.1 (was 0/4): Added a sourced, dated usage-proof slot in MarketingProof.jsx; no unsupported customer or activity count is published.
- D1.1 (was 4/6): Used the audit’s category-and-buyer wording in the homepage hero.
- D2.1 (was 4/7): Clarified who RetainAI is for and replaced the illustrated preview with the actual Contacts interface.
- D1.3 (was 3/4): Added the daily benefit of knowing which regulars need attention beside the homepage feature section.
- D2.2 (was 4/5): Made all three walkthrough controls real links to the existing 10-minute Calendly booking page.
- D5.1 (was 2/3): Created /pricing, /about, /features and /customers with distinct content, initial metadata and self-canonicals.
- D5.5 (was 2/3): Added matching FAQPage data, all six indexable answers, descriptive image text and llms.txt.
- D4.3 (was 2.5/5): Anchored C$20 monthly pricing as less than C$1 a day, with billing and separate charges explained.
- D4.4 (was 3/4): Explained the single monthly plan without annual commitment or separate feature tiers on home and /pricing.
- D3.4 (was 2/4): Named Stripe beside the trial CTA, reiterated cancel/export controls and added a genuine product preview.
- D3.5 (was 0/3): Added a guarded, dated third-party mention slot in MarketingProof.jsx; no invented endorsement is shown.
- D5.3 (was 3/4): Added /retention-crm-for-service-businesses and linked it from site navigation and the sitemap.
- D2.5 (was 1/4): Improved phone navigation and signup fields; checked home and all four email-signup stages at 375×812 with no horizontal overflow.
- D1.5 (was 2/3): Replaced the mock with an actual Contacts screenshot on home and /features, clearly labelled as example data.
- D1.4 (was 2/3): Kept every FAQ answer in the page and expanded trial eligibility, card, renewal and cancellation details on home, pricing and signup.
- D4.2 (was 3/4): Made the full-workspace trial and its billing conditions explicit while preserving the single monthly plan.
- D2.B (was +0/2): Clarified on the category page that large enterprise sales rollouts are outside RetainAI’s intended fit.
- D2.3 (was 3/5): Improved billing-text contrast and FAQ controls; checked desktop layout and preserved the existing section order.
- D2.4 (was 3/4): Reduced email signup from nine steps to four; Google skips the password step, and business setup moves after login.

## Provider and marketing state

- RetainAI Google Contacts and Calendar verification was approved November 9. A pending credential-disclosure reply was unnecessary and was not sent.
- Calendly Sandbox connected with read-only scheduled-events access. The first successful sync at **01:16:18 EST** read zero events and created/updated zero contacts. This proves authorization and an empty sync, not a nonempty booking lifecycle. Production OAuth app creation/authorization and a real booking/reschedule/cancellation acceptance test remain separate.
- Closet Muse Calendar data-access review remains with Google; its remediation reply is already sent. Public Calendar stays disabled pending approval.
- Encrypted backups were transferred privately and download/restore evidence retained outside this repository. Independent recovery-key custody and a recurring offsite routine still need confirmation. No keys, private archives or credentials belong in the repo.
- RetainAI's final live Stripe Connect round trip was explicitly deferred by the owner.
- Closet Muse's free download, build 3, screenshots, published privacy declaration and automatic release-after-approval option are prepared. Apple account prerequisites, physical iPhone acceptance and App Review submission remain outstanding. The app is not publicly released.
- Both partner offers remain **30% for the first 12 months**, subject to the existing hold/refund/attribution terms. All ten existing prospects were requalified against official sources. Only SalonSmartz has confirmed public Calendly use; its clients' tools remain unknown. Stale La Closette contact/FAQ claims were corrected, and Styleista's policy against paid reviews was respected.
- The existing marketing desk and 14-post kit were preserved. Public posting still needs the app-owned publishing identities selected by the owner. Commercial email needs legitimate sender information and partner activation needs written acceptance. No posts, new outreach or accepted partnerships are claimed.

## Evidence still needed

- Two or three real customer quotes and photos, with permission to publish.
- A verified production usage count with a public-safe source/date, excluding test accounts.
- The owner's own short founder story, portrait and confirmed public profile.
- One genuine dated third-party listing, review or mention.

Local November 11 evidence includes route checks, mobile screenshots, exact audit scores, deployment proofs and the marketing requalification table. Temporary preview servers were stopped after verification. Do not infer live-provider or physical-device acceptance from mocked tests.


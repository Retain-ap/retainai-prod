# HeyCatch evidence and remaining owner inputs

Audit: https://app.heycatch.ai/audit/hck_pk_qjz4tFpR_LvQkTRpBRn87x0WnOpJVrBJ?surface=website

Read in full on 11 November 2026. Public-site work follows Quick wins, then Do this quarter. The existing full-score pain copy (D1.2), vocabulary (D1.6), one-click pricing (D4.1), heading structure (D5.2) and lightweight dependency set (D5.4) are preserved.

## Evidence that cannot be invented

`frontend/src/proofContent.json` is the single publication file. Empty slots do not render. Do not populate it with demo users, test events, synthetic quotes, estimated customer counts, stock portraits, placeholder badges or guessed profile links.

- **D3.2 (0/5):** Collect two or three real customer quotes. Each needs permission, exact quote, name, business type/name, location, photo rights and a concrete outcome. Populate `testimonials` with `approved: true`, `name`, `quote`, `business`, `location`, `photo`, `source`, and `approvedOn` only after approval. Keep permission records privately; `source` can be a nonsensitive reference, not a private transcript. The component sits between the feature grid and pricing, as requested by the audit.
- **D3.3 (0/4):** Mateo Zufic's verified name, owner role and direct contact are public. Still needed: his own three-sentence reason for building RetainAI, a photo he owns and his confirmed public LinkedIn or X URL. These optional `owner` fields remain null. A photo or personal story was not generated.
- **D3.1 (0/4):** A count must come from a documented production query with trial/reviewer/test accounts and synthetic activity excluded. Publish `usage` only with `approved: true`, a positive `count`, precise `label`, public-safe `source` description and `updatedOn`. Do not imply that a demo workspace represents a paying customer. No production usage claim is currently published.
- **D3.5 (0/3):** Supply a real dated third-party listing, review or mention with permission to reuse its content. `externalMention` needs `approved: true`, `title`, HTTPS `url` and `publishedOn`. A link is used instead of an unlicensed logo. No badge is currently published.
- **D1.5 (2/3):** `productCapture` now contains the actual Contacts screen captured on 11 November 2026 from an isolated local workspace running the deployed Flask backend and React app. Six fictional `.test` contacts and nine sample appointments were seeded; no live provider or customer data was used. The original 1280×720 JPEG bytes are preserved (79,086 bytes), with no visual editing or re-encoding. The hand-built mock is removed, and the real screenshot appears on home and Features with an explicit example-data caption. Capture provenance: `work/serve-retainai-real-demo-20261111.py` in the task workspace, based on b3313a3/cbc6616. It was visually inspected for private information before publication.

## Decisions kept honest

The audit's suggested “less than one missed rebooking a year” needs an assumed appointment value that has not been supplied. The page instead anchors the actual C$20 monthly subscription as less than C$1 per day, with monthly billing, taxes and separate connected-service fees clear. No invented guarantee, discount, annual plan or “most popular” badge was added. The single-tier comparison bonus D4.B is not applicable.

The new category page uses the audience's own follow-up/rebooking vocabulary. It does not publish competitors' unverified current prices or claim superiority without evidence.

## Hosting requirement

Add explicit static rewrites before the existing SPA catch-all for `/pricing`, `/about`, `/features`, `/customers`, and `/retention-crm-for-service-businesses` to their respective `/.../index.html` output, including trailing-slash handling using the existing host convention. Each generated file has its own initial title, description, self-canonical, Open Graph and Twitter metadata. Check the actual short URLs after deployment, not only local files. `/llms.txt` and `/sitemap.xml` must be served as files.

## Measurement

Audit hypotheses are not results. Compare homepage-to-trial and walkthrough completion over four weeks; use 60 days for non-homepage search impressions and 90 days for category-page organic entries. No new analytics vendor, tracking cookie or fabricated baseline was introduced by this change.

## Finding checklist (scores are the audit's original scores)

| Finding | Was | Repo work / remaining evidence |
| --- | --- | --- |
| D3.2 | 0/5 | Customer quote component is gated off until real approved quotes and photos arrive. |
| D3.3 | 0/4 | Named owner block, direct contact, footer identity and actual About page; own story, portrait and profile remain needed. |
| D3.1 | 0/4 | Sourced, dated usage slot is gated off; no trustworthy production count supplied. |
| D1.1 | 4/6 | Audit-proposed category/buyer kicker, existing outcome headline and subhead retained. |
| D2.1 | 4/7 | Same hero clarification plus the actual Contacts workspace capture with example data. |
| D1.3 | 3/4 | Adds the calm, on-top-of-regulars daily job beside the unchanged feature copy. |
| D2.2 | 4/5 | Three walkthrough controls are semantic links to the existing ten-minute Calendly event. |
| D5.1 | 2/3 | Real /pricing, /about, /features and /customers routes, distinct initial metadata and self-canonicals. |
| D5.5 | 2/3 | Six actual FAQ answers in initial HTML and matching FAQPage schema; descriptive logo/capture alt; llms.txt. Existing product and organization schema retained. |
| D4.3 | 2.5/5 | Honest monthly price anchor and payment reassurance; no invented discounts or popularity badge. |
| D4.4 | 3/4 | Explains focused single plan, no annual commitment or feature tiers, without unverified competitor-price comparisons. |
| D3.4 | 2/4 | Names Stripe beside trial CTA, repeats cancel/export controls and preserves honest card requirement; no new refund guarantee. |
| D3.5 | 0/3 | Dated third-party link slot is gated off until a real mention exists. |
| D5.3 | 3/4 | Indexable service-business category page, site navigation links and sitemap entry. |
| D2.5 | 1/4 | Reachable phone navigation, compact category kicker and existing stacked pricing; parent must record actual375×812 pass on home and integrated signup. |
| D1.5 | 2/3 | Actual Contacts screenshot replaces the hand-built mock; six fictional contacts, clear example-data caption, descriptive alt, no private production data. |
| D1.4 | 2/3 | All FAQ answers remain in DOM, trial answer expanded by default with cancellation/card/eligibility details. Signup shortening is a separate integration. |
| D4.2 | 3/4 | Trial gating stated on home and pricing; existing monthly model preserved. |
| D2.B | +0/2 | Category page explicitly identifies large enterprise sales rollouts as outside the intended fit. |
| D2.3 | 3/5 | Existing page flow retained; clearer billing text contrast and native FAQ controls. Parent visual review pending. |
| D2.4 | 3/4 | Separate signup workstream owns shortening onboarding; not changed by this public-page commit. |
| D4.B | +0/1 | No change: audit itself says comparison table is not required for the one-tier product. |
| Brief fit | 8/10 | Category/buyer and trial framing addressed through mapped findings above; no invented finding code. |

Local verification before integration: all 32 frontend suites / 160 tests passed; changed-file ESLint passed; production build and prerender succeeded. The extra route-metadata lifecycle regression added afterward passed (7-test targeted suite). Screenshot replacement then passed a 36-test targeted suite and a production build/prerender. The local asset remains the original 79 KB capture; no new runtime dependencies were added. Parent is responsible for combined-branch tests, actual responsive review, hosting configuration and post-deploy URLs.

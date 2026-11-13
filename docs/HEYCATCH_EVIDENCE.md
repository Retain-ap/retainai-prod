# HeyCatch evidence and remaining owner inputs

Audit: https://app.heycatch.ai/audit/hck_pk_qjz4tFpR_LvQkTRpBRn87x0WnOpJVrBJ?surface=website

Read in full on 11 November 2026 and again on 13 November at 15:08 UTC, including all six expanded dimensions and all 13 ordered actions. The current shared report still quotes the old nine-step signup and duplicated page metadata: this was a fresh reading, not a new HeyCatch scan. All 22 below-maximum coded scores match the November 11 baseline; D4.B explicitly requires no comparison table for a single plan. Public-site work follows Quick wins, then Do this quarter. The existing full-score pain copy (D1.2), vocabulary (D1.6), one-click pricing (D4.1), heading structure (D5.2) and lightweight dependency set (D5.4) are preserved.

The report displays Trust as 4/20 even though its listed subcriteria sum to 2/20. Preserve the report's exact per-finding scores; do not silently reconcile that discrepancy. The full fresh insights, action order and comparison receipt are archived privately in the task workspace under `outputs/night-20261113/heycatch-fresh`. No new score or conversion uplift is claimed.

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

For every new public route, including `/find-customers-who-stopped-rebooking`, add both the exact path and its trailing-slash variant in Render's frontend **Redirects/Rewrites**, pointing to the route's `/index.html` file with action **Rewrite**, before `/* → /index.html`. Keep the existing rules. The rebooking guide's two rules were saved and verified on 12 November 2026 UTC. No repository Blueprint currently manages these dashboard rules.

After the deployment and routing update, run `node tools/check-public-route-html.cjs` from the repository root (Node 20 or later). It reads the public route list and expected metadata directly from the application, requests both URL forms without running JavaScript, and exits unsuccessfully if a page serves another route's title, description, canonical, social URL or indexing directive. It includes the noindex sign-in and invite pages. An optional origin argument can check a local build, for example `node tools/check-public-route-html.cjs http://localhost:3000`. It only sends anonymous GET requests; it does not change hosting settings or customer data.

A browser showing the right page is not enough: client-side routing can hide an incorrect initial HTML response from the SPA catch-all. Resolve an actual failed check rather than repeatedly deploying unchanged code or assuming the edge cache is the cause.

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
| D2.5 | 1/4 | Reachable phone navigation, compact category kicker and stacked pricing. November 11 verification covered home and all four email-signup stages at 375×812 without horizontal overflow; the homepage trial CTA was visible in the first screen. |
| D1.5 | 2/3 | Actual Contacts screenshot replaces the hand-built mock; six fictional contacts, clear example-data caption, descriptive alt, no private production data. |
| D1.4 | 2/3 | All FAQ answers remain in DOM, trial answer expanded by default with cancellation/card/eligibility details. Signup shortening is a separate integration. |
| D4.2 | 3/4 | Trial gating stated on home and pricing; existing monthly model preserved. |
| D2.B | +0/2 | Category page explicitly identifies large enterprise sales rollouts as outside the intended fit. |
| D2.3 | 3/5 | Existing page flow retained; clearer billing text contrast and native FAQ controls. Desktop visual review completed for the November 11 release. |
| D2.4 | 3/4 | Live four-step email signup (Google skips the password step), with business details deferred until after login. Compatible backend PR51 preceded frontend PR52; see HEYCATCH_SIGNUP_20261111.md. |
| D4.B | +0/1 | No change: audit itself says comparison table is not required for the one-tier product. |
| Brief fit | 8/10 | Category/buyer and trial framing addressed through mapped findings above; no invented finding code. |

Historical pre-integration verification: all 32 frontend suites / 160 tests passed; changed-file ESLint passed; production build and prerender succeeded. The extra route-metadata lifecycle regression added afterward passed (7-test targeted suite). Screenshot replacement then passed a 36-test targeted suite and a production build/prerender. The local asset remains the original 79 KB capture; no new runtime dependencies were added. The combined release and live checks below supersede those intermediate counts.

## Combined frontend release

PR51's backward-compatible backend became live before PR52's combined frontend on November 11. PR52 combined public-site commits `c8330d9` and `611fd5a` with signup commit `e3f1d82`; 33 frontend suites / 168 tests, lint and production build passed. Five public-page rewrite pairs were saved, 20/20 live route checks passed, and home plus every email-signup stage were checked at 375×812. PR53 then added the business-name send guard and passed 190 frontend / 255 backend tests with 21 route/metadata/bundle checks. The dated release record is `chats/2026-11-11-audit-release-and-launch-gates.md`.

On November 13, all 27 current anonymous public-route HTML checks passed at 15:09 UTC, including distinct initial metadata, canonical URLs and indexing rules. Later PR74's frontend and backend became live at 15:11 UTC; its runtime changes do not rewrite the audited marketing copy. Final anonymous checks passed for both apps. A new browser pass stalled on session/control access, so no fresh mobile screenshot or post-PR74 Calendly re-sync is claimed. November 11 responsive evidence remains dated, not silently relabeled as today's test. Current release details are in `chats/2026-11-13-followup-release.md`.

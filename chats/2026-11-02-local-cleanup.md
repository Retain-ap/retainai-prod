# Local cleanup, rate limits and Skimlinks — October 27 to November 2, 2026

Claude Code desktop session on the owner's Windows PC (not a cloud session).
Fresh clones of both apps live in `C:\Users\JZufi\Documents\Apps`; older copies
were left untouched.

## What was asked

Fix the broken Codex config, organize the app folders, finish open integration
work on both apps and push to Render, touch up RetainAI email, then add an
affiliate network for Closet Muse in place of Awin.

## RetainAI (on `deploy`, live)

- `4737801`: login, password reset and signup rate limits are shared across
  the 2 gunicorn workers through SQLite on the data disk (`backend/rate_limit.py`),
  keyed on `CF-Connecting-IP`. Tests in `backend/test_rate_limit.py`.
- `bd7e25a`: `backend/sendgrid_unsubscribe_footer.py` checks the five customer
  templates for an unsubscribe link; `--apply` adds a new version with one and
  keeps the old one for rollback. The owner then updated the templates via Codex.
- `202a613`: CI actions moved off the deprecated Node 20 runtime.

## Closet Muse (on `main`, live)

- `647b8be`: `@next/next/no-img-element` turned off with the reason in
  `eslint.config.mjs` (protected uploads, blob previews, any-domain retailer images).
- `5b313cb`: retailer links go through Skimlinks (site `312170X1800748`) by
  wrapping each link (`lib/affiliate.ts`) instead of loading the Skimlinks
  script, so the CSP stays closed. Privacy policy has a "Retailer links" section.
  Smoke 17/17 on the deployed commit.

## Decided against

- Moving `retainai.ca` and `closetmuse.ca` nameservers to Cloudflare: both
  already serve valid HTTPS, and a move risks Microsoft 365 mail and SendGrid DNS.
  The owner said not to if it could break anything.
- Awin: too expensive; replaced by Skimlinks.

## Still open

- Skimlinks site approval. If review asks for the script, add it to public pages only.
- Delete the old RetainAI branches (all contained in or superseded by `deploy`;
  the default branch is `deploy`). Claude's delete was blocked by a permission
  check, so the owner runs it:
  `git push origin --delete claude/services-review-completion-xx8reo codex/verified-launch-hardening-20260903 "deploy'" fix/final-launch-hardening-20260821 fix/pass-verified-session-to-dashboard main signup-fix test-deployment`
- Stripe Connect round trip in RetainAI, then remove the onrender.com redirect URI in Stripe.
- Closet Muse: backup key check, Google Calendar review video, member Apple
  sign-in, tax review, retailer feed.

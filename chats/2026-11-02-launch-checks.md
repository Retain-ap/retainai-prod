# Launch checks — November 2, 2026

Claude Code session: https://claude.ai/code/session_01Mgb7adczPzd6TngKpNVeLg

## Done
- Closet Muse: `CLOSET_MUSE_STRIPE_PORTAL_CONFIGURATION_ID=bpc_1UJqn8BntTiyox6H8A9oHlZU`
  pinned on Render; redeployed, 17/17 smoke checks, no errors.
- RetainAI: Stripe Connect callback returned `authentication_required` because it
  came back on `retainai-prod.onrender.com` (no session cookie there).
  `STRIPE_REDIRECT_URI` on Render is now `https://api.retainai.ca/api/stripe/oauth/callback`,
  and that URI is registered in the RetainAI Stripe account. Retry reached
  Stripe without a redirect error.
- `retainai.ca` redirects to `https://www.retainai.ca/`.
- SendGrid templates updated with the unsubscribe link (owner, via Codex).
- Real test signups on both apps passed the access check. Renewals cancelled
  (RetainAI ends Nov 16, Closet Muse Dec 2); Closet Muse CA$9.99 refunded.

## Still open
- Complete one Stripe Connect round trip in RetainAI (Settings → Integrations).
- Closet Muse items gated off for launch: Google Calendar review video, member
  Apple sign-in, retailer feed, native iOS app, backup key check, tax review.

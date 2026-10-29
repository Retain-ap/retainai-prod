# Production polish pass — October 28–29, 2026

Claude Code session: https://claude.ai/code/session_01Mgb7adczPzd6TngKpNVeLg
(continues [the services review](2026-10-24-services-review.md))

## What was asked

Set up the Closet Muse Style Memory price in Stripe, then do everything possible
for the best production experience on both apps, from UI/UX to the servers.

## Style Memory price

Already done on 2026-09-28: CA$5.00/month `price_1UIkiHBntTiyox6Hze5wQQDG`
(product `prod_VJNT61M6GawO9O`) in the Closet Muse Stripe account, saved as
`CLOSET_MUSE_STRIPE_STYLE_MEMORY_PRICE_ID` on Render and deployed since. No price
errors in Render logs. A real purchase has not been tested.

## RetainAI — [PR #6](https://github.com/Retain-ap/retainai-prod/pull/6), live

Browser audit (axe-core, serious/critical) of every public page and every
signed-in section at 390px and 1280px:
- Guided setup no longer covers the dashboard on phones: it starts as a
  "Setup · 2 of 8" pill, opens on tap, minimizes anywhere, remembers the choice.
- Login, invite and app pages have their own tab titles.
- Anonymous visitors no longer request the push key on every page.
- All accessibility findings fixed: calendar arrows, automation fields, template
  dropdown, AI Studio search, chart slices, decorative logos, landing preview
  buttons, low-contrast text.

## Closet Muse — [PR #4](https://github.com/Retain-ap/closet-muse/pull/4)

Same audit at phone, tablet and desktop with a local production build and
disposable accounts. The signed-in app already passed everywhere. Fixed:
- Every public page had the homepage title; each now has its own.
- Three low-contrast labels (homepage art label, recovery kicker, install button).
Release gate: 582/582 tests, 164 HTTP checks, build, audit, lint.

## Servers (via the Render connector)

- RetainAI backend: 2 gunicorn workers, 1 instance, about 225 MB of 512 MB, no
  errors since the deploys. Rate limits were already moved to shared SQLite.
- Closet Muse: about 159 MB of 512 MB. Only errors are outside scanners probing
  for the patched Next.js Server Action flaw; the app has no Server Actions.
- Both RetainAI services deploy only from `deploy`, so the old branches are unused.

## Still open (owner only)

1. Render dashboard: add or verify `retainai.ca` under the RetainAI frontend's
   Custom Domains (the connector has no domain tool).
2. SendGrid: unsubscribe link in the birthday and AI follow-up templates (a
   helper tool for this was added to the repo on Oct 27).
3. One real signup and payment on each app.
4. Closet Muse provider items: Google Calendar review, Apple sign-in for members,
   retailer network approval, App Store build, backup key check, legal review.

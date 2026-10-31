# iPad and phone fixes — October 31, 2026

Claude Code session: https://claude.ai/code/session_01Mgb7adczPzd6TngKpNVeLg

## What was asked

"The app isn't working right across any device." Review, fix and push to Render.
Closet Muse on hold.

## How it was found

Render logs: every API request from the owner's iPad session returned 200, so
the backend was fine. The real backend and frontend were run locally with a
seeded workspace and driven in Chromium at iPad portrait/landscape, iPad mini,
iPhone 14 and desktop.

## Fixed — [PR #8](https://github.com/Retain-ap/retainai-prod/pull/8), live 04:29 UTC

- Contact drawer could not be closed on iPad/phone: `isolation: isolate` on
  `.crm-main-content` trapped it and every dialog under the mobile header.
  Removed; dialogs raised to z-index 1100+.
- Calendar month grid collapsed on iPad portrait: a ≤900px rule forced every
  grid to one column. Now phones only, with `.ra-keep-grid` opt-outs.
- Guided setup covered pages on iPad and desktop: now starts collapsed everywhere.
- Contact names cut off on phones: badges move under the name.
- Calendar "Add appointment" did nothing until a day was picked: now books today.
- Account menu (Log out) is a proper, labeled button.
- follow-redirects 1.16.2 for a new high-severity advisory.

End-to-end checks passed at iPad, phone and desktop: add/search/open/close/edit
contacts, mark contacted, book an appointment, save profile, reload keeps the
session, log out.

## Still open (owner only)

- Render: add or verify `retainai.ca` under the frontend's Custom Domains.
- SendGrid: unsubscribe link in the Birthday Greeting and AI follow-up templates.
- Closet Muse: on hold by request.

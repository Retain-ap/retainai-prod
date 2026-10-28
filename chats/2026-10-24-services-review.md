# Services review and launch fixes — October 24–28, 2026

Claude Code session: https://claude.ai/code/session_01Mgb7adczPzd6TngKpNVeLg

## What was asked

Review both Render services, finish what was left, suggest additions, then finish
Closet Muse, then make the context visible from every device.

## RetainAI (merged into `deploy`, live)

[PR #3](https://github.com/Retain-ap/retainai-prod/pull/3):
- Birthday greetings respect unsubscribes and carry the unsubscribe link and headers.
- A stale browser tab can no longer undo a customer's unsubscribe; the contact
  drawer warns before switching an unsubscribed customer back.
- Production stopped trusting `http://localhost:3000` for CORS and writes.
- WhatsApp template debug route limited to the platform owner.
- axios and follow-redirects advisories patched; flaky email verification test fixed.
- Landing page JavaScript cut from 318 KB to 106 KB (dashboard loads on demand).

[PR #4](https://github.com/Retain-ap/retainai-prod/pull/4): uptime monitor
(`.github/workflows/uptime.yml`) for both apps every 15 minutes; failures email
the owner.

[PR #5](https://github.com/Retain-ap/retainai-prod/pull/5): `CLAUDE.md` context
file and this `chats/` folder.

## Closet Muse (merged into `main`, live)

- [PR #1](https://github.com/Retain-ap/closet-muse/pull/1): Next.js 16.3.8 → 16.4.3 for
  critical remote code execution advisories. Release gate passed (582 tests,
  164 HTTP checks); live smoke 17/17 on `ef57fc805045`.
- [PR #2](https://github.com/Retain-ap/closet-muse/pull/2): release record
  `docs/RELEASE_2026-10-24.md`.
- [PR #3](https://github.com/Retain-ap/closet-muse/pull/3): `CLAUDE.md` context.

## Still open (owner only)

1. Render: add or verify `retainai.ca` (no www) under the RetainAI frontend
   static site's Custom Domains. It currently fails TLS.
2. SendGrid: add `<a href="{{unsubscribe_url}}">Unsubscribe from email follow-ups</a>`
   to the birthday and AI follow-up templates.
3. Closet Muse launch items in its `docs/CONTINUE_HERE_2026-10-17.md` (backup key
   verification, Google Calendar review, Apple devices, Stripe sandbox, legal review).

## Left on purpose

- RetainAI signup/login rate limits: needs the Render worker count and client IP
  header confirmed first.
- Old RetainAI branches: check whether a Render service uses one before deleting.
- Closet Muse scheduled release check: its workflows are manual-only by the
  owner's earlier choice.

## Notes

- Claude cannot read ChatGPT. Export it from ChatGPT → Settings → Data controls
  → Export data and upload the chats that matter.
- Connecting Render under claude.ai → Settings → Connectors lets a session fix
  the domain and check deploy logs directly.

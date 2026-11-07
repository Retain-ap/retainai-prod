# Fixed AI routing and production recovery — November 7, 2026 UTC

This continues the [November 6 release handoff](2026-11-06-value-calendly-and-inspired-looks.md).
The owner opened RetainAI's MFA-protected Owner Console. Calendly account
sign-in and the switch from the personal address to `owner@retainai.ca` are
still being completed in Edge; no Calendly app credentials or live connection
are claimed.

## Fixed AI route

Claude implemented [PR39](https://github.com/Retain-ap/retainai-prod/pull/39),
and Codex independently reviewed it, verified its official routing metadata,
ran a synthetic live request from the actual backend and merged it after all
three release gates passed. The route is OpenRouter → OpenAI GPT-4.1 mini,
with OpenAI as the sole allowed provider, no model/provider fallback,
`data_collection: deny`, required parameter support and fixed price caps.
The live response identified OpenAI and `openai/gpt-4.1-mini`, HTTP 200,
cost USD 0.00002. No customer data was used.

Both services deployed `a514a8f7379da7e60c58ccf172969621d6427d8a` successfully,
and all 15 anonymous production HTTP checks passed. Detailed evidence and
limits are in [AI routing](../docs/AI_ROUTING.md). Public privacy text matches
the fixed route and still does not claim zero retention. The final Google
reply is prepared locally but **not sent**. The dedicated standard reviewer
account was subsequently created and tested; specific approval to send its
privately saved credential to Google's verification team remains required.
No owner credentials will be supplied.

## Actual production backup

The fresh production archive `retainai-backup-20261107T021411Z.zip` passed
manifest, archive checksum and SQLite checks. Codex downloaded it, encrypted
it with a new separately DPAPI-protected passphrase, and restored it into an
isolated private WSL Linux directory. The app's storage layer read **5 users,
1 workspace with contacts, 5 contacts and 15 files**, matching Owner Console.
The temporary plaintext was removed. See [backup evidence and remaining
gates](../docs/BACKUP_AND_RESTORE.md).

This is a real local production restore, not the earlier seed-data fixture.
Private cloud upload/round-trip verification, separate password-manager key
escrow, production data-key escrow and recurring off-site retention remain.
No recovery key or customer record was put in Git or chat.

## Owner account form

The owner reported a valid reviewer password being rejected by the browser.
The JSX `pattern` used an incorrectly double-escaped digit matcher. Codex
replaced it with `[0-9]` in [PR40](https://github.com/Retain-ap/retainai-prod/pull/40)
and added a rendered-input validity regression for a valid password and
missing length/character requirements. All five focused Owner Console tests
and all three release gates passed. PR40 merged as
`d5c990308f15721c9e45537077cca29cbabe28b7`. The frontend-only change went live
at 02:30:24 UTC as `dep-dbn8q0nb9u1s73cf2hv0`. Codex reloaded the fresh Owner
Console, opened the creator and verified the actual DOM pattern uses `[0-9]`.
The backend remains on the validated PR39 release. After the owner explicitly
asked Codex to generate and privately save the initial password for this new
review account, Codex created `owner+google-review-20261102@retainai.ca` with
complimentary access, then verified an actual login and dashboard access.
The owner API returned `platform_owner_required`, confirming that this is
not a platform-admin account. Google Contacts and Calendar connection controls
are reachable. The owner's Google account is not connected to this workspace.
The new credential is current-user DPAPI-protected outside the repo; its
temporary plaintext entry file was removed after login validation. The owner's
previously attempted password was not read, copied or changed by Codex.

## Unchanged launch gates

- RetainAI: complete Calendly account/app configuration and actual OAuth/import
  acceptance; dedicated Google reviewer access and final reply; the deferred
  Stripe Connect round trip; remaining cloud backup/key-custody steps.
- Closet Muse: its real private cloud backup/restore already passed; independent
  key custody, recurring retention, physical-iPhone TestFlight 3 acceptance and
  Apple's Canadian tax requirements remain. Do not repeat the active U.S. forms.
- Google approval, physical-device testing and public App Review submission
  are not inferred from passing code tests. Public Calendar stays gated until
  approval. Partner posts still await the chosen app publishing accounts.

This handoff is documentation-only. It contains no secrets or customer data.

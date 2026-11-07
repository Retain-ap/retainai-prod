# Fixed AI routing and production recovery — November 7, 2026 UTC

This continues the [November 6 release handoff](2026-11-06-value-calendly-and-inspired-looks.md).
The owner opened RetainAI's MFA-protected Owner Console. The standard Google
reviewer account is now created and tested. Calendly's normal personal account
is signed in, and its separate developer registration is prepared with
`owner@retainai.ca`; no Calendly app credentials or live connection are claimed.

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
The private, empty OneDrive folder **RetainAI Backups** is prepared. Specific
approval to upload the encrypted production archive is pending; no customer
archive has been uploaded there. Cloud upload/round-trip verification, separate
password-manager key escrow, production data-key escrow and recurring off-site
retention remain.
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

The reviewer workspace's real CSV import subsequently added two fictional
contacts, Alex Maple and Jordan Cedar, using `example.com` addresses and a
**Review demo** tag. Preview and commit showed 2 added, 0 updated, skipped or
failed. No email consent was recorded. A real AI Studio draft for Alex was
generated through the production app. No messages were sent and no automation
was enabled. The local Google reply now describes these ready-to-use samples.
The point-in-time backup above predates this reviewer account and sample data;
its 5-account/5-contact counts should not be presented as the newest live totals.

## Import and Calendar navigation

Claude implemented [PR42](https://github.com/Retain-ap/retainai-prod/pull/42),
and Codex's independent review caught an adjacent Calendar bug: both connection
prompts opened the Google Contacts importer, which requests Contacts scopes and
cannot connect Calendar. The revised change opens Settings > Integrations for
both Calendar prompts, while general contact entry points open the CSV/vCard
importer. Explicit `?source=google` still highlights Google Contacts.

All three required checks passed on the final up-to-date head `14bbcda` in
[run 42331480195](https://github.com/Retain-ap/retainai-prod/actions/runs/42331480195),
including 119 frontend tests in 29 suites. The new route regressions fail against
the old code. Local real-backend browser checks passed at phone, tablet and
desktop widths. PR42 merged as `5343012fdadfb468bf4d17ffc9758d7667b6d2be`.
Frontend deployment `dep-dbn96c142hec73c7nsi0` went live at 02:56:44 UTC.
Codex then verified the actual production reviewer session: Contacts > Import
Leads opens `/app/import` at the file importer, and both Calendar prompts open
`/app?tab=integrations` with the Google Calendar card. No authorization was
started. Backend runtime remains the separately validated PR39 release.

## Calendly owner setup

The account menu's **Developer** link currently opens the developer docs. The
docs' **Log in** link leads to a separate developer portal at
`https://login.calendly.com/`, whose sign-up form is prepared with the owner
email and name. Registration is held because its final step accepts Calendly
API terms; the owner is away and requested no questions. No password or API key
has been created for that account yet.

The existing personal Calendly login remains Google-linked. Its **Change email**
action opens a Google account chooser rather than an ordinary email edit form.
Codex backed out without choosing or granting access. Unlinking/changing that
existing authentication method requires the owner's participation. Complete any
login change before testing integrations, since Calendly documents that such
changes revoke existing OAuth and personal access tokens
([Calendly API FAQ](https://developer.calendly.com/docs/getting-started/frequently-asked-questions)).

The prepared integration should use `scheduled_events:read` and callback
`https://api.retainai.ca/api/calendly/oauth/callback`. Register a Sandbox app,
securely configure its credentials, then test the real token exchange and booking
import before production setup. A documentation example showing `scope: default`
is not evidence that the live token response has that value: do not weaken
current scope enforcement based on the example alone.

## Unchanged launch gates

- RetainAI: complete Calendly account/app configuration and actual OAuth/import
  acceptance; approval to disclose the dedicated reviewer credential and send
  the prepared Google reply; the deferred Stripe Connect round trip; remaining
  cloud backup/key-custody steps.
- Closet Muse: its real private cloud backup/restore already passed; independent
  key custody, recurring retention, physical-iPhone TestFlight 3 acceptance and
  Apple's Canadian tax requirements remain. Do not repeat the active U.S. forms.
- Google approval, physical-device testing and public App Review submission
  are not inferred from passing code tests. Public Calendar stays gated until
  approval. Partner posts still await the chosen app publishing accounts.

This handoff is documentation-only. It contains no secrets or customer data.

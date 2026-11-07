# Fixed AI routing and production recovery — November 7, 2026 UTC

This continues the [November 6 release handoff](2026-11-06-value-calendly-and-inspired-looks.md).
The owner opened RetainAI's MFA-protected Owner Console. The standard Google
reviewer account is now created and tested. Calendly's normal personal account
is signed in, and its separate developer portal has reached **Verification
email sent** after the owner-email registration was prepared. No Calendly app
credentials or live connection are claimed.

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

### Source chooser follow-up

The owner clarified that **Import Leads** should first ask which service holds
the contacts. [PR44](https://github.com/Retain-ap/retainai-prod/pull/44) adds that
popup with 12 choices: Apple Contacts, Google Contacts, WhatsApp contacts, Android
Contacts, Outlook/Microsoft People, Google Sheets, Excel, HubSpot, Salesforce,
Pipedrive, Zoho and other CSV/vCard files. Each opens its selected guide; Google
opens the existing connection card without authorizing automatically. File-based
sources are labeled as exports, and WhatsApp imports address-book contacts only.

The existing Headless UI dialog manages focus trapping, Escape, outside-click
dismissal and focus restoration. Each source's import method is exposed as its
accessible description. All 122 frontend tests passed before final CI; the build
and changed-file lint passed. Local production-build browser checks verified all
12 routes, focus wrapping/restoration and the 390px phone layout without overflow.
Claude independently reviewed the change and found no blocking issues. Its one
accessibility suggestion was incorporated. A pre-existing rebooking test fixture
now generates UTC dates to match its UTC workspace instead of depending on the
developer machine's date near midnight. No backend or provider-scope change.

## Calendly owner setup

The account menu's **Developer** link opens the developer docs. The
docs' **Log in** link leads to a separate developer portal at
`https://login.calendly.com/`. Codex prepared the owner email and name and held
the Register step for its API terms. A later read-only check found that the
page had advanced to **Verification email sent**; Codex did not submit that
step. At that checkpoint, email verification and developer-console access had
not been confirmed. No Calendly API key had been created or configured.

At the earlier checkpoint, Calendly's **Change email** action opened a Google
account chooser. The owner subsequently completed unlinking and the login-email
change. On November 7 Toronto time, Codex verified the newly opened account's
Login settings: **email/password login with `owner@retainai.ca`**. The old settings
tab still showed stale personal-email information, so use the newer account tab.
The separate developer portal still requires its own sign-in. The owner reported
email verification, but Codex has not reached the developer console, created app
credentials or connected RetainAI. Finish any further credential changes before
testing integrations, since Calendly documents that they revoke existing tokens
([Calendly API FAQ](https://developer.calendly.com/docs/getting-started/frequently-asked-questions)).

The prepared integration should use `scheduled_events:read` and callback
`https://api.retainai.ca/api/calendly/oauth/callback`. Register a Sandbox app,
securely configure its credentials, then test the real token exchange and booking
import before production setup. A documentation example showing `scope: default`
is not evidence that the live token response has that value: do not weaken
current scope enforcement based on the example alone.

The existing public **RetainAI Setup — 10 minutes** event was configured for
15 minutes. Codex changed its duration to 10 minutes, observed **Saved** and
verified the public booking page shows 10 minutes. Its existing URL, availability
and conferencing settings remain unchanged. No appointment or invitation was
created, and this booking-page correction does not prove an OAuth sync.

An authorized read-only Apple API check at 05:23 UTC on November 7 confirmed
Closet Muse build 3 is VALID and not expired; version 1.0 selects that build;
the three-item review draft is READY_FOR_REVIEW with a null submitted date.
Apple Business's browser session had expired, so banking/tax status was not
freshly verified. The earlier U.S. forms were Active and Canadian tax/account
requirements remain unresolved; do not invent registration details or resubmit
the active forms.

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

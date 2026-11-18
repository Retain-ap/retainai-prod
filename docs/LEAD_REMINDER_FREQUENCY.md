# Owner follow-up briefings

The scheduler checks every 15 minutes, but sends only from 09:00 until 17:00 in
the workspace's Automations profile timezone (then the account timezone, then
UTC). It uses the earliest eligible tick, normally shortly after 09:00, or waits
until configured quiet hours end within this daytime window. If quiet hours cover
the whole window, no briefing is sent that day. No marker permits a first
send only in that window, never immediately at deployment outside the window.

One briefing is allowed per local day when the overdue contact set or a contact's
last-contact timestamp changes. The same set is reminded at most once every
seven days. Increasing days-overdue, contact ordering, notes and display-name
edits do not create a new fingerprint. Unresolved contacts remain eligible past
the old three-day alert window, so a weekly reminder can still surface them.

`DATA_ROOT/lead_reminder_state.json` uses the existing cross-process file lock and
atomic, fsynced JSON replacement. The lock covers fresh owner/access checks,
contact reads, an attempted-delivery claim, the provider request and its receipt.
Only explicit provider acceptance adds `last_sent_at`; SendGrid acceptance does
not prove inbox delivery. A failed or uncertain attempt keeps its claim and uses
the same cooldown, because the existing boolean mailer cannot distinguish a lost
response from a definite rejection. This can defer an unchanged failed briefing
for seven days; it prevents a restart or lost response from causing repeated mail.
Unreadable state or a failed claim write prevents sending. The file is included
in the existing JSON backup sweep and workspace-deletion purge.

This changes only the owner email titled “Leads need your attention.” Customer
automation, birthday, appointment, trial, security and sign-in mail are separate.
The Settings notification toggles are still browser-local preferences; this
change does not make them server email-frequency controls.

No real emails or test notifications are sent by these tests. They use synthetic
contacts and mocked providers. Pure policy tests run without
Flask; the actual file-lock, two-process and app-integration tests run on Linux CI.

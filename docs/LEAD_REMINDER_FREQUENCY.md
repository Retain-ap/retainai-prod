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

Workspace owners can turn these emails off in Settings > Notifications >
Follow-up reminder emails. The preference is stored on the server in
`DATA_ROOT/email_preferences.json`, scoped to the signed-in owner, and defaults
to enabled when absent. Device notification choices remain separate. Managers
and members cannot change this owner email preference.

Preference saves and reminder sends use the same reminder lock. A save may wait
for an already-started email attempt; after disable is confirmed, subsequent
attempts observe it. Turning emails back on preserves all existing cooldowns
and pending delivery claims. No preference change sends an email or clears a
claim. Failed/uncertain UI saves require a readback before another change.

The preference file is included in the existing JSON backup sweep and locked
workspace purge. During recovery keep scheduling disabled until owner choices
and delivery state are reconciled: an older backup without this preference
file defaults to enabled. Do not invent or erase delivery claims to recover an
email preference.

No real emails or test notifications are sent by these tests. They use synthetic
contacts and mocked providers. Pure policy tests run without
Flask; the actual file-lock, two-process and app-integration tests run on Linux CI.

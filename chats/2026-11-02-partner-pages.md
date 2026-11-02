# Partner invitations — November 2, 2026

The owner requested partner options for both Closet Muse and RetainAI, including a
footer link and a stronger sales pitch. These are public invitations to enquire;
commission rates, referral attribution and payouts are not activated by the pages.

## Closet Muse

[PR #5](https://github.com/Retain-ap/closet-muse/pull/5) added `/partners` and the
homepage footer link. It is live at `4c4e4275ee42bd3f5f40a838c2c5bf96c9fb61bf`, Render
deploy `dep-dbkcgqivcj2c7380gqdg`. The page addresses creators, stylists and closet
organizers, with a prefilled email enquiry to the existing owner inbox.

Linux Node 24.19 release gate passed: 585 tests, 164 actual-server HTTP checks,
production audit, lint and build. Production smoke passed 17/17. Desktop, tablet
and phone layouts, footer navigation and FAQ controls were reviewed.

## RetainAI

This change adds `/partners`, route metadata, a sitemap entry and a homepage footer
link. Its pitch is for agencies, business coaches and advisors: introduce a useful
follow-up workflow to local service businesses. An explicitly illustrative salon
example shows customer context, an editable draft and the next action. Product and
pricing links support evaluation; the owner email is the enquiry destination.

There is no new form endpoint, third-party script, referral cookie, automatic
enrolment or payment change. No outreach has been sent. Commission offers remain
proposals for the owner to choose; the public page promises no earnings.

Before merging, the normal backend, frontend and secret-scan checks must pass.
After deployment, verify the footer link, direct `/partners` navigation and the
live frontend build, plus backend health. Private release evidence records the
actual results; this note does not pre-claim deployment or test success.

The previous Google/provider/device/backups and owner MFA items remain unchanged.

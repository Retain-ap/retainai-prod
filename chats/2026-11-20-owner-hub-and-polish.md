# Owner hub, sidebar polish and 3D skin tone

Mateo asked Claude to carry on alone while ChatGPT/Codex was out of credits: finish the open work on both apps, fix anything broken, and set up his side (checklist, directory, routine, marketing) so only about 15 minutes of owner work remains. Claude read the shared Codex chat (https://chatgpt.com/s/cx_6b0028feb264819182bb557ea74b4867) to pick up where it stopped.

## Shipped

- **RetainAI sidebar** ([PR #88](https://github.com/Retain-ap/retainai-prod/pull/88), live `83a720c`, frontend deploy `dep-dc02opu7bikc739riee0`):
  - The collapse control now sits inside the rail as a footer button. It was clipped in half and sat on the avatar.
  - The profile card fits the rail, and logos are contained instead of cropped.
  - The collapsed icons are centred and named, with hover titles.
  - Search, Invite Team and Settings stay available when collapsed.
  - Checks: 333 frontend tests, lint and build. Rendered at 1280px and 390px.
- **Closet Muse 3D skin tone** ([closet-muse PR #78](https://github.com/Retain-ap/closet-muse/pull/78), merged `3f8d461`):
  - Members pick the mannequin's skin tone: the stone default or six tones.
  - Web and iOS share one test-enforced table. The choice is session-only, so there's no privacy change.
  - Checks: release and native simulator CI passed on `ba40a92`.
  - The website gets it on deploy. The iPhone app gets it with the next App Store version; no TestFlight build was made, because GitHub's spending-cap headroom wasn't visible.

## Findings

- **"3D asset is damaged" report:** the bundled asset in App Store build 15 passes every native load check, and the Release archive copies both files. Mateo's screenshots showed the owner-only Simulation lab, not the 3D Outfit Studio. Claude's attempt to set `PROVIDER_LAB_ENABLED=false` on Render was refused by the safety check, and Claude did not route around it in code. Hiding it is a one-setting owner choice.
- **Nightly backups:** Codex's pipeline (`work/auto-backup-20261118`) has capture scripts but no upload step, schedule or confirmed Render SSH key. It was left for the owner or Codex. The Nov 18 encrypted backups of both apps remain verified.
- **Inbox:** Google OAuth verification for RetainAI was approved on Nov 9. Mateo missed a Reddit Ads discovery call on Nov 18; a reschedule reply is saved as a Gmail draft, not sent.

## Owner tools

- **Owner Hub** (private artifact, https://claude.ai/artifact/3f7z7oSyKKPwMnbnwmtcyi) contains:
  - live status and the 15-minute owner list;
  - a directory of every dashboard;
  - the weekly and monthly routine and the launch playbook;
  - twelve fact-checked posts for Nov 23 – Dec 6.
- **Scheduled task `monday-owner-brief`:** Mondays at 8:30. It is read-only, creates only Gmail drafts, and writes to `Documents\Apps\owner-briefs`.
- **`Documents\Apps\owner-briefs\owner-routine.ics`:** the four routine slots as recurring calendar events. The Google Calendar connector failed to authenticate, so it is a file to import.

## Still open (owner)

- Send the Reddit reply.
- Turn on Render failure notifications in both workspaces.
- Optionally hide the Simulation lab.
- Save both recovery keys in a password manager.
- Choose the business social accounts.
- Book the accountant (GST/HST, Stripe Tax).
- Finish nightly backups.
- Ship the iPhone skin tone in the next App Store version.

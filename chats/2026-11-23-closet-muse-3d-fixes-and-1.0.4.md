# Closet Muse 3D fixes, motion and 1.0.4 — 23 to 26 November 2026

Closet Muse only; no RetainAI code changed. The owner asked for:
- the 1.0.3 App Review submission;
- the 3D Studio seam glitch fixed;
- shirts showing through jackets, and skin specks through skirts, fixed;
- smoother 3D motion and a link from the Studio to Photo try-on;
- 1.0.4 shipped once Apple approved 1.0.3.

## What changed (Retain-ap/closet-muse)

- **#79, #80: version 1.0.3 and an owner-run App Review workflow.**
  - `closet-muse-app-review.yml` runs in check, prepare or submit mode, and is main-only and protected.
  - 1.0.3 (build 16) was submitted on 23 November. Apple approved it, and it was READY_FOR_SALE by 26 November.
- **#81: bottom waistbands no longer poke through tops.**
  - `layerUnder` (web) and `AvatarLayering` (iOS) remove only the poking geometry, above the top's hem and at or outside its surface.
  - Live on the website as `3df5de5`.
- **#82: shirts no longer show through jackets, and skin no longer shows through skirts.**
  - `garmentShell`/`shellUnder` (web) and `AvatarShell` (iOS) do this with closest-point shell queries.
  - Shirt points poking through jackets, over 24 scenes: 615, previously 13,566.
  - Skin specks: 0, previously 4.
  - Live as `d5faec8`.
- **#83: Studio motion and a Try on your photo hand-over.**
  - Motion: camera glides, an opening turn, a swap glow, an optional turntable, and fades. All of it respects reduced motion.
  - Each chosen piece that has a closet photo opens Photo try-on with that piece chosen. The member still adds their own photo and consents.
  - Live as `46ffb51`. The first live smoke check saw one 502 during the switchover; the retry passed 17/17.
- **#84: version 1.0.4.**
- **#85: fixed a secret-scan false positive.** The release check flagged `keyId: env.ASC_KEY_ID` in the App Review script. It was an environment-variable name, not a key. The line was rewritten, and one exact history fingerprint was added to `.gitleaksignore`.

## GitHub Actions outage

- From 23 November, 11:13 UTC, until 26 November, before 06:26 UTC, every Actions job on the account failed before a runner started. That included this repo's uptime monitor.
- Apps were up throughout. Uptime "failure" emails in that window were false alarms.
- The owner fixed billing, and jobs ran again from 26 November, 06:26 UTC.

## 1.0.4 release

- The release check passed on `325a5a3` (run 45769117935).
- The Mac native check was started on the same commit (approved paid run). An earlier run on `158f409` compiled the new Swift on iPhone and iPad. It was cancelled after the compile to save minutes, because #85 changed the commit.
- Next: upload build 17 with Friends push enabled, then submit 1.0.4 through the App Review workflow.

## Still open

- About 600 shirt points still poke through jackets, in armpit and collar creases. There are also hairline seams inside the jacket templates.
- Gmail shows two items for the owner to review:
  - a pending Cloudflare zone for retainai.ca (4 November; nameservers never switched). Copy every DNS record before switching, or delete the zone;
  - a third-party OAuth app, "Developer Portal Production", authorised on the Retain-ap GitHub account (10 November).

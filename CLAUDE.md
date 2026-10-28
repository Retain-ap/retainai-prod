# RetainAI

CRM for small businesses. Owner account: `owner@retainai.ca` (GitHub `Retain-ap`).

## How it ships

- `deploy` is the production branch. Render auto-deploys it to two services:
  - Backend `retainai-app` (Flask + gunicorn, `backend/`) at `https://api.retainai.ca`
  - Frontend `retainai-prod-1-frontend` (Create React App, `frontend/`) at `https://www.retainai.ca`
- Work on a branch, open a pull request into `deploy`, merge when CI is green.
  Add `[skip render]` to commit messages that change only docs or workflows.
- Other branches (`main`, `signup-fix`, `test-deployment`, `deploy'`, `codex/*`, `fix/*`)
  are old. Do not deploy them. Check Render before deleting any of them.

## Checks before merging

`.github/workflows/ci.yml` runs on every pull request; `PRODUCTION_CHECKLIST.md`
lists the same commands for running locally. Backend tests need Python 3.11 or 3.12
(not 3.13) with `backend/requirements.txt`.

`backend/app.py` mixes CRLF and LF line endings. Edit it without normalizing them,
or the diff becomes the whole file.

## Live status

- `.github/workflows/uptime.yml` checks RetainAI and Closet Muse every 15 minutes;
  a failure emails the owner.
- Open, owner-only steps:
  - Render: add or verify `retainai.ca` (no www) under the frontend static site's
    Custom Domains. Until then it fails TLS and the uptime check warns.
  - SendGrid: add `{{unsubscribe_url}}` to the birthday and AI follow-up templates.
- Known gap: signup and login rate limits are per-process memory and read the
  first `X-Forwarded-For` value. Fix after confirming the Render worker count and
  how Render forwards the client IP.

## Related app

Closet Muse (`Retain-ap/closet-muse`, `https://closetmuse.ca`) is a separate app
on its own Render service. See its `PROJECT_HANDOFF.md`. Keep the two apps' code,
accounts and credentials separate.

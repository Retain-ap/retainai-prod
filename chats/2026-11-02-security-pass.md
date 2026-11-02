# Security pass on both apps — November 2, 2026

Claude Code desktop session (local PC), working alongside a Codex session. Split agreed with
Codex: Claude owns dependency, security and auth fixes plus the affiliate proposal. Codex owns
frontend flows and UI bugs in its own checkout.

## Branches and files

- RetainAI [PR #16](https://github.com/Retain-ap/retainai-prod/pull/16), branch
  `security/dependency-upgrades-20261102`, CI green, **not merged** (Claude's merge was blocked by
  a permission check; the owner merges). Files: `backend/requirements.txt`, `backend/app.py`
  (3 lines in the `__main__` block, original line endings kept).
- Closet Muse `b70fcdb` on `main`, live: `app/api/readiness/route.ts`, `tests/readiness.test.mjs`.
- Nothing in `frontend/` or other Closet Muse files was touched.

## Fixed

- RetainAI backend packages with 22 known advisories: Flask 3.1.3, requests 2.33.0,
  cryptography 50.0.0, python-dotenv 1.2.2, waitress 3.0.2. pywebpush 1.14 → 2.5.0 because
  cryptography 50 rejects its curve-class call (the app doesn't send web push itself).
  pip-audit is clean; 74/74 backend tests pass; VAPID signing, push encryption and Fernet checked.
- RetainAI `python app.py` no longer starts the Werkzeug debugger on 0.0.0.0 (needs
  `FLASK_DEBUG=1`, binds 127.0.0.1). Production runs gunicorn and is unaffected.
- Closet Muse public `/api/readiness` no longer returns the server's data directory paths.
  The new test fails on the old code. Smoke 17/17 on `b70fcdb`.

## Checked, no issue found

- Unauthenticated sweep of every route: RetainAI 145 route/method pairs, Closet Muse 99. Only
  intentionally public endpoints answer, and none crash.
- Cross-account sweep (RetainAI): all 22 route/methods that take an account email return 403 for
  another business and work for your own. Every owner-console route returns 403 to a normal user.
- CSRF: writes need an allowlisted Origin, and cross-site requests with no Origin are blocked.
  Production rejects `http://localhost:3000` and `null`.
- `safe_same_origin_redirect` held against 13 open-redirect payloads.
- Closet Muse's own HTTP security suite: 77 checks pass. Production npm audit clean on both apps.
- Live: HTTPS redirects, TLS 1.0/1.1 refused, API and Closet Muse headers complete, no broken
  links, landing pages clean on phone and desktop with no console errors.

## Open (owner)

- A credential was found in this repository's git history. The owner has the details and the
  revocation steps. This repository is public; making it private is recommended.
- www.retainai.ca (static site) sends no HSTS, X-Frame-Options or CSP `frame-ancestors`. Add the
  headers in Render → static site → Headers (the connector can't).
- Merge PR #16.

## Low priority (not changed)

- `/api/test` and `/test` return `{"ok":true}` publicly (no data).
- `POST /api/wa-auto/leads/<email>/<lead_id>/appointments` accepts a lead ID that doesn't exist
  (own workspace only).
- Frontend: two moderate `react-router` advisories (Codex's area). Closet Muse: dev-only
  `minimatch` advisory in ESLint.

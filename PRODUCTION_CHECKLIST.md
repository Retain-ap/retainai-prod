# RetainAI production checklist

The public readiness endpoint is:

`https://api.retainai.ca/api/readiness`

It returns only yes/no configuration checks and never returns secret values.

## Required for a healthy result

- `SESSION_SECRET`: stable high-entropy random value shared by every backend
  worker and used only for session signing.
- `DATA_ENCRYPTION_KEY`: a different stable high-entropy random value used for
  TOTP and workspace integration credentials. It must not equal
  `SESSION_SECRET`, `APP_SECRET`, or `PLATFORM_OWNER_PASSWORD`.
- `ACCOUNT_HISTORY_SECRET`: stable random value used to prevent repeat free trials
  without retaining deleted email addresses. Never rotate it unless the
  introductory-trial history is intentionally being reset.
- `STRIPE_SECRET_KEY`: Stripe live secret key.
- `STRIPE_PRICE_ID`: live subscription price.
- `STRIPE_WEBHOOK_SECRET`: signing secret for the production webhook.
- `SENDGRID_API_KEY`: transactional email delivery, including password resets.
- Persistent storage: `USE_SQLITE=true`, with `SQLITE_PATH` on Render's persistent disk.
- `RUN_SCHEDULER=1`: enables the verified daily backup job and scheduled
  automations. Set it on exactly one backend service/instance; leave it unset
  (the safe default) on every other web process or preview service. RetainAI
  also takes an OS process lock at `SCHEDULER_LOCK_FILE`, which defaults to
  `<DATA_ROOT>/.retainai-scheduler.lock`, to prevent duplicate jobs among
  workers on the same service filesystem.

For the first release that separates encryption from session signing, set
`PREVIOUS_DATA_ENCRYPTION_KEY` temporarily to the exact old key material that
encrypted existing TOTP/WhatsApp values (the prior `SESSION_SECRET`). New values
are always encrypted with `DATA_ENCRYPTION_KEY`. Remove the previous-key setting
after affected users re-enrol 2FA and reconnect workspace WhatsApp credentials.

## Strongly recommended

- `REACT_APP_STRIPE_PUBLISHABLE_KEY`: Stripe live publishable key in the frontend service.
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`: the production Google OAuth
  web client. The backend must also set:
  - `GOOGLE_REDIRECT_URI=https://api.retainai.ca/api/google/oauth-callback`
  - `GOOGLE_PEOPLE_REDIRECT_URI=https://api.retainai.ca/api/google/people/oauth-callback`
- `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, and `APP_SECRET`: Meta messaging.
- An external uptime monitor checking `/api/readiness` every five minutes.
- Download verified snapshots from Owner Console → Backups and copy them to
  storage outside Render. On-platform backups do not protect against losing the
  entire Render disk.
- Configure the external monitor to alert `owner@retainai.ca` when readiness is
  unavailable or returns a degraded result.

## Stripe webhook events

Subscribe the production webhook to:

- `checkout.session.completed`
- `invoice.paid`
- `invoice.payment_succeeded`
- `invoice.payment_failed`
- `invoice.payment_action_required`
- `customer.subscription.updated`
- `customer.subscription.deleted`

## Google OAuth verification

Use the same Google Cloud project as the production `GOOGLE_CLIENT_ID` and
configure one **Web application** OAuth client.

1. Under **Google Auth Platform → Branding**, use:
   - App name: `RetainAI`
   - Support and developer email: `owner@retainai.ca`
   - Homepage: `https://www.retainai.ca/`
   - Privacy policy: `https://www.retainai.ca/privacy-policy`
   - Terms: `https://www.retainai.ca/terms-of-service`
   - Authorized domain: `retainai.ca`
2. Under **Audience**, select External and publish the app to production.
3. Under **Clients**, configure these JavaScript origins:
   - `https://www.retainai.ca`
   - `https://retainai.ca`
4. Configure these exact redirect URIs (including the path and no trailing
   slash):
   - `https://api.retainai.ca/api/google/oauth-callback`
   - `https://api.retainai.ca/api/google/people/oauth-callback`
5. Under **Data Access**, request only the scopes RetainAI uses:
   - `openid`
   - `email`
   - `profile`
   - `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
   - `https://www.googleapis.com/auth/calendar.events.readonly`
   - `https://www.googleapis.com/auth/contacts.readonly`
6. Verify `retainai.ca` in Google Search Console using an account that is an
   owner or editor of the Google Cloud project.
7. Submit the sensitive-scope verification. The demonstration video should
   show the English consent screen, connecting Google Calendar, displaying
   calendar events in RetainAI, importing Google contacts, and disconnecting
   the integration.

If the requested scopes or OAuth client changes, existing users may need to
disconnect and reconnect Google so the new grant is recorded.

## Release verification

Run the backend regression checks in an environment with `backend/requirements.txt`
installed:

`python -m unittest discover -s backend -p "test_*.py"`

Run the frontend production build:

`npm --prefix frontend run build`

## Monthly recovery drill

1. Create a backup from Owner Console → Backups.
2. Download it and verify the SHA-256 value shown in the Owner Console.
3. Extract it in an isolated folder.
4. Confirm `manifest.json` lists the database and workspace JSON files.
5. Restore the snapshot only into a non-production test service.

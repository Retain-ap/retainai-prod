# RetainAI production checklist

The public readiness endpoint is:

`https://api.retainai.ca/api/readiness`

It returns only yes/no configuration checks and never returns secret values.

## Required for a healthy result

- `SESSION_SECRET`: stable random value shared by every backend worker.
- `ACCOUNT_HISTORY_SECRET`: stable random value used to prevent repeat free trials
  without retaining deleted email addresses. Never rotate it unless the
  introductory-trial history is intentionally being reset.
- `STRIPE_SECRET_KEY`: Stripe live secret key.
- `STRIPE_PRICE_ID`: live subscription price.
- `STRIPE_WEBHOOK_SECRET`: signing secret for the production webhook.
- `SENDGRID_API_KEY`: transactional email delivery, including password resets.
- Persistent storage: `USE_SQLITE=true`, with `SQLITE_PATH` on Render's persistent disk.
- `RUN_SCHEDULER=1`: enables the verified daily backup job and scheduled automations.

## Strongly recommended

- `REACT_APP_STRIPE_PUBLISHABLE_KEY`: Stripe live publishable key in the frontend service.
- `GOOGLE_CLIENT_ID`: production Google sign-in client.
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

## Release verification

Run the backend security checks:

`python backend/test_security.py`

Run the frontend production build:

`npm --prefix frontend run build`

## Monthly recovery drill

1. Create a backup from Owner Console → Backups.
2. Download it and verify the SHA-256 value shown in the Owner Console.
3. Extract it in an isolated folder.
4. Confirm `manifest.json` lists the database and workspace JSON files.
5. Restore the snapshot only into a non-production test service.

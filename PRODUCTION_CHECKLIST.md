# RetainAI production checklist

The public readiness endpoint is:

`https://api.retainai.ca/api/readiness`

It returns only yes/no configuration checks and never returns secret values.

## Required for a healthy result

- `SESSION_SECRET`: stable random value shared by every backend worker.
- `STRIPE_SECRET_KEY`: Stripe live secret key.
- `STRIPE_PRICE_ID`: live subscription price.
- `STRIPE_WEBHOOK_SECRET`: signing secret for the production webhook.
- `SENDGRID_API_KEY`: transactional email delivery, including password resets.
- Persistent storage: `USE_SQLITE=true`, with `SQLITE_PATH` on Render's persistent disk.

## Strongly recommended

- `REACT_APP_STRIPE_PUBLISHABLE_KEY`: Stripe live publishable key in the frontend service.
- `GOOGLE_CLIENT_ID`: production Google sign-in client.
- `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, and `APP_SECRET`: Meta messaging.
- An external uptime monitor checking `/api/readiness` every five minutes.
- A daily copy of the persistent SQLite file to storage outside Render.

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

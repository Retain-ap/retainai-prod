# Booking platform integration: assessment

Status, November 6, 2026: after no reply on the platform question, Codex told
the owner RetainAI would assume **Square first**. A read-only Square Bookings
integration is **built but not live**: no Square application is registered and
no credentials are set, so the app says Square is "not available yet". Nothing
was purchased.

## What RetainAI needs from a booking platform

1. **Completed visits:** the date of each completed visit, for personalized
   rebooking intervals.
2. **Bookings:** when a booking was made, for the Value Receipt's "follow-up,
   then booking, then payment" link.
3. **Cancellations and no-shows:** so they are not counted as visits.
4. **Matching:** a customer email or phone, to match the booking to a RetainAI
   contact.

Read-only access covers all of this. RetainAI would not need to create or change
bookings.

## Square Bookings API (suggested by the owner)

Source: [Square Bookings API overview](https://developer.squareup.com/docs/bookings-api/what-it-is)
(read November 6, 2026).

**What it offers:**
- Retrieving bookings, with services, team members and location; searching
  availability; creating, updating and cancelling bookings.
- Seller-level **reads work without a paid Square Appointments plan**. The
  documented free-plan scopes include `APPOINTMENTS_READ` and
  `APPOINTMENTS_ALL_READ`.
- Seller-level **writes need Appointments Plus or Premium**. On a free plan they
  fail with 403 "Merchant subscription does not support write operations".
  RetainAI would not use writes.
- `booking.created` and `booking.updated` webhooks. A seller-level app receives
  every change to a booking.

**Fit:** good. A read-only seller-level integration gives booking times and
status changes, covering items 1 to 3. Customer contact details live in
Square's Customers API, which needs its own read permission; confirm the exact
scope when building.

**What it would take** (none of it done):
- A Square developer application, sandbox and production credentials, and an
  OAuth redirect URI on `api.retainai.ca`.
- Encrypted token storage per workspace, using the existing `secret_store`.
- A webhook endpoint with signature verification.
- A sandbox test seller.

## Calendly

Source: [Calendly developer docs](https://developer.calendly.com/llms.txt) and the
[webhook guide](https://developer.calendly.com/docs/api-guides/receive-data-from-scheduled-events-in-real-time-with-webhook-subscriptions.md).

**What it offers:**
- Authentication by personal access token or an OAuth app.
- A "List Events" endpoint for scheduled events.
- Webhooks `invitee.created` and `invitee.canceled`, with organization scope for
  owners and admins, or user scope.

**Not verified:** the docs pages read for this assessment do not say which
Calendly plan webhooks need. Check this before choosing.

**Fit:** partial. Calendly records scheduling and cancellation, not whether a
visit was completed. Completed visits would still have to be marked in RetainAI,
so rebooking intervals gain less than with Square.

## General mode (works today, no provider)

- Appointments created in RetainAI, or kept on a contact, already feed rebooking
  and the Value Receipt.
- Contact files import through the existing CSV/vCard importer.
- Google Calendar sync remains subject to Google's verification status; see
  `chats/`.

## Square v1 as built (`backend/square_bookings.py`, `backend/app_square.py`)

- **Who:** the workspace owner only. Team members get 403 and don't see the card.
- **Scopes:** `APPOINTMENTS_READ APPOINTMENTS_ALL_READ CUSTOMERS_READ` (seller-level reads,
  available on Square's free plan). No write scopes.
- **OAuth:**
  - Square's code flow for a confidential server, using the app secret. Square documents
    PKCE for public clients: there it replaces the secret and makes refresh tokens single-use
    and 90-day expiring. So CSRF protection comes from RetainAI's single-use, 10-minute `state`.
  - The callback must arrive in the same signed-in owner session that started it.
  - `session=false` in production.
  - A Square seller can be linked to only one workspace.
- **Tokens:**
  - Encrypted with `DATA_ENCRYPTION_KEY`, never returned or exported.
  - Renewed when older than 7 days, as Square recommends, and on a 401 (retried once). If
    Square refuses the renewal, the connection is marked "reconnect needed".
  - Disconnecting, or deleting the workspace, revokes at Square with
    `Authorization: Client <secret>` and deletes the stored tokens.
- **Sync (manual "Sync now"; no webhooks):**
  - Reads 31-day windows from 180 days back to 60 days ahead, page by page, up to 2,000
    bookings and 500 customer lookups. A capped read is reported as partial.
  - Imports only bookings whose Square customer matches exactly one existing RetainAI contact
    by email, otherwise by phone. **No contact is created**, no consent recorded, nothing sent,
    no automation started.
  - Idempotent on the Square booking ID: a re-sync updates status or time, and never
    duplicates or deletes.
- **Status mapping:**
  - `CANCELLED_BY_CUSTOMER`, `CANCELLED_BY_SELLER` and `DECLINED` become cancelled.
  - `NO_SHOW` becomes no-show.
  - `ACCEPTED` becomes scheduled, or **completed once its start time has passed**. Square has
    no "completed" status, so this is an inference, and it is documented.
  - `PENDING` becomes scheduled if in the future; a past pending booking is skipped.
- **Time:** stored in the workspace's timezone. Square location timezones are not read,
  because that would need another scope.

### What the owner must do before it can be used (not done)

1. Create a Square Developer application (free). Register
   `https://api.retainai.ca/api/square/oauth/callback` as its OAuth redirect URL, and set the
   application's API version in the Developer Console. RetainAI sends no `Square-Version`
   header, so Square applies that setting.
2. Test in Square's Sandbox first. Set on the backend service: `SQUARE_ENVIRONMENT=sandbox`,
   `SQUARE_APPLICATION_ID` and `SQUARE_APPLICATION_SECRET` (the secret as a secret value), and
   `FRONTEND_URL=https://www.retainai.ca`. Use a sandbox seller with test bookings.
3. Only after a real sandbox OAuth round trip and sync pass, switch to production credentials.
   Confirm whether Square requires App Marketplace review for connecting other sellers'
   accounts. Until all of this is done, do not describe Square as connected.

## Recommendation

Square first, as Codex told the owner. Register the Square application and
complete a sandbox OAuth round trip and sync before offering it to customers.
Do not describe Square, or any booking platform, as connected until a real
production OAuth round trip and sync have passed.

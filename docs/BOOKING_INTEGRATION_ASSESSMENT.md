# Booking platform integration: assessment

Status, November 7, 2026: the owner chose **service businesses that use
Calendly** as the first target. Calendly is now the **primary** booking
connection; the read-only Square integration stays in the product as an
**optional** second connection. Both are **built but not live**: no Calendly or
Square OAuth app is registered and no credentials are set, so each card in
Import says it is "not available yet". Nothing was purchased, and no OAuth round
trip with a real Calendly or Square account has been completed.

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

## Calendly v1 as built (`backend/calendly_bookings.py`, `backend/app_calendly.py`)

Sources (official Calendly developer docs, read November 6-7, 2026):
[Creating an OAuth app](https://developer.calendly.com/docs/authentication/creating-an-oauth-app),
[Scopes](https://developer.calendly.com/docs/authentication/scopes),
[Get access token](https://developer.calendly.com/api-docs/calendly-o-auth/o-auth/post-oauth-refresh-token.md),
and the API reference for scheduled events and invitees.

- **Who:** the workspace owner only. Team members get 403 and don't see the card.
- **Scope:** `scheduled_events:read` only, requested explicitly with `scope=`
  on the authorize URL. It covers listing the owner's scheduled events and each
  event's invitees. `users:read` is **not** requested: the token response's
  `owner` field already names the connecting Calendly user, and its
  `organization` field the organization. No webhook scope (`webhooks:write`)
  is requested, because sync is manual. A token whose `scope` lacks
  `scheduled_events:read` is revoked and nothing is stored.
- **OAuth:**
  - Authorization code flow with **PKCE S256**, which Calendly requires for every
    OAuth app. The verifier stays in the owner's signed session; only the
    challenge goes to Calendly.
  - The token request is a server request: HTTP Basic client authentication
    plus `client_id`, `code_verifier` and the same `redirect_uri` in the body.
  - RetainAI's single-use, 10-minute `state` is bound to the workspace and the
    owner who started it. The callback must arrive in the same signed-in owner
    browser session (the verifier is only there); another owner, or the same
    owner in another browser, gets "session mismatch" and no code is exchanged.
  - One Calendly user can be linked to only one RetainAI workspace.
- **Tokens:**
  - Encrypted with `DATA_ENCRYPTION_KEY`, never returned to the browser or
    included in the account export.
  - Access tokens last 2 hours; RetainAI renews 5 minutes before expiry and once
    after a 401. Calendly refresh tokens **rotate**: each works once. Renewal
    therefore runs under the connection file's lock, re-reads the stored token
    inside it, makes one attempt (no retry that could spend a token twice) and
    stores the new pair before anything else. A refused refresh marks the
    connection "reconnect needed".
  - Disconnecting, or deleting the workspace, revokes both tokens at
    `auth.calendly.com/oauth/revoke` and deletes them. If Calendly can't confirm
    the revoke, the tokens are still deleted and the owner is told to remove
    RetainAI in Calendly's integrations settings too.
- **Sync (manual "Sync now"; no webhooks), bounded and resumable:**
  - A pass reads the owner's own events (`user=<owner uri>`) in a fixed window,
    from 180 days back to 60 days ahead, sorted by start time, 100 per page.
    The caps per pass are exactly 1,000 events and 2,000 invitees, with at most
    5 invitee pages per event. A repeated or looping page token ends the pass.
    Hitting a cap is reported.
  - **Each Sync is one bounded step:** at most 40 requests (under the free
    plan's 50 per minute). It starts no new request after about 20 seconds.
    That is not a hard deadline: the request already in flight can add up to
    its 10-second timeout, so a step ends within roughly 30 seconds. That is
    well inside the backend's gunicorn `--timeout 120` (start command checked
    November 7, 2026). On a 429 it **does not sleep**: it stops, saves its
    progress and says how many seconds Calendly asked to wait
    (`X-RateLimit-Reset`). Network and server errors get one 1-second retry. A
    persistent error saves nothing from that step.
  - **Progress lives in a server-side cursor** stored with the connection:
    window, page, position and counts. It is bound to the connection
    generation and the Calendly user, and expires after 24 hours. It holds no
    OAuth credentials, and it is never shown in the UI or included in the
    account export. The cursor advances past an event only once all its
    invitees are read. The next Sync continues from it. When the window has
    been read completely, the cursor is cleared and the following Sync starts a
    fresh pass, so later cancellations and reschedules are picked up rather
    than the earliest events being re-read forever.
  - **Writes are safe across disconnects:** every connect gets a new
    `connection_id`. A step's results are written in one commit that first
    re-checks, under the connection lock and then the appointments lock, that
    the same connection and Calendly user are still in place and the workspace
    still exists. A sync that outlives a disconnect, reconnect or account
    deletion writes nothing (409 or 401).
  - **Concurrent syncs of the same connection:** a `sync_revision` counter is
    read before any Calendly request and checked at commit (compare-and-swap
    under the connection lock), then incremented. If another sync committed in
    between, the slower one saves nothing and returns 409. It therefore can't
    undo a newer cancellation or move the cursor back.
  - Imports only invitees whose email matches **exactly one** existing RetainAI
    contact. **No contact is created**, no consent is recorded or inferred,
    nothing is sent and no automation is started. Booking-question answers,
    tracking data and payment details are not stored.
  - Idempotent on `calendly:<event uuid>:<invitee uuid>`: a re-sync updates
    status or time and never duplicates or deletes. Appointments from other
    sources are untouched.
- **Status mapping:**
  - Only documented statuses count: event `active`/`canceled` and invitee
    `active`/`canceled`. Any other status, or a missing or invalid start time,
    means the row is skipped and reported. Nothing unknown is treated as a visit.
  - Event or invitee `canceled` becomes cancelled; the canceler type is kept.
  - A reschedule in Calendly cancels the old invitee (`rescheduled: true`, with
    `new_invitee`) and creates a new one: the old booking is kept as cancelled
    and marked rescheduled; the new one imports as its own booking.
  - Invitee `no_show` becomes no-show.
  - Active becomes scheduled, or **completed once its start time has passed**.
    Calendly has no "completed" status, so this is an inference, and it is
    documented in the app.
- **Time:** the UTC start from Calendly is kept (`calendly_start_utc`), the
  appointment time is shown in the workspace's timezone, and the invitee's own
  timezone is kept as `invitee_timezone`.

### What the owner must do before Calendly can be used (not done)

1. Sign in to the Calendly developer portal. The older documented
   `https://calendly.com/app/developer` route stalled in this owner's session.
   On November 7 UTC, the account menu's **Developer** link opened the docs;
   **Log in** there opened
   `https://developer.calendly.com/login?origin=https://developer.calendly.com/console/apps`,
   which redirected to the separate developer sign-in at `https://login.calendly.com/`.
   Codex prepared the owner-email registration and held the API terms step. A
   later read-only check found **Verification email sent**; Codex did not submit
   that step. Email verification and developer-console access are still pending.
   After developer sign-in, open **OAuth apps**
   and create a **Sandbox** app first:
   - If asked for the app type, choose a web (server-side) app, not native.
   - Redirect URI: exactly one, `https://api.retainai.ca/api/calendly/oauth/callback`
     (Sandbox also allows `http://localhost` for local testing).
   - Scope: `scheduled_events:read` only.
2. Set on the backend service (Render `retainai-app`): `CALENDLY_CLIENT_ID`,
   `CALENDLY_CLIENT_SECRET` (as a secret), `CALENDLY_REDIRECT_URI` (the URI above;
   must be https) and `FRONTEND_URL=https://www.retainai.ca`.
   `DATA_ENCRYPTION_KEY` must already be set. Until all are set, the card says
   Calendly is not available.
3. Complete a real Sandbox round trip: connect, sync a test event, cancel and
   reschedule it in Calendly, sync again, disconnect. Only then create the
   **Production** app (https redirect only) and switch the credentials.
4. Calendly's docs read for this work describe no review or approval step for
   Production apps. Confirm that with Calendly before offering the connection
   to customers. Until steps 1-3 pass, do not describe Calendly as connected.

Complete any planned login-email, password or login-method change before the
connection test: [Calendly's FAQ](https://developer.calendly.com/docs/getting-started/frequently-asked-questions)
says each revokes OAuth and personal access tokens. The personal Google-linked
account has not been changed. During the real Sandbox test, inspect the returned
scope without recording tokens. One documentation example uses `scope: default`;
that is not proof of the actual response and does not justify weakening the
existing `scheduled_events:read` enforcement.

## First setup path: service businesses on Calendly

Settings > Business setup defaults to **General service business**. Its setup
card in the Retention Center walks through: connect Calendly (or record visits
in RetainAI), import existing contacts, sync bookings, review consent per
contact, and review the rebooking playbook before turning anything on.
**Salon / barber** stays an optional preset with its own playbooks; Square stays
an optional connection for businesses that book through Square.

## General mode (works today, no provider)

- Appointments created in RetainAI, or kept on a contact, already feed rebooking
  and the Value Receipt.
- Contact files import through the existing CSV/vCard importer.
- Google Calendar sync remains subject to Google's verification status; see
  `chats/`.

## Square Bookings API (optional)

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

## Square v1 as built (`backend/square_bookings.py`, `backend/app_square.py`; optional, unconfigured)

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

Calendly first, as the owner chose. Register the Calendly Sandbox app and
complete a real OAuth round trip and sync before offering it to customers. Keep
Square optional and unconfigured until a Square customer asks for it. Do not
describe Calendly, Square or any booking platform as connected until a real
production OAuth round trip and sync have passed.

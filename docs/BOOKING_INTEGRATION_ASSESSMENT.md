# Booking platform integration: assessment

Status, November 6, 2026: **no booking platform is connected or chosen.** The
owner has not picked one. RetainAI's own calendar and appointments keep working
in general mode and with the optional salon/barber preset. Nothing here was
purchased, and no OAuth app was registered.

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

## Recommendation

Wait for the owner's choice. If it is Square, build a **read-only, seller-level**
integration first, test it with a Square sandbox seller, and only then offer it
to customers. Do not describe any booking platform as connected until a real
OAuth round trip and webhook delivery have passed in production.

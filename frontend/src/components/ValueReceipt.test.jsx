import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import ValueReceipt, { formatMinor } from "./ValueReceipt";

const receipt = {
  totals: { cad: { linked_verified_minor: 12000, linked_owner_recorded_minor: 8000, paid_verified_minor: 20000, paid_owner_recorded_minor: 8000, linked_count: 2, payment_count: 3 } },
  items: [
    { id: "stripe:in_1", source: "stripe", verification: "provider_verified", currency: "cad", amount_minor: 12000, refunded_minor: 0, net_minor: 12000,
      paid_at: "2026-10-12T15:00:00Z", invoice_number: "N-1", customer_name: "Ana", linked: true, reason: "",
      followup: { channel: "email", sent_at: "2026-10-05T09:00:00Z", evidence: "follow-up log" },
      confirmation: { kind: "invoice", at: "2026-10-10T10:00:00Z", label: "Invoice N-1" } },
    { id: "manual:k1", source: "manual", verification: "owner_recorded", currency: "cad", amount_minor: 8000, refunded_minor: 0, net_minor: 8000,
      paid_at: "2026-10-20T18:00:00Z", customer_name: "Ben", reference: "Cash", linked: true, reason: "",
      followup: { channel: "whatsapp", sent_at: "2026-10-14T12:00:00Z", evidence: "WhatsApp message record" },
      confirmation: { kind: "booking", at: "2026-10-15T12:00:00Z", label: "Booking (completed)" } },
    { id: "stripe:in_2", source: "stripe", verification: "provider_verified", currency: "cad", amount_minor: 8000, refunded_minor: 0, net_minor: 8000,
      paid_at: "2026-10-22T10:00:00Z", customer_name: "Cleo", linked: false, reason: "No booking or invoice before the payment", followup: null, confirmation: null },
    { id: "stripe:in_3", source: "stripe", verification: "unconfirmed", settlement: "no_charge", settlement_text: "Stripe shows paid with no charge (credit balance, minimum amount or other settlement)",
      currency: "cad", amount_minor: 5000, refunded_minor: 0, net_minor: 5000, paid_at: "2026-10-23T10:00:00Z", customer_name: "Dee", linked: false,
      reason: "Payment not confirmed: Stripe shows paid with no charge", followup: null, confirmation: null },
  ],
  rules: { linked_means: "A RetainAI follow-up was sent…", not_causal: "It does not prove the follow-up caused the payment.", excluded: "RetainAI membership charges, test-mode payments and refunded amounts are never counted." },
  stripe_connected: true,
  sync: { last_synced_at: "2026-11-01T10:00:00Z", complete: true, not_refreshed: 0, stale_items: 0 },
};

let calls;
function mockApi({ status = 200, body = receipt } = {}) {
  calls = [];
  global.fetch = jest.fn(async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || "GET", body: options.body ? JSON.parse(options.body) : null });
    if (String(url).includes("/value-receipt/payments")) return { ok: true, status: 201, json: async () => ({ ok: true, created: true }) };
    if (String(url).includes("/value-receipt/sync")) return { ok: true, status: 200, json: async () => ({ ok: true, read: 2, added: 1, updated: 1 }) };
    return { ok: status < 400, status, json: async () => (status < 400 ? body : { error: "owner_required" }) };
  });
}

afterEach(() => { delete global.fetch; });

test("keeps Stripe-verified and owner-recorded revenue apart and shows the evidence chain", async () => {
  mockApi();
  render(<ValueReceipt leads={[{ id: "a", name: "Ana" }]} />);
  const total = await screen.findByTestId("value-total-cad");
  expect(within(total).getByText(formatMinor(12000, "cad"))).toBeInTheDocument();
  expect(within(total).getByText("Linked, verified by Stripe")).toBeInTheDocument();
  expect(within(total).getByText(formatMinor(8000, "cad"))).toBeInTheDocument();
  expect(within(total).getByText("Linked, owner-recorded")).toBeInTheDocument();
  expect(screen.getByText("Verified by Stripe")).toBeInTheDocument();
  expect(screen.getByText("Owner-recorded")).toBeInTheDocument();
  expect(screen.getByText(/Follow-up by email on/)).toBeInTheDocument();
  expect(screen.getByText(/Invoice N-1 on/)).toBeInTheDocument();
  expect(screen.getByText(/does not prove/)).toBeInTheDocument();
  expect(screen.queryByText("Cleo")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Not linked" }));
  expect(screen.getByText("Cleo")).toBeInTheDocument();
  expect(screen.getByText(/Not counted: No booking or invoice before the payment/)).toBeInTheDocument();
  expect(screen.getByText("Payment not confirmed")).toBeInTheDocument();
  expect(screen.getByText(/credit balance, minimum amount/)).toBeInTheDocument();
});

test("says when the last Stripe update was partial and which refunds were not re-checked", async () => {
  mockApi({ body: { ...receipt, totals: { cad: { ...receipt.totals.cad, paid_unconfirmed_minor: 5000 } },
                    sync: { last_synced_at: "2026-11-01T10:00:00Z", complete: false, not_refreshed: 2, stale_items: 1 } } });
  render(<ValueReceipt leads={[]} />);
  expect(await screen.findByText(/The last Stripe update was partial: refunds for 1 payment shown here were not re-checked/)).toBeInTheDocument();
  expect(screen.getByText(/shown as paid by Stripe without a confirmed charge \(not counted\)/)).toBeInTheDocument();
});

test("records an owner payment with an idempotency key and reads Stripe on request", async () => {
  mockApi();
  render(<ValueReceipt leads={[{ id: "a", name: "Ana" }]} />);
  fireEvent.click(await screen.findByRole("button", { name: "Record a payment" }));
  const form = screen.getByRole("form", { name: "Record a payment" });
  fireEvent.change(within(form).getByLabelText("Amount"), { target: { value: "80.00" } });
  fireEvent.change(within(form).getByLabelText("Time received (optional)"), { target: { value: "16:30" } });
  expect(within(form).getByText(/a booking made the same day can't be linked/)).toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Save payment" }));
  expect(await screen.findByText(/shown as owner-recorded, not verified/)).toBeInTheDocument();
  const posted = calls.find((call) => call.url.endsWith("/value-receipt/payments")).body;
  expect(posted).toMatchObject({ lead_id: "a", amount: "80.00", currency: "cad", paid_time: "16:30" });
  expect(posted.idempotency_key.length).toBeGreaterThanOrEqual(8);

  fireEvent.click(screen.getByRole("button", { name: "Update from Stripe" }));
  expect(await screen.findByText(/Read 2 paid Stripe invoices: 1 new, 1 updated/)).toBeInTheDocument();
  expect(calls.some((call) => call.url.endsWith("/value-receipt/sync") && call.method === "POST")).toBe(true);
});

test("tells team members that revenue is owner-only", async () => {
  mockApi({ status: 403 });
  render(<ValueReceipt leads={[]} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Only the workspace owner can see revenue.");
});

test("requests the chosen period and formats currencies without mixing them", async () => {
  mockApi();
  render(<ValueReceipt leads={[]} />);
  await screen.findByTestId("value-total-cad");
  fireEvent.change(screen.getByLabelText("Period"), { target: { value: "30" } });
  await waitFor(() => expect(calls.filter((call) => call.url.includes("/value-receipt?")).length).toBe(2));
  expect(calls[calls.length - 1].url).toMatch(/since=\d{4}-\d{2}-\d{2}&until=\d{4}-\d{2}-\d{2}/);
  expect(formatMinor(5000, "jpy")).toMatch(/5,000/);
  expect(formatMinor(12345, "usd")).toMatch(/123\.45/);
});

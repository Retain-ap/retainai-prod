import { vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import SquareBookingsCard from "./SquareBookingsCard";

function respond(status, body) {
  return { ok: status < 400, status, json: async () => body };
}

afterEach(() => { delete global.fetch; window.history.replaceState({}, "", "/"); });

test("says plainly when Square isn't set up and offers no connect button", async () => {
  global.fetch = vi.fn(async () => respond(200, { configured: false, connected: false }));
  render(<SquareBookingsCard />);
  expect(await screen.findByTestId("square-unavailable")).toHaveTextContent("Not available yet");
  expect(screen.queryByRole("button", { name: "Connect Square" })).not.toBeInTheDocument();
  expect(screen.getByText(/never changes Square, adds contacts, records consent or messages anyone/)).toBeInTheDocument();
});

test("is hidden from team members", async () => {
  global.fetch = vi.fn(async () => respond(403, { error: "owner_required" }));
  const { container } = render(<SquareBookingsCard />);
  await waitFor(() => expect(container).toBeEmptyDOMElement());
});

test("syncs on request and explains skipped bookings", async () => {
  global.fetch = vi.fn(async (url, options = {}) => {
    if (String(url).endsWith("/square/sync") && options.method === "POST") {
      return respond(200, { read: 6, imported: 4, updated: 0, unchanged: 0, unmatched: 1, skipped: 1, truncated: false, lookup_limit: 0 });
    }
    return respond(200, { configured: true, connected: true, merchant: "…ANT1", last_sync: null });
  });
  render(<SquareBookingsCard />);
  fireEvent.click(await screen.findByRole("button", { name: "Sync now" }));
  expect(await screen.findByText(/Read 6 Square bookings: 4 new, 0 updated, 0 unchanged\. 1 skipped because the Square customer matches no single RetainAI contact; 1 pending bookings in the past skipped\./)).toBeInTheDocument();
});

test("shows the callback result from the URL", async () => {
  window.history.replaceState({}, "", "/app/import?square_error=merchant_linked_elsewhere");
  global.fetch = vi.fn(async () => respond(200, { configured: true, connected: false }));
  render(<SquareBookingsCard />);
  expect(await screen.findByText("That Square account is already connected to another RetainAI workspace.")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Connect Square" })).toBeInTheDocument();
});

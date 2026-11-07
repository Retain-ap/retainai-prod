import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import CalendlyBookingsCard from "./CalendlyBookingsCard";

function respond(status, body) {
  return { ok: status < 400, status, json: async () => body };
}

afterEach(() => { delete global.fetch; window.history.replaceState({}, "", "/"); });

test("says plainly when Calendly isn't set up and offers no connect button", async () => {
  global.fetch = jest.fn(async () => respond(200, { configured: false, connected: false }));
  render(<CalendlyBookingsCard />);
  expect(await screen.findByTestId("calendly-unavailable")).toHaveTextContent("Not available yet");
  expect(screen.queryByRole("button", { name: "Connect Calendly" })).not.toBeInTheDocument();
  expect(screen.getByText(/never\s+changes Calendly, adds contacts, records consent or messages anyone/)).toBeInTheDocument();
  expect(screen.queryByText(/Connected to Calendly/)).not.toBeInTheDocument();
});

test("is hidden from team members", async () => {
  global.fetch = jest.fn(async () => respond(403, { error: "owner_required" }));
  const { container } = render(<CalendlyBookingsCard />);
  await waitFor(() => expect(container).toBeEmptyDOMElement());
});

test("connect asks the server for the Calendly authorize address", async () => {
  const assign = jest.fn();
  const original = window.location;
  delete window.location;
  window.location = { ...original, assign, search: "" };
  global.fetch = jest.fn(async (url, options = {}) => {
    if (String(url).endsWith("/calendly/connect") && options.method === "POST") return respond(200, { url: "https://auth.calendly.com/oauth/authorize?x=1" });
    return respond(200, { configured: true, connected: false });
  });
  render(<CalendlyBookingsCard />);
  fireEvent.click(await screen.findByRole("button", { name: "Connect Calendly" }));
  await waitFor(() => expect(assign).toHaveBeenCalledWith("https://auth.calendly.com/oauth/authorize?x=1"));
  window.location = original;
});

function syncing(result, status = { configured: true, connected: true, account: "…SER1", last_sync: null }) {
  return jest.fn(async (url, options = {}) => {
    if (String(url).endsWith("/calendly/sync") && options.method === "POST") return respond(200, result);
    return respond(200, status);
  });
}

test("syncs on request and explains unmatched, cancelled and capped reads", async () => {
  global.fetch = syncing({ events: 6, invitees: 6, imported: 5, updated: 0, unchanged: 0, unmatched: 1, skipped: 0, cancelled: 2, rescheduled: 1, truncated: true, pass_complete: true, stopped: null });
  render(<CalendlyBookingsCard />);
  expect(await screen.findByText(/Connected to Calendly user …SER1/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
  expect(await screen.findByText(
    "Read 6 Calendly events: 5 new, 0 updated, 0 unchanged. 1 invitee skipped because the email matches no single RetainAI contact; 2 cancelled, 1 of them rescheduled. Calendly history beyond RetainAI's limit for one pass wasn't read."
  )).toBeInTheDocument();
});

test("a bounded or rate-limited sync says progress is saved and how to continue", async () => {
  global.fetch = syncing({ events: 3, invitees: 3, imported: 3, updated: 0, unchanged: 0, unmatched: 0, skipped: 1, cancelled: 0, rescheduled: 0, truncated: false, pass_complete: false, stopped: "rate_limited", retry_after: 37 },
    { configured: true, connected: true, account: "…SER1", last_sync: null, sync_in_progress: true });
  render(<CalendlyBookingsCard />);
  expect(await screen.findByText(/A sync is partway through; press Sync now to continue it\./)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
  expect(await screen.findByText(
    "Read 3 Calendly events: 3 new, 0 updated, 0 unchanged. 1 booking skipped because Calendly sent an unknown status or no valid time. Calendly's rate limit was reached. Progress is saved; press Sync now again in about 37 seconds to continue."
  )).toBeInTheDocument();
});

test("a lost authorization asks to reconnect instead of offering sync", async () => {
  global.fetch = jest.fn(async () => respond(200, { configured: true, connected: false, needs_reconnect: true, account: "…SER1" }));
  render(<CalendlyBookingsCard />);
  expect(await screen.findByText(/no longer accepts RetainAI's access/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Sync now" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Disconnect" })).toBeInTheDocument();
});

test("shows the callback result from the URL", async () => {
  window.history.replaceState({}, "", "/app/import?calendly_error=missing_scope");
  global.fetch = jest.fn(async () => respond(200, { configured: true, connected: false }));
  render(<CalendlyBookingsCard />);
  expect(await screen.findByText(/didn't grant read access to scheduled events/)).toBeInTheDocument();
});

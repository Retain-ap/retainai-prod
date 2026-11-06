import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Appointments from "./Appointments";

const user = { email: "owner@example.com" };
const appointment = { _localKey: "appt-1", title: "Colour consult", date: "2099-01-15", time: "10:00", done: false };
const lead = { id: "lead-1", name: "Jamie", email: "jamie@example.com", appointments: [appointment] };
const imported = { id: "imported", name: "Imported Cara", email: "cara@example.com", imported_at: "2026-11-06T00:00:00Z" };

function mockServer(storedLeads) {
  const calls = [];
  global.fetch = jest.fn(async (url, options = {}) => {
    const method = options.method || "GET";
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ url: String(url), method, body });
    if (String(url).includes("/api/appointments/")) {
      return { ok: true, status: 200, json: async () => ({ appointments: [] }) };
    }
    if (String(url).endsWith("/api/leads") && method === "GET") {
      return { ok: true, status: 200, json: async () => ({ ok: true, leads: storedLeads, revision: "rev-1" }) };
    }
    if (String(url).endsWith("/api/leads") && method === "POST") {
      const stored = body.base_revision === "rev-1" ? body.leads : null;
      return stored
        ? { ok: true, status: 200, json: async () => ({ ok: true, count: stored.length, revision: "rev-2", leads: stored }) }
        : { ok: false, status: 428, json: async () => ({ ok: false, code: "revision_required" }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
  return calls;
}

afterEach(() => {
  delete global.fetch;
});

test("standalone: completing an appointment saves only that change onto the latest list", async () => {
  // Since this screen loaded, the contact was renamed elsewhere and a contact was imported.
  const calls = mockServer([{ ...lead, name: "Jamie Renamed" }, imported]);
  const setLeads = jest.fn();
  render(<Appointments user={user} leads={[lead]} setLeads={setLeads} />);

  fireEvent.click(await screen.findByRole("button", { name: "Done" }));

  await waitFor(() => expect(setLeads.mock.calls.some(([value]) => Array.isArray(value))).toBe(true));
  const leadCalls = calls.filter((call) => call.url.endsWith("/api/leads"));
  expect(leadCalls.map((call) => call.method)).toEqual(["GET", "POST"]);
  const posted = leadCalls[1].body;
  expect(posted.base_revision).toBe("rev-1");
  expect(posted.leads).toEqual([
    { ...lead, name: "Jamie Renamed", appointments: [{ ...appointment, done: true }] },
    imported,
  ]);
  // The screen shows exactly the list the server stored (other calls are the
  // component's derived-count updater functions, not list writes).
  const listWrites = setLeads.mock.calls.map(([value]) => value).filter(Array.isArray);
  expect(listWrites).toEqual([posted.leads]);
});

test("inside the dashboard: hands the change to the shared save instead of posting itself", async () => {
  const calls = mockServer([lead]);
  const saveLeads = jest.fn(async (next) => ({ leads: next, conflicts: [] }));
  render(<Appointments user={user} leads={[lead]} setLeads={jest.fn()} saveLeads={saveLeads} />);

  fireEvent.click(await screen.findByRole("button", { name: "Done" }));

  await waitFor(() => expect(saveLeads).toHaveBeenCalledTimes(1));
  const [next, previous] = saveLeads.mock.calls[0];
  expect(previous).toEqual([lead]);
  expect(next).toEqual([{ ...lead, appointments: [{ ...appointment, done: true }] }]);
  expect(calls.some((call) => call.url.endsWith("/api/leads"))).toBe(false);
});

test("shows an error and changes nothing when the latest list cannot be loaded", async () => {
  global.fetch = jest.fn(async (url) => {
    if (String(url).includes("/api/appointments/")) return { ok: true, status: 200, json: async () => ({ appointments: [] }) };
    return { ok: false, status: 503, json: async () => ({ error: "Service unavailable" }) };
  });
  const setLeads = jest.fn();
  render(<Appointments user={user} leads={[lead]} setLeads={setLeads} />);

  fireEvent.click(await screen.findByRole("button", { name: "Done" }));

  expect(await screen.findByText(/Service unavailable/)).toBeInTheDocument();
  expect(setLeads.mock.calls.some(([value]) => Array.isArray(value))).toBe(false);
  expect(global.fetch.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
});

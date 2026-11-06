import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Appointments, { localAppointmentKey } from "./Appointments";

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

describe("appointments saved before keys were stored", () => {
  // Same title, date and time three times: twice on one contact, once on another.
  const slot = { title: "Colour consult", date: "2099-01-15", time: "10:00", done: false };
  const first = { ...slot, notes: "first" };
  const second = { ...slot, notes: "second" };
  const other = { ...slot, notes: "other contact" };
  const ana = { id: "ana", name: "Ana", email: "ana@example.com", appointments: [first, second] };
  const ben = { id: "ben", name: "Ben", email: "ben@example.com", appointments: [other] };

  async function showLegacyAppointments() {
    mockServer([ana, ben]);
    const saveLeads = jest.fn(async (next) => ({ leads: next, conflicts: [] }));
    render(<Appointments user={user} leads={[ana, ben]} setLeads={jest.fn()} saveLeads={saveLeads} />);
    expect(await screen.findAllByRole("button", { name: "Done" })).toHaveLength(3);
    return saveLeads;
  }

  const savedList = (saveLeads) => saveLeads.mock.calls[0][0];

  test("Done changes only the clicked appointment, not its identical twin or the other contact's", async () => {
    const saveLeads = await showLegacyAppointments();
    fireEvent.click(screen.getAllByRole("button", { name: "Done" })[1]);
    await waitFor(() => expect(saveLeads).toHaveBeenCalledTimes(1));
    expect(savedList(saveLeads)).toEqual([
      { ...ana, appointments: [first, { ...second, done: true }] },
      ben,
    ]);
  });

  test("reschedule moves only the clicked appointment", async () => {
    const saveLeads = await showLegacyAppointments();
    fireEvent.click(screen.getAllByRole("button", { name: /\+1 week/ })[0]);
    await waitFor(() => expect(saveLeads).toHaveBeenCalledTimes(1));
    expect(savedList(saveLeads)).toEqual([
      { ...ana, appointments: [{ ...first, date: "2099-01-22" }, second] },
      ben,
    ]);
  });

  test("delete removes only the clicked appointment", async () => {
    const confirm = jest.spyOn(window, "confirm").mockReturnValue(true);
    const saveLeads = await showLegacyAppointments();
    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[2]);
    await waitFor(() => expect(saveLeads).toHaveBeenCalledTimes(1));
    expect(savedList(saveLeads)).toEqual([ana, { ...ben, appointments: [] }]);
    confirm.mockRestore();
  });

  test("edit replaces only the clicked appointment and gives it a key of its own", async () => {
    const saveLeads = await showLegacyAppointments();
    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    fireEvent.change(screen.getByPlaceholderText("Appointment title"), { target: { value: "Cut and colour" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(saveLeads).toHaveBeenCalledTimes(1));
    const [savedAna, savedBen] = savedList(saveLeads);
    expect(savedBen).toEqual(ben);
    expect(savedAna.appointments).toHaveLength(2);
    expect(savedAna.appointments[0]).toEqual(second); // the twin is untouched
    const edited = savedAna.appointments[1];
    expect(edited).toMatchObject({ title: "Cut and colour", date: slot.date, time: slot.time, notes: "first" });
    // A positional key would now equal the twin's (it moved to position 0).
    expect(edited._localKey).toMatch(/^ana\|local\|/);
    expect(edited._localKey).not.toBe(localAppointmentKey("ana", second, 0));
  });
});

test("localAppointmentKey keeps stored keys and tells identical legacy appointments apart", () => {
  const legacy = { title: "Consult", date: "2099-01-15", time: "10:00" };
  expect(localAppointmentKey("ana", { ...legacy, _localKey: "stored" }, 4)).toBe("stored");
  expect(localAppointmentKey("ana", legacy, 0)).not.toBe(localAppointmentKey("ana", legacy, 1));
  expect(localAppointmentKey("ana", legacy, 0)).not.toBe(localAppointmentKey("ben", legacy, 0));
});

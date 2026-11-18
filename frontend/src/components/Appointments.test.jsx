import { vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import Appointments, { localAppointmentKey } from "./Appointments";

const user = { email: "owner@example.com" };
const appointment = { _localKey: "appt-1", title: "Colour consult", date: "2099-01-15", time: "10:00", done: false };
const lead = { id: "lead-1", name: "Jamie", email: "jamie@example.com", appointments: [appointment] };
const imported = { id: "imported", name: "Imported Cara", email: "cara@example.com", imported_at: "2026-11-06T00:00:00Z" };

function mockServer(storedLeads) {
  const calls = [];
  global.fetch = vi.fn(async (url, options = {}) => {
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
  const setLeads = vi.fn();
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
  const saveLeads = vi.fn(async (next) => ({ leads: next, conflicts: [] }));
  render(<Appointments user={user} leads={[lead]} setLeads={vi.fn()} saveLeads={saveLeads} />);

  fireEvent.click(await screen.findByRole("button", { name: "Done" }));

  await waitFor(() => expect(saveLeads).toHaveBeenCalledTimes(1));
  const [next, previous] = saveLeads.mock.calls[0];
  expect(previous).toEqual([lead]);
  expect(next).toEqual([{ ...lead, appointments: [{ ...appointment, done: true }] }]);
  expect(calls.some((call) => call.url.endsWith("/api/leads"))).toBe(false);
});

test("shows an error and changes nothing when the latest list cannot be loaded", async () => {
  global.fetch = vi.fn(async (url) => {
    if (String(url).includes("/api/appointments/")) return { ok: true, status: 200, json: async () => ({ appointments: [] }) };
    return { ok: false, status: 503, json: async () => ({ error: "Service unavailable" }) };
  });
  const setLeads = vi.fn();
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
    const saveLeads = vi.fn(async (next) => ({ leads: next, conflicts: [] }));
    render(<Appointments user={user} leads={[ana, ben]} setLeads={vi.fn()} saveLeads={saveLeads} />);
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
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
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

test("cancelled and missed visits appear only in history with truthful outcomes and no reinstate controls", async () => {
  localStorage.clear();
  const visit = (id, status) => ({ id, title: id, lead_id: "ana", lead_email: "ana@example.com", appointment_time: "2026-11-14T10:00:00", timezone: "America/Toronto", status, done: true, is_done: true });
  global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ timezone: "America/Toronto", appointments: [
    visit("Missed visit", "no_show"), visit("Cancelled visit", "cancelled"), visit("Attended visit", "completed"),
  ] }) });
  const staleMirror = { id: "ana", email: "ana@example.com", appointments: [
    { title: "Cancelled visit", date: "2026-11-14", time: "10:00", done: false },
  ] };
  render(<Appointments user={user} leads={[staleMirror]} setLeads={vi.fn()} />);
  await waitFor(() => expect(screen.queryByText("Loading appointments…")).not.toBeInTheDocument());
  expect(screen.queryByText("Missed visit")).not.toBeInTheDocument();
  expect(screen.queryByText("Cancelled visit")).not.toBeInTheDocument();
  expect(screen.getByText("No active appointments")).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "Completed" })).getByText("1")).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "All upcoming" })).getByText("0")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "History" }));
  const missed = within(await screen.findByRole("article", { name: "Missed visit" }));
  const cancelled = within(screen.getByRole("article", { name: "Cancelled visit" }));
  expect(missed.getByText("No-show")).toBeInTheDocument();
  expect(cancelled.getByText("Cancelled")).toBeInTheDocument();
  expect(missed.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  expect(cancelled.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  expect(missed.getByText("Toronto time")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Undo" })).toHaveLength(1);
  expect(screen.getAllByRole("article", { name: "Cancelled visit" })).toHaveLength(1);
});

test("undoing a locally completed visit clears its explicit completed status", async () => {
  localStorage.clear();
  const completedLead = { ...lead, appointments: [{ ...appointment, done: true, status: "completed" }] };
  mockServer([completedLead]);
  const saveLeads = vi.fn(async (next) => ({ leads: next, conflicts: [] }));
  render(<Appointments user={user} leads={[completedLead]} setLeads={vi.fn()} saveLeads={saveLeads} />);
  fireEvent.click(screen.getByRole("button", { name: "History" }));
  fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
  await waitFor(() => expect(saveLeads).toHaveBeenCalledTimes(1));
  expect(saveLeads.mock.calls[0][0][0].appointments[0]).toMatchObject({ done: false, status: "scheduled" });
});

test("saving a no-show note records the outcome on a local appointment", async () => {
  localStorage.clear();
  mockServer([lead]);
  const saveLeads = vi.fn(async (next) => ({ leads: next, conflicts: [] }));
  render(<Appointments user={user} leads={[lead]} setLeads={vi.fn()} saveLeads={saveLeads} />);
  fireEvent.click(await screen.findByRole("button", { name: "Done" }));
  const dialog = within(await screen.findByRole("dialog", { name: "Add post-appointment note" }));
  fireEvent.click(dialog.getByRole("button", { name: "No-show" }));
  fireEvent.click(dialog.getByRole("button", { name: "Save to customer" }));
  await waitFor(() => expect(saveLeads).toHaveBeenCalledTimes(2));
  expect(saveLeads.mock.calls[1][0][0].appointments[0]).toMatchObject({ status: "no_show", done: true, notes: "Visit outcome: No-show" });
});

test("saving a no-show note sends the actual outcome to the server", async () => {
  localStorage.clear();
  const stored = { id: "server-visit", title: "Provider visit", lead_id: lead.id, lead_email: lead.email, appointment_time: "2099-01-15T10:00:00", timezone: "America/Toronto", status: "scheduled", done: false };
  const writes = [];
  global.fetch = vi.fn(async (url, options = {}) => {
    if (options.method === "PUT") {
      const body = JSON.parse(options.body);
      writes.push(body);
      Object.assign(stored, body);
      return { ok: true, json: async () => ({ appointment: stored }) };
    }
    return { ok: true, json: async () => ({ timezone: "America/Toronto", appointments: [stored] }) };
  });
  render(<Appointments user={user} leads={[]} setLeads={vi.fn()} saveLeads={vi.fn(async (next) => ({ leads: next }))} />);
  fireEvent.click(await screen.findByRole("button", { name: "Done" }));
  const dialog = within(await screen.findByRole("dialog", { name: "Add post-appointment note" }));
  fireEvent.click(dialog.getByRole("button", { name: "No-show" }));
  fireEvent.click(dialog.getByRole("button", { name: "Save to customer" }));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1]).toMatchObject({ status: "no_show", done: true, is_done: true, completed: false });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "History" }));
  expect(within(screen.getByRole("article", { name: "Provider visit" })).getByText("No-show")).toBeInTheDocument();
});

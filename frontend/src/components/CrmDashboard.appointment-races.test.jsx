import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import CrmDashboard from "./CrmDashboard";

jest.mock("./SettingsContext", () => { const value = { settings: {}, setUser: jest.fn() }; return { useSettings: () => value }; });
jest.mock("./Sidebar", () => () => null);
jest.mock("./LeadsDashboard", () => () => null);
jest.mock("./LeadModal", () => () => null);
jest.mock("./Calendar", () => ({ onDayClick }) => <button onClick={() => onDayClick(new Date(2026, 10, 14))}>Choose appointment day</button>);
jest.mock("./Appointments", () => () => null);
jest.mock("./Messages", () => () => null);
jest.mock("./NotificationsCenter", () => () => null);
jest.mock("./Notifications", () => () => null);
jest.mock("./AiPromptsDashboard", () => () => null);
jest.mock("./Settings", () => () => null);
jest.mock("./Insights", () => () => null);
jest.mock("./Invoices", () => () => null);
jest.mock("./Automations", () => () => null);
jest.mock("./InviteTeamModal", () => () => null);
jest.mock("./RetentionCommandCenter", () => ({ appointments }) => <output data-testid="appointments">{appointments.map(item => item.title).join(",")}</output>);
jest.mock("./OwnerConsole", () => () => null);
jest.mock("./TrialCommandBar", () => () => null);
jest.mock("./OnboardingGuide", () => () => null);

const member = { email: "member@example.test", role: "owner", platformOwner: false };
const originalFetch = global.fetch;
const deferred = () => { let resolve, reject; const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; }); return { promise, resolve, reject }; };
const response = appointments => ({ ok: true, json: async () => ({ appointments, timezone: "America/Toronto" }) });
const booking = title => ({ id: title, title, lead_id: "sample", appointment_time: "2026-11-14T10:00:00-05:00", timezone: "America/Toronto" });
let reads, writes;
beforeEach(() => {
  reads = []; writes = []; localStorage.clear();
  window.matchMedia = jest.fn(() => ({ matches: false, addEventListener: jest.fn(), removeEventListener: jest.fn() }));
  global.fetch = jest.fn((url, options = {}) => {
    if (String(url).includes("/appointments/")) {
      const pending = { url: String(url), ...deferred() };
      (options.method === "POST" ? writes : reads).push(pending); return pending.promise;
    }
    return Promise.resolve({ ok: true, json: async () => ({ leads: [{ id: "sample", name: "Fictional client" }], revision: "r1", connected: false }) });
  });
});
afterEach(() => { global.fetch = originalFetch; delete window.matchMedia; delete window.RetainAI; localStorage.clear(); jest.restoreAllMocks(); });
const dashboard = (user = member, path = "/app") => <MemoryRouter initialEntries={[path]}><CrmDashboard authenticatedUser={user} /></MemoryRouter>;
const changed = () => act(() => window.dispatchEvent(new Event("appointments:changed")));
async function mount() { const view = render(dashboard()); await waitFor(() => expect(reads).toHaveLength(1)); return view; }

test("a slow initial appointment list cannot replace a newer appointments-changed result", async () => {
  await mount(); changed(); expect(reads).toHaveLength(2);
  await act(async () => reads[1].resolve(response([booking("New booking")])));
  expect(screen.getByTestId("appointments")).toHaveTextContent("New booking");
  await act(async () => reads[0].resolve(response([])));
  expect(screen.getByTestId("appointments")).toHaveTextContent("New booking");
});

test("failed overlapping refreshes keep the last confirmed list and never revive an older result", async () => {
  await mount(); await act(async () => reads[0].resolve(response([booking("Confirmed booking")])));
  changed(); changed();
  await act(async () => reads[2].reject(new Error("Latest lookup failed")));
  await act(async () => reads[1].resolve(response([booking("Old booking")])));
  expect(screen.getByTestId("appointments")).toHaveTextContent("Confirmed booking");
  expect(screen.getByTestId("appointments")).not.toHaveTextContent("Old booking");
});

test("changing workspace clears its appointments and ignores the previous workspace's delayed response", async () => {
  const view = await mount();
  await act(async () => reads[0].resolve(response([booking("First workspace")])));
  changed();
  view.rerender(dashboard({ ...member, email: "second@example.test" }));
  await waitFor(() => expect(reads).toHaveLength(3));
  expect(screen.getByTestId("appointments")).toBeEmptyDOMElement();
  await act(async () => reads[1].resolve(response([booking("Private old booking")])));
  expect(screen.getByTestId("appointments")).toBeEmptyDOMElement();
  await act(async () => reads[2].resolve(response([booking("Second workspace")])));
  expect(screen.getByTestId("appointments")).toHaveTextContent("Second workspace");
});

test("unmount invalidates the pending read and removes its refresh listener", async () => {
  const view = await mount(); view.unmount(); changed();
  expect(reads).toHaveLength(1);
  await act(async () => reads[0].resolve(response([booking("Closed workspace")])));
  expect(screen.queryByTestId("appointments")).not.toBeInTheDocument();
});

test("import completion reloads its own workspace while legacy notifications remain compatible", async () => {
  await mount();
  const leadReads = () => global.fetch.mock.calls.filter(([url]) => /\/leads(?:\?|$)/.test(String(url))).length;
  const initial = leadReads(); expect(initial).toBeGreaterThan(0);
  await act(async () => window.dispatchEvent(new CustomEvent("leads:changed", { detail: { workspaceEmail: "other@example.test" } })));
  expect(leadReads()).toBe(initial);
  await act(async () => window.dispatchEvent(new CustomEvent("leads:changed", { detail: { workspaceEmail: member.email } })));
  expect(leadReads()).toBe(initial + 1);
  await act(async () => window.dispatchEvent(new Event("leads:changed")));
  expect(leadReads()).toBe(initial + 2);
});

test.each(["success", "failure"])("late quick-add %s after unmount does not refresh or alert another workspace", async result => {
  const view = render(dashboard(member, "/app?section=calendar"));
  await waitFor(() => expect(reads).toHaveLength(1));
  await act(async () => reads[0].resolve(response([])));
  fireEvent.click(screen.getByRole("button", { name: "Choose appointment day" }));
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "sample" } });
  fireEvent.change(screen.getByPlaceholderText("Appointment title"), { target: { value: "Fictional appointment" } });
  fireEvent.click(screen.getByRole("button", { name: "Add", exact: true }));
  expect(writes).toHaveLength(1); view.unmount();
  const dispatch = jest.spyOn(window, "dispatchEvent"), alert = jest.spyOn(window, "alert").mockImplementation(() => {});
  await act(async () => result === "success" ? writes[0].resolve({ ok: true, json: async () => ({ ok: true }) }) : writes[0].reject(new Error("Old write failed")));
  expect(reads).toHaveLength(1);
  expect(dispatch.mock.calls.some(([event]) => event.type === "appointments:changed")).toBe(false);
  expect(alert).not.toHaveBeenCalled();
});

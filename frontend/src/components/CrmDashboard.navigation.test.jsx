import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import CrmDashboard from "./CrmDashboard";

jest.mock("./SettingsContext", () => {
  const context = { settings: {}, setUser: jest.fn() };
  return { useSettings: () => context };
});
jest.mock("./Sidebar", () => ({ setSection }) => <nav>{["overview", "dashboard", "calendar", "settings"].map(section => <button key={section} onClick={() => setSection(section)}>{section}</button>)}</nav>);
jest.mock("./LeadsDashboard", () => () => <div>Contact records</div>);
jest.mock("./LeadModal", () => () => null);
jest.mock("./Calendar", () => () => <div>Calendar grid</div>);
jest.mock("./Appointments", () => () => <div>Appointment list</div>);
jest.mock("./Messages", () => ({ onOpenBusinessSettings }) => <div>Message inbox<button onClick={onOpenBusinessSettings}>Inbox business settings</button></div>);
jest.mock("./NotificationsCenter", () => () => null);
jest.mock("./Notifications", () => () => null);
jest.mock("./AiPromptsDashboard", () => ({ onOpenBusinessSettings, initialFocus }) => <div>AI Studio<button onClick={onOpenBusinessSettings}>Studio business settings</button>{initialFocus && <output data-testid="studio-focus">{`${initialFocus.leadId}|${initialFocus.playbook}|${initialFocus.context}`}</output>}</div>);
jest.mock("./Settings", () => ({ initialTab }) => <div>Settings {initialTab || "profile"}</div>);
jest.mock("./Insights", () => () => null);
jest.mock("./Invoices", () => () => null);
jest.mock("./Automations", () => () => <div>Automation playbooks</div>);
jest.mock("./InviteTeamModal", () => () => null);
jest.mock("./RetentionCommandCenter", () => ({ onOpenMessages, onOpenAppointments, onOpenImports, onDraftFollowUp, onMarkContacted }) => <div>Retention overview<button onClick={onOpenMessages}>Overview messages shortcut</button><button onClick={onOpenAppointments}>Setup add appointment</button><button onClick={onOpenImports}>Setup import contacts</button><button onClick={() => onDraftFollowUp({ id: "lead-1", email: "ava@example.com" }, "Due to rebook: last completed visit Oct 1; usually every 30 days.")}>Rebook draft</button><button onClick={() => onMarkContacted({ id: "lead-1" }).then(() => { global.__marked = "ok"; }, (error) => { global.__marked = error.message; })}>Rebook mark contacted</button></div>);
jest.mock("./OwnerConsole", () => () => <div>Platform owner console</div>);
jest.mock("./TrialCommandBar", () => () => null);

const member = { email: "reviewer@example.test", role: "owner", platformOwner: false };
const originalFetch = global.fetch;

function HistoryControls() {
  const navigate = useNavigate();
  const location = useLocation();
  return <><button onClick={() => navigate(-1)}>Browser back</button><button onClick={() => navigate(1)}>Browser forward</button><output data-testid="location">{location.pathname}{location.search}</output></>;
}

async function mount(initial = "/app", user = member) {
  render(<MemoryRouter initialEntries={[initial]}><HistoryControls /><CrmDashboard authenticatedUser={user} /></MemoryRouter>);
  await act(async () => { await Promise.resolve(); });
}

beforeEach(() => {
  localStorage.clear();
  window.matchMedia = jest.fn(query => ({ matches: false, media: query, addEventListener: jest.fn(), removeEventListener: jest.fn() }));
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ leads: [], appointments: [], connected: false }) }));
});
afterEach(() => { global.fetch = originalFetch; localStorage.clear(); delete window.RetainAI; delete window.matchMedia; });

test("browser back restores the initial overview and forward restores contacts", async () => {
  await mount();
  expect(screen.getByText("Retention overview")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "dashboard", exact: true }));
  expect(screen.getByText("Contact records")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.getByText("Retention overview")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Browser forward" }));
  expect(screen.getByText("Contact records")).toBeInTheDocument();
});

test("a regular Calendar visit resets a previous appointments deep link", async () => {
  await mount("/app?section=calendar&view=appointments");
  expect(screen.getByText("Appointment list")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "dashboard", exact: true }));
  fireEvent.click(screen.getByRole("button", { name: "calendar", exact: true }));
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByText("Calendar grid")).toBeInTheDocument();
  expect(screen.queryByText("Appointment list")).not.toBeInTheDocument();
});

test("command palette changes the URL and history restores Settings", async () => {
  await mount("/app?tab=profile");
  fireEvent.keyDown(window, { key: "k", ctrlKey: true });
  fireEvent.click(screen.getByRole("button", { name: /Open customer contacts/ }));
  expect(screen.getByText("Contact records")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("/app?section=dashboard");
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.getByText("Settings profile")).toBeInTheDocument();
});

test("an overview shortcut and team shortcut keep their destinations in the URL", async () => {
  await mount();
  fireEvent.click(screen.getByRole("button", { name: "Overview messages shortcut" }));
  expect(screen.getByText("Message inbox")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("section=messages");
  act(() => window.RetainAI.openTeam());
  expect(screen.getByText("Settings team")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("tab=team");
});

test("the owner can navigate to Overview and restore the owner landing page with Back", async () => {
  await mount("/app", { ...member, platformOwner: true });
  expect(screen.getByText("Platform owner console")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "overview", exact: true }));
  expect(screen.getByText("Retention overview")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.getByText("Platform owner console")).toBeInTheDocument();
});

test("calendar view buttons participate in browser history", async () => {
  await mount("/app?section=calendar");
  fireEvent.click(screen.getByRole("button", { name: "Appointments", exact: true }));
  expect(screen.getByText("Appointment list")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("view=appointments");
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.getByText("Calendar grid")).toBeInTheDocument();
});

test("onboarding shortcuts preserve their destination when leaving an import deep link", async () => {
  await mount("/app/import");
  expect(screen.getByText("Settings imports")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Setup ·/ }));
  fireEvent.click(screen.getByRole("button", { name: "Activate your first playbook" }));
  expect(screen.getByText("Automation playbooks")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("section=automations");
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.getByText("Settings imports")).toBeInTheDocument();
});

test("navigation events cannot open a privileged page for a standard team member", async () => {
  await mount("/app?section=owner", { ...member, role: "member" });
  expect(screen.getByText("Retention overview")).toBeInTheDocument();
  for (const section of ["owner", "invoices", "__proto__"]) {
    act(() => window.RetainAI.openSection(section));
    act(() => window.dispatchEvent(new CustomEvent("retainai:navigate", { detail: section })));
    expect(screen.getByText("Retention overview")).toBeInTheDocument();
    expect(screen.queryByText("Platform owner console")).not.toBeInTheDocument();
  }
});

test("Google Calendar prompts open Settings > Integrations, not the Contacts importer, and authorize nothing", async () => {
  await mount("/app?section=calendar");
  fireEvent.click(screen.getByRole("button", { name: "Refresh Google events" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/app?tab=integrations"));
  expect(screen.getByText("Settings integrations")).toBeInTheDocument();
  expect(screen.getByTestId("location")).not.toHaveTextContent("/app/import");

  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  expect(await screen.findByText("Calendar grid")).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Connect Calendar" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/app?tab=integrations"));
  expect(screen.getByText("Settings integrations")).toBeInTheDocument();

  const requested = global.fetch.mock.calls.map(([url]) => String(url));
  expect(requested.some((url) => /authorize|oauth/i.test(url))).toBe(false);
});

test("contact import shortcuts open the multi-source importer without the Google-only deep link", async () => {
  await mount("/app?section=dashboard");
  act(() => window.RetainAI.openImports());
  expect(screen.getByText("Settings imports")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/app\/import$/);
});

test("the chosen contact source survives navigation and unknown values use the generic importer", async () => {
  await mount("/app?section=dashboard");
  act(() => window.RetainAI.openImports("whatsapp"));
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/app\/import\?source=whatsapp$/);
  act(() => window.RetainAI.openImports("https://untrusted.example"));
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/app\/import$/);
});

test("the setup checklist's Add appointment opens the appointment list; contact import stays separate", async () => {
  await mount();
  fireEvent.click(screen.getByRole("button", { name: "Setup add appointment" }));
  expect(screen.getByText("Appointment list")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/app\?section=calendar&view=appointments$/);
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.getByText("Retention overview")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Setup import contacts" }));
  expect(screen.getByText("Settings imports")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/app\/import$/);
});

test.each([
  ["/app?section=ai-prompts", "Studio business settings"],
  ["/app?section=messages", "Inbox business settings"],
])("a business-name prompt in %s opens Settings > Profile", async (start, action) => {
  await mount(start);
  fireEvent.click(screen.getByRole("button", { name: action }));
  expect(screen.getByText("Settings profile")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("/app?tab=profile");
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.getByRole("button", { name: action })).toBeInTheDocument();
});

test("Draft follow-up opens AI Studio on that customer with its context; nothing is sent", async () => {
  await mount("/app");
  fireEvent.click(screen.getByRole("button", { name: "Rebook draft" }));
  expect(screen.getByTestId("location")).toHaveTextContent("/app?section=ai-prompts");
  expect(screen.getByTestId("studio-focus")).toHaveTextContent("lead-1|followup|Due to rebook: last completed visit Oct 1; usually every 30 days.");
  expect(global.fetch.mock.calls.some(([url]) => String(url).includes("send-ai-message"))).toBe(false);
});

test("Mark contacted records the contact on the server for that one customer and reloads contacts", async () => {
  await mount("/app");
  global.fetch.mockClear();
  global.fetch.mockImplementation(async (url) => String(url).includes("leads/contacted")
    ? { ok: true, status: 200, json: async () => ({ ok: true, lead: { id: "lead-1" } }) }
    : { ok: true, json: async () => ({ leads: [], appointments: [], connected: false }) });
  const reloads = jest.fn();
  window.addEventListener("leads:changed", reloads);
  fireEvent.click(screen.getByRole("button", { name: "Rebook mark contacted" }));
  await waitFor(() => expect(global.__marked).toBe("ok"));
  const [url, options] = global.fetch.mock.calls.find(([called]) => String(called).includes("leads/contacted"));
  expect(String(url)).toMatch(/\/api\/leads\/contacted$/);
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toEqual({ leadId: "lead-1" });
  expect(reloads).toHaveBeenCalled();
  window.removeEventListener("leads:changed", reloads);
  delete global.__marked;
});

test("a refused mark-contacted reports a clear error", async () => {
  await mount("/app");
  global.fetch.mockImplementation(async (url) => String(url).includes("leads/contacted")
    ? { ok: false, status: 404, json: async () => ({ ok: false, error: "lead_not_found" }) }
    : { ok: true, json: async () => ({ leads: [], appointments: [], connected: false }) });
  fireEvent.click(screen.getByRole("button", { name: "Rebook mark contacted" }));
  await waitFor(() => expect(global.__marked).toBe("This customer is no longer in your contacts. Reload and try again."));
  delete global.__marked;
});

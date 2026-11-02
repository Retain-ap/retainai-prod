import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
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
jest.mock("./Messages", () => () => <div>Message inbox</div>);
jest.mock("./NotificationsCenter", () => () => null);
jest.mock("./Notifications", () => () => null);
jest.mock("./AiPromptsDashboard", () => () => null);
jest.mock("./Settings", () => ({ initialTab }) => <div>Settings {initialTab || "profile"}</div>);
jest.mock("./Insights", () => () => null);
jest.mock("./Invoices", () => () => null);
jest.mock("./Automations", () => () => <div>Automation playbooks</div>);
jest.mock("./InviteTeamModal", () => () => null);
jest.mock("./RetentionCommandCenter", () => ({ onOpenMessages }) => <div>Retention overview<button onClick={onOpenMessages}>Overview messages shortcut</button></div>);
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

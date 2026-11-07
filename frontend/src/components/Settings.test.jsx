import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import Settings from "./Settings";

const user = {
  email: "owner@example.com",
  name: "Owner",
  business: "Acme",
  businessType: "Salon",
  role: "owner",
  canInviteTeam: true,
  canEditBusiness: true,
  canManageBilling: true,
};

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Service Unavailable",
    headers: { get: () => "application/json" },
    text: async () => JSON.stringify(body),
  };
}

test("keeps an unsaved profile draft editable when the backend rejects it", async () => {
  const warning = jest.spyOn(console, "warn").mockImplementation(() => {});
  localStorage.setItem("user", JSON.stringify(user));
  global.fetch = jest.fn().mockImplementation((_url, options = {}) => {
    if (options.method === "POST") return Promise.resolve(response({ error: "unavailable" }, 503));
    return Promise.resolve(response(user));
  });

  render(
    <MemoryRouter>
      <Settings user={user} refreshUser={jest.fn()} />
    </MemoryRouter>
  );

  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  fireEvent.click(await screen.findByRole("button", { name: "Edit Profile" }));
  fireEvent.change(screen.getByDisplayValue("Acme"), { target: { value: "Acme Updated" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByText(/temporarily unavailable/i)).toBeInTheDocument();
  expect(screen.getByDisplayValue("Acme Updated")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem("user")).business).toBe("Acme");
  expect(warning).toHaveBeenCalledWith("Profile save failed.", expect.any(Error));
  warning.mockRestore();
});

test("does not restart profile polling when the refresh callback identity changes", async () => {
  localStorage.setItem("user", JSON.stringify(user));
  global.fetch = jest.fn().mockResolvedValue(response(user));

  const view = render(
    <MemoryRouter>
      <Settings user={user} refreshUser={jest.fn().mockResolvedValue(undefined)} />
    </MemoryRouter>
  );

  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  await Promise.resolve();
  const requestsAfterInitialLoad = global.fetch.mock.calls.length;

  view.rerender(
    <MemoryRouter>
      <Settings user={user} refreshUser={jest.fn().mockResolvedValue(undefined)} />
    </MemoryRouter>
  );
  await Promise.resolve();
  await Promise.resolve();

  expect(global.fetch).toHaveBeenCalledTimes(requestsAfterInitialLoad);
});

test("allows leaving the route-selected Import Contacts tab", async () => {
  localStorage.setItem("user", JSON.stringify(user));
  global.fetch = jest.fn().mockResolvedValue(response(user));

  render(
    <MemoryRouter>
      <Settings
        user={user}
        initialTab="imports"
        refreshUser={jest.fn().mockResolvedValue(undefined)}
      />
    </MemoryRouter>
  );

  expect(await screen.findByText("Import contacts")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Profile" }));

  expect(await screen.findByRole("button", { name: "Edit Profile" })).toBeInTheDocument();
});

// Mirrors CrmDashboard: the ?tab= query is what selects Settings' initialTab.
function RoutedSettings({ profile = user }) {
  const location = useLocation();
  const navigate = useNavigate();
  const initialTab = new URLSearchParams(location.search).get("tab");
  return (
    <>
      <button onClick={() => navigate(-1)}>Browser back</button>
      <button onClick={() => navigate(1)}>Browser forward</button>
      <output data-testid="location">{location.pathname}{location.search}</output>
      <Settings user={profile} initialTab={initialTab} refreshUser={jest.fn().mockResolvedValue(undefined)} />
    </>
  );
}

function renderRouted(path, profile) {
  localStorage.setItem("user", JSON.stringify(profile || user));
  global.fetch = jest.fn().mockResolvedValue(response(profile || user));
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RoutedSettings profile={profile} />
    </MemoryRouter>
  );
}

test("settings tabs and help shortcuts update the URL so reload and Back match the visible tab", async () => {
  renderRouted("/app?tab=profile");
  expect(await screen.findByRole("button", { name: "Edit Profile" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Integrations" }));
  expect(await screen.findByText("Connected accounts")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("/app?tab=integrations");

  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  expect(await screen.findByRole("button", { name: "Edit Profile" })).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("/app?tab=profile");

  fireEvent.click(screen.getByRole("button", { name: "Browser forward" }));
  expect(await screen.findByText("Connected accounts")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Help & Support" }));
  expect(screen.getByTestId("location")).toHaveTextContent("/app?tab=help");
  fireEvent.click(await screen.findByRole("button", { name: /^Integrations .+/ }));
  expect(await screen.findByText("Connected accounts")).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("/app?tab=integrations");
});

test("tab links respect role restrictions and never put a hidden tab in the URL", async () => {
  const member = { ...user, role: "member", canInviteTeam: false, canEditBusiness: false, canManageBilling: false };
  renderRouted("/app?tab=billing", member);

  await waitFor(() => expect(screen.getByRole("button", { name: "Profile" })).toHaveAttribute("aria-current", "page"));
  expect(screen.queryByRole("button", { name: "Billing" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Team" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Help & Support" }));
  expect(screen.getByTestId("location")).toHaveTextContent("/app?tab=help");
  fireEvent.click(await screen.findByRole("button", { name: /^Account & team/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Profile" })).toHaveAttribute("aria-current", "page"));
  expect(screen.getByTestId("location")).toHaveTextContent("/app?tab=profile");
});

test("the owner can choose the optional salon and barber preset; general is the default", async () => {
  localStorage.setItem("user", JSON.stringify(user));
  global.fetch = jest.fn().mockImplementation((_url, options = {}) => {
    if (options.method === "POST") return Promise.resolve(response({ ok: true, ...user, setup_preset: "salon_barber" }));
    return Promise.resolve(response(user));
  });

  render(
    <MemoryRouter>
      <Settings user={user} refreshUser={jest.fn()} />
    </MemoryRouter>
  );

  expect(await screen.findByText("General service business")).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Edit Profile" }));
  fireEvent.change(screen.getByLabelText("Setup preset"), { target: { value: "salon_barber" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(global.fetch.mock.calls.some(([, options]) => options?.method === "POST")).toBe(true));
  const [, options] = global.fetch.mock.calls.find(([, call]) => call?.method === "POST");
  expect(JSON.parse(options.body)).toMatchObject({ setup_preset: "salon_barber", businessType: "Salon" });
});

function googleCard() {
  return screen.getByRole("heading", { name: "Google Contacts" }).closest("section");
}

function renderImports(path) {
  localStorage.setItem("user", JSON.stringify(user));
  global.fetch = jest.fn().mockResolvedValue(response(user));
  render(
    <MemoryRouter initialEntries={[path]}>
      <Settings user={user} initialTab="imports" refreshUser={jest.fn().mockResolvedValue(undefined)} />
    </MemoryRouter>
  );
}

test("opening the importer from Contacts starts at the file importer, not the Google card", async () => {
  renderImports("/app/import");
  expect(await screen.findByText("Import contacts")).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Contact sources" })).toBeInTheDocument();
  expect(googleCard()).not.toHaveClass("google-import-focus");
});

test("only a Google prompt (?source=google) highlights the Google Contacts card", async () => {
  renderImports("/app/import?source=google");
  expect(await screen.findByText("Import contacts")).toBeInTheDocument();
  expect(googleCard()).toHaveClass("google-import-focus");
});

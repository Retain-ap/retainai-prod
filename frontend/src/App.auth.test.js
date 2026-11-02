import { render, screen } from "@testing-library/react";
import App from "./App";

jest.mock("./components/SettingsContext", () => ({
  SettingsProvider: ({ children }) => children,
}));
jest.mock("./components/CrmDashboard", () => ({
  __esModule: true,
  default: ({ authenticatedUser }) => (
    <div>
      <span>{authenticatedUser?.email || "Missing verified session"}</span>
      <span>{authenticatedUser?.platformOwner ? "Owner console enabled" : "Standard workspace"}</span>
    </div>
  ),
}));

const originalFetch = global.fetch;

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState({}, "", "/app?section=owner");
});

afterEach(() => {
  global.fetch = originalFetch;
  localStorage.clear();
  sessionStorage.clear();
});

test.each([
  [true, "Owner console enabled"],
  [false, "Standard workspace"],
])("passes the server-verified owner capability (%s) through the lazy app route", async (allowed, expected) => {
  // Cached owner access must never override the fresh server response.
  localStorage.setItem("user", JSON.stringify({ email: "stale@example.com", platformOwner: true }));
  global.fetch = jest.fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ authenticated: true, user: { email: "reviewer@example.com", platformOwner: true } }),
    })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ allowed }) });

  render(<App />);

  expect(await screen.findByText("reviewer@example.com")).toBeInTheDocument();
  expect(screen.getByText(expected)).toBeInTheDocument();
  expect(screen.queryByText("Missing verified session")).not.toBeInTheDocument();
  expect(global.fetch).toHaveBeenCalledWith(expect.stringMatching(/\/owner\/access$/), {
    credentials: "include",
    cache: "no-store",
  });
});

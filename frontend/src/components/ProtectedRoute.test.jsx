import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProtectedRoute from "./ProtectedRoute";

function renderRoute() {
  function PrivateWorkspace() {
    return <div>Private workspace</div>;
  }

  return render(
    <MemoryRouter
      initialEntries={["/app"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/login" element={<div>Login screen</div>} />
        <Route
          path="/app"
          element={
            <ProtectedRoute>
              <PrivateWorkspace />
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    localStorage.clear();
    jest.restoreAllMocks();
  });

  test("redirects only when the session endpoint explicitly rejects authentication", async () => {
    localStorage.setItem("user", JSON.stringify({ email: "member@example.com" }));
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 });

    renderRoute();

    expect(await screen.findByText("Login screen")).toBeInTheDocument();
    expect(localStorage.getItem("user")).toBeNull();
  });

  test("preserves the session and offers retry during a service outage", async () => {
    localStorage.setItem("user", JSON.stringify({ email: "member@example.com" }));
    global.fetch = jest
      .fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ authenticated: true, user: { email: "member@example.com" } }),
      })
      .mockRejectedValueOnce(new TypeError("owner access unavailable"));

    renderRoute();

    expect(await screen.findByText("We could not reach your workspace")).toBeInTheDocument();
    expect(localStorage.getItem("user")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Private workspace")).toBeInTheDocument();
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(4));
  });
});

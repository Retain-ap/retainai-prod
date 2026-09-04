import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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

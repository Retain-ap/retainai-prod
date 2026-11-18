import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import LeadReminderEmailSetting from "./LeadReminderEmailSetting";

const response = (enabled, ok = true) => ({ ok, json: async () => ({ preferences: { lead_reminder_emails: enabled } }) });
const ownerEmail = "Owner@Example.test";
beforeEach(() => { global.fetch = jest.fn(); });

test("loads server preference and confirms a disable without changing browser preferences", async () => {
  localStorage.setItem("retainai:notification-preferences", "unchanged");
  fetch.mockResolvedValueOnce(response(true)).mockResolvedValueOnce(response(false));
  render(<LeadReminderEmailSetting ownerEmail={ownerEmail} />);
  const checkbox = screen.getByRole("checkbox", { name: "Email me when leads need attention" });
  expect(checkbox).toBeDisabled();
  await waitFor(() => expect(checkbox).toBeChecked());
  fireEvent.click(checkbox);
  expect(await screen.findByText("Follow-up reminder emails turned off.")).toBeInTheDocument();
  expect(checkbox).not.toBeChecked();
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ lead_reminder_emails: false });
  expect(fetch.mock.calls[1][1].credentials).toBe("include");
  expect(fetch.mock.calls[0][1].headers["X-User-Email"]).toBe("owner@example.test");
  expect(fetch.mock.calls[1][1].headers["X-User-Email"]).toBe("owner@example.test");
  expect(localStorage.getItem("retainai:notification-preferences")).toBe("unchanged");
});

test("blocks duplicate saves while waiting for server confirmation", async () => {
  let finish;
  fetch.mockResolvedValueOnce(response(true)).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  render(<LeadReminderEmailSetting ownerEmail={ownerEmail} />);
  const checkbox = screen.getByRole("checkbox");
  await waitFor(() => expect(checkbox).not.toBeDisabled());
  fireEvent.click(checkbox); fireEvent.click(checkbox);
  expect(checkbox).toBeDisabled();
  expect(fetch).toHaveBeenCalledTimes(2);
  await act(async () => finish(response(false)));
  expect(checkbox).not.toBeChecked();
});

test("a lost save response requires a readback and never claims success", async () => {
  fetch.mockResolvedValueOnce(response(true)).mockRejectedValueOnce(new Error("lost response")).mockResolvedValueOnce(response(false));
  render(<LeadReminderEmailSetting ownerEmail={ownerEmail} />);
  await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeDisabled());
  fireEvent.click(screen.getByRole("checkbox"));
  expect(await screen.findByRole("alert")).toHaveTextContent("could not confirm");
  expect(screen.getByRole("checkbox")).toBeDisabled();
  expect(screen.queryByText("Follow-up reminder emails turned off.")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reload email preference" }));
  await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeDisabled());
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(fetch.mock.calls.filter(([, options]) => options.method === "POST")).toHaveLength(1);
});

test("a late response from a previous account cannot replace the current setting", async () => {
  let finishOld;
  fetch.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; })).mockResolvedValueOnce(response(false));
  const view = render(<LeadReminderEmailSetting key="old-owner" ownerEmail="old@example.test" />);
  view.rerender(<LeadReminderEmailSetting key="new-owner" ownerEmail="new@example.test" />);
  await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeDisabled());
  await act(async () => finishOld(response(true)));
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(fetch.mock.calls[0][1].headers["X-User-Email"]).toBe("old@example.test");
  expect(fetch.mock.calls[1][1].headers["X-User-Email"]).toBe("new@example.test");
});

test("missing displayed owner identity disables changes without a request", async () => {
  render(<LeadReminderEmailSetting ownerEmail="  " />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Sign in as the workspace owner");
  const checkbox = screen.getByRole("checkbox");
  expect(checkbox).toBeDisabled();
  fireEvent.click(checkbox);
  expect(fetch).not.toHaveBeenCalled();
});

test("a stale tab remains bound to its displayed owner when the session changes", async () => {
  fetch.mockResolvedValueOnce(response(true)).mockResolvedValueOnce(response(null, false));
  render(<LeadReminderEmailSetting ownerEmail="first@example.test" />);
  await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeDisabled());
  fireEvent.click(screen.getByRole("checkbox"));
  expect(await screen.findByRole("alert")).toHaveTextContent("could not confirm");
  expect(fetch.mock.calls[1][1].headers["X-User-Email"]).toBe("first@example.test");
  expect(screen.getByRole("checkbox")).toBeDisabled();
});

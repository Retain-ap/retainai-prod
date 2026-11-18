import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import LeadReminderEmailSetting from "./LeadReminderEmailSetting";

const response = (enabled, ok = true) => ({ ok, json: async () => ({ preferences: { lead_reminder_emails: enabled } }) });
beforeEach(() => { global.fetch = jest.fn(); });

test("loads server preference and confirms a disable without changing browser preferences", async () => {
  localStorage.setItem("retainai:notification-preferences", "unchanged");
  fetch.mockResolvedValueOnce(response(true)).mockResolvedValueOnce(response(false));
  render(<LeadReminderEmailSetting />);
  const checkbox = screen.getByRole("checkbox", { name: "Email me when leads need attention" });
  expect(checkbox).toBeDisabled();
  await waitFor(() => expect(checkbox).toBeChecked());
  fireEvent.click(checkbox);
  expect(await screen.findByText("Follow-up reminder emails turned off.")).toBeInTheDocument();
  expect(checkbox).not.toBeChecked();
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ lead_reminder_emails: false });
  expect(fetch.mock.calls[1][1].credentials).toBe("include");
  expect(localStorage.getItem("retainai:notification-preferences")).toBe("unchanged");
});

test("blocks duplicate saves while waiting for server confirmation", async () => {
  let finish;
  fetch.mockResolvedValueOnce(response(true)).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  render(<LeadReminderEmailSetting />);
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
  render(<LeadReminderEmailSetting />);
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
  const view = render(<LeadReminderEmailSetting key="old-owner" />);
  view.rerender(<LeadReminderEmailSetting key="new-owner" />);
  await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeDisabled());
  await act(async () => finishOld(response(true)));
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});

import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import LeadDrawer from "./LeadDrawer";

test("does not claim a reminder was saved when the parent persistence rejects", async () => {
  const onUpdateLead = jest.fn().mockRejectedValue(new Error("storage unavailable"));
  const warn = jest.spyOn(console, "warn").mockImplementation(() => {});

  render(
    <LeadDrawer
      lead={{ id: "lead-1", name: "Jamie", email: "jamie@example.com", reminders: [] }}
      onClose={jest.fn()}
      onEdit={jest.fn()}
      onDelete={jest.fn()}
      onUpdateLead={onUpdateLead}
    />
  );

  fireEvent.click(screen.getByRole("tab", { name: "Reminders" }));
  fireEvent.change(screen.getByPlaceholderText(/Add a reminder/i), {
    target: { value: "Call tomorrow" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));

  await waitFor(() => expect(onUpdateLead).toHaveBeenCalledTimes(1));
  expect(await screen.findByText("Could not save reminders")).toBeInTheDocument();
  expect(screen.queryByText("Reminders saved")).not.toBeInTheDocument();
  warn.mockRestore();
});

test("asks before overriding a customer's own unsubscribe", async () => {
  const onUpdateLead = jest.fn().mockResolvedValue(undefined);
  const confirm = jest.spyOn(window, "confirm").mockReturnValue(false);
  const lead = {
    id: "lead-1",
    name: "Jamie",
    email: "jamie@example.com",
    email_opt_out: true,
    email_consent_status: "withdrawn",
    email_consent_source: "customer_unsubscribe_link",
    email_consent_updated_at: "2026-10-01T12:00:00+00:00",
  };

  render(
    <LeadDrawer
      lead={lead}
      onClose={jest.fn()}
      onEdit={jest.fn()}
      onDelete={jest.fn()}
      onUpdateLead={onUpdateLead}
    />
  );

  expect(screen.getByText(/unsubscribed using the email link/i)).toBeInTheDocument();
  const select = screen.getByLabelText("Follow-up email status");
  fireEvent.change(select, { target: { value: "confirmed" } });
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(onUpdateLead).not.toHaveBeenCalled();
  expect(select).toHaveValue("withdrawn");

  confirm.mockReturnValue(true);
  fireEvent.change(select, { target: { value: "confirmed" } });
  await waitFor(() => expect(onUpdateLead).toHaveBeenCalledTimes(1));
  confirm.mockRestore();
});

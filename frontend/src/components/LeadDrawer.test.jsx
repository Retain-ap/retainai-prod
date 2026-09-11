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

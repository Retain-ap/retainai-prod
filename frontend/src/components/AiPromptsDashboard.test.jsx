import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AiPromptsDashboard from "./AiPromptsDashboard";

const lead = { id: "lead-1", name: "Jordan", email: "jordan@example.com" };

function prepareDraft(onSendAIPromptEmail) {
  render(
    <AiPromptsDashboard
      leads={[lead]}
      user={{ email: "owner@example.com", business: "Acme" }}
      onSendAIPromptEmail={onSendAIPromptEmail}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
  fireEvent.change(
    screen.getByPlaceholderText("Your generated message will appear here. You can also write your own."),
    { target: { value: "Thanks for visiting us." } }
  );
  fireEvent.click(screen.getByRole("button", { name: /Send email/ }));
}

test("does not report success when the delivery callback resolves false", async () => {
  const send = jest.fn().mockResolvedValue(false);
  prepareDraft(send);

  expect(await screen.findByText("Message could not be sent.")).toBeInTheDocument();
  expect(screen.queryByText("Message sent successfully.")).not.toBeInTheDocument();
});

test("reports success only after the delivery callback confirms success", async () => {
  const send = jest.fn().mockResolvedValue(true);
  prepareDraft(send);

  expect(await screen.findByText("Message sent successfully.")).toBeInTheDocument();
  await waitFor(() => expect(send).toHaveBeenCalledWith(
    lead,
    "Thanks for visiting us.",
    "A quick follow-up for Jordan",
    "followup"
  ));
});

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
    "Checking in, Jordan",
    "followup"
  ));
});

describe("business name required before customer messages", () => {
  const refusal = {
    ok: false,
    code: "business_profile_required",
    settings_path: "/app?tab=profile",
    error: "Add your business name in Settings before creating or sending customer messages.",
  };
  const draftBox = () => screen.getByPlaceholderText("Your generated message will appear here. You can also write your own.");

  afterEach(() => {
    sessionStorage.clear();
    delete global.fetch;
  });

  test("a refused send keeps the draft and offers Settings, holding the draft for the return", async () => {
    const send = jest.fn().mockRejectedValue(Object.assign(new Error(refusal.error), { code: refusal.code }));
    const openSettings = jest.fn();
    render(<AiPromptsDashboard leads={[lead]} user={{ email: "owner@example.com" }} onSendAIPromptEmail={send} onOpenBusinessSettings={openSettings} />);
    fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
    fireEvent.change(draftBox(), { target: { value: "Thanks for visiting us." } });
    fireEvent.click(screen.getByRole("button", { name: /Send email/ }));

    const action = await screen.findByRole("link", { name: "Add business name in Settings" });
    expect(screen.getByRole("alert")).toHaveTextContent(refusal.error);
    expect(action).toHaveAttribute("href", "/app?tab=profile");
    expect(draftBox()).toHaveValue("Thanks for visiting us.");
    expect(screen.queryByText("Message sent successfully.")).not.toBeInTheDocument();

    fireEvent.click(action);
    expect(openSettings).toHaveBeenCalledTimes(1);
    expect(JSON.parse(sessionStorage.getItem("retainai:held-draft:ai-studio"))).toMatchObject({ leadId: "lead-1", draft: "Thanks for visiting us." });
  });

  test("a refused draft request shows the Settings action and leaves an existing draft alone", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 409, json: async () => refusal });
    render(<AiPromptsDashboard leads={[lead]} user={{ email: "owner@example.com" }} />);
    fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
    fireEvent.change(draftBox(), { target: { value: "My own words." } });
    fireEvent.click(screen.getByRole("button", { name: /Generate another version/ }));

    expect(await screen.findByRole("link", { name: "Add business name in Settings" })).toHaveAttribute("href", "/app?tab=profile");
    expect(draftBox()).toHaveValue("My own words.");
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  test("other errors do not show the Settings action", async () => {
    const send = jest.fn().mockRejectedValue(new Error("Message could not be sent."));
    prepareDraft(send);
    expect(await screen.findByText("Message could not be sent.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add business name in Settings" })).not.toBeInTheDocument();
  });

  test("a held draft comes back to the same customer after Settings", async () => {
    sessionStorage.setItem("retainai:held-draft:ai-studio", JSON.stringify({ leadId: "lead-1", playbook: "reengage", tone: "Concise", length: "Short", context: "Visited in May.", draft: "Held words." }));
    render(<AiPromptsDashboard leads={[lead]} user={{ email: "owner@example.com", business: "Acme" }} />);
    expect(await screen.findByDisplayValue("Held words.")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Visited in May.")).toBeInTheDocument();
    expect(screen.getByText("Writing for")).toBeInTheDocument();
    await waitFor(() => expect(sessionStorage.getItem("retainai:held-draft:ai-studio")).toBeNull());
  });
});

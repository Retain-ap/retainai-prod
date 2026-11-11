import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import AiPromptsDashboard from "./AiPromptsDashboard";
import { heldDraftScope, holdDraft } from "../businessProfile";

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
  const owner = { email: "owner@example.com" };
  const ownerScope = () => heldDraftScope("ai-studio", owner);
  const draftBox = () => screen.getByPlaceholderText("Your generated message will appear here. You can also write your own.");
  const holdFor = (user, fields = {}) => holdDraft(heldDraftScope("ai-studio", user), {
    leadId: "lead-1", playbook: "reengage", tone: "Concise", length: "Short", context: "Visited in May.", draft: "Held words.", ...fields,
  });

  afterEach(() => {
    sessionStorage.clear();
    delete global.fetch;
  });

  test("a refused send keeps the draft, clears Sending… and holds the draft for this account", async () => {
    const send = jest.fn().mockRejectedValue(Object.assign(new Error(refusal.error), { code: refusal.code }));
    const openSettings = jest.fn();
    render(<AiPromptsDashboard leads={[lead]} user={owner} onSendAIPromptEmail={send} onOpenBusinessSettings={openSettings} />);
    fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
    fireEvent.change(draftBox(), { target: { value: "Thanks for visiting us." } });
    fireEvent.click(screen.getByRole("button", { name: /Send email/ }));

    const action = await screen.findByRole("link", { name: "Add business name in Settings" });
    expect(screen.getByRole("alert")).toHaveTextContent(refusal.error);
    expect(action).toHaveAttribute("href", "/app?tab=profile");
    expect(draftBox()).toHaveValue("Thanks for visiting us.");
    expect(screen.queryByText("Sending…")).not.toBeInTheDocument();
    expect(screen.queryByText("Message sent successfully.")).not.toBeInTheDocument();

    fireEvent.click(action);
    expect(openSettings).toHaveBeenCalledTimes(1);
    expect(Object.keys(sessionStorage)).toEqual([ownerScope()]);
    expect(JSON.parse(sessionStorage.getItem(ownerScope()))).toMatchObject({ leadId: "lead-1", draft: "Thanks for visiting us." });
  });

  test("a draft edited after the refusal is held as last typed", async () => {
    const send = jest.fn().mockRejectedValue(Object.assign(new Error(refusal.error), { code: refusal.code }));
    render(<AiPromptsDashboard leads={[lead]} user={owner} onSendAIPromptEmail={send} onOpenBusinessSettings={jest.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
    fireEvent.change(draftBox(), { target: { value: "First words" } });
    fireEvent.click(screen.getByRole("button", { name: /Send email/ }));
    const action = await screen.findByRole("link", { name: "Add business name in Settings" });
    fireEvent.change(draftBox(), { target: { value: "First words, then an edit" } });
    fireEvent.click(action);
    expect(JSON.parse(sessionStorage.getItem(ownerScope()))).toMatchObject({ draft: "First words, then an edit" });
    expect(send).toHaveBeenCalledTimes(1);
  });

  test("a refused draft request shows the Settings action and leaves an existing draft alone", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 409, json: async () => refusal });
    render(<AiPromptsDashboard leads={[lead]} user={owner} />);
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

  test("a held draft waits for customers to load, then returns once and is removed", async () => {
    holdFor(owner);
    const { rerender } = render(<AiPromptsDashboard leads={[]} user={owner} />);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); });
    expect(sessionStorage.getItem(ownerScope())).not.toBeNull();

    rerender(<AiPromptsDashboard leads={[lead]} user={owner} />);
    expect(await screen.findByDisplayValue("Held words.")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Visited in May.")).toBeInTheDocument();
    expect(screen.getByText("Writing for")).toBeInTheDocument();
    expect(sessionStorage.getItem(ownerScope())).toBeNull();
  });

  test.each([
    ["another person", { email: "other@example.com" }],
    ["the same person in another workspace", { email: "owner@example.com", org_id: "second@example.com" }],
    ["an unknown account", {}],
  ])("%s never receives a held draft for the same customer id", async (_label, other) => {
    holdFor(owner);
    render(<AiPromptsDashboard leads={[lead]} user={other} />);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); });
    expect(screen.queryByDisplayValue("Held words.")).not.toBeInTheDocument();
    expect(screen.queryByText("Writing for")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(ownerScope())).not.toBeNull();
  });

  test("an unknown account holds nothing", async () => {
    const send = jest.fn().mockRejectedValue(Object.assign(new Error(refusal.error), { code: refusal.code }));
    render(<AiPromptsDashboard leads={[lead]} user={{}} onSendAIPromptEmail={send} onOpenBusinessSettings={jest.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
    fireEvent.change(draftBox(), { target: { value: "Private words." } });
    fireEvent.click(screen.getByRole("button", { name: /Send email/ }));
    fireEvent.click(await screen.findByRole("link", { name: "Add business name in Settings" }));
    expect(sessionStorage.length).toBe(0);
  });
});

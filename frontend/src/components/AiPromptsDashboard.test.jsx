import { vi } from "vitest";
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
  const send = vi.fn().mockResolvedValue(false);
  prepareDraft(send);

  expect(await screen.findByText("Message could not be sent.")).toBeInTheDocument();
  expect(screen.queryByText("Message sent successfully.")).not.toBeInTheDocument();
});

test("reports success only after the delivery callback confirms success", async () => {
  const send = vi.fn().mockResolvedValue(true);
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
    const send = vi.fn().mockRejectedValue(Object.assign(new Error(refusal.error), { code: refusal.code }));
    const openSettings = vi.fn();
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
    const send = vi.fn().mockRejectedValue(Object.assign(new Error(refusal.error), { code: refusal.code }));
    render(<AiPromptsDashboard leads={[lead]} user={owner} onSendAIPromptEmail={send} onOpenBusinessSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
    fireEvent.change(draftBox(), { target: { value: "First words" } });
    fireEvent.click(screen.getByRole("button", { name: /Send email/ }));
    const action = await screen.findByRole("link", { name: "Add business name in Settings" });
    fireEvent.change(draftBox(), { target: { value: "First words, then an edit" } });
    fireEvent.click(action);
    expect(JSON.parse(sessionStorage.getItem(ownerScope()))).toMatchObject({ draft: "First words, then an edit" });
    expect(send).toHaveBeenCalledTimes(1);
  });

  test("a 4500-character draft survives Settings whole, and the box allows the 5000 the send accepts", async () => {
    const long = "Thank you for visiting. ".repeat(187) + "Thanks again";
    expect(long).toHaveLength(4500);
    const send = vi.fn().mockRejectedValue(Object.assign(new Error(refusal.error), { code: refusal.code }));
    const { unmount } = render(<AiPromptsDashboard leads={[lead]} user={owner} onSendAIPromptEmail={send} onOpenBusinessSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
    expect(draftBox()).toHaveAttribute("maxLength", "5000");
    fireEvent.change(draftBox(), { target: { value: long } });
    expect(screen.getByText("4500/5000")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Send email/ }));
    fireEvent.click(await screen.findByRole("link", { name: "Add business name in Settings" }));
    expect(send).toHaveBeenCalledWith(lead, long.trim(), "Checking in, Jordan", "followup");
    unmount();

    render(<AiPromptsDashboard leads={[lead]} user={owner} />);
    expect((await screen.findByText("Writing for")) && draftBox()).toHaveValue(long);
    expect(sessionStorage.getItem(ownerScope())).toBeNull();
  });

  test("a draft over the send limit is refused visibly instead of being cut short", async () => {
    const send = vi.fn();
    render(<AiPromptsDashboard leads={[lead]} user={owner} onSendAIPromptEmail={send} />);
    fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
    fireEvent.change(draftBox(), { target: { value: "x".repeat(5001) } });
    fireEvent.click(screen.getByRole("button", { name: /Send email/ }));
    expect(await screen.findByText("Shorten the message to 5000 characters or fewer before sending.")).toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
    expect(draftBox().value).toHaveLength(5001);
  });

  test("a refused draft request shows the Settings action and leaves an existing draft alone", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => refusal });
    render(<AiPromptsDashboard leads={[lead]} user={owner} />);
    fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
    fireEvent.change(draftBox(), { target: { value: "My own words." } });
    fireEvent.click(screen.getByRole("button", { name: /Generate another version/ }));

    expect(await screen.findByRole("link", { name: "Add business name in Settings" })).toHaveAttribute("href", "/app?tab=profile");
    expect(draftBox()).toHaveValue("My own words.");
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  test("other errors do not show the Settings action", async () => {
    const send = vi.fn().mockRejectedValue(new Error("Message could not be sent."));
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
    const send = vi.fn().mockRejectedValue(Object.assign(new Error(refusal.error), { code: refusal.code }));
    render(<AiPromptsDashboard leads={[lead]} user={{}} onSendAIPromptEmail={send} onOpenBusinessSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
    fireEvent.change(draftBox(), { target: { value: "Private words." } });
    fireEvent.click(screen.getByRole("button", { name: /Send email/ }));
    fireEvent.click(await screen.findByRole("link", { name: "Add business name in Settings" }));
    expect(sessionStorage.length).toBe(0);
  });
});

describe("opening from the rebooking list", () => {
  afterEach(() => {
    sessionStorage.clear();
    delete global.fetch;
  });

  test("selects the customer with the follow-up playbook and factual context, and generates or sends nothing", async () => {
    global.fetch = vi.fn();
    const applied = vi.fn();
    const send = vi.fn();
    render(<AiPromptsDashboard leads={[lead]} user={{ email: "owner@example.com" }} onSendAIPromptEmail={send}
      initialFocus={{ leadId: "lead-1", playbook: "followup", context: "Due to rebook: last completed visit Oct 1; usually every 30 days." }} onFocusApplied={applied} />);
    expect(await screen.findByText("Writing for")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Due to rebook: last completed visit Oct 1; usually every 30 days.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Follow-up/ })).toHaveClass("active");
    expect(applied).toHaveBeenCalled();
    expect(global.fetch).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });

  test("a focus request for a customer who is gone is cleared without selecting anyone", async () => {
    const applied = vi.fn();
    render(<AiPromptsDashboard leads={[lead]} user={{ email: "owner@example.com" }} initialFocus={{ leadId: "gone", playbook: "followup", context: "x" }} onFocusApplied={applied} />);
    await waitFor(() => expect(applied).toHaveBeenCalled());
    expect(screen.queryByText("Writing for")).not.toBeInTheDocument();
  });

  test("an explicit focus leaves a held business-name draft stored for later", async () => {
    holdDraft(heldDraftScope("ai-studio", { email: "owner@example.com" }), { leadId: "lead-1", draft: "Held words.", playbook: "reengage" });
    render(<AiPromptsDashboard leads={[lead]} user={{ email: "owner@example.com" }} initialFocus={{ leadId: "lead-1", playbook: "followup", context: "Due to rebook." }} onFocusApplied={vi.fn()} />);
    expect(await screen.findByDisplayValue("Due to rebook.")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Held words.")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(heldDraftScope("ai-studio", { email: "owner@example.com" }))).not.toBeNull();
  });
});

describe("opening from the rebooking list with the dashboard clearing the request", () => {
  afterEach(() => sessionStorage.clear());

  function Host({ focus }) {
    // Mirrors CrmDashboard: the request is cleared once AI Studio applies it.
    const [initialFocus, setInitialFocus] = React.useState(focus);
    return <AiPromptsDashboard leads={[lead, { id: "lead-2", name: "Riley", email: "riley@example.com" }]} user={{ email: "owner@example.com" }}
      initialFocus={initialFocus} onFocusApplied={() => setInitialFocus(null)} />;
  }

  test("an older held draft never replaces the customer and context just requested", async () => {
    const scope = heldDraftScope("ai-studio", { email: "owner@example.com" });
    holdDraft(scope, { leadId: "lead-2", draft: "Older held words.", context: "Older context", playbook: "reengage" });
    render(<Host focus={{ leadId: "lead-1", playbook: "followup", context: "Due to rebook: last completed visit Oct 1." }} />);
    expect(await screen.findByDisplayValue("Due to rebook: last completed visit Oct 1.")).toBeInTheDocument();
    // Let the cleared request re-run every effect.
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    expect(screen.getByDisplayValue("Due to rebook: last completed visit Oct 1.")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Older held words.")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("Older context")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Follow-up/ })).toHaveClass("active");
    expect(sessionStorage.getItem(scope)).not.toBeNull();
  });

  test("without a request, a held draft is still restored as before", async () => {
    const scope = heldDraftScope("ai-studio", { email: "owner@example.com" });
    holdDraft(scope, { leadId: "lead-2", draft: "Held words.", playbook: "reengage" });
    render(<Host focus={null} />);
    expect(await screen.findByDisplayValue("Held words.")).toBeInTheDocument();
  });
});

test("a request for a customer who was removed shows that, and an unrelated held draft does not appear", async () => {
  const scope = heldDraftScope("ai-studio", { email: "owner@example.com" });
  holdDraft(scope, { leadId: "lead-1", draft: "Unrelated held words.", playbook: "reengage" });
  function Host() {
    const [initialFocus, setInitialFocus] = React.useState({ leadId: "deleted-customer", playbook: "followup", context: "Due to rebook." });
    return <AiPromptsDashboard leads={[lead]} user={{ email: "owner@example.com" }} initialFocus={initialFocus} onFocusApplied={() => setInitialFocus(null)} />;
  }
  render(<Host />);
  expect(await screen.findByRole("heading", { name: "That customer is no longer in your contacts" })).toBeInTheDocument();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  expect(screen.queryByText("Writing for")).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue("Unrelated held words.")).not.toBeInTheDocument();
  expect(sessionStorage.getItem(scope)).not.toBeNull();
  // Choosing a customer clears the notice.
  fireEvent.click(screen.getByRole("button", { name: /Jordan/ }));
  expect(screen.queryByText("That customer is no longer in your contacts")).not.toBeInTheDocument();
  sessionStorage.clear();
});

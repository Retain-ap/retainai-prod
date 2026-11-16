import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Automations from "./Automations";
import api from "./AutomationsService";

jest.mock("./AutomationsService", () => ({
  __esModule: true,
  default: Object.fromEntries([
    "getTemplates", "getProfile", "getWATemplates", "getHealth", "listFlows",
    "getHistory", "getDashboard", "createFlow", "updateFlow", "enableFlow",
    "dryRun", "executeNow",
  ].map((name) => [name, jest.fn()])),
}));

const user = { email: "owner@example.com" };
const copy = (value) => JSON.parse(JSON.stringify(value));
const savedFlow = (overrides = {}) => ({
  id: "flow-1", owner: user.email, name: "Follow up", enabled: false,
  trigger: { type: "no_reply", days: 3 },
  steps: [{ type: "send_email", subject: "Checking in", body: "Hello {{lead.first_name}}" }],
  caps: { per_lead_per_day: 2, respect_quiet_hours: true },
  auto_stop_on_reply: true, ...overrides,
});
let flows;

beforeEach(() => {
  jest.resetAllMocks();
  localStorage.clear();
  flows = [];
  api.getTemplates.mockResolvedValue({ templates: [] });
  api.getProfile.mockResolvedValue({ profile: {} });
  api.getWATemplates.mockResolvedValue({ templates: [] });
  api.getHealth.mockResolvedValue({ ok: true });
  api.getHistory.mockResolvedValue({ runs: [] });
  api.getDashboard.mockResolvedValue({});
  api.listFlows.mockImplementation(async () => ({ flows: copy(flows) }));
  api.createFlow.mockImplementation(async (_, flow) => {
    const saved = { ...copy(flow), id: `new-${flows.length + 1}` };
    flows.push(saved);
    return { flow: copy(saved) };
  });
  api.updateFlow.mockImplementation(async (_, id, flow) => {
    const saved = { ...copy(flow), id };
    flows = flows.map((item) => item.id === id ? saved : item);
    return { flow: copy(saved) };
  });
  api.enableFlow.mockImplementation(async (_, id, enabled) => {
    const saved = { ...flows.find((item) => item.id === id), enabled };
    flows = flows.map((item) => item.id === id ? saved : item);
    return { flow: copy(saved) };
  });
  api.dryRun.mockResolvedValue({ would: [] });
  api.executeNow.mockResolvedValue({ did: [] });
});

afterEach(() => jest.restoreAllMocks());

async function openNew() {
  render(<Automations user={user} />);
  fireEvent.click(await screen.findByRole("button", { name: "New Automation" }));
}

async function openSaved(flow = savedFlow()) {
  flows = [copy(flow)];
  render(<Automations user={user} />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
}

function addStep(label) {
  fireEvent.click(screen.getByRole("button", { name: "Add step" }));
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label} `) }));
}

test("saves an incomplete draft without publishing or executing it", async () => {
  await openNew();
  fireEvent.change(screen.getByLabelText("Automation name"), { target: { value: "Later" } });
  fireEvent.click(screen.getByRole("button", { name: "Publish", exact: true }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Choose a trigger. Add at least one step.");
  expect(api.createFlow).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(api.createFlow).toHaveBeenCalledTimes(1));
  expect(api.createFlow.mock.calls[0][1]).toMatchObject({ name: "Later", enabled: false, steps: [] });
  expect(await screen.findByRole("status")).toHaveTextContent("Draft saved");
  expect(localStorage.getItem("retainai:onboarding-playbook")).toBeNull();
  expect(api.enableFlow).not.toHaveBeenCalled();
  expect(api.executeNow).not.toHaveBeenCalled();
});

test("publishes a new workflow once and marks onboarding only after the write succeeds", async () => {
  await openNew();
  fireEvent.click(screen.getByRole("button", { name: "New customer", exact: true }));
  addStep("Send email");
  fireEvent.change(screen.getByLabelText("Email subject"), { target: { value: "Welcome" } });
  fireEvent.change(screen.getByLabelText("Email body"), { target: { value: "Hello {{lead.first_name}}" } });
  let finish;
  api.createFlow.mockImplementationOnce((_, flow) => new Promise((resolve) => {
    finish = () => { flows = [{ ...copy(flow), id: "new-1" }]; resolve({ flow: flows[0] }); };
  }));
  fireEvent.click(screen.getByRole("button", { name: "Publish", exact: true }));
  expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
  expect(localStorage.getItem("retainai:onboarding-playbook")).toBeNull();
  finish();
  await screen.findByRole("button", { name: "Pause Untitled Automation" });
  expect(api.createFlow).toHaveBeenCalledTimes(1);
  expect(api.createFlow.mock.calls[0][1]).toMatchObject({
    enabled: true, trigger: { type: "new_lead", within_hours: 24 },
    steps: [{ type: "send_email", subject: "Welcome", body: "Hello {{lead.first_name}}" }],
  });
  expect(localStorage.getItem("retainai:onboarding-playbook")).toBe("1");
  expect(api.executeNow).not.toHaveBeenCalled();
});

test.each([
  ["No reply", "How many days with no reply?", "7", { type: "no_reply", days: 7 }],
  ["New customer", "Treat as a new customer for how many hours?", "48", { type: "new_lead", within_hours: 48 }],
  ["Appointment no-show", null, null, { type: "appointment_no_show" }],
  ["Appointment completed", "Run for appointments completed within how many days?", "5", { type: "appointment_completed", within_days: 5 }],
])("preserves the %s trigger configuration when saving", async (label, field, value, trigger) => {
  await openNew();
  fireEvent.click(screen.getByRole("button", { name: label, exact: true }));
  if (field) fireEvent.change(screen.getByLabelText(field), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(api.createFlow).toHaveBeenCalledTimes(1));
  expect(api.createFlow.mock.calls[0][1].trigger).toEqual(trigger);
});

test("offers every action and retains nested data while reordering and editing a saved workflow", async () => {
  const original = savedFlow({ steps: [
    { type: "wait", days: 1, hours: 2, minutes: 3 },
    { type: "if_no_reply", within_days: 4, then: [
      { type: "if_no_booking", within_days: 5, then: [{ type: "send_email", subject: "Nested", body: "Keep me" }] },
      { type: "send_whatsapp", text: "Hello", template: { name: "welcome", language: "en_US", params: ["{{lead.first_name}}"] } },
    ] },
    { type: "ai_draft", purpose: "follow_up" },
    { type: "push_owner", title: "Call", message: "Remember" },
    { type: "add_tag", tag: "Follow-up" },
  ] });
  await openSaved(original);
  fireEvent.click(screen.getByRole("button", { name: "Add step" }));
  for (const label of ["Send email", "Send WhatsApp", "Wait", "Draft with AI", "Check for no reply", "Check for no booking", "Notify owner", "Add tag"]) {
    expect(screen.getByRole("button", { name: new RegExp(`^${label} `) })).toBeInTheDocument();
  }
  fireEvent.click(screen.getByRole("button", { name: /^Edit step 2:/ }));
  fireEvent.click(screen.getByRole("button", { name: "Move step up" }));
  fireEvent.change(screen.getByLabelText("Email subject"), { target: { value: "Updated nested subject" } });
  fireEvent.click(screen.getByRole("button", { name: /^Sending rules/ }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Stop if the customer replies" }));
  fireEvent.change(screen.getByLabelText("Maximum sends per customer each day"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(api.updateFlow).toHaveBeenCalledTimes(1));
  const submitted = api.updateFlow.mock.calls[0][2];
  const branch = copy(original.steps[1]);
  branch.then[0].then[0].subject = "Updated nested subject";
  expect(submitted.steps).toEqual([branch, original.steps[0], ...original.steps.slice(2)]);
  expect(submitted).toMatchObject({ id: original.id, enabled: false, auto_stop_on_reply: false, caps: { per_lead_per_day: 3, respect_quiet_hours: true } });
  expect(api.createFlow).not.toHaveBeenCalled();
});

test("removes the selected step without removing neighboring or nested actions", async () => {
  const branch = { type: "if_no_reply", within_days: 2, then: [{ type: "add_tag", tag: "Waiting" }] };
  await openSaved(savedFlow({ steps: [{ type: "wait", days: 1 }, branch] }));
  fireEvent.click(screen.getByRole("button", { name: /^Edit step 1:/ }));
  fireEvent.click(screen.getByRole("button", { name: "Remove", exact: true }));
  expect(screen.getByRole("button", { name: /^Edit step 1: If no reply/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(api.updateFlow).toHaveBeenCalledTimes(1));
  expect(api.updateFlow.mock.calls[0][2].steps).toEqual([branch]);
});

test("pauses the saved active workflow without publishing open edits, then saves those edits as a draft", async () => {
  await openSaved(savedFlow({ enabled: true }));
  fireEvent.change(screen.getByLabelText("Automation name"), { target: { value: "Unsaved revision" } });
  expect(screen.getByRole("button", { name: "Save and publish" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Pause", exact: true }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled());
  expect(api.enableFlow).toHaveBeenCalledWith(user.email, "flow-1", false);
  expect(api.updateFlow).not.toHaveBeenCalled();
  expect(flows[0]).toMatchObject({ name: "Follow up", enabled: false });
  expect(screen.getByLabelText("Automation name")).toHaveValue("Unsaved revision");
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(api.updateFlow).toHaveBeenCalledTimes(1));
  expect(api.updateFlow.mock.calls[0][2]).toMatchObject({ name: "Unsaved revision", enabled: false });
});

test("save and publish updates the existing active workflow in one write", async () => {
  await openSaved(savedFlow({ enabled: true }));
  fireEvent.change(screen.getByLabelText("Automation name"), { target: { value: "Published revision" } });
  fireEvent.click(screen.getByRole("button", { name: "Save and publish" }));
  await screen.findByRole("button", { name: "Pause Published revision" });
  expect(api.updateFlow).toHaveBeenCalledWith(user.email, "flow-1", expect.objectContaining({ enabled: true, name: "Published revision" }));
  expect(api.enableFlow).not.toHaveBeenCalled();
  expect(api.createFlow).not.toHaveBeenCalled();
});

test("failed publication keeps edits and does not mark onboarding complete", async () => {
  await openSaved();
  api.updateFlow.mockRejectedValueOnce(new Error("Write unavailable"));
  fireEvent.change(screen.getByLabelText("Automation name"), { target: { value: "Keep my edit" } });
  fireEvent.click(screen.getByRole("button", { name: "Publish", exact: true }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Write unavailable");
  expect(screen.getByLabelText("Automation name")).toHaveValue("Keep my edit");
  expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled();
  expect(localStorage.getItem("retainai:onboarding-playbook")).toBeNull();
});

test("failed pause leaves the active state and unsaved edits intact", async () => {
  await openSaved(savedFlow({ enabled: true }));
  api.enableFlow.mockRejectedValueOnce(new Error("Pause unavailable"));
  fireEvent.change(screen.getByLabelText("Automation name"), { target: { value: "Keep my edit" } });
  fireEvent.click(screen.getByRole("button", { name: "Pause", exact: true }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Pause unavailable");
  expect(screen.getByLabelText("Automation name")).toHaveValue("Keep my edit");
  expect(screen.getByRole("button", { name: "Save and publish" })).toBeEnabled();
  expect(localStorage.getItem("retainai:onboarding-playbook")).toBe("1");
  expect(api.updateFlow).not.toHaveBeenCalled();
});

test("a failed list refresh after creation retains the saved ID and avoids duplicate creation", async () => {
  await openNew();
  api.listFlows.mockRejectedValueOnce(new Error("Refresh unavailable"));
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Automation saved. The list could not refresh");
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText("Automation name"), { target: { value: "Updated draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(api.updateFlow).toHaveBeenCalledTimes(1));
  expect(api.createFlow).toHaveBeenCalledTimes(1);
  expect(api.updateFlow.mock.calls[0][1]).toBe("new-1");
});

test("nested WhatsApp template validation blocks publication but allows saving a draft", async () => {
  await openSaved(savedFlow({ steps: [{ type: "if_no_reply", within_days: 2, then: [{ type: "send_whatsapp", text: "Hello" }] }] }));
  fireEvent.click(screen.getByRole("button", { name: "Publish", exact: true }));
  expect(await screen.findByRole("alert")).toHaveTextContent("step 1 → step 1: select an approved WhatsApp template fallback");
  expect(api.updateFlow).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(api.updateFlow).toHaveBeenCalledTimes(1));
  expect(api.updateFlow.mock.calls[0][2].enabled).toBe(false);
});

test("list publication and pausing use the saved status endpoint", async () => {
  flows = [savedFlow()];
  render(<Automations user={user} />);
  fireEvent.click(await screen.findByRole("button", { name: "Publish Follow up" }));
  fireEvent.click(await screen.findByRole("button", { name: "Pause Follow up" }));
  await screen.findByRole("button", { name: "Publish Follow up" });
  expect(api.enableFlow.mock.calls).toEqual([[user.email, "flow-1", true], [user.email, "flow-1", false]]);
  expect(api.updateFlow).not.toHaveBeenCalled();
});

test("preview remains non-sending and live testing still requires confirmation", async () => {
  await openSaved();
  fireEvent.click(screen.getByText("Test this workflow"));
  fireEvent.change(screen.getByLabelText("Test customer email"), { target: { value: "customer@example.test" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview", exact: true }));
  await screen.findByText("No actions would run.");
  expect(api.dryRun).toHaveBeenCalledWith(user.email, expect.objectContaining({ id: "flow-1" }), { lead_email: "customer@example.test" });
  expect(api.executeNow).not.toHaveBeenCalled();
  const confirm = jest.spyOn(window, "confirm").mockReturnValue(false);
  fireEvent.click(screen.getByRole("button", { name: "Send Live Test" }));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining("customer@example.test"));
  expect(api.executeNow).not.toHaveBeenCalled();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Send Live Test" }));
  await screen.findByText("Nothing executed.");
  expect(api.executeNow).toHaveBeenCalledWith(user.email, expect.objectContaining({ id: "flow-1" }), {
    lead_email: "customer@example.test", ignore_waits: true, ignore_quiet_hours: true, bypass_rate_limits: true,
  });
  expect(api.updateFlow).not.toHaveBeenCalled();
});

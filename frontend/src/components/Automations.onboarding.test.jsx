import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import Automations from "./Automations";
import api from "./AutomationsService";

jest.mock("./AutomationsService", () => ({
  __esModule: true,
  default: {
    getTemplates: jest.fn(),
    getProfile: jest.fn(),
    getWATemplates: jest.fn(),
    getHealth: jest.fn(),
    listFlows: jest.fn(),
    getHistory: jest.fn(),
    getDashboard: jest.fn(),
  },
}));

const user = { email: "owner@example.com" };
const template = { id: "t1", name: "Smart rebooking follow-up", description: "Rebook customers", steps: [], trigger: { type: "no_reply", days: 30 } };

beforeEach(() => {
  localStorage.clear();
  api.getTemplates.mockResolvedValue({ templates: [template] });
  api.getProfile.mockResolvedValue({ profile: {} });
  api.getWATemplates.mockResolvedValue({ templates: [] });
  api.getHealth.mockResolvedValue({ ok: true });
  api.getHistory.mockResolvedValue({ runs: [] });
  api.getDashboard.mockResolvedValue({});
});

test("opening a playbook does not mark 'Activate your first playbook' as done", async () => {
  localStorage.setItem("retainai:selected-playbook", "rebook");
  localStorage.setItem("retainai:onboarding-playbook", "1"); // left over from the old behaviour
  api.listFlows.mockResolvedValue({ flows: [] });
  render(<Automations user={user} />);
  await waitFor(() => expect(api.listFlows).toHaveBeenCalled());
  await waitFor(() => expect(localStorage.getItem("retainai:selected-playbook")).toBeNull());
  expect(localStorage.getItem("retainai:onboarding-playbook")).toBeNull();
  expect(await screen.findByDisplayValue(/Smart rebooking/)).toBeInTheDocument(); // opened for review only
});

test("the step is done while a saved automation is active", async () => {
  api.listFlows.mockResolvedValue({ flows: [{ id: "f1", name: "Rebook", enabled: true, steps: [], trigger: { type: "no_reply", days: 30 } }] });
  render(<Automations user={user} />);
  await waitFor(() => expect(localStorage.getItem("retainai:onboarding-playbook")).toBe("1"));
});

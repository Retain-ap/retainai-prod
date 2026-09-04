import React, { useMemo, useState } from "react";
import { FaCheckCircle, FaChevronRight, FaRocket } from "react-icons/fa";
import { getWorkspaceCapabilities } from "../workspaceIdentity";

export default function OnboardingGuide({ user, leads = [], setSection, openImports }) {
  const capabilities = getWorkspaceCapabilities(user);
  const storageKey = `retainai:onboarding-dismissed:${user?.email || "user"}`;
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(storageKey) === "1"
  );
  const steps = useMemo(
    () => [
      ...(capabilities.canEditBusiness ? [{
        label: "Complete your business profile",
        done: Boolean(user?.business && user?.businessType),
        action: () => setSection("settings"),
      }] : []),
      {
        label: "Import your customer contacts",
        done: leads.length > 0,
        action: openImports,
      },
      ...(capabilities.canEditBusiness ? [{
        label: "Connect WhatsApp Business",
        done: Boolean(user?.whatsapp_connected || user?.whatsapp),
        action: () => setSection("settings"),
      }] : []),
      {
        label: "Send a WhatsApp test message",
        done: localStorage.getItem("retainai:onboarding-test-message") === "1",
        action: () => setSection("messages"),
      },
      ...(capabilities.canEditBusiness ? [{
        label: "Connect your calendar",
        done: Boolean(user?.gcal_connected || user?.google_refresh_token),
        action: () => setSection("settings"),
      }] : []),
      {
        label: "Review today’s retention briefing",
        done: leads.length > 0,
        action: () => setSection("overview"),
      },
      {
        label: "Activate your first playbook",
        done: localStorage.getItem("retainai:onboarding-playbook") === "1",
        action: () => setSection("automations"),
      },
      ...(capabilities.canInviteTeam ? [{
        label: "Invite a teammate",
        done: localStorage.getItem("retainai:onboarding-team") === "1",
        action: () => window.RetainAI?.openTeam?.(),
      }] : []),
    ],
    [
      capabilities.canEditBusiness,
      capabilities.canInviteTeam,
      leads.length,
      openImports,
      setSection,
      user,
    ]
  );
  const complete = steps.filter((step) => step.done).length;
  if (dismissed || complete === steps.length) return null;

  return (
    <aside className="onboarding-guide">
      <div className="onboarding-guide-head">
        <div>
          <span><FaRocket /> Guided setup</span>
          <strong>{complete} of {steps.length} complete</strong>
        </div>
        <button
          type="button"
          onClick={() => {
            localStorage.setItem(storageKey, "1");
            setDismissed(true);
          }}
        >
          Hide
        </button>
      </div>
      <div className="onboarding-progress">
        <span style={{ width: `${(complete / steps.length) * 100}%` }} />
      </div>
      {steps.map((step) => (
        <button
          type="button"
          className={step.done ? "done" : ""}
          onClick={step.action}
          key={step.label}
        >
          <FaCheckCircle />
          <span>{step.label}</span>
          <FaChevronRight />
        </button>
      ))}
    </aside>
  );
}

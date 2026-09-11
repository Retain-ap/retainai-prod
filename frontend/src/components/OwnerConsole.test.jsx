import React from "react";
import { render, screen } from "@testing-library/react";
import OwnerConsole from "./OwnerConsole";

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

test("keeps available owner-console data visible when one section fails", async () => {
  global.fetch = jest.fn().mockImplementation((url) => {
    const value = String(url);
    if (value.includes("owner/audit")) return Promise.resolve(response({ error: "unavailable" }, 503));
    if (value.includes("owner/overview")) {
      return Promise.resolve(response({
        accounts_total: 9,
        recent_signups: 1,
        active_accounts: 7,
        trials: 2,
        contacts_total: 24,
        onboarded_accounts: 5,
        average_onboarding: 75,
        at_risk_accounts: 1,
        recorded_mrr: {},
        past_due: 0,
        suspended: 0,
        integrations: {},
      }));
    }
    if (value.includes("owner/accounts")) return Promise.resolve(response({ accounts: [] }));
    if (value.includes("owner/support-queue")) return Promise.resolve(response({ queue: [] }));
    if (value.includes("owner/health")) return Promise.resolve(response({ checks: {} }));
    if (value.includes("owner/features")) return Promise.resolve(response({ features: {} }));
    if (value.includes("owner/backups")) return Promise.resolve(response({ backups: [] }));
    return Promise.resolve(response({}));
  });

  render(<OwnerConsole />);

  expect(await screen.findByText(/Some owner data is temporarily unavailable: audit log/i)).toBeInTheDocument();
  expect(screen.getByText("9")).toBeInTheDocument();
});

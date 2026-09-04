import React from "react";
import { render, screen } from "@testing-library/react";
import WhatsAppHealthCard from "./WhatsAppHealthCard";

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function installWhatsAppResponses({ graphOk, graphError = "Invalid OAuth access token" }) {
  global.fetch = jest.fn().mockImplementation((url) => {
    const value = String(url);
    if (value.includes("whatsapp/inbound-health")) {
      return Promise.resolve(response({ webhook_last_seen_at: "2026-09-03T12:00:00Z", unmatched_count: 0 }));
    }
    if (value.includes("integrations/whatsapp")) {
      return Promise.resolve(response({ phone_id: "phone", waba_id: "waba", source: "workspace" }));
    }
    if (value.includes("whatsapp/templates")) {
      return Promise.resolve(response({ templates: [{ name: "follow_up", status: "APPROVED" }] }));
    }
    return Promise.resolve(response({
      has_token: true,
      has_phone_id: true,
      has_waba_id: true,
      graph_ok: graphOk,
      graph_error: graphOk ? "" : graphError,
      webhook_last_seen_at: "2026-09-03T12:00:00Z",
    }));
  });
}

test("does not report WhatsApp connected when Meta rejects the stored credentials", async () => {
  installWhatsAppResponses({ graphOk: false });
  render(<WhatsAppHealthCard user={{ email: "owner@example.com", role: "owner" }} />);

  expect(await screen.findByText("Check setup")).toBeInTheDocument();
  expect(screen.queryByText("Connected")).not.toBeInTheDocument();
  expect(await screen.findByText(/Meta could not validate this connection/i)).toHaveTextContent(
    "Invalid OAuth access token"
  );
});

test("reports connected only when credentials, templates, and webhook are ready", async () => {
  installWhatsAppResponses({ graphOk: true });
  render(<WhatsAppHealthCard user={{ email: "owner@example.com", role: "owner" }} />);

  expect(await screen.findByText("Connected")).toBeInTheDocument();
  expect(screen.getByText(/Meta API credentials validated/i)).toHaveClass("ready");
});

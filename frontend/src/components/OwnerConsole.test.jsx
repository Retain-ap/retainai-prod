import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import OwnerConsole from "./OwnerConsole";

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

test("accepts a strong tester password and rejects passwords missing a required character class", async () => {
  global.fetch = jest.fn().mockResolvedValue(response({ accounts: [], recorded_mrr: {}, integrations: {} }));
  render(<OwnerConsole />);
  fireEvent.click(await screen.findByRole("tab", { name: "Customer Accounts" }));
  fireEvent.click(screen.getByRole("button", { name: "Add complimentary account" }));
  const password = screen.getByLabelText("Temporary password");

  // Exercise the rendered input's browser validation, including JSX attribute escaping.
  fireEvent.change(password, { target: { value: "LaunchReview7!" } });
  expect(password.checkValidity()).toBe(true);
  for (const invalid of ["Short7!", "launchreview7!", "LAUNCHREVIEW7!", "LaunchReview!!", "LaunchReview77", "LaunchReview\\d!"]) {
    fireEvent.change(password, { target: { value: invalid } });
    expect(password.checkValidity()).toBe(false);
  }
});

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

test("explains the MFA requirement and links to Security instead of reporting an outage", async () => {
  global.fetch = jest.fn().mockResolvedValue(response({
    error: "owner_mfa_required",
    message: "Enable and verify two-factor authentication before using the Owner Console.",
  }, 403));

  render(<OwnerConsole />);

  expect(await screen.findByText("Two-factor authentication required")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open Security settings" })).toHaveAttribute("href", "/app?tab=security");
  expect(screen.queryByText(/temporarily unavailable/i)).not.toBeInTheDocument();
  expect(screen.queryByRole("tablist", { name: "Owner console" })).not.toBeInTheDocument();

  global.fetch.mockResolvedValue(response({}));
  fireEvent.click(screen.getByRole("button", { name: "Refresh data" }));
  expect(await screen.findByRole("tablist", { name: "Owner console" })).toBeInTheDocument();
  expect(screen.queryByText("Two-factor authentication required")).not.toBeInTheDocument();
});

test("hides owner data when one response requires MFA even if other requests succeeded", async () => {
  global.fetch = jest.fn().mockImplementation(url => Promise.resolve(
    String(url).includes("owner/overview")
      ? response({ accounts_total: 999, recorded_mrr: {}, integrations: {} })
      : response({ error: "owner_mfa_required" }, 403)
  ));

  render(<OwnerConsole />);

  expect(await screen.findByText("Two-factor authentication required")).toBeInTheDocument();
  expect(screen.queryByText("999")).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Customer Accounts" })).not.toBeInTheDocument();
});

test("verifies a stored backup on request and says plainly that archives are not encrypted on the disk", async () => {
  const backup = { name: "retainai-backup-20261106T032000Z.zip", bytes: 1048576, created_at: "2026-11-06T03:20:03Z", sha256: "a".repeat(64) };
  global.fetch = jest.fn().mockImplementation((url, options = {}) => {
    const value = String(url);
    if (value.includes("/verify") && options.method === "POST") {
      return Promise.resolve(response({ ok: true, files: 15, checksum_file_matched: true, sqlite_integrity: "ok" }));
    }
    if (value.includes("owner/backups")) return Promise.resolve(response({ backups: [backup] }));
    if (value.includes("owner/overview")) return Promise.resolve(response({ recorded_mrr: {}, integrations: {} }));
    if (value.includes("owner/accounts")) return Promise.resolve(response({ accounts: [] }));
    if (value.includes("owner/support-queue")) return Promise.resolve(response({ queue: [] }));
    if (value.includes("owner/health")) return Promise.resolve(response({ checks: {} }));
    if (value.includes("owner/features")) return Promise.resolve(response({ features: {} }));
    return Promise.resolve(response({ audit: [] }));
  });

  render(<OwnerConsole />);
  fireEvent.click(await screen.findByRole("tab", { name: /Backups/ }));
  expect(screen.getByText(/Archives are not encrypted on the disk/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Verify" }));
  expect(await screen.findByText("Verified: 15 files match the manifest and stored checksum; database ok.")).toBeInTheDocument();
  const [url, options] = global.fetch.mock.calls.find(([, call]) => call?.method === "POST");
  expect(String(url)).toContain(`owner/backups/${backup.name}/verify`);
  expect(options.credentials).toBe("include");
});

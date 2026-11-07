import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import LeadsDashboard from "./LeadsDashboard";

const originalResizeObserver = global.ResizeObserver;
beforeAll(() => {
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
});
afterAll(() => { global.ResizeObserver = originalResizeObserver; });

async function openChooser(onImportLeads) {
  render(<LeadsDashboard leads={[]} onImportLeads={onImportLeads} />);
  const trigger = screen.getByRole("button", { name: "Import Leads" });
  trigger.focus();
  fireEvent.click(trigger);
  return screen.findByRole("dialog", { name: "Where are your contacts?" });
}

test("Import Leads asks for a source before navigating or authorizing", async () => {
  const onImportLeads = jest.fn();
  const dialog = await openChooser(onImportLeads);
  for (const label of ["Apple Contacts", "Google Contacts", "WhatsApp contacts", "Android Contacts", "Outlook / Microsoft People", "Google Sheets", "Microsoft Excel", "HubSpot", "Salesforce", "Pipedrive", "Zoho CRM", "Another service or file"]) {
    expect(within(dialog).getByRole("button", { name: label, exact: true })).toBeInTheDocument();
  }
  expect(onImportLeads).not.toHaveBeenCalled();
  expect(within(dialog).getByText(/From your phone's address book/)).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Google Sheets", exact: true })).toHaveAccessibleDescription("Download your sheet as CSV");
  fireEvent.click(within(dialog).getByRole("button", { name: "Google Sheets", exact: true }));
  expect(onImportLeads).toHaveBeenCalledWith("sheets");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

test("Escape cancels without navigating and returns focus to Import Leads", async () => {
  const onImportLeads = jest.fn();
  const dialog = await openChooser(onImportLeads);
  fireEvent.keyDown(dialog, { key: "Escape", code: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(onImportLeads).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.getByRole("button", { name: "Import Leads" })).toHaveFocus());
});

test("without a handler a choice still opens its import guide, never OAuth", async () => {
  const original = window.location;
  const assign = jest.fn();
  delete window.location;
  window.location = { ...original, assign, href: original.href };
  try {
    const dialog = await openChooser();
    expect(assign).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Google Contacts", exact: true }));
    expect(assign).toHaveBeenCalledWith("/app/import?source=google");
    expect(window.location.href).not.toMatch(/google\/authorize/);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  } finally {
    window.location = original;
  }
});

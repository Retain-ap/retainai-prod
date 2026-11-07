import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import LeadsDashboard from "./LeadsDashboard";

function importButton() {
  return screen.getByRole("button", { name: "Import contacts from a file or Google Contacts" });
}

test("the Import Leads button describes every supported import source, not only Google", () => {
  render(<LeadsDashboard leads={[]} onImportLeads={jest.fn()} />);
  const button = importButton();
  expect(button).toHaveTextContent("Import Leads");
  expect(button.getAttribute("title")).toMatch(/CSV or vCard file \(iPhone, Mac, Outlook, Google, HubSpot and other CRMs\) or from Google Contacts/);
  expect(button.getAttribute("title")).not.toBe("Import from Google Contacts");
});

test("it opens the dashboard's contact importer", () => {
  const onImportLeads = jest.fn();
  render(<LeadsDashboard leads={[]} onImportLeads={onImportLeads} />);
  fireEvent.click(importButton());
  expect(onImportLeads).toHaveBeenCalledTimes(1);
});

test("without a handler it still opens the importer and never starts Google authorization", () => {
  const original = window.location;
  const assign = jest.fn();
  delete window.location;
  window.location = { ...original, assign, href: original.href };
  try {
    render(<LeadsDashboard leads={[]} />);
    fireEvent.click(importButton());
    expect(assign).toHaveBeenCalledWith("/app/import");
    expect(window.location.href).not.toMatch(/google\/authorize/);
  } finally {
    window.location = original;
  }
});

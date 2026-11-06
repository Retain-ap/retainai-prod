import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import LeadDrawer from "./LeadDrawer";

test("does not claim a reminder was saved when the parent persistence rejects", async () => {
  const onUpdateLead = jest.fn().mockRejectedValue(new Error("storage unavailable"));
  const warn = jest.spyOn(console, "warn").mockImplementation(() => {});

  render(
    <LeadDrawer
      lead={{ id: "lead-1", name: "Jamie", email: "jamie@example.com", reminders: [] }}
      onClose={jest.fn()}
      onEdit={jest.fn()}
      onDelete={jest.fn()}
      onUpdateLead={onUpdateLead}
    />
  );

  fireEvent.click(screen.getByRole("tab", { name: "Reminders" }));
  fireEvent.change(screen.getByPlaceholderText(/Add a reminder/i), {
    target: { value: "Call tomorrow" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));

  await waitFor(() => expect(onUpdateLead).toHaveBeenCalledTimes(1));
  expect(await screen.findByText("Could not save reminders")).toBeInTheDocument();
  expect(screen.queryByText("Reminders saved")).not.toBeInTheDocument();
  warn.mockRestore();
});

test("asks before overriding a customer's own unsubscribe", async () => {
  const onUpdateLead = jest.fn().mockResolvedValue(undefined);
  const confirm = jest.spyOn(window, "confirm").mockReturnValue(false);
  const lead = {
    id: "lead-1",
    name: "Jamie",
    email: "jamie@example.com",
    email_opt_out: true,
    email_consent_status: "withdrawn",
    email_consent_source: "customer_unsubscribe_link",
    email_consent_updated_at: "2026-10-01T12:00:00+00:00",
  };

  render(
    <LeadDrawer
      lead={lead}
      onClose={jest.fn()}
      onEdit={jest.fn()}
      onDelete={jest.fn()}
      onUpdateLead={onUpdateLead}
    />
  );

  expect(screen.getByText(/unsubscribed using the email link/i)).toBeInTheDocument();
  const select = screen.getByLabelText("Follow-up email status");
  fireEvent.change(select, { target: { value: "confirmed" } });
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(onUpdateLead).not.toHaveBeenCalled();
  expect(select).toHaveValue("withdrawn");

  confirm.mockReturnValue(true);
  fireEvent.change(select, { target: { value: "confirmed" } });
  await waitFor(() => expect(onUpdateLead).toHaveBeenCalledTimes(1));
  confirm.mockRestore();
});

describe("without a dashboard save handler", () => {
  const drawerLead = { id: "lead-1", name: "Jamie", email: "jamie@example.com", owner: "owner@example.com", reminders: [] };
  const otherContact = { id: "imported", name: "Imported Cara", email: "cara@example.com", imported_at: "2026-11-06T00:00:00Z" };

  function mockLeadsServer(storedLeads, { failPost = false } = {}) {
    const calls = [];
    global.fetch = jest.fn(async (url, options = {}) => {
      const body = options.body ? JSON.parse(options.body) : null;
      calls.push({ url: String(url), method: options.method || "GET", body });
      if ((options.method || "GET") === "GET") {
        return { ok: true, status: 200, json: async () => ({ ok: true, leads: storedLeads, revision: "rev-1" }) };
      }
      if (failPost) return { ok: false, status: 428, json: async () => ({ ok: false, code: "revision_required" }) };
      return { ok: true, status: 200, json: async () => ({ ok: true, count: body.leads.length, revision: "rev-2", leads: body.leads }) };
    });
    return calls;
  }

  afterEach(() => {
    delete global.fetch;
  });

  function addReminder(text) {
    fireEvent.click(screen.getByRole("tab", { name: "Reminders" }));
    fireEvent.change(screen.getByPlaceholderText(/Add a reminder/i), { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
  }

  test("saves only the edited field onto the latest list with its revision", async () => {
    // The server already has a newer name for this contact and an imported contact.
    const calls = mockLeadsServer([{ ...drawerLead, name: "Jamie Renamed Elsewhere" }, otherContact]);
    render(<LeadDrawer lead={drawerLead} onClose={jest.fn()} onEdit={jest.fn()} onDelete={jest.fn()} />);
    addReminder("Call tomorrow");

    expect(await screen.findByText("Reminders saved")).toBeInTheDocument();
    expect(calls.map((call) => call.method)).toEqual(["GET", "POST"]);
    const posted = calls[1].body;
    expect(posted.base_revision).toBe("rev-1");
    expect(posted.leads).toHaveLength(2);
    expect(posted.leads[0].name).toBe("Jamie Renamed Elsewhere");
    expect(posted.leads[0].reminders).toEqual([expect.objectContaining({ text: "Call tomorrow" })]);
    expect(posted.leads[1]).toEqual(otherContact);
  });

  test("never recreates a contact deleted elsewhere and never saves unversioned", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    const calls = mockLeadsServer([otherContact]);
    render(<LeadDrawer lead={drawerLead} onClose={jest.fn()} onEdit={jest.fn()} onDelete={jest.fn()} />);
    addReminder("Call tomorrow");

    expect(await screen.findByText("Could not save reminders")).toBeInTheDocument();
    const posts = calls.filter((call) => call.method === "POST");
    posts.forEach((post) => expect(post.body.base_revision).toBe("rev-1"));
    posts.forEach((post) => expect(post.body.leads).toEqual([otherContact]));
    warn.mockRestore();
  });
});

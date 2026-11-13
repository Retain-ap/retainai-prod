import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import RetentionCommandCenter from "./RetentionCommandCenter";

function daysAgo(days) {
  const date = new Date();
  // These workspaces use UTC; the fixture must too, including near midnight.
  date.setUTCDate(date.getUTCDate() - days);
  return date.toISOString().slice(0, 10);
}

const ana = { id: "a", name: "Ana Rivera", email: "ana@example.com", last_contacted: new Date().toISOString() };
const ben = { id: "b", name: "Ben Old", email: "ben@example.com", last_contacted: "2025-01-01T00:00:00Z" };
const completed = (lead, days) => ({ lead, date: daysAgo(days), time: "10:00", status: "completed", _backend: {} });
// Ana visits every 30 days; her last visit was 40 days ago, so she is 10 days overdue.
const appointments = [completed(ana, 100), completed(ana, 70), completed(ana, 40)];

beforeEach(() => {
  global.fetch = jest.fn(async () => ({ ok: false, status: 403, json: async () => ({ error: "owner_required" }) }));
});
afterEach(() => { delete global.fetch; });

test("rebooking opportunities use each customer's visit rhythm and save an owner interval", async () => {
  const onUpdateLead = jest.fn().mockResolvedValue(undefined);
  const prompt = jest.spyOn(window, "prompt").mockReturnValue("21");
  render(<RetentionCommandCenter leads={[ana, ben]} appointments={appointments} user={{ timezone: "UTC" }} onUpdateLead={onUpdateLead} />);
  fireEvent.click(screen.getByRole("tab", { name: "Revenue Opportunities" }));

  expect(screen.getByText(/Rebooking overdue by 10 days · every 30 days/)).toBeInTheDocument();
  expect(screen.getByText(/median of 2 gaps between 3 completed visits/)).toBeInTheDocument();
  expect(screen.getByText(/Win-back: no completed visit recorded/)).toBeInTheDocument();
  expect(screen.getByText(/Nothing is sent automatically/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Set interval" }));
  expect(onUpdateLead).toHaveBeenCalledWith({ ...ana, rebook_interval_days: 21 });
  prompt.mockRestore();
});

test("no value is invented: only values the owner recorded are shown or added up", () => {
  const valued = { ...ana, id: "v", name: "Val Recorded", email: "val@example.com", average_sale: 120 };
  const { unmount } = render(<RetentionCommandCenter leads={[ana]} appointments={appointments} user={{ timezone: "UTC" }} />);
  expect(screen.getByText("No customer values recorded")).toBeInTheDocument();
  expect(screen.queryByText(/\$75/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Revenue Opportunities" }));
  expect(screen.getByText("No value recorded")).toBeInTheDocument();
  unmount();

  render(<RetentionCommandCenter leads={[ana, valued]} appointments={[...appointments, completed(valued, 70), completed(valued, 40)]} user={{ timezone: "UTC" }} />);
  // Shown on the metric card and in Today's priorities.
  expect(screen.getAllByText(/\$120 recorded for 1 of 2/).length).toBeGreaterThanOrEqual(1);
});

test("a due customer can be drafted for review or marked contacted; nothing is sent from the list", async () => {
  const onDraftFollowUp = jest.fn();
  const onMarkContacted = jest.fn().mockResolvedValue({});
  render(<RetentionCommandCenter leads={[ana]} appointments={appointments} user={{ timezone: "UTC" }} onDraftFollowUp={onDraftFollowUp} onMarkContacted={onMarkContacted} />);
  fireEvent.click(screen.getByRole("tab", { name: "Revenue Opportunities" }));

  fireEvent.click(screen.getByRole("button", { name: "Draft follow-up" }));
  expect(onDraftFollowUp).toHaveBeenCalledTimes(1);
  const [lead, context] = onDraftFollowUp.mock.calls[0];
  expect(lead).toBe(ana);
  expect(context).toMatch(/^Due to rebook: last completed visit .+; they usually return about every 30 days \(measured from their completed visits\)\.$/);

  fireEvent.click(screen.getByRole("button", { name: "Mark contacted" }));
  await waitFor(() => expect(onMarkContacted).toHaveBeenCalledWith(ana));
  expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("send-ai-message"), expect.anything());
});

test("a failed mark-contacted shows the reason and keeps the customer on the list", async () => {
  const onMarkContacted = jest.fn().mockRejectedValue(new Error("The contact could not be recorded (HTTP 500)."));
  render(<RetentionCommandCenter leads={[ana]} appointments={appointments} user={{ timezone: "UTC" }} onMarkContacted={onMarkContacted} />);
  fireEvent.click(screen.getByRole("tab", { name: "Revenue Opportunities" }));
  fireEvent.click(screen.getByRole("button", { name: "Mark contacted" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The contact could not be recorded (HTTP 500).");
  expect(screen.getByRole("button", { name: "Mark contacted" })).toBeEnabled();
});

test("unsubscribed or email-less customers get no email draft action", () => {
  const optedOut = { ...ana, id: "o", name: "Opted Out", email: "out@example.com", email_opt_out: true };
  const noEmail = { ...ana, id: "n", name: "No Email", email: "" };
  render(<RetentionCommandCenter leads={[optedOut, noEmail]} appointments={[...appointments.map((a) => ({ ...a, lead: optedOut })), ...appointments.map((a) => ({ ...a, lead: noEmail }))]}
    user={{ timezone: "UTC" }} onDraftFollowUp={jest.fn()} onMarkContacted={jest.fn()} />);
  fireEvent.click(screen.getByRole("tab", { name: "Revenue Opportunities" }));
  expect(screen.queryByRole("button", { name: "Draft follow-up" })).not.toBeInTheDocument();
  expect(screen.getByText("Unsubscribed from email")).toBeInTheDocument();
  expect(screen.getByText("No email address")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Mark contacted" })).toHaveLength(2);
});

test("a customer followed up this week waits to book instead of staying on the contact list", () => {
  const followedUp = { ...ana, last_outreach_at: `${daysAgo(2)}T15:00:00Z` };
  render(<RetentionCommandCenter leads={[followedUp]} appointments={appointments.map((a) => ({ ...a, lead: followedUp }))} user={{ timezone: "UTC" }} onMarkContacted={jest.fn()} />);
  fireEvent.click(screen.getByRole("tab", { name: "Revenue Opportunities" }));
  expect(screen.getByText("No one is due right now")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Contacted, waiting to book (1)" })).toBeInTheDocument();
  expect(screen.getByText(/Back on the list .+ if they haven't booked\./)).toBeInTheDocument();
});

test("rejects an invalid interval without saving", () => {
  const onUpdateLead = jest.fn();
  const prompt = jest.spyOn(window, "prompt").mockReturnValue("3");
  const alert = jest.spyOn(window, "alert").mockImplementation(() => {});
  render(<RetentionCommandCenter leads={[ana]} appointments={appointments} user={{ timezone: "UTC" }} onUpdateLead={onUpdateLead} />);
  fireEvent.click(screen.getByRole("tab", { name: "Revenue Opportunities" }));
  fireEvent.click(screen.getByRole("button", { name: "Set interval" }));
  expect(onUpdateLead).not.toHaveBeenCalled();
  expect(alert).toHaveBeenCalled();
  prompt.mockRestore();
  alert.mockRestore();
});

test("the Value Receipt keeps estimates separate and makes no protected-value claim", async () => {
  render(<RetentionCommandCenter leads={[ana, ben]} appointments={appointments} user={{ timezone: "UTC" }} />);
  fireEvent.click(screen.getByRole("tab", { name: "Value Receipt" }));
  expect(screen.getByText("Estimates · not revenue")).toBeInTheDocument();
  expect(screen.getByText(/never included in verified revenue/)).toBeInTheDocument();
  expect(screen.queryByText(/protecting relationships worth/)).not.toBeInTheDocument();
  expect(screen.queryByText(/admin time saved/i)).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Only the workspace owner can see revenue."));
});

test("general mode is the default service-business setup; Calendly is optional for the booking step", () => {
  render(<RetentionCommandCenter leads={[ana]} appointments={appointments} user={{ timezone: "UTC" }} />);
  expect(screen.queryByRole("region", { name: "Salon and barber setup" })).not.toBeInTheDocument();
  const panel = screen.getByRole("region", { name: "Service business setup" });
  expect(within(panel).getByText("General service business setup chosen")).toBeInTheDocument();
  expect(within(panel).getByText("Bring in your bookings")).toBeInTheDocument();
  expect(within(panel).getByText(/or sync them from Calendly if it is available/)).toBeInTheDocument();
  expect(within(panel).getByText(/Importing or syncing never records consent/)).toBeInTheDocument();
  expect(panel).toHaveTextContent(/No bookings imported from a booking platform yet/);
  expect(panel).not.toHaveTextContent(/connected to Calendly/i); // never claims a live connection
  fireEvent.click(screen.getByRole("tab", { name: "Playbooks" }));
  expect(screen.getByText("Recover unpaid invoices")).toBeInTheDocument();
  expect(screen.queryByText("Day-before appointment reminder")).not.toBeInTheDocument();
});

test("appointments added in RetainAI complete the booking step without Calendly", () => {
  render(<RetentionCommandCenter leads={[ana]} appointments={appointments} user={{ timezone: "UTC" }} />);
  const panel = screen.getByRole("region", { name: "Service business setup" });
  const step = within(panel).getByTestId("setup-step-bookings");
  expect(step).toHaveClass("done");
  expect(within(step).queryByRole("button", { name: "Add appointment" })).not.toBeInTheDocument();
});

test("with no bookings yet, the booking step offers Add appointment, separate from contact import", () => {
  const onOpenImports = jest.fn();
  const onOpenAppointments = jest.fn();
  render(<RetentionCommandCenter leads={[]} appointments={[]} user={{ timezone: "UTC" }} onOpenImports={onOpenImports} onOpenAppointments={onOpenAppointments} />);
  const panel = screen.getByRole("region", { name: "Service business setup" });
  const step = within(panel).getByTestId("setup-step-bookings");
  expect(step).not.toHaveClass("done");
  expect(within(step).queryByRole("button", { name: "Open" })).not.toBeInTheDocument();
  fireEvent.click(within(step).getByRole("button", { name: "Add appointment" }));
  expect(onOpenAppointments).toHaveBeenCalledTimes(1);
  expect(onOpenImports).not.toHaveBeenCalled();
  // Importing contacts keeps its own action.
  fireEvent.click(within(panel).getByRole("button", { name: "Import" }));
  expect(onOpenImports).toHaveBeenCalledTimes(1);
  expect(onOpenAppointments).toHaveBeenCalledTimes(1);
});

test("bookings synced from Calendly tick the booking step and are counted, not named", () => {
  const synced = { ...appointments[0], source: "calendly", id: "calendly:E1:I1" };
  render(<RetentionCommandCenter leads={[ana]} appointments={[synced, ...appointments.slice(1)]} user={{ timezone: "UTC" }} />);
  const panel = screen.getByRole("region", { name: "Service business setup" });
  expect(panel).toHaveTextContent("1 booking imported from Calendly, plus appointments added in RetainAI.");
  expect(within(panel).queryByRole("button", { name: "Open" })).not.toBeInTheDocument();
  expect(panel).not.toHaveTextContent("Ana Rivera");
});

test("the salon preset adds a checklist, count-only metrics and review-only playbooks", () => {
  const onOpenAutomations = jest.fn();
  const imported = { id: "i", name: "Imported Iris", email: "iris@example.com", imported_at: "2026-11-01T00:00:00Z" };
  const noShow = { lead: ana, date: daysAgo(5), time: "10:00", status: "no-show", _backend: {} };
  render(
    <RetentionCommandCenter
      leads={[ana, imported]}
      appointments={[...appointments, noShow]}
      user={{ timezone: "UTC", setup_preset: "salon_barber" }}
      onOpenAutomations={onOpenAutomations}
    />
  );
  const panel = screen.getByRole("region", { name: "Salon and barber setup" });
  expect(within(panel).getByText("Confirm email consent for 1 imported client")).toBeInTheDocument();
  expect(within(panel).getByText("A client has a personal rebooking rhythm")).toBeInTheDocument();
  const metrics = within(panel).getByTestId("salon-metrics");
  expect(within(metrics).getByTestId("salon-metric-withRhythm")).toHaveTextContent(/^1Clients with a rebooking rhythm$/);
  expect(within(metrics).getByTestId("salon-metric-dueNow")).toHaveTextContent(/^1Due to rebook this week$/);
  expect(within(metrics).getByTestId("salon-metric-noShowRate30")).toHaveTextContent(/^100%No-show rate/);
  expect(panel).not.toHaveTextContent("Ana Rivera"); // counts only, no names
  expect(panel).toHaveTextContent(/No bookings imported from a booking platform yet/);

  fireEvent.click(within(panel).getByRole("button", { name: "Review" }));
  expect(screen.getByText("Day-before appointment reminder")).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Review this playbook" })[0]);
  expect(onOpenAutomations).toHaveBeenCalledWith("rebook");
  expect(screen.getAllByText(/Nothing is sent until you activate it/).length).toBeGreaterThan(0);
});

describe("draft context only calls a measured visit pattern the customer's habit", () => {
  const draftContextFor = (lead, visits) => {
    const onDraftFollowUp = jest.fn();
    const { unmount } = render(<RetentionCommandCenter leads={[lead]} appointments={visits} user={{ timezone: "UTC" }} onDraftFollowUp={onDraftFollowUp} />);
    fireEvent.click(screen.getByRole("tab", { name: "Revenue Opportunities" }));
    fireEvent.click(screen.getByRole("button", { name: "Draft follow-up" }));
    unmount();
    return onDraftFollowUp.mock.calls[0][1];
  };

  test("one completed visit uses a labelled standard interval, never 'usually'", () => {
    const single = { id: "s", name: "Sol Single", email: "sol@example.com" };
    const context = draftContextFor(single, [completed(single, 90)]);
    expect(context).toMatch(/only one completed visit recorded; planning uses a standard 60-day interval, not a habit of this customer\.$/);
    expect(context).not.toMatch(/usually/);
  });

  test("an owner-set interval is attributed to the owner, not the customer", () => {
    const owned = { id: "o", name: "Oli Owner", email: "oli@example.com", rebook_interval_days: 21 };
    const context = draftContextFor(owned, [completed(owned, 90)]);
    expect(context).toMatch(/the owner set a 21-day rebooking interval for this customer\.$/);
    expect(context).not.toMatch(/usually/);
  });

  test("two visits describe the single measured gap, not a habit", () => {
    const pair = { id: "p", name: "Pat Pair", email: "pat@example.com" };
    const context = draftContextFor(pair, [completed(pair, 100), completed(pair, 60)]);
    expect(context).toMatch(/one gap of 40 days between their two completed visits so far\.$/);
    expect(context).not.toMatch(/usually/);
  });

  test("three or more visits may state the measured cadence", () => {
    const context = draftContextFor(ana, appointments);
    expect(context).toMatch(/they usually return about every 30 days \(measured from their completed visits\)\.$/);
  });
});

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
  expect(screen.getByText(/Values are estimates, not revenue/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Set interval" }));
  expect(onUpdateLead).toHaveBeenCalledWith({ ...ana, rebook_interval_days: 21 });
  prompt.mockRestore();
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

import { vi } from "vitest";
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import Analytics from "./Analytics";

// Charts are outside this regression; exercise the real normalization, merge,
// summary and displayed metrics without jsdom needing layout/ResizeObserver.
vi.mock("recharts", () => Object.fromEntries([
  "FunnelChart", "Funnel", "LabelList", "PieChart", "Pie", "Cell", "BarChart", "Bar",
  "XAxis", "YAxis", "Tooltip", "ResponsiveContainer", "Legend", "AreaChart", "Area",
].map((name) => [name, () => null])));

const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });

test.each(["ana-old@example.com", ""])("completed metrics suppress stale mirrors by stable contact ID even with provider email '%s'", async (providerEmail) => {
  const visit = (id, status) => ({ id, title: id, lead_id: "ana", lead_email: providerEmail, appointment_time: "2026-10-14T10:00:00", status, done: true, is_done: true });
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ timezone: "America/Toronto", appointments: [
    visit("Attended", "completed"), visit("Missed", "no_show"), visit("Cancelled", "cancelled"),
  ] }) });
  render(<Analytics user={{ email: "owner@example.com" }} leads={[{ id: "ana", email: "ana@example.com", appointments: [
    { title: "Cancelled", date: "2026-10-14", time: "10:00", done: true },
    { title: "Local cancelled", date: "2026-10-14", time: "11:00", status: "canceled", done: true },
    { title: "Local no-show", date: "2026-10-14", time: "12:00", status: "no-show", done: true },
    { title: "Legacy completed", date: "2026-10-14", time: "13:00", done: true },
  ] }]} />);
  await waitFor(() => expect(screen.queryByText("Refreshing appointment data…")).not.toBeInTheDocument());
  expect(within(screen.getByRole("group", { name: "Completed appts" })).getByText("2")).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "No-shows" })).getByText("2")).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "Overdue appts" })).getByText("0")).toBeInTheDocument();
});

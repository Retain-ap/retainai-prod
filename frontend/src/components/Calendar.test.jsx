import { vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Calendar from "./Calendar";

const originalFetch = global.fetch;

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

afterEach(() => {
  global.fetch = originalFetch;
});

test("surfaces appointment load failures and clears the error after retry", async () => {
  global.fetch = vi
    .fn()
    .mockResolvedValueOnce(jsonResponse({ error: "calendar_unavailable" }, 503))
    .mockResolvedValueOnce(jsonResponse({ appointments: [] }));

  render(
    <Calendar
      user={{ email: "member@example.com", orgOwnerEmail: "owner@example.com" }}
      setSelectedDate={vi.fn()}
      onDayClick={vi.fn()}
    />
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Appointments could not be loaded"
  );
  expect(global.fetch.mock.calls[0][0]).toContain("owner%40example.com");

  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(global.fetch).toHaveBeenCalledTimes(2);
});

test("places offset and all-day events on their workspace calendar day", async () => {
  global.fetch = vi.fn().mockResolvedValue(
    jsonResponse({
      timezone: "America/Toronto",
      appointments: [
        {
          id: "appointment-1",
          title: "Evening consultation",
          appointment_time: "2026-09-04T01:30:00Z",
          timezone: "America/Toronto",
        },
      ],
    })
  );

  render(
    <Calendar
      user={{ email: "owner@example.com" }}
      selectedDate={new Date(2026, 8, 3, 12, 0, 0)}
      setSelectedDate={vi.fn()}
      onDayClick={vi.fn()}
      googleEvents={[
        {
          id: "google-1",
          summary: "Team holiday",
          start: { date: "2026-09-03" },
        },
      ]}
    />
  );

  expect(await screen.findByText("Evening consultation")).toBeInTheDocument();
  expect(screen.getByText("Team holiday")).toBeInTheDocument();
  expect(screen.getByText("All day")).toBeInTheDocument();
  expect(screen.getByText("Toronto time")).toHaveAttribute("title", "America/Toronto");
});

test.each([
  ["cancelled", "Cancelled"],
  ["no_show", "No-show"],
])("provider %s is displayed as its actual outcome, not completed", async (status, label) => {
  global.fetch = jest.fn().mockResolvedValue(jsonResponse({
    timezone: "America/Toronto",
    appointments: [{ id: "visit", title: "Provider visit", appointment_time: "2026-11-14T10:00:00", timezone: "America/Toronto", status, done: true, is_done: true }],
  }));
  render(<Calendar user={{ email: "owner@example.com" }} selectedDate={new Date(2026, 10, 14, 12)} setSelectedDate={jest.fn()} onDayClick={jest.fn()} />);
  expect(await screen.findByText(`${label} appointment`)).toBeInTheDocument();
  expect(screen.getByText(label)).toBeInTheDocument();
  expect(screen.queryByText("Completed")).not.toBeInTheDocument();
  expect(screen.queryByText("Completed appointment")).not.toBeInTheDocument();
  expect(screen.getByText("Toronto time")).toBeInTheDocument();
});

test("local no-show status also overrides done while legacy completed visits remain completed", async () => {
  global.fetch = jest.fn().mockResolvedValue(jsonResponse({ timezone: "America/Toronto", appointments: [] }));
  const leads = [{ id: "ana", name: "Ana", appointments: [
    { title: "Missed local visit", date: "2026-11-14", time: "10:00", status: "no-show", done: true },
    { title: "Finished legacy visit", date: "2026-11-14", time: "11:00", done: true },
  ] }];
  render(<Calendar user={{ email: "owner@example.com" }} leads={leads} selectedDate={new Date(2026, 10, 14, 12)} setSelectedDate={jest.fn()} onDayClick={jest.fn()} />);
  expect(await screen.findByText("No-show appointment")).toBeInTheDocument();
  expect(screen.getByText("Completed appointment")).toBeInTheDocument();
  expect(screen.getAllByText("Completed")).toHaveLength(1);
});

test("an older UTC record retains its recorded wall time and explicitly displays UTC", async () => {
  global.fetch = jest.fn().mockResolvedValue(jsonResponse({ timezone: "America/Toronto", appointments: [
    { id: "old", title: "Older UTC visit", appointment_time: "2026-11-14T15:00:00", timezone: "UTC" },
  ] }));
  render(<Calendar user={{ email: "owner@example.com" }} selectedDate={new Date(2026, 10, 14, 12)} setSelectedDate={jest.fn()} onDayClick={jest.fn()} />);
  expect(await screen.findByText("UTC")).toHaveAttribute("title", "UTC");
  expect(screen.queryByText("Toronto time")).not.toBeInTheDocument();
});

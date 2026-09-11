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
  global.fetch = jest
    .fn()
    .mockResolvedValueOnce(jsonResponse({ error: "calendar_unavailable" }, 503))
    .mockResolvedValueOnce(jsonResponse({ appointments: [] }));

  render(
    <Calendar
      user={{ email: "member@example.com", orgOwnerEmail: "owner@example.com" }}
      setSelectedDate={jest.fn()}
      onDayClick={jest.fn()}
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
  global.fetch = jest.fn().mockResolvedValue(
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
      setSelectedDate={jest.fn()}
      onDayClick={jest.fn()}
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
});

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import NotificationsCenter from "./NotificationsCenter";

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

test("uses workspace identity and rolls back a failed optimistic read", async () => {
  global.fetch = jest
    .fn()
    .mockResolvedValueOnce(
      jsonResponse({
        notifications: [
          {
            id: "notice-1",
            subject: "Customer reply",
            message: "Please call me",
            timestamp: new Date().toISOString(),
            read: false,
          },
        ],
      })
    )
    .mockResolvedValueOnce(jsonResponse({ error: "write_failed" }, 500));

  render(
    <NotificationsCenter
      user={{ email: "member@example.com", orgOwnerEmail: "owner@example.com", role: "member" }}
    />
  );

  expect(await screen.findByText("Customer reply")).toBeInTheDocument();
  expect(global.fetch.mock.calls[0][0]).toContain("owner%40example.com");

  fireEvent.click(screen.getByRole("button", { name: "Mark as Read" }));

  expect(await screen.findByText("write_failed")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Mark as Read" })).toBeInTheDocument();
  expect(global.fetch.mock.calls[1][0]).toContain("owner%40example.com");
});

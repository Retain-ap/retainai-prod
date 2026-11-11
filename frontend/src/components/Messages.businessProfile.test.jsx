import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Messages from "./Messages";

const lead = { id: "lead-1", name: "Jordan Lee", email: "jordan@example.com", phone: "+14165550100" };
const refusal = {
  code: "business_profile_required",
  settings_path: "/app?tab=profile",
  error: "Add your business name in Settings before creating or sending customer messages.",
};

beforeAll(() => {
  // jsdom has no element scrolling; the thread scrolls to the newest message.
  Element.prototype.scrollTo = jest.fn();
});

beforeEach(() => {
  global.fetch = jest.fn((url) => {
    const body = String(url).includes("/api/generate-message") ? refusal : {};
    const status = String(url).includes("/api/generate-message") ? 409 : 200;
    return Promise.resolve({ ok: status === 200, status, json: async () => body, text: async () => JSON.stringify(body) });
  });
});

afterEach(() => {
  sessionStorage.clear();
  delete global.fetch;
});

test("AI Reply without a business name keeps the typed reply and offers Settings instead of a template", async () => {
  const openSettings = jest.fn();
  render(<Messages user={{ email: "owner@example.com" }} leads={[lead]} onOpenBusinessSettings={openSettings} />);
  const box = await screen.findByPlaceholderText(/24h|Type a message|Optional notes/);
  fireEvent.change(box, { target: { value: "Typed reply" } });
  fireEvent.click(screen.getByRole("button", { name: "AI Reply" }));

  const action = await screen.findByRole("link", { name: "Add business name in Settings" });
  expect(action).toHaveAttribute("href", "/app?tab=profile");
  expect(screen.getByRole("alert")).toHaveTextContent(refusal.error);
  expect(box).toHaveValue("Typed reply");

  fireEvent.click(action);
  expect(openSettings).toHaveBeenCalledTimes(1);
  const held = Object.keys(sessionStorage).find((key) => key.startsWith("retainai:held-draft:messages:"));
  expect(JSON.parse(sessionStorage.getItem(held))).toEqual({ text: "Typed reply" });
});

test("a held reply returns to its thread", async () => {
  sessionStorage.setItem("retainai:held-draft:messages:owner@example.com|lead-1", JSON.stringify({ text: "Held reply" }));
  render(<Messages user={{ email: "owner@example.com" }} leads={[lead]} />);
  expect(await screen.findByDisplayValue("Held reply")).toBeInTheDocument();
  await waitFor(() => expect(sessionStorage.getItem("retainai:held-draft:messages:owner@example.com|lead-1")).toBeNull());
});

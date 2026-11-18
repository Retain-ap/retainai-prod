import { vi } from "vitest";
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import Messages from "./Messages";
import { heldDraftScope, holdDraft } from "../businessProfile";

const lead = { id: "lead-1", name: "Jordan Lee", email: "jordan@example.com", phone: "+14165550100" };
const refusal = {
  code: "business_profile_required",
  settings_path: "/app?tab=profile",
  error: "Add your business name in Settings before creating or sending customer messages.",
};

beforeAll(() => {
  // jsdom has no element scrolling; the thread scrolls to the newest message.
  Element.prototype.scrollTo = vi.fn();
});

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    const body = String(url).includes("/api/generate-message") ? refusal : {};
    const status = String(url).includes("/api/generate-message") ? 409 : 200;
    return Promise.resolve({ ok: status === 200, status, json: async () => body, text: async () => JSON.stringify(body) });
  });
});

afterEach(() => {
  sessionStorage.clear();
  delete global.fetch;
});

const owner = { email: "owner@example.com" };
const threadScope = (user = owner) => heldDraftScope("messages", user, "lead-1");
const composer = () => screen.findByPlaceholderText(/24h|Type a message|Optional notes/);

test("AI Reply without a business name keeps the typed reply and offers Settings instead of a template", async () => {
  const openSettings = vi.fn();
  render(<Messages user={owner} leads={[lead]} onOpenBusinessSettings={openSettings} />);
  const box = await composer();
  fireEvent.change(box, { target: { value: "Typed reply" } });
  fireEvent.click(screen.getByRole("button", { name: "AI Reply" }));

  const action = await screen.findByRole("link", { name: "Add business name in Settings" });
  expect(action).toHaveAttribute("href", "/app?tab=profile");
  expect(screen.getByRole("alert")).toHaveTextContent(refusal.error);
  expect(box).toHaveValue("Typed reply");

  fireEvent.click(action);
  expect(openSettings).toHaveBeenCalledTimes(1);
  expect(Object.keys(sessionStorage)).toEqual([threadScope()]);
  expect(JSON.parse(sessionStorage.getItem(threadScope()))).toMatchObject({ text: "Typed reply" });
});

test("a reply edited after the refusal is held as last typed, with no further AI call", async () => {
  render(<Messages user={owner} leads={[lead]} onOpenBusinessSettings={vi.fn()} />);
  const box = await composer();
  fireEvent.change(box, { target: { value: "First words" } });
  fireEvent.click(screen.getByRole("button", { name: "AI Reply" }));
  const action = await screen.findByRole("link", { name: "Add business name in Settings" });
  const aiCalls = () => global.fetch.mock.calls.filter(([url]) => String(url).includes("/api/generate-message")).length;
  expect(aiCalls()).toBe(1);

  fireEvent.change(box, { target: { value: "First words, then an edit" } });
  fireEvent.click(action);
  expect(JSON.parse(sessionStorage.getItem(threadScope()))).toMatchObject({ text: "First words, then an edit" });
  expect(aiCalls()).toBe(1);
});

test("a held reply waits for its customer to load, then returns to its thread once", async () => {
  holdDraft(threadScope(), { text: "Held reply" });
  const { rerender } = render(<Messages user={owner} leads={[]} />);
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); });
  expect(sessionStorage.getItem(threadScope())).not.toBeNull();

  rerender(<Messages user={owner} leads={[lead]} />);
  expect(await screen.findByDisplayValue("Held reply")).toBeInTheDocument();
  expect(sessionStorage.getItem(threadScope())).toBeNull();
});

test.each([
  ["another person", { email: "other@example.com" }],
  ["the same person in another workspace", { email: "owner@example.com", org_id: "second@example.com" }],
])("%s never receives a held reply for the same customer id", async (_label, other) => {
  holdDraft(threadScope(), { text: "Held reply" });
  render(<Messages user={other} leads={[lead]} />);
  const box = await composer();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5)); });
  expect(box).toHaveValue("");
  expect(sessionStorage.getItem(threadScope())).not.toBeNull();
});

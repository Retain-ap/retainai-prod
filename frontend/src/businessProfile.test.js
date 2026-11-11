import { HELD_DRAFT_MAX_CHARS, consumeHeldDraft, heldDraftScope, holdDraft, peekHeldDraft } from "./businessProfile";

afterEach(() => {
  sessionStorage.clear();
  jest.restoreAllMocks();
});

test("scopes name the workspace and the signed-in person, and refuse unknown parts", () => {
  const member = { email: "Staff@Example.com", org_id: "Owner@Example.com" };
  expect(heldDraftScope("messages", member, "lead-1")).toBe(heldDraftScope("messages", { email: "staff@example.com", org_id: "owner@example.com" }, "lead-1"));
  expect(heldDraftScope("messages", member, "lead-1")).not.toBe(heldDraftScope("messages", { email: "owner@example.com" }, "lead-1"));
  expect(heldDraftScope("messages", member, "lead-1")).not.toBe(heldDraftScope("messages", member, "lead-2"));
  expect(heldDraftScope("messages", {}, "lead-1")).toBe("");
  expect(heldDraftScope("messages", member, "")).toBe("");
  expect(heldDraftScope("messages", member, undefined)).toBe("");
  expect(holdDraft("", { text: "x" })).toBe(false);
  expect(sessionStorage.length).toBe(0);
});

test("held text is bounded, peeking keeps it, and consuming leaves a newer draft alone", () => {
  const scope = heldDraftScope("ai-studio", { email: "owner@example.com" });
  holdDraft(scope, { draft: "x".repeat(HELD_DRAFT_MAX_CHARS + 50), nested: { ignored: true } });
  const first = peekHeldDraft(scope);
  expect(first.draft).toHaveLength(HELD_DRAFT_MAX_CHARS);
  expect(first.nested).toBeUndefined();
  expect(peekHeldDraft(scope)).toEqual(first);

  holdDraft(scope, { draft: "newer" });
  consumeHeldDraft(scope, first);
  expect(peekHeldDraft(scope).draft).toBe("newer");
  consumeHeldDraft(scope, peekHeldDraft(scope));
  expect(sessionStorage.getItem(scope)).toBeNull();
});

test("an expired held draft is not restored", () => {
  const scope = heldDraftScope("ai-studio", { email: "owner@example.com" });
  const now = Date.now();
  jest.spyOn(Date, "now").mockReturnValue(now - 13 * 60 * 60 * 1000);
  holdDraft(scope, { draft: "old" });
  Date.now.mockReturnValue(now);
  expect(peekHeldDraft(scope)).toBeNull();
});

// Customer drafts and sends need the owner's real business name. The backend
// answers 409 {code: "business_profile_required"} before any AI or email
// provider call; these helpers turn that into a Settings action and keep the
// owner's unsent draft while they add the name.
import { getWorkspaceEmail, normalizeWorkspaceEmail } from "./workspaceIdentity";

export const BUSINESS_PROFILE_REQUIRED = "business_profile_required";
// Settings > Profile holds the business name (same URL as openSection("settings")).
export const BUSINESS_SETTINGS_PATH = "/app?tab=profile";
export const BUSINESS_PROFILE_MESSAGE =
  "Add your business name in Settings before creating or sending customer messages.";

export function isBusinessProfileRequired(value) {
  return Boolean(value) && value.code === BUSINESS_PROFILE_REQUIRED;
}

// Held drafts live in this tab's session storage only, under a key naming the
// workspace and the signed-in person, so another account in the same tab never
// sees them. Text is bounded and a draft older than HELD_DRAFT_MAX_AGE_MS is ignored.
export const HELD_DRAFT_MAX_CHARS = 4000;
const HELD_DRAFT_MAX_AGE_MS = 12 * 60 * 60 * 1000;
const PREFIX = "retainai:held-draft";

/**
 * The storage key for a held draft, or "" when the account or any part is
 * unknown (nothing is held or restored then).
 */
export function heldDraftScope(kind, user, ...parts) {
  const workspace = getWorkspaceEmail(user);
  const actor = normalizeWorkspaceEmail(user?.email);
  const values = parts.map((part) => String(part ?? "").trim());
  if (!kind || !workspace || !actor || values.some((part) => !part)) return "";
  return [PREFIX, kind, workspace, actor, ...values].map(encodeURIComponent).join(":");
}

const bounded = (value) => (typeof value === "string" ? value.slice(0, HELD_DRAFT_MAX_CHARS) : value);

export function holdDraft(scope, fields) {
  if (!scope || !fields || typeof fields !== "object") return false;
  const value = { savedAt: Date.now(), nonce: Math.random().toString(36).slice(2) };
  for (const [key, field] of Object.entries(fields)) {
    if (typeof field === "string" || typeof field === "number") value[key] = bounded(field);
  }
  try {
    sessionStorage.setItem(scope, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

/** Read a held draft without removing it. */
export function peekHeldDraft(scope) {
  if (!scope) return null;
  try {
    const value = JSON.parse(sessionStorage.getItem(scope) || "null");
    if (!value || typeof value !== "object" || typeof value.nonce !== "string") return null;
    const age = Date.now() - Number(value.savedAt);
    if (!(age >= 0 && age <= HELD_DRAFT_MAX_AGE_MS)) return null;
    return value;
  } catch {
    return null;
  }
}

/** Remove a held draft once it has been put back, unless a newer one replaced it. */
export function consumeHeldDraft(scope, held) {
  if (!scope || !held) return;
  try {
    const current = JSON.parse(sessionStorage.getItem(scope) || "null");
    if (current && current.nonce === held.nonce) sessionStorage.removeItem(scope);
  } catch {}
}

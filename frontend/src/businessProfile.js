// Customer drafts and sends need the owner's real business name. The backend
// answers 409 {code: "business_profile_required"} before any AI or email
// provider call; these helpers turn that into a Settings action and keep the
// owner's unsent draft while they add the name.

export const BUSINESS_PROFILE_REQUIRED = "business_profile_required";
// Settings > Profile holds the business name (same URL as openSection("settings")).
export const BUSINESS_SETTINGS_PATH = "/app?tab=profile";
export const BUSINESS_PROFILE_MESSAGE =
  "Add your business name in Settings before creating or sending customer messages.";

export function isBusinessProfileRequired(value) {
  return Boolean(value) && value.code === BUSINESS_PROFILE_REQUIRED;
}

const heldKey = (scope) => `retainai:held-draft:${scope}`;

// Session storage only: the draft stays in this browser tab and is removed
// once it has been put back.
export function holdDraft(scope, value) {
  try {
    sessionStorage.setItem(heldKey(scope), JSON.stringify(value));
  } catch {}
}

export function takeHeldDraft(scope) {
  let value = null;
  try {
    const raw = sessionStorage.getItem(heldKey(scope));
    value = raw ? JSON.parse(raw) : null;
  } catch {
    value = null;
  }
  if (value) {
    // Removed after this render pass, so a development double-run of the
    // restoring effect still finds it.
    setTimeout(() => {
      try {
        sessionStorage.removeItem(heldKey(scope));
      } catch {}
    }, 0);
  }
  return value;
}

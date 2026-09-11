export function normalizeWorkspaceEmail(value) {
  return String(value || "").trim().toLowerCase();
}

/**
 * Return the tenant key used by workspace-scoped APIs and browser caches.
 * A signed-in team member's email identifies the actor, not the workspace.
 */
export function getWorkspaceEmail(user) {
  if (!user || typeof user !== "object") return "";

  return normalizeWorkspaceEmail(
    user.org_id ||
      user.orgOwnerEmail ||
      user.org_owner_email ||
      user.workspaceEmail ||
      user.workspace_email ||
      user.email
  );
}

/**
 * Keep client-side visibility aligned with the server-provided capability
 * flags. Role and explicit capabilities are authoritative; merely having an
 * actor email that resembles the workspace key never grants owner controls.
 */
export function getWorkspaceCapabilities(user) {
  const role = String(user?.role || "").trim().toLowerCase();
  const platformOwner = Boolean(user?.platformOwner);
  const explicitWorkspaceOwner =
    Boolean(user?.canInviteTeam) &&
    Boolean(user?.canEditBusiness) &&
    Boolean(user?.canManageBilling);
  const isWorkspaceOwner = platformOwner || role === "owner" || explicitWorkspaceOwner;

  return {
    platformOwner,
    isWorkspaceOwner,
    canInviteTeam: platformOwner || Boolean(user?.canInviteTeam) || isWorkspaceOwner,
    canEditBusiness: platformOwner || Boolean(user?.canEditBusiness) || isWorkspaceOwner,
    canManageBilling: platformOwner || Boolean(user?.canManageBilling) || isWorkspaceOwner,
  };
}

export function getVisibleSettingsTabKeys(user) {
  const capabilities = getWorkspaceCapabilities(user);
  const keys = ["profile"];

  if (capabilities.canInviteTeam) keys.push("team");
  if (capabilities.canEditBusiness) keys.push("integrations");

  keys.push("imports");

  if (capabilities.canManageBilling) keys.push("billing");

  keys.push("notifications", "security");

  if (capabilities.isWorkspaceOwner) keys.push("account");

  keys.push("help");
  return keys;
}

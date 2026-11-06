// Safe whole-list contact saves.
//
// The backend stores a workspace's contacts as one list and returns a
// revision for it. A save sends the revision it was built from; if anything
// changed the list since (an import, another tab, a webhook) the server
// answers 409 with the current list instead of overwriting it. The client then
// re-applies only the change the user made and tries again.

export const leadKey = (lead) => String(lead?.id ?? lead?.email ?? "");

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().filter((key) => value[key] !== undefined)
      .map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value === undefined ? null : value);
}

export const sameValue = (a, b) => stable(a) === stable(b);

/** The contacts one user action added, changed or deleted. */
export function diffLeads(previous = [], next = []) {
  const before = new Map(previous.map((lead) => [leadKey(lead), lead]));
  const after = new Map(next.map((lead) => [leadKey(lead), lead]));
  const upserts = [];
  const deletes = [];
  after.forEach((lead, key) => {
    const base = before.get(key);
    if (!base || !sameValue(base, lead)) upserts.push({ key, base: base || null, next: lead });
  });
  before.forEach((base, key) => {
    if (!after.has(key)) deletes.push({ key, base });
  });
  return { upserts, deletes };
}

export const hasChanges = (changes) => Boolean(changes && (changes.upserts.length || changes.deletes.length));

/**
 * Apply a user's changes onto the server's current list.
 *
 * Only the fields the user changed are written, so edits made elsewhere to
 * other fields of the same contact survive. A contact deleted here but changed
 * elsewhere is kept; a contact edited here but deleted elsewhere is restored.
 */
export function applyLeadChanges(server = [], changes = { upserts: [], deletes: [] }) {
  const leads = [...server];
  const position = new Map(leads.map((lead, index) => [leadKey(lead), index]));
  const conflicts = [];
  const label = (lead) => lead?.name || lead?.email || "a contact";

  changes.upserts.forEach(({ key, base, next }) => {
    const index = position.get(key);
    if (index === undefined) {
      if (base) conflicts.push({ key, name: label(next), reason: "restored" });
      position.set(key, leads.length);
      leads.push(next);
      return;
    }
    const current = leads[index];
    if (!base) {
      leads[index] = { ...current, ...next };
      return;
    }
    const merged = { ...current };
    new Set([...Object.keys(base), ...Object.keys(next)]).forEach((field) => {
      if (sameValue(base[field], next[field])) return;
      if (next[field] === undefined) delete merged[field];
      else merged[field] = next[field];
    });
    leads[index] = merged;
  });

  const removed = new Set();
  changes.deletes.forEach(({ key, base }) => {
    const index = position.get(key);
    if (index === undefined) return;
    if (sameValue(leads[index], base)) removed.add(index);
    else conflicts.push({ key, name: label(leads[index]), reason: "changed_elsewhere" });
  });
  return { leads: leads.filter((_, index) => !removed.has(index)), conflicts };
}

/** Apply several change sets in order (unsaved earlier edits first). */
export function applyAllChanges(server = [], changeSets = []) {
  let leads = server;
  const conflicts = [];
  changeSets.filter(hasChanges).forEach((changes) => {
    const result = applyLeadChanges(leads, changes);
    leads = result.leads;
    conflicts.push(...result.conflicts);
  });
  return { leads, conflicts };
}

/**
 * Save `changeSets` against the last list the server confirmed.
 *
 * `server` is { revision, leads } as last returned by the backend and is
 * updated in place with exactly what the server stored. Without a confirmed
 * list, `load()` fetches one first: a whole-list save is never sent without
 * the revision it was built from.
 */
export async function saveLeadChanges({ send, load, server, changeSets, maxAttempts = 3 }) {
  const refresh = async () => {
    const fresh = await load();
    if (!fresh?.revision || !Array.isArray(fresh.leads)) throw new Error("Could not load the latest contacts.");
    server.revision = fresh.revision;
    server.leads = fresh.leads;
  };
  if (!server.revision) await refresh();
  let body = applyAllChanges(server.leads, changeSets);
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const { status, data } = await send({ leads: body.leads, base_revision: server.revision });
    if (status === 409 && data?.error === "leads_changed" && Array.isArray(data.leads) && data.revision) {
      server.revision = data.revision;
      server.leads = data.leads;
      body = applyAllChanges(data.leads, changeSets);
      continue;
    }
    if (status === 428) {
      await refresh();
      body = applyAllChanges(server.leads, changeSets);
      continue;
    }
    if (status >= 200 && status < 300 && data?.ok === true && Number(data?.count) === body.leads.length) {
      // Keep the list exactly as stored (the server may have kept a customer's
      // unsubscribe) paired with its revision, as the base for the next save.
      server.revision = data.revision || "";
      server.leads = Array.isArray(data.leads) ? data.leads : body.leads;
      return { leads: server.leads, conflicts: body.conflicts };
    }
    throw new Error(data?.error || `Could not save customer changes (${status})`);
  }
  throw new Error("Contacts kept changing while saving. Reload the page and try again.");
}

/**
 * What to show after reloading the list while edits are still unsaved.
 *
 * Returns the list to display and the new base for the pending (debounced)
 * edits, so that diffing the display against that base later yields exactly
 * the pending edits: nothing imported or changed elsewhere is reverted.
 */
export function rebaseOnReload({ serverLeads, unsaved = [], pendingBase = null, shown = [] }) {
  const withUnsaved = applyAllChanges(serverLeads, unsaved).leads;
  if (!pendingBase) return { shown: withUnsaved, pendingBase: null };
  const pending = diffLeads(pendingBase, shown);
  return { shown: applyLeadChanges(withUnsaved, pending).leads, pendingBase: withUnsaved };
}

export function conflictMessage(conflicts = []) {
  if (!conflicts.length) return "";
  const kept = conflicts.filter((item) => item.reason === "changed_elsewhere").map((item) => item.name);
  const restored = conflicts.filter((item) => item.reason === "restored").map((item) => item.name);
  const parts = [];
  if (kept.length) parts.push(`not deleted because they were changed elsewhere: ${kept.join(", ")}`);
  if (restored.length) parts.push(`kept with your edits although they were deleted elsewhere: ${restored.join(", ")}`);
  return `Your changes were saved. Some contacts were changed at the same time and were ${parts.join("; ")}.`;
}

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

/**
 * Save `changes` against the last list the server confirmed.
 *
 * `server` is { revision, leads } as last returned by the backend and is
 * updated in place. Without a confirmed list (the first load failed) the
 * caller's full list is sent the old way, with no revision.
 */
export async function saveLeadChanges({ send, server, changes, fallbackLeads, maxAttempts = 3 }) {
  const conflicts = [];
  let body = server.revision ? applyLeadChanges(server.leads, changes) : { leads: fallbackLeads, conflicts: [] };
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    conflicts.push(...body.conflicts);
    const payload = server.revision ? { leads: body.leads, base_revision: server.revision } : { leads: body.leads };
    const { status, data } = await send(payload);
    if (status === 409 && data?.error === "leads_changed" && Array.isArray(data.leads) && data.revision) {
      server.revision = data.revision;
      server.leads = data.leads;
      body = applyLeadChanges(data.leads, changes);
      conflicts.length = 0;
      continue;
    }
    if (status >= 200 && status < 300 && data?.ok === true && Number(data?.count) === body.leads.length) {
      if (data.revision) {
        server.revision = data.revision;
        server.leads = body.leads;
      }
      return { leads: body.leads, conflicts };
    }
    throw new Error(data?.error === "leads_changed" ? "Contacts changed while saving. Reload and try again." : (data?.error || `Could not save customer changes (${status})`));
  }
  throw new Error("Contacts kept changing while saving. Reload the page and try again.");
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

import { vi } from "vitest";
import { applyLeadChanges, conflictMessage, diffLeads, rebaseOnReload, saveLeadChanges } from "./leadSync";

// A stand-in for GET/POST /api/leads with the same contract as the backend,
// including the server keeping a customer's own unsubscribe.
function fakeServer(initial) {
  const state = { leads: initial, revision: 1, posts: [], offline: false };
  const rev = () => `r${state.revision}`;
  state.send = async (payload) => {
    state.posts.push(payload);
    if (!payload.base_revision) return { status: 428, data: { ok: false, code: "revision_required", error: "Reload" } };
    if (payload.base_revision !== rev()) {
      return { status: 409, data: { ok: false, error: "leads_changed", leads: state.leads, revision: rev() } };
    }
    const stored = payload.leads.map((lead) => {
      const prior = state.leads.find((item) => item.id === lead.id);
      return prior?.email_consent_source === "customer_unsubscribe_link"
        ? { ...lead, email_opt_out: true, email_consent_source: "customer_unsubscribe_link" }
        : lead;
    });
    state.leads = stored;
    state.revision += 1;
    return { status: 200, data: { ok: true, count: payload.leads.length, revision: rev(), leads: stored } };
  };
  state.load = async () => {
    if (state.offline) throw new Error("Network down");
    return { revision: rev(), leads: state.leads };
  };
  state.change = (leads) => { state.leads = leads; state.revision += 1; };
  return state;
}

const ana = { id: "a", name: "Ana", email: "ana@example.com", phone: "1" };
const ben = { id: "b", name: "Ben", email: "ben@example.com" };
const cara = { id: "c", name: "Cara", email: "cara@example.com", imported_at: "2026-11-06T00:00:00Z" };
const save = (server, confirmed, changeSets) => saveLeadChanges({ send: server.send, load: server.load, server: confirmed, changeSets });

test("a normal save sends the confirmed revision and keeps the stored list with its revision", async () => {
  const server = fakeServer([ana, ben]);
  const confirmed = await server.load();
  const ui = [{ ...ana, name: "Ana Edited" }, ben];
  const result = await save(server, confirmed, [diffLeads([ana, ben], ui)]);
  expect(server.posts).toEqual([{ leads: ui, base_revision: "r1" }]);
  expect(result.leads).toEqual(ui);
  expect(confirmed).toEqual({ revision: "r2", leads: ui });
});

test("never sends an unversioned save: loads a fresh list first, or fails without sending", async () => {
  const server = fakeServer([ana, ben]);
  server.change([ana, ben, cara]); // imported while this page's first load had failed
  const noConfirmedList = { revision: "", leads: [] };
  await save(server, noConfirmedList, [diffLeads([ana, ben], [ana, { ...ben, name: "Ben Edited" }])]);
  expect(server.posts[0].base_revision).toBe("r2");
  expect(server.leads).toEqual([ana, { ...ben, name: "Ben Edited" }, cara]);

  const offline = fakeServer([ana]);
  offline.offline = true;
  await expect(save(offline, { revision: "", leads: [] }, [diffLeads([ana], [ana, ben])])).rejects.toThrow(/Network down/);
  expect(offline.posts).toEqual([]);
});

test("a 428 from the server reloads the list and retries with a revision", async () => {
  const server = fakeServer([ana]);
  const send = vi.fn()
    .mockResolvedValueOnce({ status: 428, data: { ok: false, code: "revision_required" } })
    .mockImplementation(server.send);
  await saveLeadChanges({ send, load: server.load, server: { revision: "stale-but-present", leads: [ana] }, changeSets: [diffLeads([ana], [ana, ben])] });
  expect(server.leads).toEqual([ana, ben]);
});

test("a save built before an import keeps the imported contact and the user's edit", async () => {
  const server = fakeServer([ana, ben]);
  const confirmed = await server.load(); // page loaded before the import
  server.change([ana, ben, cara]);
  const ui = [{ ...ana, name: "Ana Edited" }, ben];
  const result = await save(server, confirmed, [diffLeads([ana, ben], ui)]);
  expect(server.posts.map((post) => post.base_revision)).toEqual(["r1", "r2"]);
  expect(server.leads).toEqual([{ ...ana, name: "Ana Edited" }, ben, cara]);
  expect(result.conflicts).toEqual([]);
});

test("the stored list keeps a customer's unsubscribe, so the next save cannot drop it", async () => {
  const unsubscribed = { ...ben, email_opt_out: true, email_consent_source: "customer_unsubscribe_link" };
  const server = fakeServer([ana, unsubscribed]);
  const confirmed = { revision: "r1", leads: [ana, ben] }; // a page that never saw the unsubscribe
  server.leads = [ana, unsubscribed];
  const first = await save(server, confirmed, [diffLeads([ana, ben], [ana, { ...ben, name: "Benjamin" }])]);
  expect(first.leads[1]).toMatchObject({ name: "Benjamin", email_opt_out: true });
  expect(confirmed.leads[1].email_opt_out).toBe(true);
  // Next save from the returned base: only the edited field is sent as a change.
  await save(server, confirmed, [diffLeads(first.leads, [{ ...ana, name: "Ana 2" }, first.leads[1]])]);
  expect(server.leads[1]).toMatchObject({ email_opt_out: true, email_consent_source: "customer_unsubscribe_link" });
});

test("two tabs saving from the same revision keep both edits, field by field", async () => {
  const server = fakeServer([ana, ben]);
  const tabOne = await server.load();
  const tabTwo = await server.load();
  await save(server, tabOne, [diffLeads([ana, ben], [{ ...ana, name: "Ana One" }, ben])]);
  await save(server, tabTwo, [diffLeads([ana, ben], [{ ...ana, phone: "2" }, { ...ben, name: "Ben Two" }])]);
  expect(server.leads).toEqual([{ ...ana, name: "Ana One", phone: "2" }, { ...ben, name: "Ben Two" }]);
});

test("a pending debounced edit survives an import reload and saves without reverting it", async () => {
  const server = fakeServer([ana, ben]);
  const confirmed = await server.load();
  // The user edits Ben; the debounced save has not fired yet.
  let pendingBase = [ana, ben];
  let shown = [ana, { ...ben, name: "Ben Pending" }];
  // An import lands and the dashboard reloads (leads:changed).
  server.change([ana, ben, cara]);
  const fresh = await server.load();
  Object.assign(confirmed, fresh);
  ({ shown, pendingBase } = rebaseOnReload({ serverLeads: fresh.leads, pendingBase, shown }));
  expect(shown).toEqual([ana, { ...ben, name: "Ben Pending" }, cara]);
  // Another edit while still pending, then the timer fires.
  shown = shown.map((lead) => (lead.id === "a" ? { ...lead, name: "Ana Later" } : lead));
  await save(server, confirmed, [diffLeads(pendingBase, shown)]);
  expect(server.leads).toEqual([{ ...ana, name: "Ana Later" }, { ...ben, name: "Ben Pending" }, cara]);
});

test("queued and failed edits are kept and sent in order with the next save", async () => {
  const server = fakeServer([ana, ben]);
  const confirmed = await server.load();
  const failedEarlier = diffLeads([ana, ben], [{ ...ana, name: "Ana Offline" }, ben]);
  // A reload while that edit is unsaved still shows it.
  server.change([ana, ben, cara]);
  const view = rebaseOnReload({ serverLeads: server.leads, unsaved: [failedEarlier] });
  expect(view.shown[0].name).toBe("Ana Offline");
  const next = diffLeads(view.shown, view.shown.map((lead) => (lead.id === "c" ? { ...lead, phone: "9" } : lead)));
  await save(server, confirmed, [failedEarlier, next]);
  expect(server.leads).toEqual([{ ...ana, name: "Ana Offline" }, ben, { ...cara, phone: "9" }]);
});

test("deleting a contact that changed elsewhere keeps it and says so", async () => {
  const server = fakeServer([ana, ben]);
  const confirmed = await server.load();
  server.change([ana, { ...ben, notes: "Called today" }]);
  const result = await save(server, confirmed, [diffLeads([ana, ben], [ana])]);
  expect(server.leads.map((lead) => lead.id)).toEqual(["a", "b"]);
  expect(result.conflicts).toEqual([{ key: "b", name: "Ben", reason: "changed_elsewhere" }]);
  expect(conflictMessage(result.conflicts)).toMatch(/not deleted because they were changed elsewhere: Ben/);
});

test("an unchanged deletion and a new contact apply cleanly", () => {
  const changes = diffLeads([ana, ben], [{ id: "d", name: "Dev" }, ana]);
  const { leads, conflicts } = applyLeadChanges([ana, ben, cara], changes);
  expect(leads.map((lead) => lead.id)).toEqual(["a", "c", "d"]);
  expect(conflicts).toEqual([]);
});

test("gives up with a clear error if the list keeps changing", async () => {
  let revision = 1;
  const send = async () => ({ status: 409, data: { ok: false, error: "leads_changed", leads: [ana], revision: `r${++revision}` } });
  await expect(saveLeadChanges({ send, load: async () => ({ revision: "r1", leads: [ana] }), server: { revision: "r1", leads: [ana] }, changeSets: [diffLeads([ana], [ben])] }))
    .rejects.toThrow(/kept changing/);
});

test("createLeadsApi + saveFreshLeadChanges: loads first, patches one contact, sends the revision", async () => {
  const { createLeadsApi, leadPatchChanges, saveFreshLeadChanges } = await vi.importActual("./leadSync");
  const requests = [];
  const fetchImpl = vi.fn(async (url, options) => {
    requests.push({ url, method: options.method, body: options.body ? JSON.parse(options.body) : null, headers: options.headers });
    if (options.method === "GET") return { ok: true, status: 200, json: async () => ({ leads: [{ ...ana, name: "Newer" }, cara], revision: "r7" }) };
    const body = JSON.parse(options.body);
    return { ok: true, status: 200, json: async () => ({ ok: true, count: body.leads.length, revision: "r8", leads: body.leads }) };
  });
  const result = await saveFreshLeadChanges(createLeadsApi("owner@example.com", fetchImpl), [leadPatchChanges(ana, { notes: "Hi" })]);
  expect(requests.map((request) => request.method)).toEqual(["GET", "POST"]);
  expect(requests[1].url).toMatch(/\/api\/leads$/);
  expect(requests[1].headers["X-User-Email"]).toBe("owner@example.com");
  expect(requests[1].body).toEqual({ leads: [{ ...ana, name: "Newer", notes: "Hi" }, cara], base_revision: "r7" });
  expect(result.leads).toEqual(requests[1].body.leads);
});

test("a field patch never recreates a contact deleted elsewhere", async () => {
  const { leadPatchChanges } = await vi.importActual("./leadSync");
  const { leads, conflicts } = applyLeadChanges([cara], leadPatchChanges(ana, { notes: "Hi" }));
  expect(leads).toEqual([cara]);
  expect(conflicts).toEqual([{ key: "a", name: "Ana", reason: "missing" }]);
});

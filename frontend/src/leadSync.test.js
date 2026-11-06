import { applyLeadChanges, conflictMessage, diffLeads, saveLeadChanges } from "./leadSync";

// A stand-in for POST /api/leads with the same contract as the backend.
function fakeServer(initial) {
  const state = { leads: initial, revision: 1, posts: [] };
  state.send = async (payload) => {
    state.posts.push(payload);
    if (payload.base_revision !== undefined && payload.base_revision !== `r${state.revision}`) {
      return { status: 409, data: { ok: false, error: "leads_changed", leads: state.leads, revision: `r${state.revision}` } };
    }
    state.leads = payload.leads;
    state.revision += 1;
    return { status: 200, data: { ok: true, count: payload.leads.length, revision: `r${state.revision}` } };
  };
  state.load = () => ({ revision: `r${state.revision}`, leads: state.leads });
  state.importContact = (lead) => { state.leads = [...state.leads, lead]; state.revision += 1; };
  return state;
}

const ana = { id: "a", name: "Ana", email: "ana@example.com", phone: "1" };
const ben = { id: "b", name: "Ben", email: "ben@example.com" };
const cara = { id: "c", name: "Cara", email: "cara@example.com", imported_at: "2026-11-06T00:00:00Z" };

test("a normal save sends the confirmed revision and keeps working without one", async () => {
  const server = fakeServer([ana, ben]);
  const confirmed = server.load();
  const ui = [{ ...ana, name: "Ana Edited" }, ben];
  const result = await saveLeadChanges({ send: server.send, server: confirmed, changes: diffLeads([ana, ben], ui), fallbackLeads: ui });
  expect(server.posts[0].base_revision).toBe("r1");
  expect(result.leads).toEqual(ui);
  expect(confirmed.revision).toBe("r2");

  // No confirmed list (the first load failed): the old full-list save is used.
  const legacy = fakeServer([ana]);
  await saveLeadChanges({ send: legacy.send, server: { revision: "", leads: [] }, changes: diffLeads([ana], [ana, ben]), fallbackLeads: [ana, ben] });
  expect(legacy.posts[0]).toEqual({ leads: [ana, ben] });
});

test("a save built before an import keeps the imported contact and the user's edit", async () => {
  const server = fakeServer([ana, ben]);
  const confirmed = server.load(); // page loaded before the import
  server.importContact(cara);
  const before = [ana, ben];
  const ui = [{ ...ana, name: "Ana Edited" }, ben];
  const result = await saveLeadChanges({ send: server.send, server: confirmed, changes: diffLeads(before, ui), fallbackLeads: ui });
  expect(server.posts.map((post) => post.base_revision)).toEqual(["r1", "r2"]);
  expect(server.leads).toEqual([{ ...ana, name: "Ana Edited" }, ben, cara]);
  expect(result.leads).toEqual(server.leads);
  expect(result.conflicts).toEqual([]);
});

test("two tabs saving from the same revision keep both edits, field by field", async () => {
  const server = fakeServer([ana, ben]);
  const tabOne = server.load();
  const tabTwo = server.load();
  await saveLeadChanges({ send: server.send, server: tabOne, changes: diffLeads([ana, ben], [{ ...ana, name: "Ana One" }, ben]) });
  await saveLeadChanges({ send: server.send, server: tabTwo, changes: diffLeads([ana, ben], [{ ...ana, phone: "2" }, { ...ben, name: "Ben Two" }]) });
  expect(server.leads).toEqual([{ ...ana, name: "Ana One", phone: "2" }, { ...ben, name: "Ben Two" }]);
});

test("deleting a contact that changed elsewhere keeps it and says so", async () => {
  const server = fakeServer([ana, ben]);
  const confirmed = server.load();
  await server.send({ leads: [ana, { ...ben, notes: "Called today" }], base_revision: "r1" });
  const result = await saveLeadChanges({ send: server.send, server: confirmed, changes: diffLeads([ana, ben], [ana]) });
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
  await expect(saveLeadChanges({ send, server: { revision: "r1", leads: [ana] }, changes: diffLeads([ana], [ben]) }))
    .rejects.toThrow(/kept changing/);
});

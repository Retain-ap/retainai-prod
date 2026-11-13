import { CONTACT_SNOOZE_DAYS, businessKind, dayStart, dueForRebooking, rebookingSuggestions, visitsByLead, waitingToBook } from "./rebooking";

const visit = (lead, date, extra = {}) => ({ lead, date, time: "10:00", ...extra });
const done = (lead, date) => visit(lead, date, { status: "completed", _backend: {} });
const today = "2026-11-06";

test("uses the customer's own completed-visit rhythm and explains it", () => {
  const ana = { id: "a", name: "Ana" };
  const [item] = rebookingSuggestions({
    leads: [ana],
    appointments: [done(ana, "2026-07-01"), done(ana, "2026-08-05"), done(ana, "2026-09-09"), done(ana, "2026-10-10")],
    user: {},
    today,
  });
  expect(item.basis).toBe("personal");
  expect(item.intervalDays).toBe(35); // median of 35, 35, 31
  expect(item.lastVisit).toBe("2026-10-10");
  expect(item.dueDate).toBe("2026-11-14");
  expect(item.daysUntilDue).toBe(8);
  expect(item.reasons.join(" ")).toMatch(/median of 3 gaps between 4 completed visits/);
});

test("ignores cancelled, no-show and duplicate visits, and treats legacy done flags as completed", () => {
  const ben = { id: "b", email: "ben@example.com" };
  const visits = visitsByLead([
    done(ben, "2026-09-01"),
    done(ben, "2026-09-02"), // same visit recorded twice
    visit(ben, "2026-09-20", { status: "cancelled", done: true, _backend: {} }),
    visit(ben, "2026-09-25", { status: "no-show", done: true, _backend: {} }),
    visit(ben, "2026-10-01", { done: true }), // legacy appointment on the contact
    visit(ben, "2026-12-01", { status: "scheduled", _backend: {} }),
  ]).get("b");
  expect(visits.completed.map((day) => new Date(day).toISOString().slice(0, 10))).toEqual(["2026-09-01", "2026-10-01"]);
  expect(visits.upcoming).toHaveLength(1);
});

test("falls back from one interval, to the workspace rhythm, to a business default", () => {
  const regulars = ["r1", "r2", "r3"].map((id) => ({ id }));
  const history = regulars.flatMap((lead) => [done(lead, "2026-06-01"), done(lead, "2026-07-01"), done(lead, "2026-07-31")]);
  const pair = { id: "p" };
  const single = { id: "s" };
  const result = rebookingSuggestions({
    leads: [...regulars, pair, single],
    appointments: [...history, done(pair, "2026-08-01"), done(pair, "2026-09-12"), done(single, "2026-10-01")],
    user: {},
    today,
  });
  const byId = Object.fromEntries(result.map((item) => [item.lead.id, item]));
  expect(byId.p.basis).toBe("personal_single");
  expect(byId.p.intervalDays).toBe(42);
  expect(byId.s.basis).toBe("workspace");
  expect(byId.s.intervalDays).toBe(30);

  const alone = rebookingSuggestions({ leads: [single], appointments: [done(single, "2026-10-01")], user: { businessType: "Barber shop" }, today })[0];
  expect(alone.basis).toBe("default");
  expect(alone.intervalDays).toBe(28);
  expect(alone.reasons.join(" ")).toMatch(/barbershop default/);
  expect(rebookingSuggestions({ leads: [single], appointments: [done(single, "2026-10-01")], user: {}, today })[0].intervalDays).toBe(60);
});

test("an interval the owner set wins, and booked or not-yet-due customers are not flagged", () => {
  const ana = { id: "a", rebook_interval_days: 14 };
  const ben = { id: "b" };
  const cleo = { id: "c" };
  const suggestions = rebookingSuggestions({
    leads: [ana, ben, cleo],
    appointments: [
      done(ana, "2026-10-01"),
      done(ben, "2026-08-01"), done(ben, "2026-09-01"), visit(ben, "2026-11-10", { status: "scheduled", _backend: {} }),
      done(cleo, "2026-10-01"), done(cleo, "2026-11-01"),
    ],
    user: {},
    today,
  });
  const byId = Object.fromEntries(suggestions.map((item) => [item.lead.id, item]));
  expect(byId.a.basis).toBe("override");
  expect(byId.a.daysUntilDue).toBe(-22);
  expect(byId.b.bookedFor).toBe("2026-11-10");
  expect(dueForRebooking(suggestions).map((item) => item.lead.id)).toEqual(["a"]);
});

test("customers without a completed visit get no rebooking date", () => {
  expect(rebookingSuggestions({ leads: [{ id: "x" }], appointments: [], user: {}, today })).toEqual([]);
  expect(businessKind({ setup_preset: "salon_barber" })).toBe("salon");
  expect(businessKind({ businessType: "Consulting" })).toBe("general");
});

test("impossible dates are ignored and visits dated in the future are never completion evidence", () => {
  const ana = { id: "a" };
  const result = rebookingSuggestions({
    leads: [ana],
    appointments: [
      done(ana, "2026-08-01"), done(ana, "2026-09-01"),
      done(ana, "2026-02-31"), // not a real date (would roll over to March 3)
      done(ana, "2026-13-01"),
      done(ana, "2026-12-25"), // marked completed but in the future
    ],
    user: {},
    today,
  });
  expect(result[0].completedVisits).toBe(2);
  expect(result[0].lastVisit).toBe("2026-09-01");
  expect(result[0].intervalDays).toBe(31);
  expect(dayStart("2026-02-31")).toBeNull();
  expect(dayStart("2026-02-28")).toBe(Date.UTC(2026, 1, 28));
  expect(rebookingSuggestions({ leads: [ana], appointments: [done(ana, "2026-09-01")], user: {}, today: "not-a-date" })).toEqual([]);
});

test("a due customer contacted in the last week waits to book instead of staying on the contact list", () => {
  const leads = [
    { id: "fresh", last_outreach_at: "2026-11-04T15:00:00Z" }, // contacted 2 days ago
    { id: "stale", last_outreach_at: "2026-10-26T15:00:00Z" }, // contacted 11 days ago: back on the list
    { id: "before", last_outreach_at: "2026-09-20T15:00:00Z" }, // contact before the last visit is not a follow-up
    { id: "never" },
  ];
  const suggestions = rebookingSuggestions({
    leads,
    appointments: leads.map((lead) => done(lead, "2026-10-01")),
    user: { businessType: "Barber shop" },
    today,
  });
  const byId = Object.fromEntries(suggestions.map((item) => [item.lead.id, item]));
  expect(byId.fresh).toMatchObject({ contactedOn: "2026-11-04", waitingUntil: "2026-11-11", contactedRecently: true });
  expect(byId.stale).toMatchObject({ contactedOn: "2026-10-26", contactedRecently: false });
  expect(byId.before).toMatchObject({ contactedOn: "", contactedRecently: false });
  expect(dueForRebooking(suggestions).map((item) => item.lead.id).sort()).toEqual(["before", "never", "stale"]);
  expect(waitingToBook(suggestions).map((item) => item.lead.id)).toEqual(["fresh"]);
  expect(CONTACT_SNOOZE_DAYS).toBe(7);
});

test("a booked customer is neither due nor waiting, even if contacted", () => {
  const lead = { id: "booked", last_outreach_at: "2026-11-04T15:00:00Z" };
  const suggestions = rebookingSuggestions({
    leads: [lead],
    appointments: [done(lead, "2026-09-01"), visit(lead, "2026-11-20", { status: "scheduled", _backend: {} })],
    user: {},
    today,
  });
  expect(dueForRebooking(suggestions)).toEqual([]);
  expect(waitingToBook(suggestions)).toEqual([]);
});

test("creating a contact (which stamps last_contacted) does not count as following up", () => {
  const lead = { id: "new", last_contacted: "2026-11-05T09:00:00Z", createdAt: "2026-11-05T09:00:00Z" };
  const [item] = rebookingSuggestions({ leads: [lead], appointments: [done(lead, "2026-09-01")], user: {}, today });
  expect(item.contactedRecently).toBe(false);
  expect(dueForRebooking([item])).toHaveLength(1);
});

describe("outreach days are compared in the workspace's own time zone", () => {
  // Visits on Oct 1 with a 28-day barber default: due Oct 29, so overdue on Nov 6.
  const suggest = (lastOutreachAt, timeZone) => {
    const lead = { id: "x", last_outreach_at: lastOutreachAt };
    return rebookingSuggestions({ leads: [lead], appointments: [done(lead, "2026-10-01")], user: { businessType: "Barber shop" }, today, timeZone })[0];
  };

  test("a Toronto evening follow-up (already tomorrow in UTC) counts today, not tomorrow", () => {
    const item = suggest("2026-11-07T01:30:00Z", "America/Toronto"); // Nov 6, 8:30 pm in Toronto
    expect(item).toMatchObject({ contactedOn: "2026-11-06", waitingUntil: "2026-11-13", contactedRecently: true });
    expect(dueForRebooking([item])).toEqual([]);
    expect(waitingToBook([item])).toHaveLength(1);
  });

  test("an Auckland morning follow-up (still yesterday in UTC) uses the Auckland day at the 7-day boundary", () => {
    const item = suggest("2026-10-30T12:30:00Z", "Pacific/Auckland"); // Oct 31, 1:30 am in Auckland: 6 days ago
    expect(item).toMatchObject({ contactedOn: "2026-10-31", contactedRecently: true });
    expect(waitingToBook([item])).toHaveLength(1);
  });

  test("seven local days after the follow-up the customer is back on the list", () => {
    const sevenDaysAgo = suggest("2026-10-31T00:30:00Z", "America/Toronto"); // Oct 30, 8:30 pm in Toronto
    expect(sevenDaysAgo).toMatchObject({ contactedOn: "2026-10-30", waitingUntil: "2026-11-06", contactedRecently: false });
    expect(dueForRebooking([sevenDaysAgo])).toHaveLength(1);
    const sixDaysAgo = suggest("2026-10-31T23:30:00Z", "America/Toronto"); // Oct 31, 7:30 pm in Toronto
    expect(sixDaysAgo).toMatchObject({ contactedOn: "2026-10-31", contactedRecently: true });
    expect(dueForRebooking([sixDaysAgo])).toEqual([]);
  });

  test("a follow-up later in the workspace's future day is not counted yet", () => {
    // 11 pm Nov 6 in Auckland is still Nov 6 for an Auckland workspace, but Nov 7 for one in London.
    expect(suggest("2026-11-06T10:00:00Z", "Pacific/Auckland").contactedOn).toBe("2026-11-06");
    expect(suggest("2026-11-07T10:00:00Z", "Europe/London").contactedOn).toBe("");
  });
});

test("reviewer case: a Toronto follow-up at 10 pm Nov 12 (03:00 UTC Nov 13) is waiting on Nov 12, not due", () => {
  const lead = { id: "r", last_outreach_at: "2026-11-13T03:00:00Z" };
  const suggestions = rebookingSuggestions({ leads: [lead], appointments: [done(lead, "2026-10-01")], user: { businessType: "Barber shop" }, today: "2026-11-12", timeZone: "America/Toronto" });
  expect(suggestions[0].daysUntilDue).toBeLessThan(0); // overdue since Oct 29
  expect(dueForRebooking(suggestions)).toHaveLength(0);
  expect(waitingToBook(suggestions)).toHaveLength(1);
});

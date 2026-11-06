import { businessKind, dayStart, dueForRebooking, rebookingSuggestions, visitsByLead } from "./rebooking";

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

import {
  addDaysToDateKey,
  appointmentDateKey,
  appointmentTimeKey,
  buildAppointmentTimestamp,
  calendarDayDistance,
  compareAppointmentToNow,
  dayKeyNow,
  parseAppointmentDateTime,
  timeKeyNow,
} from "./appointmentDateTime";

describe("appointment date/time contract", () => {
  test("renders an offset timestamp in the workspace timezone without shifting the day", () => {
    const value = "2026-09-04T01:30:00Z";
    expect(appointmentDateKey(value, "America/Toronto")).toBe("2026-09-03");
    expect(appointmentTimeKey(value, "America/Toronto")).toBe("21:30");
  });

  test("keeps date-only and legacy naive values as wall-clock values", () => {
    expect(appointmentDateKey("2026-09-03", "America/Toronto")).toBe("2026-09-03");
    expect(appointmentDateKey("2026-09-03T10:15:00", "America/Vancouver")).toBe("2026-09-03");
    expect(appointmentTimeKey("2026-09-03T10:15:00", "America/Vancouver")).toBe("10:15");
  });

  test("builds only valid datetime-local payloads", () => {
    expect(buildAppointmentTimestamp("2026-09-03", "10:15")).toBe("2026-09-03T10:15:00");
    expect(buildAppointmentTimestamp("2026-02-30", "10:15")).toBe("");
    expect(buildAppointmentTimestamp("2026-09-03", "25:00")).toBe("");
  });

  test("classifies same-day appointments by the workspace wall clock", () => {
    const now = new Date("2026-09-04T01:30:00Z"); // Sep 3, 21:30 in Toronto
    expect(dayKeyNow("America/Toronto", now)).toBe("2026-09-03");
    expect(timeKeyNow("America/Toronto", now)).toBe("21:30");
    expect(compareAppointmentToNow("2026-09-03", "21:00", "America/Toronto", now)).toBe(-1);
    expect(compareAppointmentToNow("2026-09-03", "22:00", "America/Toronto", now)).toBe(1);
  });

  test("calendar-day math is stable across daylight-saving boundaries", () => {
    expect(addDaysToDateKey("2026-03-07", 1)).toBe("2026-03-08");
    expect(calendarDayDistance("2026-03-07", "2026-03-14")).toBe(7);
  });

  test("rejects invalid timestamps", () => {
    expect(parseAppointmentDateTime("not-a-date")).toBeNull();
  });
});

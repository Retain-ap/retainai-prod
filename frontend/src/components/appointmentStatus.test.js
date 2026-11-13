import { appointmentStatus, appointmentTimezoneLabel } from "./appointmentStatus";

test.each(["cancelled", "canceled", "CANCELLED"])("%s is not a completion even when imported terminal flags are true", (status) => {
  expect(appointmentStatus({ status, done: true, is_done: true, completed: true })).toBe("cancelled");
});

test.each(["no_show", "no-show", "No show"])("%s is not a completion even when imported terminal flags are true", (status) => {
  expect(appointmentStatus({ status, done: true, is_done: true })).toBe("no_show");
});

test("retains explicitly completed and legacy completed visits", () => {
  expect(appointmentStatus({ status: "completed", done: false })).toBe("completed");
  expect(appointmentStatus({ done: true })).toBe("completed");
  expect(appointmentStatus({ completed: true })).toBe("completed");
  expect(appointmentStatus({ is_done: true })).toBe("completed");
  expect(appointmentStatus({ done: false })).toBe("scheduled");
});

test("timezone labels preserve UTC and IANA Etc offsets", () => {
  expect(appointmentTimezoneLabel("America/Toronto")).toBe("Toronto time");
  expect(appointmentTimezoneLabel("America/New_York")).toBe("New York time");
  expect(appointmentTimezoneLabel("UTC")).toBe("UTC");
  expect(appointmentTimezoneLabel("Etc/GMT+5")).toBe("Etc/GMT+5");
  expect(appointmentTimezoneLabel("")).toBe("");
});

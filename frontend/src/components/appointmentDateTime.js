const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
const LOCAL_DATE_TIME =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/;
const OFFSET_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i;

const pad2 = (value) => String(value).padStart(2, "0");

function validLocalDate(parts) {
  const date = new Date(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour || 0,
    parts.minute || 0,
    parts.second || 0,
    parts.millisecond || 0
  );
  return (
    date.getFullYear() === parts.year &&
    date.getMonth() === parts.month - 1 &&
    date.getDate() === parts.day &&
    date.getHours() === (parts.hour || 0) &&
    date.getMinutes() === (parts.minute || 0)
  );
}

function sourceParts(value) {
  const raw = String(value || "").trim();
  const dateOnlyMatch = raw.match(DATE_ONLY);
  if (dateOnlyMatch) {
    const parts = {
      year: Number(dateOnlyMatch[1]),
      month: Number(dateOnlyMatch[2]),
      day: Number(dateOnlyMatch[3]),
      hour: 0,
      minute: 0,
      second: 0,
      millisecond: 0,
    };
    return validLocalDate(parts) ? parts : null;
  }

  const localMatch = raw.match(LOCAL_DATE_TIME);
  if (!localMatch) return null;
  const milliseconds = String(localMatch[7] || "").padEnd(3, "0").slice(0, 3);
  const parts = {
    year: Number(localMatch[1]),
    month: Number(localMatch[2]),
    day: Number(localMatch[3]),
    hour: Number(localMatch[4]),
    minute: Number(localMatch[5]),
    second: Number(localMatch[6] || 0),
    millisecond: Number(milliseconds || 0),
  };
  return validLocalDate(parts) ? parts : null;
}

export function isValidTimeZone(timeZone) {
  if (!timeZone) return false;
  try {
    new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date());
    return true;
  } catch {
    return false;
  }
}

export function getBrowserTimeZone() {
  try {
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return isValidTimeZone(timeZone) ? timeZone : "UTC";
  } catch {
    return "UTC";
  }
}

export function parseAppointmentDateTime(value) {
  if (value instanceof Date) {
    const clone = new Date(value.getTime());
    return Number.isNaN(clone.getTime()) ? null : clone;
  }
  if (typeof value === "number") {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  const raw = String(value || "").trim();
  if (!raw) return null;
  const parts = !OFFSET_SUFFIX.test(raw) ? sourceParts(raw) : null;
  if (parts) {
    return new Date(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
      parts.millisecond
    );
  }

  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function partsInTimeZone(date, timeZone) {
  if (!date || Number.isNaN(date.getTime()) || !isValidTimeZone(timeZone)) return null;
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const values = {};
  formatter.formatToParts(date).forEach((part) => {
    if (part.type !== "literal") values[part.type] = part.value;
  });
  return {
    year: Number(values.year),
    month: Number(values.month),
    day: Number(values.day),
    hour: Number(values.hour),
    minute: Number(values.minute),
    second: Number(values.second),
  };
}

export function appointmentDateTimeParts(value, timeZone) {
  const raw = String(value || "").trim();
  if (!OFFSET_SUFFIX.test(raw)) {
    const wallClock = sourceParts(raw);
    if (wallClock) return wallClock;
  }

  const date = parseAppointmentDateTime(value);
  if (!date) return null;
  const zoned = partsInTimeZone(date, timeZone);
  if (zoned) return zoned;
  return {
    year: date.getFullYear(),
    month: date.getMonth() + 1,
    day: date.getDate(),
    hour: date.getHours(),
    minute: date.getMinutes(),
    second: date.getSeconds(),
  };
}

export function dateKeyFromParts(parts) {
  if (!parts) return "";
  return `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}`;
}

export function timeKeyFromParts(parts) {
  if (!parts) return "";
  return `${pad2(parts.hour)}:${pad2(parts.minute)}`;
}

export function appointmentDateKey(value, timeZone) {
  return dateKeyFromParts(appointmentDateTimeParts(value, timeZone));
}

export function appointmentTimeKey(value, timeZone) {
  return timeKeyFromParts(appointmentDateTimeParts(value, timeZone));
}

export function localDateKey(value = new Date()) {
  const date = parseAppointmentDateTime(value);
  if (!date) return "";
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

export function dayKeyNow(timeZone, now = new Date()) {
  const zoned = partsInTimeZone(parseAppointmentDateTime(now), timeZone);
  return zoned ? dateKeyFromParts(zoned) : localDateKey(now);
}

export function timeKeyNow(timeZone, now = new Date()) {
  const parsed = parseAppointmentDateTime(now);
  const zoned = partsInTimeZone(parsed, timeZone);
  if (zoned) return timeKeyFromParts(zoned);
  return parsed
    ? `${pad2(parsed.getHours())}:${pad2(parsed.getMinutes())}`
    : "";
}

/**
 * Compare a wall-clock appointment with the current wall clock in its
 * workspace timezone. This deliberately does not turn a legacy naive value
 * into a browser-local instant, which is what caused same-day appointments to
 * jump between Today and Overdue for users outside the business timezone.
 */
export function compareAppointmentToNow(dateKey, timeKey, timeZone, now = new Date()) {
  const appointmentDay = String(dateKey || "");
  const today = dayKeyNow(timeZone, now);
  const dayDistance = calendarDayDistance(today, appointmentDay);
  if (!Number.isFinite(dayDistance)) return Number.NaN;
  if (dayDistance !== 0) return dayDistance < 0 ? -1 : 1;

  const appointmentTime = /^\d{2}:\d{2}$/.test(String(timeKey || ""))
    ? String(timeKey)
    : "00:00";
  const currentTime = timeKeyNow(timeZone, now);
  if (!currentTime) return Number.NaN;
  return appointmentTime < currentTime ? -1 : appointmentTime > currentTime ? 1 : 0;
}

export function appointmentMonthKey(value, timeZone) {
  const dateKey = appointmentDateKey(value, timeZone);
  return dateKey ? dateKey.slice(0, 7) : "";
}

export function localDateFromKey(dateKey, hour = 12) {
  const parts = sourceParts(`${dateKey}T${pad2(hour)}:00:00`);
  if (!parts) return null;
  return new Date(parts.year, parts.month - 1, parts.day, parts.hour, 0, 0, 0);
}

export function buildAppointmentTimestamp(dateKey, timeKey) {
  const dateMatch = String(dateKey || "").match(DATE_ONLY);
  const timeMatch = String(timeKey || "").match(/^(\d{2}):(\d{2})$/);
  if (!dateMatch || !timeMatch) return "";
  const candidate = `${dateKey}T${timeKey}:00`;
  return sourceParts(candidate) ? candidate : "";
}

export function addDaysToDateKey(dateKey, days) {
  const match = String(dateKey || "").match(DATE_ONLY);
  if (!match) return "";
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  if (Number.isNaN(date.getTime())) return "";
  date.setUTCDate(date.getUTCDate() + Number(days || 0));
  return `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())}`;
}

export function calendarDayDistance(fromDateKey, toDateKey) {
  const from = String(fromDateKey || "").match(DATE_ONLY);
  const to = String(toDateKey || "").match(DATE_ONLY);
  if (!from || !to) return Number.NaN;
  const fromValue = Date.UTC(Number(from[1]), Number(from[2]) - 1, Number(from[3]));
  const toValue = Date.UTC(Number(to[1]), Number(to[2]) - 1, Number(to[3]));
  return Math.round((toValue - fromValue) / 86400000);
}

export function formatDateKey(dateKey, options = {}) {
  const date = localDateFromKey(dateKey);
  if (!date) return "";
  return new Intl.DateTimeFormat(undefined, {
    timeZone: "UTC",
    ...options,
  }).format(new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate(), 12)));
}

export function formatTimeKey(timeKey, options = {}) {
  const match = String(timeKey || "").match(/^(\d{2}):(\d{2})$/);
  if (!match) return "";
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) return "";
  return new Intl.DateTimeFormat(undefined, {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    ...options,
  }).format(new Date(Date.UTC(2000, 0, 1, hour, minute)));
}

/** Provider imports use `done` for all terminal visits, including cancellations.
 * Only the explicit outcome tells us whether a customer actually attended.
 * Older locally saved appointments have just a completion flag.
 */
export function appointmentStatus(appointment) {
  const status = String(appointment?.status || "").trim().toLowerCase().replace(/[- ]/g, "_");
  if (status === "cancelled" || status === "canceled") return "cancelled";
  if (status === "no_show" || status === "noshow") return "no_show";
  if (status === "completed") return "completed";
  return (appointment?.done ?? appointment?.completed ?? appointment?.is_done)
    ? "completed"
    : "scheduled";
}

export function appointmentStatusLabel(status) {
  return { cancelled: "Cancelled", no_show: "No-show", completed: "Completed" }[status] || "Scheduled";
}

export function appointmentTimezoneLabel(timeZone) {
  const zone = String(timeZone || "").trim();
  if (!zone) return "";
  if (zone === "UTC" || zone === "Etc/UTC") return "UTC";
  // Keep Etc/GMT offsets intact: their IANA sign has the opposite convention
  // from an ordinary displayed UTC offset.
  if (zone.startsWith("Etc/")) return zone;
  return `${zone.split("/").pop().replace(/_/g, " ")} time`;
}

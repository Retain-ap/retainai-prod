// src/components/LeadDrawer.jsx
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { QRCodeSVG } from "qrcode.react";

const API_BASE =
  (process.env.REACT_APP_API_BASE && process.env.REACT_APP_API_BASE.trim()) ||
  (process.env.REACT_APP_API_URL && process.env.REACT_APP_API_URL.trim()) ||
  window.location.origin.replace(/\/$/, "");

function migrateNotesToUpdates(lead) {
  if (lead?.updates && Array.isArray(lead.updates)) return lead.updates;
  if (lead?.notes) {
    return [
      {
        type: "note",
        text: lead.notes,
        date: lead.createdAt || lead.created_at || new Date().toISOString(),
        author: "user",
      },
    ];
  }
  return [];
}

function formatDateTime(v) {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleString();
  } catch {
    return String(v);
  }
}

function formatDateOnly(v) {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleDateString();
  } catch {
    return String(v);
  }
}

function firstTwo(value) {
  return (value || "??").slice(0, 2).toUpperCase();
}

function getStatusMeta(status) {
  if (status === "cold") {
    return {
      label: "Overdue",
      bg: "rgba(230,101,101,0.18)",
      border: "rgba(230,101,101,0.45)",
      color: "#ff8a8a",
      helper: "Overdue for follow up",
    };
  }
  if (status === "warning") {
    return {
      label: "Follow Up",
      bg: "rgba(247,203,83,0.18)",
      border: "rgba(247,203,83,0.45)",
      color: "#f7cb53",
      helper: "Time to follow up",
    };
  }
  return {
    label: "Active",
    bg: "rgba(27,201,130,0.18)",
    border: "rgba(27,201,130,0.45)",
    color: "#62e4aa",
    helper: "Active and up to date",
  };
}

function normalizeReminder(r) {
  if (typeof r === "string") {
    return {
      id: `rem_${Date.now()}_${Math.random().toString(16).slice(2)}`,
      text: r,
      date: new Date().toISOString(),
      done: false,
    };
  }
  return {
    id: r?.id || `rem_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    text: r?.text || "",
    date: r?.date || new Date().toISOString(),
    done: !!r?.done,
  };
}

function getUserEmailFromStorage() {
  const storedUE = localStorage.getItem("userEmail");
  if (storedUE) return storedUE;

  try {
    const u = JSON.parse(localStorage.getItem("user") || "null");
    if (u?.org_id) return String(u.org_id).trim().toLowerCase();
    if (u?.email) return String(u.email).trim().toLowerCase();
  } catch {}

  return "";
}

export default function LeadDrawer({
  lead,
  onClose,
  onEdit,
  onDelete,
  onUpdateLead,
}) {
  const [activeTab, setActiveTab] = useState("Details");
  const [showQR, setShowQR] = useState(false);

  const [updates, setUpdates] = useState(migrateNotesToUpdates(lead));
  const [reminders, setReminders] = useState(
    Array.isArray(lead?.reminders) ? lead.reminders.map(normalizeReminder) : []
  );
  const [newReminder, setNewReminder] = useState("");
  const [savingReminder, setSavingReminder] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  useEffect(() => {
    setUpdates(migrateNotesToUpdates(lead));
    setReminders(Array.isArray(lead?.reminders) ? lead.reminders.map(normalizeReminder) : []);
    setSaveMsg("");
  }, [lead]);

  const userEmail = useMemo(() => {
    return getUserEmailFromStorage() || lead?.owner || "";
  }, [lead?.owner]);

  const tabs = useMemo(
    () => [
      { key: "Details", label: "Details" },
      { key: "Notes", label: "Notes" },
      { key: "Reminders", label: `Reminders${reminders.length ? ` (${reminders.length})` : ""}` },
    ],
    [reminders.length]
  );

  const statusMeta = useMemo(() => getStatusMeta(lead?.status), [lead?.status]);

  const persistLeadPatch = useCallback(
    async (patch) => {
      if (!lead) return null;

      const mergedLead = { ...lead, ...patch };

      if (typeof onUpdateLead === "function") {
        onUpdateLead(mergedLead);
        return mergedLead;
      }

      if (!userEmail) throw new Error("Missing user email");

      const res = await fetch(`${API_BASE}/api/leads`, {
        method: "GET",
        credentials: "include",
        headers: {
          Accept: "application/json",
          "X-User-Email": userEmail,
        },
      });

      if (!res.ok) throw new Error("Failed to load leads");

      const data = await res.json().catch(() => ({}));
      const all = Array.isArray(data?.leads) ? data.leads : [];

      const idx = all.findIndex(
        (l) =>
          String(l?.id || "") === String(lead?.id || "") ||
          (lead?.email && String(l?.email || "").toLowerCase() === String(lead.email).toLowerCase())
      );

      if (idx === -1) throw new Error("Lead not found");

      all[idx] = { ...all[idx], ...patch };

      const save = await fetch(`${API_BASE}/api/leads`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-User-Email": userEmail,
        },
        body: JSON.stringify({ leads: all }),
      });

      if (!save.ok) throw new Error("Failed to save leads");
      return all[idx];
    },
    [lead, onUpdateLead, userEmail]
  );

  const persistReminders = useCallback(
    async (nextReminders) => {
      const normalized = nextReminders.map(normalizeReminder);
      setReminders(normalized);
      setSavingReminder(true);
      setSaveMsg("");

      try {
        await persistLeadPatch({
          reminders: normalized,
          updated_at: new Date().toISOString(),
        });
        setSaveMsg("Reminders saved");
        setTimeout(() => setSaveMsg(""), 1800);
      } catch (e) {
        console.warn("Failed to persist reminders:", e);
        setSaveMsg("Could not save reminders");
        setTimeout(() => setSaveMsg(""), 2200);
      } finally {
        setSavingReminder(false);
      }
    },
    [persistLeadPatch]
  );

  const addReminder = () => {
    const t = (newReminder || "").trim();
    if (!t) return;

    const next = [
      ...reminders,
      {
        id: `rem_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        text: t,
        date: new Date().toISOString(),
        done: false,
      },
    ];

    setNewReminder("");
    persistReminders(next);
  };

  const removeReminder = (id) => {
    const next = reminders.filter((r) => String(r.id) !== String(id));
    persistReminders(next);
  };

  const toggleReminderDone = (id) => {
    const next = reminders.map((r) =>
      String(r.id) === String(id) ? { ...r, done: !r.done } : r
    );
    persistReminders(next);
  };

  if (!lead) return null;

  const phone = lead.phone || lead.whatsapp || "";
  const canEmail = !!lead.email;
  const canCall = !!phone;

  return (
    <div
      className="lead-drawer"
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        height: "100vh",
        width: 430,
        minWidth: 430,
        background: "linear-gradient(180deg, #1f2023 0%, #1a1b1e 100%)",
        boxShadow: "-8px 0 28px rgba(0,0,0,0.45)",
        zIndex: 5000,
        display: "flex",
        flexDirection: "column",
        borderLeft: "1px solid rgba(56,255,152,0.18)",
        color: "#e9edef",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "22px 22px 14px 22px",
          borderBottom: "1px solid #2b2f33",
          background: "rgba(255,255,255,0.01)",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
          <div
            style={{
              width: 48,
              height: 48,
              background: "#2a2d31",
              border: "1px solid #34383d",
              borderRadius: "50%",
              fontWeight: 900,
              color: "#cbd3da",
              fontSize: 20,
              display: "grid",
              placeItems: "center",
              flex: "0 0 48px",
            }}
          >
            {firstTwo(lead.name || lead.email)}
          </div>

          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              style={{
                color: "#fff",
                fontWeight: 900,
                fontSize: 28,
                lineHeight: 1.05,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                marginBottom: 4,
              }}
            >
              {lead.name || "Unnamed Lead"}
            </div>

            <div
              style={{
                color: "#a7b0b8",
                fontSize: 15,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {lead.email || "No email"}
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
              <span
                title={statusMeta.helper}
                style={{
                  background: statusMeta.bg,
                  border: `1px solid ${statusMeta.border}`,
                  color: statusMeta.color,
                  borderRadius: 999,
                  padding: "6px 12px",
                  fontSize: 12,
                  fontWeight: 900,
                  letterSpacing: 0.2,
                }}
              >
                {statusMeta.label}
              </span>

              {!!lead.tags?.length &&
                lead.tags.slice(0, 3).map((t) => (
                  <span
                    key={t}
                    style={{
                      background: "#25282c",
                      color: "#d0d6dc",
                      borderRadius: 999,
                      padding: "6px 10px",
                      fontSize: 12,
                      fontWeight: 800,
                      border: "1px solid #34383d",
                    }}
                  >
                    {t}
                  </span>
                ))}
            </div>
          </div>

          <button
            onClick={onClose}
            style={{
              background: "transparent",
              color: "#9aa3ab",
              border: "none",
              fontWeight: 900,
              fontSize: 28,
              cursor: "pointer",
              lineHeight: 1,
              padding: 2,
            }}
            title="Close"
          >
            ×
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div
        className="lead-drawer-tabs"
        role="tablist"
        aria-label="Customer details"
        style={{
          display: "flex",
          gap: 8,
          padding: "14px 18px 10px 18px",
          borderBottom: "1px solid #2b2f33",
          background: "#1c1d20",
        }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`lead-drawer-tab${activeTab === tab.key ? " active" : ""}`}
            role="tab"
            aria-selected={activeTab === tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              background: activeTab === tab.key ? "#2a2d31" : "transparent",
              color: activeTab === tab.key ? "#fff" : "#98a2ab",
              border: activeTab === tab.key ? "1px solid #373c42" : "1px solid transparent",
              borderRadius: 10,
              fontSize: 14,
              fontWeight: 800,
              padding: "9px 14px",
              cursor: "pointer",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Body */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "18px 20px 18px 20px",
          fontSize: 15,
          color: "#d7dde2",
        }}
      >
        {activeTab === "Details" && (
          <div style={{ display: "grid", gap: 14 }}>
            <SectionCard title="Lead Details">
              <DetailRow label="Email" value={lead.email || "—"} />
              <DetailRow label="Phone" value={phone || "—"} />
              <DetailRow label="Birthday" value={lead.birthday ? formatDateOnly(lead.birthday) : "—"} />
              <DetailRow label="Owner" value={lead.owner || userEmail || "—"} />
            </SectionCard>

            <SectionCard title="Relationship Snapshot">
              <DetailRow
                label="Last Contacted"
                value={lead.last_contacted ? formatDateTime(lead.last_contacted) : "—"}
              />
              <DetailRow
                label="Created"
                value={lead.createdAt || lead.created_at ? formatDateTime(lead.createdAt || lead.created_at) : "—"}
              />
              <DetailRow
                label="Last Updated"
                value={lead.updated_at ? formatDateTime(lead.updated_at) : "—"}
              />
            </SectionCard>

            {!!lead.tags?.length && (
              <SectionCard title="Tags">
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {lead.tags.map((t) => (
                    <span
                      key={t}
                      style={{
                        background: "#25282c",
                        color: "#e3e8ec",
                        borderRadius: 999,
                        padding: "7px 12px",
                        fontWeight: 800,
                        fontSize: 12,
                        border: "1px solid #34383d",
                      }}
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </SectionCard>
            )}
          </div>
        )}

        {activeTab === "Notes" && (
          <div>
            {updates.length === 0 ? (
              <EmptyState
                title="No notes yet"
                text="Notes, voice notes, and AI updates for this lead will appear here."
              />
            ) : (
              <div style={{ display: "grid", gap: 12 }}>
                {updates.map((u, i) => (
                  <div
                    key={i}
                    style={{
                      background: "#23262a",
                      border: "1px solid #31353a",
                      borderRadius: 14,
                      padding: "14px 14px",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        marginBottom: 8,
                        color: "#9da7b0",
                        fontSize: 12,
                        fontWeight: 800,
                        textTransform: "uppercase",
                        letterSpacing: 0.35,
                      }}
                    >
                      <span>
                        {u.type === "note" && "Note"}
                        {u.type === "voice" && "Voice Note"}
                        {u.type === "ai" && "AI Suggestion"}
                        {!u.type && "Update"}
                      </span>
                      <span style={{ color: "#6f7a83", fontWeight: 600 }}>
                        {u.date ? formatDateTime(u.date) : ""}
                      </span>
                    </div>

                    {u.type === "note" && (
                      <div style={{ color: "#f0f3f5", whiteSpace: "pre-wrap", lineHeight: 1.55 }}>
                        {u.text}
                      </div>
                    )}

                    {u.type === "voice" && (
                      <div>
                        <audio controls src={u.audioUrl} style={{ width: "100%", marginBottom: 10 }} />
                        <div style={{ color: "#e7ebee", lineHeight: 1.5 }}>
                          <strong>Transcript:</strong> {u.transcript || "—"}
                        </div>
                      </div>
                    )}

                    {u.type === "ai" && (
                      <div style={{ color: "#7ce6b1", whiteSpace: "pre-wrap", lineHeight: 1.55 }}>
                        {u.text}
                      </div>
                    )}

                    {!["note", "voice", "ai"].includes(u.type) && (
                      <div style={{ color: "#f0f3f5", whiteSpace: "pre-wrap", lineHeight: 1.55 }}>
                        {u.text || "—"}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === "Reminders" && (
          <div>
            <div
              style={{
                display: "flex",
                gap: 10,
                marginBottom: 16,
                alignItems: "center",
              }}
            >
              <input
                value={newReminder}
                onChange={(e) => setNewReminder(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") addReminder();
                }}
                placeholder="Add a reminder for this lead…"
                style={{
                  flex: 1,
                  background: "#17191b",
                  color: "#eef2f4",
                  border: "1px solid #34383d",
                  borderRadius: 10,
                  padding: "12px 13px",
                  fontSize: 14,
                  outline: "none",
                }}
              />
              <button
                onClick={addReminder}
                style={{
                  background: "#f7cb53",
                  color: "#1f2225",
                  fontWeight: 900,
                  border: "none",
                  borderRadius: 10,
                  padding: "12px 16px",
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                }}
              >
                Add
              </button>
            </div>

            {(savingReminder || saveMsg) && (
              <div
                style={{
                  marginBottom: 12,
                  color: saveMsg === "Could not save reminders" ? "#ff8a8a" : "#8edcb6",
                  fontSize: 13,
                  fontWeight: 700,
                }}
              >
                {savingReminder ? "Saving reminders…" : saveMsg}
              </div>
            )}

            {reminders.length === 0 ? (
              <EmptyState
                title="No reminders yet"
                text="Set reminders here so you do not lose track of follow-ups."
              />
            ) : (
              <div style={{ display: "grid", gap: 10 }}>
                {reminders.map((r) => (
                  <div
                    key={r.id}
                    style={{
                      background: r.done ? "rgba(27,201,130,0.10)" : "#23262a",
                      border: r.done ? "1px solid rgba(27,201,130,0.28)" : "1px solid #31353a",
                      borderRadius: 14,
                      padding: "12px 12px",
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 10,
                    }}
                  >
                    <button
                      onClick={() => toggleReminderDone(r.id)}
                      title={r.done ? "Mark as not done" : "Mark as done"}
                      style={{
                        marginTop: 2,
                        width: 20,
                        height: 20,
                        borderRadius: "50%",
                        border: r.done ? "none" : "2px solid #5c6770",
                        background: r.done ? "#1bc982" : "transparent",
                        cursor: "pointer",
                        flex: "0 0 20px",
                      }}
                    />

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          color: r.done ? "#9fdcbc" : "#f7cb53",
                          fontWeight: 800,
                          lineHeight: 1.45,
                          textDecoration: r.done ? "line-through" : "none",
                          wordBreak: "break-word",
                        }}
                      >
                        {r.text}
                      </div>
                      <div
                        style={{
                          color: "#98a2ab",
                          fontSize: 12,
                          marginTop: 5,
                        }}
                      >
                        Added {formatDateTime(r.date)}
                      </div>
                    </div>

                    <button
                      onClick={() => removeReminder(r.id)}
                      title="Delete reminder"
                      style={{
                        background: "transparent",
                        border: "none",
                        color: "#e66565",
                        fontWeight: 900,
                        fontSize: 18,
                        cursor: "pointer",
                        lineHeight: 1,
                        padding: "2px 4px",
                      }}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div
        style={{
          display: "flex",
          gap: 10,
          padding: "16px 20px",
          borderTop: "1px solid #2b2f33",
          background: "#1b1c1f",
          alignItems: "center",
          justifyContent: "flex-end",
          flexWrap: "wrap",
        }}
      >
        {canEmail && (
          <a
            href={`mailto:${lead.email}`}
            style={{
              background: "#25282c",
              color: "#fff",
              textDecoration: "none",
              fontWeight: 900,
              border: "1px solid #3a3f45",
              borderRadius: 10,
              padding: "10px 16px",
              fontSize: 15,
            }}
          >
            Email
          </a>
        )}

        <button
          onClick={onEdit}
          style={{
            background: "#25282c",
            color: "#fff",
            fontWeight: 900,
            border: "1px solid #7d848b",
            borderRadius: 10,
            padding: "10px 18px",
            fontSize: 15,
            cursor: "pointer",
          }}
        >
          Edit
        </button>

        <button
          onClick={onDelete}
          style={{
            background: "transparent",
            color: "#ff7f7f",
            fontWeight: 900,
            border: "1px solid #e66565",
            borderRadius: 10,
            padding: "10px 18px",
            fontSize: 15,
            cursor: "pointer",
          }}
        >
          Delete
        </button>

        {canCall && (
          <>
            <button
              onClick={() => setShowQR(true)}
              title="Scan to call"
              style={{
                background: "#1bc982",
                color: "#16231c",
                fontWeight: 900,
                border: "none",
                borderRadius: 10,
                padding: "10px 18px",
                fontSize: 15,
                cursor: "pointer",
              }}
            >
              Call
            </button>

            {showQR && (
              <div
                style={{
                  position: "fixed",
                  inset: 0,
                  background: "rgba(0,0,0,0.72)",
                  zIndex: 10000,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
                onClick={() => setShowQR(false)}
              >
                <div
                  style={{
                    background: "#202225",
                    borderRadius: 22,
                    boxShadow: "0 8px 32px rgba(0,0,0,0.42)",
                    padding: 30,
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    border: "1px solid #33383d",
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <QRCodeSVG value={`tel:${phone}`} size={180} fgColor="#1bc982" />
                  <div
                    style={{
                      color: "#d0d7dd",
                      marginTop: 16,
                      fontWeight: 700,
                      fontSize: 16,
                    }}
                  >
                    Scan to call {phone}
                  </div>
                  <button
                    onClick={() => setShowQR(false)}
                    style={{
                      marginTop: 20,
                      background: "#1bc982",
                      color: "#16231c",
                      fontWeight: 900,
                      border: "none",
                      borderRadius: 10,
                      padding: "10px 24px",
                      fontSize: 16,
                      cursor: "pointer",
                    }}
                  >
                    Close
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function SectionCard({ title, children }) {
  return (
    <div
      style={{
        background: "#23262a",
        border: "1px solid #31353a",
        borderRadius: 16,
        padding: "14px 14px",
      }}
    >
      <div
        style={{
          color: "#fff",
          fontWeight: 900,
          fontSize: 14,
          marginBottom: 12,
          letterSpacing: 0.15,
        }}
      >
        {title}
      </div>
      <div style={{ display: "grid", gap: 10 }}>{children}</div>
    </div>
  );
}

function DetailRow({ label, value }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "120px 1fr",
        gap: 10,
        alignItems: "start",
      }}
    >
      <div style={{ color: "#97a0a8", fontWeight: 700, fontSize: 13 }}>{label}</div>
      <div style={{ color: "#eef2f4", fontWeight: 600, wordBreak: "break-word" }}>{value}</div>
    </div>
  );
}

function EmptyState({ title, text }) {
  return (
    <div
      style={{
        background: "#23262a",
        border: "1px dashed #3a4047",
        borderRadius: 14,
        padding: "18px 16px",
      }}
    >
      <div style={{ color: "#fff", fontWeight: 900, marginBottom: 6 }}>{title}</div>
      <div style={{ color: "#98a2ab", lineHeight: 1.5 }}>{text}</div>
    </div>
  );
}

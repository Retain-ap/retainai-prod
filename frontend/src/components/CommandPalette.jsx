import React, { useEffect, useMemo, useState } from "react";
import { FaSearch } from "react-icons/fa";
import "./product-system.css";

export default function CommandPalette({ setSection, isOwner }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  useEffect(() => {
    const onKey = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const actions = useMemo(
    () => [
      ["overview", "Open retention briefing", "Overview"],
      ["dashboard", "Open customer contacts", "Contacts"],
      ["messages", "Open messages", "Communication"],
      ["ai-prompts", "Open AI prompts and message studio", "Communication"],
      ["calendar", "Open calendar", "Scheduling"],
      ["automations", "Open automation playbooks", "Growth"],
      ["analytics", "Open analytics", "Insights"],
      ["invoices", "Open invoices", "Billing"],
      ["settings", "Open settings", "Account"],
      ...(isOwner ? [["owner", "Open owner command centre", "Platform"]] : []),
    ],
    [isOwner]
  );
  const filtered = actions.filter((item) => `${item[1]} ${item[2]}`.toLowerCase().includes(query.toLowerCase()));
  if (!open) return null;
  return (
    <div className="command-overlay" onMouseDown={() => setOpen(false)}>
      <div className="command-panel" onMouseDown={(event) => event.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <FaSearch style={{ color: "var(--ra-gold)" }} />
          <input autoFocus className="product-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search RetainAI or jump to a page…" />
        </div>
        <div className="command-results">
          {filtered.map(([section, label, group]) => (
            <button className="command-result" key={section} onClick={() => { setSection(section); setOpen(false); }}>
              <strong>{label}</strong><small>{group}</small>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

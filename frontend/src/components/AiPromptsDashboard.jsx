import React, { useEffect, useMemo, useState } from "react";
import { FaCheck, FaCopy, FaMagic, FaPaperPlane, FaSearch, FaShieldAlt } from "react-icons/fa";
import { apiUrl } from "../apiBase";
import { BUSINESS_SETTINGS_PATH, HELD_DRAFT_MAX_CHARS, consumeHeldDraft, heldDraftScope, holdDraft, isBusinessProfileRequired, peekHeldDraft } from "../businessProfile";
import "./AiPrompts.css";

const PLAYBOOKS = [
  { key: "followup", label: "Follow-up", description: "Continue the conversation and make the next step easy.", instruction: "Write a friendly, personalized follow-up with one clear next step." },
  { key: "reengage", label: "Re-engage", description: "Reconnect naturally with a customer who has gone quiet.", instruction: "Write a gentle, empathetic message to re-engage an inactive customer without pressure." },
  { key: "birthday", label: "Birthday", description: "Create a warm relationship-building birthday note.", instruction: "Write a warm, personalized birthday greeting that feels genuine and not promotional." },
  { key: "apology", label: "Service recovery", description: "Acknowledge a known concern and offer a practical next step.", instruction: "Acknowledge only the concern recorded in the customer context and avoid unsupported admissions." },
  { key: "upsell", label: "Recommendation", description: "Suggest an option only when customer context supports it.", instruction: "Make a low-pressure recommendation without inventing products, prices, benefits, or preferences." },
];

// send-ai-message accepts up to 5000 characters; the box and held draft match it.
const DRAFT_MAX_CHARS = HELD_DRAFT_MAX_CHARS;
const TONES = ["Warm", "Professional", "Friendly", "Concise"];
const LENGTHS = ["Short", "Standard", "Detailed"];
const firstName = (name) => String(name || "").trim().split(/\s+/)[0] || "";
const SUBJECTS = {
  followup: (name) => firstName(name) ? `Checking in, ${firstName(name)}` : "Checking in",
  reengage: () => "A quick check-in",
  birthday: (name) => firstName(name) ? `Happy birthday, ${firstName(name)}!` : "Happy birthday!",
  apology: () => "Following up on your experience",
  upsell: () => "An option you may find helpful",
};

export default function AiPromptsDashboard({ leads = [], user = {}, onSendAIPromptEmail, onOpenBusinessSettings, initialFocus = null, onFocusApplied }) {
  const [search, setSearch] = useState("");
  const [focusedLead, setFocusedLead] = useState(null);
  const [activePlaybook, setActivePlaybook] = useState(PLAYBOOKS[0].key);
  const [tone, setTone] = useState("Warm");
  const [length, setLength] = useState("Standard");
  const [context, setContext] = useState("");
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [needsBusinessName, setNeedsBusinessName] = useState(false);

  // The backend uses the saved business name; no placeholder name is sent.
  const brandName = user.businessName || user.business || "";
  const userName = user.name || user.email?.split("@")[0] || "Your Team";
  // One held draft per workspace and signed-in person; "" (nothing held) when unknown.
  const heldScope = heldDraftScope("ai-studio", user);

  const filteredLeads = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return leads;
    return leads.filter((lead) =>
      [lead.name, lead.email, lead.status, ...(lead.tags || [])]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query))
    );
  }, [leads, search]);

  // Put back a draft held while the owner went to Settings to add a business name.
  // It is removed only after it is back on screen for this account's same
  // customer; while customers are still loading it stays where it is.
  useEffect(() => {
    // A customer chosen from the rebooking list wins; a held draft stays stored for later.
    if (initialFocus) return;
    const held = peekHeldDraft(heldScope);
    if (!held) return;
    const lead = leads.find((item) => String(item.id) === String(held.leadId));
    if (!lead) return;
    setFocusedLead(lead);
    if (PLAYBOOKS.some((playbook) => playbook.key === held.playbook)) setActivePlaybook(held.playbook);
    if (TONES.includes(held.tone)) setTone(held.tone);
    if (LENGTHS.includes(held.length)) setLength(held.length);
    setContext(String(held.context || ""));
    setDraft(String(held.draft || ""));
    consumeHeldDraft(heldScope, held);
  }, [heldScope, initialFocus, leads]);

  // Open on a customer chosen from the rebooking list, with factual context the
  // owner can edit. This only prepares the screen: nothing is generated or sent.
  useEffect(() => {
    if (!initialFocus?.leadId || !leads.length) return;
    const lead = leads.find((item) => String(item.id) === String(initialFocus.leadId));
    if (lead) {
      setFocusedLead(lead);
      if (PLAYBOOKS.some((playbook) => playbook.key === initialFocus.playbook)) setActivePlaybook(initialFocus.playbook);
      setContext(String(initialFocus.context || "").slice(0, 800));
      setDraft("");
      setError("");
      setNeedsBusinessName(false);
      setStatus("");
    }
    if (typeof onFocusApplied === "function") onFocusApplied();
  }, [initialFocus, leads, onFocusApplied]);

  const showError = (err, fallback) => {
    setStatus("");
    setNeedsBusinessName(isBusinessProfileRequired(err));
    setError(err?.message || err?.error || fallback);
  };

  const openBusinessSettings = (event) => {
    if (focusedLead?.id != null) holdDraft(heldScope, { leadId: String(focusedLead.id), playbook: activePlaybook, tone, length, context, draft });
    if (typeof onOpenBusinessSettings === "function") {
      event.preventDefault();
      onOpenBusinessSettings();
    }
  };

  const selectLead = (lead) => {
    setFocusedLead(lead);
    setDraft("");
    setContext("");
    setError("");
    setNeedsBusinessName(false);
    setStatus("");
  };

  const selectPlaybook = (playbookKey) => {
    setActivePlaybook(playbookKey);
    setDraft("");
    setContext("");
    setError("");
    setNeedsBusinessName(false);
    setStatus("");
  };

  const generateDraft = async () => {
    if (!focusedLead) return;
    setLoading(true);
    setError("");
    setNeedsBusinessName(false);
    setStatus("");
    try {
      const response = await fetch(apiUrl("generate_prompt"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          leadId: focusedLead.id,
          promptType: activePlaybook,
          tone,
          length,
          additionalContext: context,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (isBusinessProfileRequired(data)) return showError(data, "RetainAI could not create a draft.");
      if (!response.ok || !data.prompt) throw new Error(data.error || "RetainAI could not create a draft.");
      setDraft(String(data.prompt).replace(/^(subject:.*)$/gim, "").trim());
      setStatus("Draft ready — review it before sending.");
    } catch (err) {
      showError(err, "RetainAI could not create a draft.");
    } finally {
      setLoading(false);
    }
  };

  const copyDraft = async () => {
    if (!draft.trim()) return;
    await navigator.clipboard.writeText(draft);
    setStatus("Copied to clipboard.");
  };

  const sendDraft = async () => {
    if (!focusedLead?.email) return showError({ message: "This customer needs an email address before you can send." });
    if (!draft.trim()) return showError({ message: "Create or write a message before sending." });
    if (draft.trim().length > DRAFT_MAX_CHARS) return showError({ message: `Shorten the message to ${DRAFT_MAX_CHARS} characters or fewer before sending.` });
    setLoading(true);
    setError("");
    setNeedsBusinessName(false);
    setStatus("Sending…");
    try {
      const subject = (SUBJECTS[activePlaybook] || SUBJECTS.followup)(focusedLead.name);
      if (typeof onSendAIPromptEmail === "function") {
        const sent = await onSendAIPromptEmail(
          focusedLead,
          draft.trim(),
          subject,
          activePlaybook
        );
        if (sent !== true) throw new Error("Message could not be sent.");
      } else {
        const response = await fetch(apiUrl("send-ai-message"), {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ leadId: focusedLead.id, leadEmail: focusedLead.email, leadName: focusedLead.name || "", userEmail: user.email, userName, businessName: brandName, message: draft.trim(), promptType: activePlaybook, subject }),
        });
        const data = await response.json().catch(() => ({}));
        if (isBusinessProfileRequired(data)) return showError(data, "Message could not be sent.");
        if (!response.ok) throw new Error(data.error || "Message could not be sent.");
      }
      setStatus("Message sent successfully.");
    } catch (err) {
      showError(err, "Message could not be sent.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="ai-root">
      <section className="ai-hero">
        <div><div className="ai-eyebrow"><FaMagic /> RETAINAI MESSAGE STUDIO</div><h2>Turn customer context into thoughtful outreach.</h2><p>Create on-brand messages faster while keeping every send reviewed and under your control.</p></div>
        <div className="ai-trust"><FaShieldAlt /><span><strong>Human-approved</strong>AI never sends until you choose to.</span></div>
      </section>
      <div className="ai-workspace">
        <aside className="ai-contacts-panel">
          <div className="ai-panel-heading"><div><span>1</span><strong>Choose a customer</strong></div><small>{filteredLeads.length} available</small></div>
          <label className="ai-search"><FaSearch /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search customers…" aria-label="Search customers" /></label>
          <div className="ai-contact-list">
            {filteredLeads.length === 0 ? <div className="ai-empty">No matching customers.</div> : filteredLeads.map((lead) => (
              <button key={lead.id || lead.email} type="button" className={`ai-contact${focusedLead === lead ? " active" : ""}`} onClick={() => selectLead(lead)}><span className="ai-avatar">{(lead.name || lead.email || "C").charAt(0).toUpperCase()}</span><span><strong>{lead.name || "Unnamed customer"}</strong><small>{lead.email || "No email address"}</small></span>{focusedLead === lead && <FaCheck />}</button>
            ))}
          </div>
        </aside>
        <main className="ai-compose-panel">
          {!focusedLead ? <div className="ai-welcome"><FaMagic /><h3>Choose a customer to begin</h3><p>RetainAI will use their saved notes, tags, and relationship context to prepare a personalized draft.</p></div> : (
            <>
              <div className="ai-selected-customer"><span className="ai-avatar">{(focusedLead.name || "C").charAt(0).toUpperCase()}</span><div><small>Writing for</small><strong>{focusedLead.name || "Unnamed customer"}</strong><span>{focusedLead.email || "No email address"}</span></div></div>
              <div className="ai-step"><div className="ai-step-title"><span>2</span><div><strong>Select a playbook</strong><small>Start with a proven relationship moment.</small></div></div><div className="ai-playbooks">{PLAYBOOKS.map((playbook) => <button key={playbook.key} type="button" className={activePlaybook === playbook.key ? "active" : ""} onClick={() => selectPlaybook(playbook.key)}><strong>{playbook.label}</strong><small>{playbook.description}</small></button>)}</div></div>
              <div className="ai-step"><div className="ai-step-title"><span>3</span><div><strong>Shape the message</strong><small>Control the voice and add only details you know are accurate.</small></div></div><div className="ai-control-grid"><label>Tone<select value={tone} onChange={(event) => setTone(event.target.value)}>{TONES.map((item) => <option key={item}>{item}</option>)}</select></label><label>Length<select value={length} onChange={(event) => setLength(event.target.value)}>{LENGTHS.map((item) => <option key={item}>{item}</option>)}</select></label></div><label className="ai-context">Extra context <span>optional</span><textarea value={context} onChange={(event) => setContext(event.target.value)} placeholder="Example: They asked about booking again next month." maxLength={800} /><small>{context.length}/800</small></label><button type="button" className="ai-generate" onClick={generateDraft} disabled={loading}><FaMagic /> {loading ? "Creating your draft…" : draft ? "Generate another version" : "Create message"}</button></div>
              <div className="ai-step ai-draft-step"><div className="ai-step-title"><span>4</span><div><strong>Review and send</strong><small>Edit anything you like. You remain in control.</small></div></div><textarea className="ai-draft" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Your generated message will appear here. You can also write your own." maxLength={DRAFT_MAX_CHARS} aria-describedby="ai-draft-count" /><small id="ai-draft-count" className="ai-draft-count">{draft.length}/{DRAFT_MAX_CHARS}</small>{error && <div className="ai-feedback error" role="alert">{error}{needsBusinessName && <> <a className="ai-settings-link" href={BUSINESS_SETTINGS_PATH} onClick={openBusinessSettings}>Add business name in Settings</a></>}</div>}{status && !error && <div className="ai-feedback success">{status}</div>}<div className="ai-actions"><button type="button" className="ai-secondary" onClick={copyDraft} disabled={!draft.trim()}><FaCopy /> Copy</button><button type="button" className="ai-send" onClick={sendDraft} disabled={loading || !draft.trim()}><FaPaperPlane /> Send email</button></div><p className="ai-compliance"><FaShieldAlt /> Confirm the message is accurate and appropriate before sending. Avoid sensitive personal or medical details.</p></div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

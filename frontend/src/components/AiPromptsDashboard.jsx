import React, { useMemo, useState } from "react";
import { FaCheck, FaCopy, FaMagic, FaPaperPlane, FaSearch, FaShieldAlt } from "react-icons/fa";
import { apiUrl } from "../apiBase";
import "./AiPrompts.css";

const PLAYBOOKS = [
  { key: "followup", label: "Follow-up", description: "Continue the conversation and make the next step easy.", instruction: "Write a friendly, personalized follow-up with one clear next step." },
  { key: "reengage", label: "Re-engage", description: "Reconnect naturally with a customer who has gone quiet.", instruction: "Write a gentle, empathetic message to re-engage an inactive customer without pressure." },
  { key: "birthday", label: "Birthday", description: "Create a warm relationship-building birthday note.", instruction: "Write a warm, personalized birthday greeting that feels genuine and not promotional." },
  { key: "apology", label: "Service recovery", description: "Acknowledge an issue and rebuild trust professionally.", instruction: "Write a sincere apology that acknowledges the concern, takes ownership, and offers a practical next step." },
  { key: "upsell", label: "Recommendation", description: "Recommend a relevant service based on customer context.", instruction: "Write a helpful, low-pressure recommendation for an additional service or product with a clear customer benefit." },
];

const TONES = ["Warm", "Professional", "Friendly", "Concise"];
const LENGTHS = ["Short", "Standard", "Detailed"];
const SUBJECTS = {
  followup: (name) => `A quick follow-up for ${name || "you"}`,
  reengage: () => "We would love to see you again",
  birthday: (name) => `Happy birthday, ${name || "from all of us"}!`,
  apology: () => "We are sorry — and we want to make this right",
  upsell: () => "A recommendation selected for you",
};

export default function AiPromptsDashboard({ leads = [], user = {}, onSendAIPromptEmail }) {
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

  const brandName = user.business || user.businessName || user.lineOfBusiness || "Your Business";
  const businessType = user.businessType || "";
  const userName = user.name || user.email?.split("@")[0] || "Your Team";
  const selectedPlaybook = PLAYBOOKS.find((item) => item.key === activePlaybook) || PLAYBOOKS[0];

  const filteredLeads = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return leads;
    return leads.filter((lead) =>
      [lead.name, lead.email, lead.status, ...(lead.tags || [])]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query))
    );
  }, [leads, search]);

  const selectLead = (lead) => {
    setFocusedLead(lead);
    setDraft("");
    setContext("");
    setError("");
    setStatus("");
  };

  const generateDraft = async () => {
    if (!focusedLead) return;
    setLoading(true);
    setError("");
    setStatus("");
    try {
      const response = await fetch(apiUrl("generate_prompt"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userEmail: user.email,
          leadName: focusedLead.name || "",
          businessName: brandName,
          businessType,
          userName,
          tags: focusedLead.tags || [],
          notes: focusedLead.notes || "",
          lastContacted: focusedLead.last_contacted || "",
          status: focusedLead.status || "",
          promptType: activePlaybook,
          tone,
          length,
          additionalContext: context,
          instruction: selectedPlaybook.instruction,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.prompt) throw new Error(data.error || "RetainAI could not create a draft.");
      setDraft(String(data.prompt).replace(/^(subject:.*)$/gim, "").trim());
      setStatus("Draft ready — review it before sending.");
    } catch (err) {
      setError(err.message || "RetainAI could not create a draft.");
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
    if (!focusedLead?.email) return setError("This customer needs an email address before you can send.");
    if (!draft.trim()) return setError("Create or write a message before sending.");
    setLoading(true);
    setError("");
    setStatus("Sending…");
    try {
      const subject = (SUBJECTS[activePlaybook] || SUBJECTS.followup)(focusedLead.name);
      if (typeof onSendAIPromptEmail === "function") {
        await onSendAIPromptEmail(focusedLead, draft.trim(), subject, activePlaybook);
      } else {
        const response = await fetch(apiUrl("send-ai-message"), {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ leadEmail: focusedLead.email, leadName: focusedLead.name || "", userEmail: user.email, userName, businessName: brandName, message: draft.trim(), promptType: activePlaybook, subject }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "Message could not be sent.");
      }
      setStatus("Message sent successfully.");
    } catch (err) {
      setError(err.message || "Message could not be sent.");
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
          <label className="ai-search"><FaSearch /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search customers…" /></label>
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
              <div className="ai-step"><div className="ai-step-title"><span>2</span><div><strong>Select a playbook</strong><small>Start with a proven relationship moment.</small></div></div><div className="ai-playbooks">{PLAYBOOKS.map((playbook) => <button key={playbook.key} type="button" className={activePlaybook === playbook.key ? "active" : ""} onClick={() => setActivePlaybook(playbook.key)}><strong>{playbook.label}</strong><small>{playbook.description}</small></button>)}</div></div>
              <div className="ai-step"><div className="ai-step-title"><span>3</span><div><strong>Shape the message</strong><small>Control the voice and give AI the missing context.</small></div></div><div className="ai-control-grid"><label>Tone<select value={tone} onChange={(event) => setTone(event.target.value)}>{TONES.map((item) => <option key={item}>{item}</option>)}</select></label><label>Length<select value={length} onChange={(event) => setLength(event.target.value)}>{LENGTHS.map((item) => <option key={item}>{item}</option>)}</select></label></div><label className="ai-context">Extra context <span>optional</span><textarea value={context} onChange={(event) => setContext(event.target.value)} placeholder="Example: They loved the last service and asked about booking again next month." maxLength={800} /><small>{context.length}/800</small></label><button type="button" className="ai-generate" onClick={generateDraft} disabled={loading}><FaMagic /> {loading ? "Creating your draft…" : draft ? "Generate another version" : "Create message"}</button></div>
              <div className="ai-step ai-draft-step"><div className="ai-step-title"><span>4</span><div><strong>Review and send</strong><small>Edit anything you like. You remain in control.</small></div></div><textarea className="ai-draft" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Your generated message will appear here. You can also write your own." />{error && <div className="ai-feedback error">{error}</div>}{status && !error && <div className="ai-feedback success">{status}</div>}<div className="ai-actions"><button type="button" className="ai-secondary" onClick={copyDraft} disabled={!draft.trim()}><FaCopy /> Copy</button><button type="button" className="ai-send" onClick={sendDraft} disabled={loading || !draft.trim()}><FaPaperPlane /> Send email</button></div><p className="ai-compliance"><FaShieldAlt /> Confirm the message is accurate and appropriate before sending. Avoid sensitive personal or medical details.</p></div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

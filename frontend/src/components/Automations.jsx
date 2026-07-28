// src/components/Automations.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import api from "./AutomationsService";

/* -------------------- THEME -------------------- */
const C = {
  bg: "#171819",
  panel: "#1f2022",
  card: "#242628",
  soft: "#202224",
  border: "#2e3134",
  text: "#eef1f3",
  muted: "#aab0b6",
  gold: "#f7cb53",
  green: "#30b46c",
  redBg: "#3a1111",
  redTxt: "#ffbcbc",
};

const shellCard = {
  background: C.card,
  border: `1px solid ${C.border}`,
  borderRadius: 18,
  boxShadow: "0 8px 28px rgba(0,0,0,0.22)",
};

const softCard = {
  background: C.soft,
  border: `1px solid ${C.border}`,
  borderRadius: 16,
};

/* -------------------- UI PRIMITIVES -------------------- */
function Btn({ children, onClick, kind = "solid", disabled, type = "button", style = {} }) {
  const base = {
    borderRadius: 12,
    padding: "10px 14px",
    fontWeight: 800,
    cursor: disabled ? "not-allowed" : "pointer",
    transition: "0.15s ease",
    opacity: disabled ? 0.6 : 1,
    ...style,
  };

  if (kind === "ghost") {
    return (
      <button
        type={type}
        onClick={onClick}
        disabled={disabled}
        style={{
          ...base,
          background: "#2a2a2a",
          color: "#fff",
          border: `1px solid ${C.border}`,
        }}
      >
        {children}
      </button>
    );
  }

  if (kind === "danger") {
    return (
      <button
        type={type}
        onClick={onClick}
        disabled={disabled}
        style={{
          ...base,
          background: C.redBg,
          color: C.redTxt,
          border: "1px solid #4a1515",
        }}
      >
        {children}
      </button>
    );
  }

  if (kind === "outline") {
    return (
      <button
        type={type}
        onClick={onClick}
        disabled={disabled}
        style={{
          ...base,
          background: "transparent",
          color: C.gold,
          border: `1px solid ${C.gold}`,
        }}
      >
        {children}
      </button>
    );
  }

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        ...base,
        background: C.gold,
        color: "#111",
        border: "none",
      }}
    >
      {children}
    </button>
  );
}

const Input = React.forwardRef(function Input(props, ref) {
  return (
    <input
      ref={ref}
      {...props}
      style={{
        width: "100%",
        background: "#232323",
        color: "#fff",
        border: `1px solid ${C.border}`,
        borderRadius: 12,
        padding: "10px 12px",
        outline: "none",
        boxSizing: "border-box",
        ...(props.style || {}),
      }}
    />
  );
});

const TextArea = React.forwardRef(function TextArea(props, ref) {
  return (
    <textarea
      ref={ref}
      {...props}
      style={{
        width: "100%",
        background: "#232323",
        color: "#fff",
        border: `1px solid ${C.border}`,
        borderRadius: 12,
        padding: "10px 12px",
        outline: "none",
        resize: "vertical",
        boxSizing: "border-box",
        ...(props.style || {}),
      }}
    />
  );
});

function Select({ children, ...props }) {
  return (
    <select
      {...props}
      style={{
        width: "100%",
        background: "#232323",
        color: "#fff",
        border: `1px solid ${C.border}`,
        borderRadius: 12,
        padding: "10px 12px",
        outline: "none",
        boxSizing: "border-box",
        ...(props.style || {}),
      }}
    >
      {children}
    </select>
  );
}

function Toggle({ checked, onChange }) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
      <span style={{ fontSize: 13, color: C.muted }}>Off</span>
      <div style={{ position: "relative", width: 50, height: 28 }}>
        <input
          type="checkbox"
          checked={!!checked}
          onChange={onChange}
          style={{ position: "absolute", opacity: 0, inset: 0, cursor: "pointer" }}
        />
        <div
          style={{
            width: 50,
            height: 28,
            borderRadius: 999,
            background: "#2a2a2a",
            border: `1px solid ${C.border}`,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 3,
            left: checked ? 25 : 3,
            width: 20,
            height: 20,
            borderRadius: 999,
            background: checked ? "#fff" : "#777",
            transition: "0.15s ease",
          }}
        />
      </div>
      <span style={{ fontSize: 13, color: C.muted }}>On</span>
    </label>
  );
}

function Chip({ children, active, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        borderRadius: 999,
        padding: "7px 11px",
        fontSize: 12,
        fontWeight: 800,
        cursor: "pointer",
        background: active ? C.gold : "#242424",
        color: active ? "#111" : "#fff",
        border: `1px solid ${active ? C.gold : C.border}`,
      }}
    >
      {children}
    </button>
  );
}

function SectionTitle({ title, subtitle, right }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 16,
        marginBottom: 14,
        flexWrap: "wrap",
      }}
    >
      <div>
        <div style={{ fontSize: 20, fontWeight: 900, color: C.text }}>{title}</div>
        {subtitle ? <div style={{ fontSize: 13, color: C.muted, marginTop: 4 }}>{subtitle}</div> : null}
      </div>
      {right}
    </div>
  );
}

function StatCard({ label, value, accent }) {
  return (
    <div
      style={{
        ...softCard,
        padding: 14,
        borderColor: accent ? C.gold : C.border,
      }}
    >
      <div style={{ color: C.muted, fontSize: 12, fontWeight: 800 }}>{label}</div>
      <div style={{ color: C.text, fontSize: 24, fontWeight: 900, marginTop: 6 }}>{value}</div>
    </div>
  );
}

/* -------------------- TOKENS -------------------- */
const TOKENS = ["{{business_name}}", "{{booking_link}}", "{{lead.first_name}}", "{{last_ai_text}}"];

function TokenRow({ onInsert }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {TOKENS.map((t) => (
        <button
          key={t}
          type="button"
          onClick={() => onInsert?.(t)}
          style={{
            fontSize: 12,
            background: "#242424",
            border: `1px solid ${C.border}`,
            color: "#fff",
            padding: "6px 9px",
            borderRadius: 10,
            cursor: "pointer",
          }}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

/* -------------------- HELPERS -------------------- */
const PRETTY_TRIGGER = {
  no_reply: (t) => `When a lead hasn't replied for ${t.days || 3} day${Number(t.days || 3) === 1 ? "" : "s"}`,
  new_lead: (t) => `When a new lead comes in (within ${t.within_hours || 24} hours)`,
  appointment_no_show: () => "When a lead misses an appointment",
};

function normalizeFlow(flow, userEmail) {
  return {
    id: flow?.id,
    owner: (flow?.owner || userEmail || "").toLowerCase(),
    name: flow?.name || "Untitled Flow",
    enabled: !!flow?.enabled,
    trigger: flow?.trigger || { type: "" },
    steps: Array.isArray(flow?.steps) ? flow.steps : [],
    caps: {
      per_lead_per_day: Number(flow?.caps?.per_lead_per_day ?? 1),
      respect_quiet_hours: flow?.caps?.respect_quiet_hours !== false,
    },
    auto_stop_on_reply: flow?.auto_stop_on_reply !== false,
  };
}

function buildEmptyFlow(userEmail) {
  return normalizeFlow(
    {
      id: undefined,
      owner: userEmail,
      name: "Untitled Flow",
      enabled: false,
      trigger: { type: "" },
      steps: [],
      caps: { per_lead_per_day: 1, respect_quiet_hours: true },
      auto_stop_on_reply: true,
    },
    userEmail
  );
}

function splitParams(str) {
  if (!str) return [];
  return String(str)
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length || s === "");
}

function joinParams(arr) {
  return (arr || []).map((s) => (s == null ? "" : String(s))).join(", ");
}

function normalizeWATemplates(raw) {
  if (!Array.isArray(raw)) return [];
  const byName = {};

  raw.forEach((item) => {
    if (typeof item === "string") {
      byName[item] = byName[item] || { name: item, languages: [] };
      return;
    }

    const name = item?.name || "";
    if (!name) return;

    byName[name] = byName[name] || { name, languages: [] };

    if (Array.isArray(item.languages)) {
      item.languages.forEach((l) => {
        if (!l?.code) return;
        byName[name].languages.push({
          code: l.code,
          status: (l.status || "APPROVED").toUpperCase(),
          body_params: Number(l.body_params ?? 0),
        });
      });
    } else if (item.language) {
      byName[name].languages.push({
        code: item.language,
        status: (item.status || "APPROVED").toUpperCase(),
        body_params: Number(item.body_params ?? 0),
      });
    }
  });

  Object.values(byName).forEach((t) => {
    t.languages.sort((a, b) => (a.status === "APPROVED" ? -1 : 1));
  });

  return Object.values(byName).sort((a, b) => a.name.localeCompare(b.name));
}

function humanStepLabel(step) {
  if (!step?.type) return "Step";

  if (step.type === "wait") {
    const d = Number(step.days || 0);
    const h = Number(step.hours || 0);
    const m = Number(step.minutes || 0);
    const bits = [];
    if (d) bits.push(`${d} day${d === 1 ? "" : "s"}`);
    if (h) bits.push(`${h} hour${h === 1 ? "" : "s"}`);
    if (m) bits.push(`${m} min`);
    return `Wait ${bits.length ? bits.join(", ") : "for a bit"}`;
  }

  if (step.type === "ai_draft") return "Create an AI draft";
  if (step.type === "send_email") return "Send an email";
  if (step.type === "send_whatsapp") {
    return step?.template?.name ? `Send WhatsApp template: ${step.template.name}` : "Send a WhatsApp message";
  }
  if (step.type === "push_owner") return "Notify the owner";
  if (step.type === "add_tag") return `Add tag: ${step.tag || "Needs Attention"}`;
  if (step.type === "if_no_reply") return `If no reply in ${step.within_days || 2} day(s)`;
  if (step.type === "if_no_booking") return `If no booking in ${step.within_days || 2} day(s)`;

  return step.type.replaceAll("_", " ");
}

function flowSummary(flow) {
  const trig = flow?.trigger || {};
  const triggerText = trig.type ? PRETTY_TRIGGER[trig.type]?.(trig) || trig.type : "Choose a trigger";
  const stepCount = Array.isArray(flow?.steps) ? flow.steps.length : 0;
  return `${triggerText}. ${stepCount} step${stepCount === 1 ? "" : "s"} in this flow.`;
}

function buildDefaultStep(type) {
  switch (type) {
    case "ai_draft":
      return { type: "ai_draft" };
    case "send_whatsapp":
      return { type: "send_whatsapp", text: "{{last_ai_text}}" };
    case "send_email":
      return {
        type: "send_email",
        subject: "Quick check-in from {{business_name}}",
        body:
          "Hi {{lead.first_name}},\n\nJust checking in. Book here: {{booking_link}}\n\nThanks,\n{{business_name}}",
      };
    case "wait":
      return { type: "wait", hours: 24 };
    case "if_no_reply":
      return { type: "if_no_reply", within_days: 2, then: [] };
    case "if_no_booking":
      return { type: "if_no_booking", within_days: 2, then: [] };
    case "push_owner":
      return { type: "push_owner", title: "Give them a quick call", message: "Lead may need a call" };
    case "add_tag":
      return { type: "add_tag", tag: "Needs Attention" };
    default:
      return { type };
  }
}

function cloneTemplateToFlow(template, userEmail) {
  const f = JSON.parse(JSON.stringify(template || {}));
  delete f.id;
  f.enabled = false;
  f.owner = userEmail;
  return normalizeFlow(f, userEmail);
}

function ArrowRight() {
  return (
    <svg width="36" height="16" viewBox="0 0 36 16" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M0 8H30" stroke="#3a3a3a" strokeWidth="2" />
      <path d="M25 3L30 8L25 13" stroke="#3a3a3a" strokeWidth="2" />
    </svg>
  );
}

function FlowNode({ title, subtitle }) {
  return (
    <div
      style={{
        background: C.soft,
        border: `1px solid ${C.border}`,
        borderRadius: 14,
        padding: 12,
        minWidth: 180,
        maxWidth: 240,
        boxShadow: "0 2px 18px rgba(0,0,0,0.18)",
        flex: "0 0 auto",
      }}
    >
      <div style={{ color: C.muted, fontSize: 12 }}>{subtitle}</div>
      <div
        style={{
          color: "#fff",
          fontWeight: 900,
          marginTop: 4,
          lineHeight: 1.3,
          wordBreak: "break-word",
        }}
      >
        {title}
      </div>
    </div>
  );
}

function FlowDiagram({ flow }) {
  const trig = flow?.trigger || {};
  const title =
    trig.type === "no_reply"
      ? `No reply (${trig.days || 3}d)`
      : trig.type === "new_lead"
      ? `New lead (≤ ${trig.within_hours || 24}h)`
      : trig.type === "appointment_no_show"
      ? "Appointment no-show"
      : "Trigger";

  const steps = flow?.steps || [];

  return (
    <div
      style={{
        overflowX: "auto",
        overflowY: "hidden",
        maxWidth: "100%",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          width: "max-content",
          minWidth: "100%",
          paddingBottom: 4,
        }}
      >
        <FlowNode subtitle="Trigger" title={title} />
        {steps.map((s, i) => (
          <React.Fragment key={i}>
            <ArrowRight />
            <FlowNode subtitle="Step" title={humanStepLabel(s)} />
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

/* -------------------- FIELD -------------------- */
function Field({ label, children }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: C.muted, marginBottom: 6, fontWeight: 800 }}>{label}</div>
      {children}
    </div>
  );
}

/* -------------------- STEP EDITOR -------------------- */
function StepCard({ step, onChange, onRemove, waTemplates }) {
  const set = (patch) => onChange({ ...step, ...patch });
  const emailBodyRef = useRef(null);
  const waBodyRef = useRef(null);

  const insertToken = (ref, tok, key) => {
    const el = ref.current;
    if (!el) return;
    const start = el.selectionStart || 0;
    const end = el.selectionEnd || 0;
    const next = el.value.slice(0, start) + tok + el.value.slice(end);
    el.value = next;
    el.selectionStart = el.selectionEnd = start + tok.length;
    el.focus();
    set({ [key]: next });
  };

  const normalizedTemplates = useMemo(() => normalizeWATemplates(waTemplates || []), [waTemplates]);

  const waTpl = step.template || {};
  const setTpl = (patch) => set({ template: { ...(step.template || {}), ...patch } });

  const selectedTpl = useMemo(
    () => normalizedTemplates.find((t) => t.name === waTpl.name) || null,
    [normalizedTemplates, waTpl.name]
  );

  const selectedLangMeta = useMemo(() => {
    if (!selectedTpl) return null;
    const code = waTpl.language || selectedTpl.languages[0]?.code;
    return selectedTpl.languages.find((l) => l.code === code) || selectedTpl.languages[0] || null;
  }, [selectedTpl, waTpl.language]);

  const paramCount = Number(selectedLangMeta?.body_params || 0);

  const paramsArray = useMemo(() => {
    const arr = splitParams(waTpl.params);
    while (arr.length < paramCount) arr.push("");
    return arr.slice(0, paramCount);
  }, [waTpl.params, paramCount]);

  const fillCommonParams = () => {
    const commons = ["{{lead.first_name}}", "{{business_name}}", "{{booking_link}}", "{{last_ai_text}}"];
    const out = [];
    for (let i = 0; i < paramCount; i++) out.push(commons[i] || "");
    setTpl({ params: joinParams(out) });
  };

  return (
    <div style={{ ...softCard, padding: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <div>
          <div style={{ color: C.text, fontSize: 16, fontWeight: 900 }}>{humanStepLabel(step)}</div>
          <div style={{ color: C.muted, fontSize: 12, marginTop: 3 }}>{step.type.replaceAll("_", " ")}</div>
        </div>
        <Btn kind="danger" onClick={onRemove}>
          Remove
        </Btn>
      </div>

      {step.type === "wait" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 10 }}>
          <Field label="Days">
            <Input type="number" value={step.days || 0} onChange={(e) => set({ days: +e.target.value })} />
          </Field>
          <Field label="Hours">
            <Input type="number" value={step.hours || 0} onChange={(e) => set({ hours: +e.target.value })} />
          </Field>
          <Field label="Minutes">
            <Input type="number" value={step.minutes || 0} onChange={(e) => set({ minutes: +e.target.value })} />
          </Field>
        </div>
      )}

      {step.type === "ai_draft" && (
        <div style={{ color: C.muted, fontSize: 13 }}>
          RetainAI will draft the message first so the next message step can use <b>{"{{last_ai_text}}"}</b>.
        </div>
      )}

      {step.type === "send_email" && (
        <div style={{ display: "grid", gap: 12 }}>
          <Field label="Email subject">
            <Input
              value={step.subject || ""}
              onChange={(e) => set({ subject: e.target.value })}
              placeholder="Quick check-in from {{business_name}}"
            />
          </Field>

          <Field label="Email body">
            <TextArea
              ref={emailBodyRef}
              rows={5}
              value={step.body || ""}
              onChange={(e) => set({ body: e.target.value })}
              placeholder={"Hi {{lead.first_name}},\n\nJust checking in. Book here: {{booking_link}}\n\nThanks,\n{{business_name}}"}
            />
          </Field>

          <TokenRow onInsert={(t) => insertToken(emailBodyRef, t, "body")} />
        </div>
      )}

      {step.type === "send_whatsapp" && (
        <div style={{ display: "grid", gap: 12 }}>
          <Field label="WhatsApp message">
            <TextArea
              ref={waBodyRef}
              rows={4}
              value={step.text || ""}
              onChange={(e) => set({ text: e.target.value })}
              placeholder="Use {{last_ai_text}} or include {{booking_link}} / {{business_name}}"
            />
          </Field>

          <TokenRow onInsert={(t) => insertToken(waBodyRef, t, "text")} />

          <div style={{ ...softCard, padding: 12, background: "#1d1f20" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 10 }}>
              <div>
                <div style={{ color: C.text, fontWeight: 800 }}>Template fallback</div>
                <div style={{ color: C.muted, fontSize: 12, marginTop: 2 }}>
                  Used outside the 24-hour WhatsApp window
                </div>
              </div>
              <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 12, color: C.muted }}>
                <input
                  type="checkbox"
                  checked={!!(waTpl.name || waTpl.language || waTpl.params)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      const first = normalizedTemplates[0];
                      setTpl({
                        name: waTpl.name || first?.name || "",
                        language: waTpl.language || first?.languages?.[0]?.code || "en_US",
                        params: waTpl.params || "",
                      });
                    } else {
                      set({ template: undefined });
                    }
                  }}
                />
                Enable
              </label>
            </div>

            {waTpl.name || waTpl.language || waTpl.params ? (
              <div style={{ display: "grid", gap: 10 }}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr) minmax(120px,0.7fr)",
                    gap: 10,
                  }}
                >
                  <Field label="Template">
                    <Select
                      value={waTpl.name || ""}
                      onChange={(e) => {
                        const name = e.target.value;
                        const tpl = normalizedTemplates.find((t) => t.name === name);
                        const lang = tpl?.languages?.[0]?.code || "en_US";
                        const patch = { name, language: lang };

                        if ((tpl?.languages?.[0]?.body_params || 0) > 0) {
                          const commons = ["{{lead.first_name}}", "{{business_name}}", "{{booking_link}}", "{{last_ai_text}}"];
                          patch.params = joinParams(commons.slice(0, tpl.languages[0].body_params));
                        }

                        setTpl(patch);
                      }}
                    >
                      <option value="">Select…</option>
                      {normalizedTemplates.map((n) => (
                        <option key={n.name} value={n.name}>
                          {n.name}
                        </option>
                      ))}
                    </Select>
                  </Field>

                  <Field label="Language">
                    <Select
                      value={waTpl.language || selectedTpl?.languages?.[0]?.code || "en_US"}
                      onChange={(e) => setTpl({ language: e.target.value })}
                    >
                      {(selectedTpl?.languages || []).map((l) => (
                        <option key={l.code} value={l.code}>
                          {l.code}
                        </option>
                      ))}
                      {!selectedTpl?.languages?.length && <option value="en_US">en_US</option>}
                    </Select>
                  </Field>

                  <Field label="Params">
                    <Input readOnly value={paramCount} />
                  </Field>
                </div>

                {paramCount > 0 ? (
                  <>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 10 }}>
                      {paramsArray.map((val, i) => (
                        <Input
                          key={i}
                          value={val}
                          onChange={(e) => {
                            const next = [...paramsArray];
                            next[i] = e.target.value;
                            setTpl({ params: joinParams(next) });
                          }}
                          placeholder={
                            i === 0
                              ? "{{lead.first_name}}"
                              : i === 1
                              ? "{{business_name}}"
                              : i === 2
                              ? "{{booking_link}}"
                              : "{{last_ai_text}}"
                          }
                        />
                      ))}
                    </div>
                    <div>
                      <Btn kind="ghost" onClick={fillCommonParams}>
                        Fill common tokens
                      </Btn>
                    </div>
                  </>
                ) : (
                  <Field label="Template params (comma-separated)">
                    <Input
                      value={waTpl.params || ""}
                      onChange={(e) => setTpl({ params: e.target.value })}
                      placeholder="{{lead.first_name}}, {{business_name}}, {{booking_link}}"
                    />
                  </Field>
                )}
              </div>
            ) : null}
          </div>
        </div>
      )}

      {(step.type === "if_no_reply" || step.type === "if_no_booking") && (
        <div style={{ display: "grid", gap: 12 }}>
          <Field label="Check after how many days?">
            <Input
              type="number"
              value={step.within_days || 2}
              onChange={(e) => set({ within_days: +e.target.value })}
              style={{ maxWidth: 160 }}
            />
          </Field>

          <div>
            <div style={{ color: C.text, fontWeight: 800, marginBottom: 8 }}>Then do this</div>
            <div style={{ display: "grid", gap: 10 }}>
              {(step.then || []).map((s, i) => (
                <StepCard
                  key={i}
                  step={s}
                  waTemplates={waTemplates}
                  onChange={(patch) => {
                    const arr = [...(step.then || [])];
                    arr[i] = patch;
                    set({ then: arr });
                  }}
                  onRemove={() => {
                    const arr = [...(step.then || [])];
                    arr.splice(i, 1);
                    set({ then: arr });
                  }}
                />
              ))}
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
              {["send_email", "send_whatsapp", "wait"].map((t) => (
                <Btn
                  key={t}
                  kind="ghost"
                  onClick={() => set({ then: [...(step.then || []), buildDefaultStep(t)] })}
                >
                  + {t.replaceAll("_", " ")}
                </Btn>
              ))}
            </div>
          </div>
        </div>
      )}

      {step.type === "push_owner" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 10 }}>
          <Field label="Notification title">
            <Input value={step.title || "Give them a quick call"} onChange={(e) => set({ title: e.target.value })} />
          </Field>
          <Field label="Notification message">
            <Input value={step.message || "Lead may need a call"} onChange={(e) => set({ message: e.target.value })} />
          </Field>
        </div>
      )}

      {step.type === "add_tag" && (
        <Field label="Tag to add">
          <Input value={step.tag || "Needs Attention"} onChange={(e) => set({ tag: e.target.value })} />
        </Field>
      )}
    </div>
  );
}

function TemplateCard({ template, onUse }) {
  const previewTrigger = PRETTY_TRIGGER[template?.trigger?.type]?.(template.trigger || {}) || "Ready-to-use automation";
  const stepCount = Array.isArray(template?.steps) ? template.steps.length : 0;

  return (
    <div style={{ ...shellCard, padding: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
        <div>
          <div style={{ color: C.text, fontWeight: 900, fontSize: 18 }}>
            {template?.name || "Automation Template"}
          </div>
          <div style={{ color: C.muted, fontSize: 13, marginTop: 6 }}>{previewTrigger}</div>
        </div>
        <div
          style={{
            background: "rgba(247,203,83,0.12)",
            color: C.gold,
            border: "1px solid rgba(247,203,83,0.3)",
            borderRadius: 999,
            padding: "5px 10px",
            fontSize: 12,
            fontWeight: 900,
          }}
        >
          {stepCount} step{stepCount === 1 ? "" : "s"}
        </div>
      </div>

      <div style={{ marginTop: 14, color: C.text, fontSize: 14, lineHeight: 1.55 }}>
        {flowSummary(template)}
      </div>

      <div style={{ marginTop: 16 }}>
        <Btn onClick={onUse}>Use Template</Btn>
      </div>
    </div>
  );
}

function FlowCard({ flow, onEdit, onDelete, onToggle }) {
  return (
    <div style={{ ...shellCard, padding: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div style={{ color: C.text, fontWeight: 900, fontSize: 18 }}>{flow.name}</div>
            <span
              style={{
                background: flow.enabled ? "rgba(48,180,108,0.13)" : "rgba(170,176,182,0.12)",
                color: flow.enabled ? C.green : C.muted,
                border: `1px solid ${flow.enabled ? "rgba(48,180,108,0.3)" : "rgba(170,176,182,0.25)"}`,
                borderRadius: 999,
                padding: "4px 10px",
                fontSize: 12,
                fontWeight: 900,
              }}
            >
              {flow.enabled ? "Active" : "Draft"}
            </span>
          </div>

          <div style={{ color: C.muted, fontSize: 13, marginTop: 8 }}>
            {flowSummary(flow)}
          </div>
        </div>

        <Toggle checked={flow.enabled} onChange={onToggle} />
      </div>

      <div style={{ marginTop: 14 }}>
        <FlowDiagram flow={flow} />
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 16 }}>
        <Btn kind="ghost" onClick={onEdit}>
          Edit
        </Btn>
        <Btn kind="danger" onClick={onDelete}>
          Delete
        </Btn>
      </div>
    </div>
  );
}

function TriggerChooser({ editing, setEditing }) {
  const trig = editing?.trigger || { type: "" };

  const setTriggerType = (type) => {
    setEditing({
      ...editing,
      trigger:
        type === "no_reply"
          ? { type, days: trig.days || 3 }
          : type === "new_lead"
          ? { type, within_hours: trig.within_hours || 24 }
          : { type },
    });
  };

  return (
    <div style={{ ...shellCard, padding: 18 }}>
      <SectionTitle
        title="1. Choose when this should run"
        subtitle="Start with the event that should kick off the automation."
      />

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        <Chip active={trig.type === "no_reply"} onClick={() => setTriggerType("no_reply")}>
          No reply
        </Chip>
        <Chip active={trig.type === "new_lead"} onClick={() => setTriggerType("new_lead")}>
          New lead
        </Chip>
        <Chip active={trig.type === "appointment_no_show"} onClick={() => setTriggerType("appointment_no_show")}>
          Appointment no-show
        </Chip>
      </div>

      {trig.type === "no_reply" && (
        <Field label="How many days with no reply?">
          <Input
            type="number"
            value={trig.days || 3}
            onChange={(e) =>
              setEditing({
                ...editing,
                trigger: { ...trig, days: +e.target.value },
              })
            }
            style={{ maxWidth: 180 }}
          />
        </Field>
      )}

      {trig.type === "new_lead" && (
        <Field label="Treat as new lead for how many hours?">
          <Input
            type="number"
            value={trig.within_hours || 24}
            onChange={(e) =>
              setEditing({
                ...editing,
                trigger: { ...trig, within_hours: +e.target.value },
              })
            }
            style={{ maxWidth: 180 }}
          />
        </Field>
      )}
    </div>
  );
}

function GuardrailsCard({ editing, setEditing }) {
  return (
    <div style={{ ...shellCard, padding: 18 }}>
      <SectionTitle
        title="2. Guardrails"
        subtitle="Keep automations calm and customer-friendly."
      />

      <div style={{ display: "grid", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <div style={{ color: C.text, fontWeight: 800 }}>Stop if the lead replies</div>
            <div style={{ color: C.muted, fontSize: 12, marginTop: 4 }}>
              Prevents follow-ups after the conversation becomes active again.
            </div>
          </div>
          <Toggle
            checked={editing.auto_stop_on_reply}
            onChange={(e) => setEditing({ ...editing, auto_stop_on_reply: e.target.checked })}
          />
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <div style={{ color: C.text, fontWeight: 800 }}>Respect quiet hours</div>
            <div style={{ color: C.muted, fontSize: 12, marginTop: 4 }}>
              Delays sends if the message would go out too late or too early.
            </div>
          </div>
          <Toggle
            checked={editing.caps?.respect_quiet_hours !== false}
            onChange={(e) =>
              setEditing({
                ...editing,
                caps: { ...(editing.caps || {}), respect_quiet_hours: e.target.checked },
              })
            }
          />
        </div>

        <Field label="Max sends per lead per day">
          <Input
            type="number"
            value={editing.caps?.per_lead_per_day ?? 1}
            onChange={(e) =>
              setEditing({
                ...editing,
                caps: { ...(editing.caps || {}), per_lead_per_day: +e.target.value },
              })
            }
            style={{ maxWidth: 180 }}
          />
        </Field>
      </div>
    </div>
  );
}

function StepsBuilder({ editing, setEditing, waTemplates }) {
  const addStep = (type) => {
    const next = [...(editing.steps || []), buildDefaultStep(type)];
    setEditing({ ...editing, steps: next });
  };

  return (
    <div style={{ ...shellCard, padding: 18 }}>
      <SectionTitle
        title="3. What should happen next?"
        subtitle="Add only the steps you need. Keep it simple."
        right={
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {["wait", "ai_draft", "send_email", "send_whatsapp", "if_no_reply", "if_no_booking", "push_owner", "add_tag"].map((k) => (
              <Btn key={k} kind="ghost" onClick={() => addStep(k)} style={{ padding: "8px 10px", fontSize: 12 }}>
                + {k.replaceAll("_", " ")}
              </Btn>
            ))}
          </div>
        }
      />

      {(editing.steps || []).length ? (
        <div style={{ display: "grid", gap: 12 }}>
          {(editing.steps || []).map((s, i) => (
            <StepCard
              key={i}
              step={s}
              waTemplates={waTemplates}
              onChange={(patch) => {
                const arr = [...(editing.steps || [])];
                arr[i] = patch;
                setEditing({ ...editing, steps: arr });
              }}
              onRemove={() => {
                const arr = [...(editing.steps || [])];
                arr.splice(i, 1);
                setEditing({ ...editing, steps: arr });
              }}
            />
          ))}
        </div>
      ) : (
        <div style={{ color: C.muted, fontSize: 13 }}>
          No steps yet. Add a message, a wait, or a reminder to get started.
        </div>
      )}
    </div>
  );
}

function BuilderSummary({ editing }) {
  return (
    <div style={{ ...shellCard, padding: 18 }}>
      <SectionTitle
        title="Flow Summary"
        subtitle="This is how the automation will feel to the user."
      />

      <div style={{ color: C.text, fontSize: 15, lineHeight: 1.6 }}>
        {flowSummary(editing)}
      </div>

      <div style={{ marginTop: 16 }}>
        <FlowDiagram flow={editing} />
      </div>
    </div>
  );
}

function Preview({ userEmail, flow }) {
  const [leadEmail, setLeadEmail] = useState("");
  const [list, setList] = useState(null);
  const [did, setDid] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const run = async () => {
    setLoading(true);
    setErr("");
    setList(null);
    setDid(null);
    try {
      const data = await api.dryRun(userEmail, flow, { lead_email: leadEmail });
      setList(Array.isArray(data?.would) ? data.would : []);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  };

  const runNow = async () => {
    setLoading(true);
    setErr("");
    setDid(null);
    try {
      const data = await api.executeNow(userEmail, flow, {
        lead_email: leadEmail,
        ignore_waits: true,
        ignore_quiet_hours: true,
        bypass_rate_limits: true,
      });
      setDid(Array.isArray(data?.did) ? data.did : []);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  };

  const renderInfoBits = (a) => {
    const bits = [];
    if (a.info?.subject) bits.push(a.info.subject);
    if (a.info?.text) bits.push(a.info.text);
    if (a.info?.template?.name) bits.push(`[tpl:${a.info.template.name}${a.info.template.language ? "/" + a.info.template.language : ""}]`);
    if (a.info?.used_lang) bits.push(`lang=${a.info.used_lang}`);
    if (a.info?.mode) bits.push(`mode=${a.info.mode}`);
    return bits.length ? <span style={{ opacity: 0.75 }}> — {bits.join(" · ")}</span> : null;
  };

  return (
    <div style={{ ...softCard, padding: 16 }}>
      <SectionTitle
        title="Test this flow"
        subtitle="Preview first, or run it live to actually send emails, WhatsApp, tags, and owner actions."
      />

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Input
          placeholder="lead@example.com"
          value={leadEmail}
          onChange={(e) => setLeadEmail(e.target.value)}
          style={{ flex: 1, minWidth: 240 }}
        />
        <Btn kind="ghost" onClick={run} disabled={!leadEmail || loading}>
          {loading ? "Running..." : "Preview"}
        </Btn>
        <Btn onClick={runNow} disabled={!leadEmail || loading}>
          {loading ? "Executing..." : "Run Live"}
        </Btn>
      </div>

      {err ? (
        <div
          style={{
            marginTop: 12,
            background: C.redBg,
            color: C.redTxt,
            border: "1px solid #4a1515",
            borderRadius: 12,
            padding: "10px 12px",
            fontSize: 13,
          }}
        >
          {err}
        </div>
      ) : null}

      <div style={{ marginTop: 14, display: "grid", gap: 14 }}>
        <div style={{ ...softCard, padding: 14 }}>
          <div style={{ color: C.text, fontWeight: 900, marginBottom: 8 }}>Would run now</div>
          {list === null ? (
            <div style={{ color: C.muted, fontSize: 13 }}>No preview run yet.</div>
          ) : !list.length ? (
            <div style={{ color: C.muted, fontSize: 13 }}>No actions would run.</div>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {list.map((a, i) => (
                <li key={i} style={{ marginBottom: 6 }}>
                  {a.type}
                  {renderInfoBits(a)}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div style={{ ...softCard, padding: 14 }}>
          <div style={{ color: C.text, fontWeight: 900, marginBottom: 8 }}>Executed actions</div>
          {!Array.isArray(did) ? (
            <div style={{ color: C.muted, fontSize: 13 }}>
              Nothing executed yet. Use <b>Run Live</b> to actually send the email / WhatsApp and perform the flow.
            </div>
          ) : !did.length ? (
            <div style={{ color: C.muted, fontSize: 13 }}>Nothing executed.</div>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {did.map((a, i) => (
                <li key={i} style={{ marginBottom: 6 }}>
                  {a.type} — {a.status}
                  {renderInfoBits(a)}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

/* -------------------- MAIN -------------------- */
export default function Automations({ user }) {
  const userEmail = (user?.email || "demo@retainai.ca").toLowerCase();

  const [tab, setTab] = useState("flows");
  const [templates, setTemplates] = useState([]);
  const [flows, setFlows] = useState([]);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [savingFlow, setSavingFlow] = useState(false);
  const [error, setError] = useState("");

  const [profile, setProfile] = useState({
    business_name: "",
    booking_link: "",
    quiet_hours_start: "",
    quiet_hours_end: "",
  });
  const [savingProfile, setSavingProfile] = useState(false);
  const [waTemplates, setWATemplates] = useState([]);

  async function refreshFlows() {
    const d = await api.listFlows(userEmail);
    const items = Array.isArray(d?.flows) ? d.flows : [];
    setFlows(items.map((f) => normalizeFlow(f, userEmail)));
  }

  useEffect(() => {
    let mounted = true;

    (async () => {
      try {
        setLoading(true);
        setError("");

        const [t, p, wa] = await Promise.all([
          api.getTemplates(),
          api.getProfile(userEmail),
          api.getWATemplates(userEmail).catch(() => ({ templates: [] })),
        ]);

        if (!mounted) return;

        setTemplates(Array.isArray(t?.templates) ? t.templates : []);
        setProfile({
          business_name: p?.profile?.business_name || "",
          booking_link: p?.profile?.booking_link || "",
          quiet_hours_start: p?.profile?.quiet_hours_start ?? "",
          quiet_hours_end: p?.profile?.quiet_hours_end ?? "",
        });

        const waItems = wa?.templates || [];
        setWATemplates(Array.isArray(waItems) ? waItems : []);

        await refreshFlows();
      } catch (e) {
        if (mounted) setError(String(e.message || e));
      } finally {
        if (mounted) setLoading(false);
      }
    })();

    return () => {
      mounted = false;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userEmail]);

  const applyTemplate = (t) => {
    setEditing(cloneTemplateToFlow(t, userEmail));
    setTab("builder");
  };

  const saveFlow = async () => {
    if (!editing) return;

    try {
      setSavingFlow(true);
      setError("");

      const payload = normalizeFlow(editing, userEmail);
      const isUpdate = !!payload.id && flows.some((x) => x.id === payload.id);

      if (isUpdate) {
        const d = await api.updateFlow(userEmail, payload.id, payload);
        const updated = normalizeFlow(d?.flow || payload, userEmail);
        setFlows((prev) => prev.map((f) => (f.id === updated.id ? updated : f)));
      } else {
        const d = await api.createFlow(userEmail, payload);
        const created = normalizeFlow(d?.flow || payload, userEmail);
        setFlows((prev) => [...prev, created]);
      }

      await refreshFlows();
      setEditing(null);
      setTab("flows");
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSavingFlow(false);
    }
  };

  const saveProf = async () => {
    setSavingProfile(true);
    try {
      await api.saveProfile(userEmail, profile);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSavingProfile(false);
    }
  };

  const stats = {
    totalTemplates: templates.length,
    totalFlows: flows.length,
    activeFlows: flows.filter((f) => f.enabled).length,
    draftFlows: flows.filter((f) => !f.enabled).length,
  };

  return (
    <div
      style={{
        width: "100%",
        minHeight: "100vh",
        background: C.bg,
        color: C.text,
      }}
    >
      <div
        style={{
          padding: "22px 22px 16px 22px",
          borderBottom: `1px solid ${C.border}`,
          background: C.panel,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div>
            <div style={{ fontSize: 30, fontWeight: 900, letterSpacing: -0.5 }}>Automations</div>
            <div style={{ color: C.muted, marginTop: 6, fontSize: 14 }}>
              Build simple follow-up flows that are easy to launch, easy to understand, and easy to manage.
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Chip active={tab === "templates"} onClick={() => setTab("templates")}>
              Templates
            </Chip>
            <Chip active={tab === "flows"} onClick={() => setTab("flows")}>
              My Flows
            </Chip>
            <Chip
              active={tab === "builder"}
              onClick={() => {
                if (!editing) setEditing(buildEmptyFlow(userEmail));
                setTab("builder");
              }}
            >
              Builder
            </Chip>
          </div>
        </div>
      </div>

      <div style={{ padding: 22 }}>
        {error ? (
          <div
            style={{
              marginBottom: 16,
              background: C.redBg,
              color: C.redTxt,
              border: "1px solid #4a1515",
              borderRadius: 14,
              padding: "12px 14px",
              fontSize: 14,
            }}
          >
            {error}
          </div>
        ) : null}

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0,1.3fr) minmax(340px,1fr)",
            gap: 16,
            marginBottom: 22,
            alignItems: "stretch",
          }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12 }}>
            <StatCard label="Templates" value={stats.totalTemplates} />
            <StatCard label="Flows" value={stats.totalFlows} />
            <StatCard label="Active" value={stats.activeFlows} accent />
            <StatCard label="Drafts" value={stats.draftFlows} />
          </div>

          <div style={{ ...shellCard, padding: 16 }}>
            <SectionTitle
              title="Automation Settings"
              subtitle="These values can be reused across flows."
              right={
                <Btn onClick={saveProf} disabled={savingProfile}>
                  {savingProfile ? "Saving..." : "Save"}
                </Btn>
              }
            />

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(4, minmax(0,1fr))",
                gap: 10,
              }}
            >
              <Field label="Business name">
                <Input
                  value={profile.business_name}
                  onChange={(e) => setProfile({ ...profile, business_name: e.target.value })}
                  placeholder="RetainAI"
                />
              </Field>

              <Field label="Booking link">
                <Input
                  value={profile.booking_link}
                  onChange={(e) => setProfile({ ...profile, booking_link: e.target.value })}
                  placeholder="https://..."
                />
              </Field>

              <Field label="Quiet hours start">
                <Input
                  value={profile.quiet_hours_start}
                  onChange={(e) => setProfile({ ...profile, quiet_hours_start: e.target.value })}
                  placeholder="21:00"
                />
              </Field>

              <Field label="Quiet hours end">
                <Input
                  value={profile.quiet_hours_end}
                  onChange={(e) => setProfile({ ...profile, quiet_hours_end: e.target.value })}
                  placeholder="08:00"
                />
              </Field>
            </div>
          </div>
        </div>

        {loading ? (
          <div style={{ ...shellCard, padding: 22, color: C.muted }}>Loading automations...</div>
        ) : null}

        {!loading && tab === "templates" && (
          <div style={{ display: "grid", gap: 18 }}>
            <SectionTitle
              title="Start with a goal"
              subtitle="Pick a ready-made automation and customize it in a minute."
            />

            {templates.length ? (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
                {templates.map((t, i) => (
                  <TemplateCard key={t.id || i} template={t} onUse={() => applyTemplate(t)} />
                ))}
              </div>
            ) : (
              <div style={{ ...shellCard, padding: 18, color: C.muted }}>
                No automation templates were returned by the API right now.
              </div>
            )}
          </div>
        )}

        {!loading && tab === "flows" && (
          <div style={{ display: "grid", gap: 18 }}>
            <SectionTitle
              title="My Flows"
              subtitle="Your live and draft automations in one place."
              right={
                <Btn
                  onClick={() => {
                    setEditing(buildEmptyFlow(userEmail));
                    setTab("builder");
                  }}
                >
                  New Flow
                </Btn>
              }
            />

            {flows.length ? (
              <div style={{ display: "grid", gap: 16 }}>
                {flows.map((f) => (
                  <FlowCard
                    key={f.id}
                    flow={f}
                    onEdit={() => {
                      setEditing(normalizeFlow(f, userEmail));
                      setTab("builder");
                    }}
                    onDelete={async () => {
                      if (!window.confirm("Delete this flow?")) return;
                      const prev = [...flows];
                      setFlows((curr) => curr.filter((x) => x.id !== f.id));
                      try {
                        await api.deleteFlow(userEmail, f.id);
                        await refreshFlows();
                      } catch (err) {
                        setFlows(prev);
                        setError(String(err.message || err));
                      }
                    }}
                    onToggle={async () => {
                      const enabled = !f.enabled;
                      const prev = [...flows];
                      setFlows((curr) => curr.map((x) => (x.id === f.id ? { ...x, enabled } : x)));
                      try {
                        await api.updateFlow(userEmail, f.id, { ...f, enabled });
                        await refreshFlows();
                      } catch (err) {
                        setFlows(prev);
                        setError(String(err.message || err));
                      }
                    }}
                  />
                ))}
              </div>
            ) : (
              <div style={{ ...shellCard, padding: 18, color: C.muted }}>
                No flows yet — start from a template or create a new one.
              </div>
            )}
          </div>
        )}

        {!loading && tab === "builder" && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(420px, 560px) minmax(0, 1fr)",
              gap: 18,
              alignItems: "start",
            }}
          >
            <div style={{ display: "grid", gap: 16, alignSelf: "start" }}>
              <div style={{ ...shellCard, padding: 18 }}>
                <SectionTitle
                  title="Flow Setup"
                  subtitle="Name your automation and turn it into something your team can understand at a glance."
                  right={
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <Btn kind="ghost" onClick={() => setEditing(buildEmptyFlow(userEmail))}>
                        New
                      </Btn>
                      <Btn
                        kind="outline"
                        onClick={() => {
                          setEditing(null);
                          setTab("flows");
                        }}
                      >
                        Cancel
                      </Btn>
                      <Btn onClick={saveFlow} disabled={!editing || savingFlow}>
                        {savingFlow ? "Saving..." : "Save Flow"}
                      </Btn>
                    </div>
                  }
                />

                {!editing ? (
                  <div style={{ color: C.muted, fontSize: 14 }}>
                    Open a flow or create a new one to begin.
                  </div>
                ) : (
                  <div style={{ display: "grid", gap: 14 }}>
                    <Field label="Flow name">
                      <Input
                        value={editing.name || ""}
                        onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                        placeholder="Re-engage cold leads"
                      />
                    </Field>

                    <TriggerChooser editing={editing} setEditing={setEditing} />
                    <GuardrailsCard editing={editing} setEditing={setEditing} />
                    <StepsBuilder editing={editing} setEditing={setEditing} waTemplates={waTemplates} />
                  </div>
                )}
              </div>
            </div>

            <div
              style={{
                display: "grid",
                gap: 16,
                alignSelf: "start",
                minWidth: 0,
              }}
            >
              <BuilderSummary editing={editing || buildEmptyFlow(userEmail)} />
              {editing ? <Preview userEmail={userEmail} flow={editing} /> : null}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
// src/components/Automations.jsx
import React, { useEffect, useRef, useState, useMemo } from "react";
import api from "./AutomationsService";

/* ---- THEME ---- */
const BG = "#171819";
const PANEL = "#1f2022";
const CARD = "#242628";
const CARD_SOFT = "#202224";
const BORDER = "#2e3134";
const TEXT = "#eef1f3";
const MUTED = "#aab0b6";
const GOLD = "#f7cb53";
const GOLD_DARK = "#d9ae3a";
const DANGER_BG = "#3a1111";
const DANGER_TXT = "#ffbcbc";

const shellCard = {
  background: CARD,
  border: `1px solid ${BORDER}`,
  borderRadius: 18,
  boxShadow: "0 8px 28px rgba(0,0,0,0.22)",
};

/* ---- PRIMITIVES ---- */
const Btn = ({ children, onClick, kind = "solid", disabled, className, type = "button" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className={
      "px-3 py-2 rounded-xl font-medium transition " +
      (kind === "solid"
        ? "bg-[#f7cb53] text-black hover:opacity-95 disabled:opacity-60"
        : kind === "danger"
        ? "bg-[#3a1111] text-[#ffbcbc] hover:bg-[#4a1515] disabled:opacity-60"
        : "bg-[#2a2a2a] text-white hover:bg-[#323232] disabled:opacity-60") +
      (className ? ` ${className}` : "")
    }
  >
    {children}
  </button>
);

const Input = React.forwardRef((props, ref) => (
  <input
    ref={ref}
    {...props}
    className={
      "w-full bg-[#232323] text-white border border-[#2a2a2a] rounded-xl px-3 py-2 focus:outline-none " +
      (props.className || "")
    }
  />
));

const TextArea = React.forwardRef((props, ref) => (
  <textarea
    ref={ref}
    {...props}
    className={
      "w-full bg-[#232323] text-white border border-[#2a2a2a] rounded-xl px-3 py-2 focus:outline-none " +
      (props.className || "")
    }
  />
));

const Toggle = ({ checked, onChange }) => (
  <label className="inline-flex items-center cursor-pointer select-none">
    <span className="mr-2 text-sm">Off</span>
    <div className="relative">
      <input type="checkbox" className="sr-only" checked={!!checked} onChange={onChange} />
      <div className="block w-12 h-7 rounded-full bg-[#2a2a2a]" />
      <div
        className={
          "dot absolute left-1 top-1 w-5 h-5 rounded-full transition " +
          (checked ? "translate-x-5 bg-white" : "bg-[#777]")
        }
      />
    </div>
    <span className="ml-2 text-sm">On</span>
  </label>
);

/* ---- TOKENS ---- */
const TOKENS = ["{{business_name}}", "{{booking_link}}", "{{lead.first_name}}", "{{last_ai_text}}"];

const TokenRow = ({ onInsert }) => (
  <div className="flex flex-wrap gap-2">
    {TOKENS.map((t) => (
      <button
        key={t}
        type="button"
        onClick={() => onInsert?.(t)}
        className="text-xs bg-[#242424] border border-[#2a2a2a] px-2 py-1 rounded hover:bg-[#2a2a2a]"
      >
        {t}
      </button>
    ))}
  </div>
);

/* ---- LABELS ---- */
const PRETTY = {
  no_reply: (t) => `No reply for ${t.days || 3} days`,
  new_lead: (t) => `New lead (≤ ${t.within_hours || 24}h)`,
  appointment_no_show: () => "Appointment no-show",
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

/* ---- ARROW ---- */
const ArrowRight = () => (
  <svg width="36" height="16" viewBox="0 0 36 16" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M0 8H30" stroke="#3a3a3a" strokeWidth="2" />
    <path d="M25 3L30 8L25 13" stroke="#3a3a3a" strokeWidth="2" />
  </svg>
);

/* ---- FLOW NODES ---- */
const HNode = ({ title, subtitle }) => (
  <div
    style={{
      background: CARD_SOFT,
      border: `1px solid ${BORDER}`,
      borderRadius: 14,
      padding: 12,
      minWidth: 210,
      boxShadow: "0 2px 18px rgba(0,0,0,0.18)",
    }}
  >
    <div className="text-xs" style={{ color: MUTED }}>
      {subtitle}
    </div>
    <div className="text-white font-semibold">{title}</div>
  </div>
);

const StepPreview = ({ step }) => {
  const t = step.type;
  if (t === "wait") {
    const dur = step.days ? `${step.days}d` : step.hours ? `${step.hours}h` : step.minutes ? `${step.minutes}m` : "";
    return <HNode subtitle="Delay" title={`Wait ${dur}`} />;
  }
  if (t === "ai_draft") return <HNode subtitle="Content" title="AI Draft" />;
  if (t === "send_email") return <HNode subtitle="Action" title="Send Email" />;
  if (t === "send_whatsapp") {
    const label =
      step.template?.name
        ? `Send WhatsApp · tpl: ${step.template.name}`
        : "Send WhatsApp";
    return <HNode subtitle="Action" title={label} />;
  }
  if (t === "push_owner") return <HNode subtitle="Action" title="Push Owner" />;
  if (t === "add_tag") return <HNode subtitle="Action" title={`Add Tag: ${step.tag || "…"}`} />;
  if (t === "if_no_reply") return <HNode subtitle="Branch" title={`If No Reply ≤ ${step.within_days || 2}d`} />;
  if (t === "if_no_booking") return <HNode subtitle="Branch" title={`If No Booking ≤ ${step.within_days || 2}d`} />;
  return <HNode subtitle="Step" title={t} />;
};

const FlowDiagram = ({ flow }) => {
  const trig = flow?.trigger || {};
  const title =
    trig.type === "no_reply"
      ? `no_reply (${trig.days || 3}d)`
      : trig.type === "new_lead"
      ? `new_lead (≤ ${trig.within_hours || 24}h)`
      : trig.type || "Trigger";

  const steps = flow?.steps || [];

  return (
    <div className="overflow-x-auto">
      <div className="flex items-center gap-3 min-w-[680px]">
        <HNode subtitle="Trigger" title={title} />
        {steps.map((s, i) => (
          <React.Fragment key={i}>
            <ArrowRight />
            <StepPreview step={s} />
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};

/* ---- WA helpers ---- */
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

/* ---- STEP CARD ---- */
function StepCard({ step, onChange, onRemove, waTemplates }) {
  const set = (patch) => onChange({ ...step, ...patch });
  const bodyRef = useRef(null);
  const waRef = useRef(null);

  const insertToken = (ref, tok) => {
    const el = ref.current;
    if (!el) return;
    const s = el.selectionStart || 0;
    const e = el.selectionEnd || 0;
    const next = el.value.slice(0, s) + tok + el.value.slice(e);
    el.value = next;
    el.selectionStart = el.selectionEnd = s + tok.length;
    el.focus();
    if (ref === bodyRef) set({ body: next });
    if (ref === waRef) set({ text: next });
  };

  const waTpl = step.template || {};
  const setTpl = (patch) => set({ template: { ...(step.template || {}), ...patch } });

  const normalized = useMemo(() => normalizeWATemplates(waTemplates || []), [waTemplates]);
  const templateNames = useMemo(() => normalized.map((t) => t.name), [normalized]);
  const selectedTpl = useMemo(
    () => normalized.find((t) => t.name === waTpl.name) || null,
    [normalized, waTpl.name]
  );
  const languages = useMemo(
    () => (selectedTpl?.languages || []).map((l) => l.code),
    [selectedTpl]
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
    <div style={{ background: CARD_SOFT, border: `1px solid ${BORDER}`, borderRadius: 14, padding: 14 }}>
      <div className="flex items-center justify-between">
        <div className="font-semibold capitalize">{step.type.replaceAll("_", " ")}</div>
        {onRemove && (
          <button className="text-sm opacity-80 hover:opacity-100" onClick={onRemove}>
            Remove
          </button>
        )}
      </div>

      {step.type === "wait" && (
        <div className="grid grid-cols-3 gap-2 mt-3">
          <div>
            <div className="text-xs mb-1">Days</div>
            <Input type="number" value={step.days || 0} onChange={(e) => set({ days: +e.target.value })} />
          </div>
          <div>
            <div className="text-xs mb-1">Hours</div>
            <Input type="number" value={step.hours || 0} onChange={(e) => set({ hours: +e.target.value })} />
          </div>
          <div>
            <div className="text-xs mb-1">Minutes</div>
            <Input type="number" value={step.minutes || 0} onChange={(e) => set({ minutes: +e.target.value })} />
          </div>
        </div>
      )}

      {step.type === "send_whatsapp" && (
        <div className="mt-3">
          <div className="text-xs mb-1">Message</div>
          <TextArea
            ref={waRef}
            rows={3}
            value={step.text || ""}
            onChange={(e) => set({ text: e.target.value })}
            placeholder="Use {{last_ai_text}} or include {{booking_link}} / {{business_name}}"
          />
          <div className="mt-2">
            <TokenRow onInsert={(t) => insertToken(waRef, t)} />
          </div>

          <div className="mt-3 rounded-xl p-3" style={{ border: `1px dashed ${BORDER}` }}>
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold">Template fallback (outside 24h)</div>
              <label className="text-xs flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={!!(waTpl.name || waTpl.language || waTpl.params)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      const first = normalizeWATemplates(waTemplates || [])[0];
                      setTpl({
                        name: waTpl.name || first?.name || "",
                        language: waTpl.language || first?.languages?.[0]?.code || "en_US",
                        params: waTpl.params || "",
                      });
                    } else {
                      const clone = { ...(step.template || {}) };
                      delete clone.name;
                      delete clone.language;
                      delete clone.params;
                      set({ template: Object.keys(clone).length ? clone : undefined });
                    }
                  }}
                />
                Enable
              </label>
            </div>

            {(waTpl.name || waTpl.language || waTpl.params) && (
              <div className="grid gap-2 mt-3">
                <div className="grid md:grid-cols-3 gap-2">
                  <div>
                    <div className="text-xs mb-1">Template</div>
                    {templateNames.length ? (
                      <select
                        className="w-full bg-[#232323] text-white border border-[#2a2a2a] rounded-xl p-2"
                        value={waTpl.name || ""}
                        onChange={(e) => {
                          const name = e.target.value;
                          const tpl = normalized.find((t) => t.name === name);
                          const lang = tpl?.languages?.[0]?.code || "en_US";
                          const nextPatch = { name, language: lang };

                          if ((tpl?.languages?.[0]?.body_params || 0) > 0) {
                            const commons = ["{{lead.first_name}}", "{{business_name}}", "{{booking_link}}", "{{last_ai_text}}"];
                            const n = tpl.languages[0].body_params;
                            nextPatch.params = joinParams(commons.slice(0, n));
                          }

                          setTpl(nextPatch);
                        }}
                      >
                        <option value="">Select…</option>
                        {templateNames.map((n) => (
                          <option key={n} value={n}>
                            {n}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Input
                        value={waTpl.name || ""}
                        onChange={(e) => setTpl({ name: e.target.value })}
                        placeholder="your_template"
                      />
                    )}
                  </div>

                  <div>
                    <div className="text-xs mb-1">Language</div>
                    {languages.length ? (
                      <select
                        className="w-full bg-[#232323] text-white border border-[#2a2a2a] rounded-xl p-2"
                        value={waTpl.language || languages[0]}
                        onChange={(e) => setTpl({ language: e.target.value })}
                      >
                        {languages.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Input
                        value={waTpl.language || "en_US"}
                        onChange={(e) => setTpl({ language: e.target.value })}
                        placeholder="en_US"
                      />
                    )}
                  </div>

                  <div>
                    <div className="text-xs mb-1">Required params</div>
                    <div className="text-sm bg-[#232323] border border-[#2a2a2a] rounded-xl px-3 py-2">
                      {paramCount}
                    </div>
                  </div>
                </div>

                {paramCount > 0 ? (
                  <div className="mt-1">
                    <div className="text-xs mb-1">Body parameters</div>
                    <div className="grid md:grid-cols-2 gap-2">
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
                    <div className="flex items-center gap-2 mt-2">
                      <Btn kind="ghost" onClick={fillCommonParams}>
                        Fill common tokens
                      </Btn>
                      <div className="text-xs opacity-70">Tip: start with common tokens, then tweak.</div>
                    </div>
                  </div>
                ) : (
                  <div>
                    <div className="text-xs mb-1">Params (comma-separated)</div>
                    <Input
                      value={waTpl.params || ""}
                      onChange={(e) => setTpl({ params: e.target.value })}
                      placeholder="{{lead.first_name}}, {{business_name}}, {{booking_link}}"
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {step.type === "send_email" && (
        <div className="mt-3">
          <div className="text-xs mb-1">Subject</div>
          <Input
            value={step.subject || ""}
            onChange={(e) => set({ subject: e.target.value })}
            placeholder="Quick check-in from {{business_name}}"
          />
          <div className="text-xs mb-1 mt-3">Body</div>
          <TextArea
            ref={bodyRef}
            rows={5}
            value={step.body || ""}
            onChange={(e) => set({ body: e.target.value })}
            placeholder={`Hi {{lead.first_name}},\n\nJust checking in. Book here: {{booking_link}}\n\nThanks,\n{{business_name}}`}
          />
          <div className="mt-2">
            <TokenRow onInsert={(t) => insertToken(bodyRef, t)} />
          </div>
          <div className="text-xs text-[#9a9a9a] mt-2">This will be formatted as a clean email automatically.</div>
        </div>
      )}

      {(step.type === "if_no_reply" || step.type === "if_no_booking") && (
        <div className="mt-3">
          <div className="text-xs mb-1">Within days</div>
          <Input
            type="number"
            value={step.within_days || 2}
            onChange={(e) => set({ within_days: +e.target.value })}
            style={{ maxWidth: 120 }}
          />
          <div className="text-xs text-[#bdbdbd] mt-3">Then do:</div>
          <div className="flex flex-col gap-2 mt-2">
            {(step.then || []).map((s, i) => (
              <StepCard
                key={i}
                step={s}
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
                waTemplates={waTemplates}
              />
            ))}
            <div className="flex flex-wrap gap-2">
              <Btn
                kind="ghost"
                onClick={() =>
                  set({
                    then: [
                      ...(step.then || []),
                      {
                        type: "send_email",
                        subject: "We still here?",
                        body: "Quick check-in — want to grab a spot with {{business_name}}?\n\nBook here: {{booking_link}}",
                      },
                    ],
                  })
                }
              >
                + Email
              </Btn>
              <Btn
                kind="ghost"
                onClick={() =>
                  set({
                    then: [...(step.then || []), { type: "send_whatsapp", text: "Just checking in — {{booking_link}}" }],
                  })
                }
              >
                + WhatsApp
              </Btn>
              <Btn
                kind="ghost"
                onClick={() => set({ then: [...(step.then || []), { type: "wait", hours: 24 }] })}
              >
                + Wait
              </Btn>
            </div>
          </div>
        </div>
      )}

      {step.type === "push_owner" && (
        <div className="grid md:grid-cols-2 gap-2 mt-3">
          <div>
            <div className="text-xs mb-1">Title</div>
            <Input value={step.title || "Lead to call"} onChange={(e) => set({ title: e.target.value })} />
          </div>
          <div>
            <div className="text-xs mb-1">Message</div>
            <Input value={step.message || "Lead may need a call"} onChange={(e) => set({ message: e.target.value })} />
          </div>
        </div>
      )}

      {step.type === "add_tag" && (
        <div className="mt-3">
          <div className="text-xs mb-1">Tag</div>
          <Input value={step.tag || "Needs Attention"} onChange={(e) => set({ tag: e.target.value })} />
        </div>
      )}
    </div>
  );
}

/* ---- PREVIEW ---- */
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
      setList(Array.isArray(data.would) ? data.would : []);
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
      setDid(Array.isArray(data.did) ? data.did : []);
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
    return bits.length ? <span className="opacity-70"> — {bits.join(" · ")}</span> : null;
  };

  return (
    <div>
      <div className="text-sm mb-1">Test with lead email</div>
      <div className="flex gap-2">
        <Input placeholder="lead@example.com" value={leadEmail} onChange={(e) => setLeadEmail(e.target.value)} />
        <Btn kind="ghost" onClick={run} disabled={!leadEmail || loading}>
          {loading ? "Running…" : "Run"}
        </Btn>
        <Btn onClick={runNow} disabled={!leadEmail || loading}>
          {loading ? "Sending…" : "Run Now"}
        </Btn>
      </div>
      {err && <div className="text-xs text-[#ffbcbc] mt-2">{err}</div>}

      <div className="mt-3 rounded-xl border" style={{ borderColor: BORDER, padding: 12 }}>
        <div className="font-semibold mb-2">Would run now</div>
        {list === null ? (
          <div className="text-sm text-[#9a9a9a]">No run yet.</div>
        ) : list.length === 0 ? (
          <div className="text-sm text-[#9a9a9a]">No actions would run.</div>
        ) : (
          <ul className="list-disc ml-5">
            {list.map((a, i) => (
              <li key={i} className="mb-1">
                {a.type}
                {renderInfoBits(a)}
              </li>
            ))}
          </ul>
        )}

        {Array.isArray(did) && (
          <>
            <div className="font-semibold mt-4 mb-2">Executed actions</div>
            {did.length === 0 ? (
              <div className="text-sm text-[#9a9a9a]">Nothing executed.</div>
            ) : (
              <ul className="list-disc ml-5">
                {did.map((a, i) => (
                  <li key={i} className="mb-1">
                    {a.type} — {a.status}
                    {renderInfoBits(a)}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ---- MAIN ---- */
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

  function buildEmptyFlow() {
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

  function ensureEditingFlow() {
    if (editing) return;
    setEditing(buildEmptyFlow());
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
  }, [userEmail]);

  function applyTemplate(t) {
    const f = JSON.parse(JSON.stringify(t));
    delete f.id;
    f.enabled = false;
    f.owner = userEmail;

    const strip = (html = "") =>
      html
        .replace(/<\/p>\s*<p>/g, "\n\n")
        .replace(/<br\s*\/?>/g, "\n")
        .replace(/<\/?[^>]+>/g, "")
        .trim();

    f.steps = (f.steps || []).map((s) =>
      s.type === "send_email" && s.html && !s.body ? { ...s, body: strip(s.html) } : s
    );

    setEditing(normalizeFlow(f, userEmail));
    setTab("builder");
  }

  async function saveFlow() {
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
  }

  async function saveProf() {
    setSavingProfile(true);
    try {
      await api.saveProfile(userEmail, profile);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSavingProfile(false);
    }
  }

  const buildDefaultStep = (k) => {
    switch (k) {
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
        return { type: k };
    }
  };

  return (
    <div
      className="w-full min-h-[100vh]"
      style={{
        background: BG,
        color: TEXT,
        display: "grid",
        gridTemplateRows: "auto auto 1fr",
      }}
    >
      <div className="px-5 py-4 border-b" style={{ borderColor: BORDER, background: PANEL }}>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-2xl font-bold">Automations</h2>
            <div className="text-sm" style={{ color: MUTED }}>
              Build simple, calm follow-up flows that your team can actually manage.
            </div>
          </div>

          <div className="flex gap-2 flex-wrap">
            <Btn kind={tab === "templates" ? "solid" : "ghost"} onClick={() => setTab("templates")}>
              Templates
            </Btn>
            <Btn kind={tab === "flows" ? "solid" : "ghost"} onClick={() => setTab("flows")}>
              My Flows
            </Btn>
            <Btn
              kind={tab === "builder" ? "solid" : "ghost"}
              onClick={() => {
                ensureEditingFlow();
                setTab("builder");
              }}
            >
              Builder
            </Btn>
          </div>
        </div>
      </div>

      <div className="px-5 py-4 border-b" style={{ borderColor: BORDER, background: "#1c1d1f" }}>
        {error && (
          <div
            className="mb-3 text-sm rounded-xl px-3 py-2"
            style={{ background: DANGER_BG, color: DANGER_TXT, border: "1px solid #4a1515" }}
          >
            {error}
          </div>
        )}

        <div style={{ ...shellCard, padding: 16 }}>
          <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
            <div>
              <div className="text-base font-semibold">Automation Settings</div>
              <div className="text-xs" style={{ color: MUTED }}>
                These values get reused across your messages and flows.
              </div>
            </div>
            <Btn onClick={saveProf} disabled={savingProfile}>
              {savingProfile ? "Saving…" : "Save Profile"}
            </Btn>
          </div>

          <div className="grid lg:grid-cols-5 gap-3 items-end">
            <div>
              <div className="text-xs mb-1">Business</div>
              <Input
                value={profile.business_name}
                onChange={(e) => setProfile({ ...profile, business_name: e.target.value })}
                placeholder="RetainAI Clinic"
              />
            </div>
            <div className="lg:col-span-2">
              <div className="text-xs mb-1">Booking link</div>
              <Input
                value={profile.booking_link}
                onChange={(e) => setProfile({ ...profile, booking_link: e.target.value })}
                placeholder="https://calendly.com/you/30min"
              />
            </div>
            <div>
              <div className="text-xs mb-1">Quiet start (0–23)</div>
              <Input
                type="number"
                value={profile.quiet_hours_start ?? ""}
                onChange={(e) =>
                  setProfile({ ...profile, quiet_hours_start: e.target.value === "" ? "" : +e.target.value })
                }
              />
            </div>
            <div>
              <div className="text-xs mb-1">Quiet end (0–23)</div>
              <Input
                type="number"
                value={profile.quiet_hours_end ?? ""}
                onChange={(e) =>
                  setProfile({ ...profile, quiet_hours_end: e.target.value === "" ? "" : +e.target.value })
                }
              />
            </div>
          </div>

          <div className="mt-3 text-xs flex items-center gap-2 flex-wrap" style={{ color: MUTED }}>
            Tokens:
            {TOKENS.map((tok) => (
              <code key={tok} className="bg-[#242424] px-2 py-1 rounded text-xs">
                {tok}
              </code>
            ))}
          </div>
        </div>
      </div>

      <div className="p-5 overflow-auto">
        {tab === "templates" && (
          <div className="grid md:grid-cols-3 gap-4">
            {templates.map((t) => (
              <div key={t.id} className="rounded-2xl p-4 flex flex-col" style={shellCard}>
                <div className="text-lg font-semibold mb-1">{t.name}</div>
                <div className="text-sm mb-3" style={{ color: MUTED }}>
                  {PRETTY[t.trigger?.type]?.(t.trigger) || t.trigger?.type}
                </div>
                <FlowDiagram flow={t} />
                <Btn onClick={() => applyTemplate(t)} className="mt-3">
                  Use Template
                </Btn>
              </div>
            ))}
            {!templates.length && <div className="text-sm" style={{ color: MUTED }}>No templates available.</div>}
          </div>
        )}

        {tab === "flows" && (
          <div className="grid md:grid-cols-2 gap-4">
            {loading && <div className="text-sm" style={{ color: MUTED }}>Loading your flows…</div>}

            {!loading &&
              flows.map((f) => (
                <div key={f.id} className="rounded-2xl p-4" style={shellCard}>
                  <div className="flex items-center justify-between mb-3 gap-3">
                    <div>
                      <div className="text-lg font-semibold">{f.name}</div>
                      <div className="text-sm" style={{ color: MUTED }}>
                        {PRETTY[f.trigger?.type]?.(f.trigger) || f.trigger?.type}
                      </div>
                    </div>

                    <Toggle
                      checked={!!f.enabled}
                      onChange={async (e) => {
                        const enabled = e.target.checked;
                        setFlows((prev) => prev.map((x) => (x.id === f.id ? { ...x, enabled } : x)));
                        try {
                          await api.enableFlow(userEmail, f.id, enabled);
                          await refreshFlows();
                        } catch (err) {
                          setFlows((prev) => prev.map((x) => (x.id === f.id ? { ...x, enabled: !enabled } : x)));
                          setError(String(err.message || err));
                        }
                      }}
                    />
                  </div>

                  <FlowDiagram flow={f} />

                  <div className="mt-4 flex gap-2">
                    <Btn
                      kind="ghost"
                      onClick={() => {
                        const strip = (html = "") =>
                          html
                            .replace(/<\/p>\s*<p>/g, "\n\n")
                            .replace(/<br\s*\/?>/g, "\n")
                            .replace(/<\/?[^>]+>/g, "")
                            .trim();

                        const hydrated = {
                          ...f,
                          steps: (f.steps || []).map((s) =>
                            s.type === "send_email" && s.html && !s.body
                              ? { ...s, body: strip(s.html || "") }
                              : s
                          ),
                        };

                        setEditing(normalizeFlow(hydrated, userEmail));
                        setTab("builder");
                      }}
                    >
                      Edit
                    </Btn>

                    <Btn
                      kind="danger"
                      onClick={async () => {
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
                    >
                      Delete
                    </Btn>
                  </div>
                </div>
              ))}

            {!loading && !flows.length && (
              <div className="text-sm" style={{ color: MUTED }}>
                No flows yet — start from a template or open Builder.
              </div>
            )}
          </div>
        )}

        {tab === "builder" && (
          <div className="grid xl:grid-cols-3 gap-6">
            <div className="rounded-2xl p-4" style={shellCard}>
              <div className="flex items-center justify-between gap-3 mb-3">
                <div>
                  <div className="text-lg font-semibold">Builder</div>
                  <div className="text-xs" style={{ color: MUTED }}>
                    Start with a trigger, then add only the steps you need.
                  </div>
                </div>
                <Btn
                  kind="ghost"
                  onClick={() => setEditing(buildEmptyFlow())}
                >
                  New Flow
                </Btn>
              </div>

              {!editing ? (
                <div className="text-sm" style={{ color: MUTED }}>
                  Open a flow or click New Flow to begin.
                </div>
              ) : (
                <>
                  <div className="mb-3">
                    <div className="text-sm mb-1">Name</div>
                    <Input value={editing.name || ""} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
                  </div>

                  <div className="text-sm mb-1">Trigger</div>
                  <select
                    className="w-full bg-[#232323] text-white border border-[#2a2a2a] rounded-xl p-2 mb-2"
                    value={editing.trigger?.type || ""}
                    onChange={(e) =>
                      setEditing({
                        ...editing,
                        trigger: { ...(editing.trigger || {}), type: e.target.value },
                      })
                    }
                  >
                    <option value="">Select…</option>
                    <option value="no_reply">No reply</option>
                    <option value="new_lead">New lead</option>
                    <option value="appointment_no_show">Appointment no-show</option>
                  </select>

                  {editing.trigger?.type === "no_reply" && (
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-sm">Days:</span>
                      <Input
                        type="number"
                        value={editing.trigger?.days || 3}
                        onChange={(e) =>
                          setEditing({
                            ...editing,
                            trigger: { ...(editing.trigger || {}), days: +e.target.value },
                          })
                        }
                        style={{ maxWidth: 100 }}
                      />
                    </div>
                  )}

                  {editing.trigger?.type === "new_lead" && (
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-sm">Within hours:</span>
                      <Input
                        type="number"
                        value={editing.trigger?.within_hours || 24}
                        onChange={(e) =>
                          setEditing({
                            ...editing,
                            trigger: { ...(editing.trigger || {}), within_hours: +e.target.value },
                          })
                        }
                        style={{ maxWidth: 120 }}
                      />
                    </div>
                  )}

                  <div className="mt-4 text-sm font-semibold">Guardrails</div>
                  <div className="flex items-center gap-2 mt-2">
                    <input
                      type="checkbox"
                      checked={editing.caps?.respect_quiet_hours ?? true}
                      onChange={(e) =>
                        setEditing({
                          ...editing,
                          caps: { ...(editing.caps || {}), respect_quiet_hours: e.target.checked },
                        })
                      }
                    />
                    <span className="text-sm">Respect quiet hours</span>
                  </div>

                  <div className="flex items-center gap-2 mt-2">
                    <span className="text-sm">Max sends / day / lead:</span>
                    <Input
                      type="number"
                      value={editing.caps?.per_lead_per_day ?? 1}
                      onChange={(e) =>
                        setEditing({
                          ...editing,
                          caps: { ...(editing.caps || {}), per_lead_per_day: +e.target.value },
                        })
                      }
                      style={{ maxWidth: 120 }}
                    />
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <Btn onClick={saveFlow} disabled={savingFlow}>
                      {savingFlow ? "Saving…" : "Save Flow"}
                    </Btn>
                    <Btn kind="ghost" onClick={() => setTab("flows")}>
                      Back to Flows
                    </Btn>
                  </div>
                </>
              )}
            </div>

            <div className="rounded-2xl p-4" style={shellCard}>
              <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
                <div>
                  <div className="text-lg font-semibold">Steps</div>
                  <div className="text-xs" style={{ color: MUTED }}>
                    Add actions one at a time so the flow stays easy to follow.
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  {[
                    "ai_draft",
                    "send_whatsapp",
                    "send_email",
                    "wait",
                    "if_no_reply",
                    "if_no_booking",
                    "push_owner",
                    "add_tag",
                  ].map((k) => (
                    <Btn
                      key={k}
                      kind="ghost"
                      onClick={() => {
                        const flow = editing || buildEmptyFlow();
                        const def = buildDefaultStep(k);
                        setEditing({ ...flow, steps: [...(flow.steps || []), def] });
                      }}
                    >
                      + {k.replaceAll("_", " ")}
                    </Btn>
                  ))}
                </div>
              </div>

              {editing ? (
                <div className="flex flex-col gap-3">
                  {(editing.steps || []).map((s, i) => (
                    <StepCard
                      key={i}
                      step={s}
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
                      waTemplates={waTemplates}
                    />
                  ))}
                  {!(editing.steps || []).length && (
                    <div className="text-sm" style={{ color: MUTED }}>
                      No steps yet — add one from the toolbar above.
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-sm" style={{ color: MUTED }}>
                  Open or create a flow to edit steps.
                </div>
              )}
            </div>

            <div className="rounded-2xl p-4" style={shellCard}>
              <div className="text-lg font-semibold mb-3">Live Flow View</div>
              {editing ? (
                <FlowDiagram flow={editing} />
              ) : (
                <div className="text-sm" style={{ color: MUTED }}>
                  No flow selected.
                </div>
              )}

              <div className="h-4" />
              {editing && (
                <>
                  <div className="text-lg font-semibold mb-2">Preview</div>
                  <Preview userEmail={userEmail} flow={editing} />
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
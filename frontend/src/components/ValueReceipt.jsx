import React, { useCallback, useEffect, useMemo, useState } from "react";
import { apiUrl } from "../apiBase";
import "./product-system.css";
import "./ValueReceipt.css";

const PERIODS = [["30", "Last 30 days"], ["90", "Last 90 days"], ["365", "Last 12 months"]];
const ZERO_DECIMAL = new Set(["jpy", "krw"]);
const CURRENCY_CHOICES = ["cad", "usd", "eur", "gbp", "aud", "nzd"];

export function formatMinor(minor, currency) {
  const code = String(currency || "cad").toUpperCase();
  const exponent = ZERO_DECIMAL.has(String(currency).toLowerCase()) ? 0 : 2;
  try {
    return new Intl.NumberFormat("en-CA", { style: "currency", currency: code }).format((minor || 0) / 10 ** exponent);
  } catch {
    return `${((minor || 0) / 10 ** exponent).toFixed(exponent)} ${code}`;
  }
}

function localDay(offsetDays = 0) {
  const date = new Date();
  date.setDate(date.getDate() - offsetDays);
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function shortDate(iso) {
  const date = iso ? new Date(iso) : null;
  return date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—";
}

function newKey() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `pay-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function EvidenceBadge({ item }) {
  if (item.verification === "provider_verified") return <span className="status-pill active">Verified by Stripe</span>;
  if (item.paid_outside_stripe) return <span className="status-pill trial">Marked paid outside Stripe</span>;
  return <span className="status-pill trial">Owner-recorded</span>;
}

async function call(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    ...options,
    headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error === "owner_required" ? "Only the workspace owner can see revenue." : (data.error || `Request failed (${response.status})`));
    error.status = response.status;
    throw error;
  }
  return data;
}

export default function ValueReceipt({ leads = [] }) {
  const [period, setPeriod] = useState("90");
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [show, setShow] = useState("linked");
  const [form, setForm] = useState(null);
  const [notice, setNotice] = useState("");

  const query = useMemo(() => `since=${localDay(Number(period) - 1)}&until=${localDay(0)}`, [period]);

  const load = useCallback(async () => {
    setError("");
    try {
      setReceipt(await call(`value-receipt?${query}`));
    } catch (err) {
      setReceipt(null);
      setError(err.message);
    }
  }, [query]);

  useEffect(() => { load(); }, [load]);

  async function sync() {
    setBusy("sync"); setNotice(""); setError("");
    try {
      const result = await call("value-receipt/sync", { method: "POST" });
      setNotice(`Read ${result.read} paid Stripe invoice${result.read === 1 ? "" : "s"}: ${result.added} new, ${result.updated} updated.`);
      await load();
    } catch (err) { setError(err.message === "stripe_read_failed" ? "Stripe could not be reached. Nothing was changed; try again." : err.message); }
    finally { setBusy(""); }
  }

  async function savePayment(event) {
    event.preventDefault();
    setBusy("save"); setError("");
    try {
      await call("value-receipt/payments", { method: "POST", body: JSON.stringify(form) });
      setForm(null);
      setNotice("Payment recorded. It is shown as owner-recorded, not verified.");
      await load();
    } catch (err) { setError(err.message); }
    finally { setBusy(""); }
  }

  async function removePayment(item) {
    if (!window.confirm("Remove this owner-recorded payment?")) return;
    setBusy(item.id); setError("");
    try { await call(`value-receipt/payments/${encodeURIComponent(item.id)}`, { method: "DELETE" }); await load(); }
    catch (err) { setError(err.message); }
    finally { setBusy(""); }
  }

  async function recordRefund(item) {
    const value = window.prompt(`Total refunded for this payment (${String(item.currency).toUpperCase()}). Enter 0 for none.`, "0");
    if (value === null) return;
    setBusy(item.id); setError("");
    try {
      await call(`value-receipt/payments/${encodeURIComponent(item.id)}/refund`, { method: "POST", body: JSON.stringify({ refunded_amount: value }) });
      await load();
    } catch (err) { setError(err.message); }
    finally { setBusy(""); }
  }

  async function exportCsv() {
    setBusy("export"); setError("");
    try {
      const response = await fetch(apiUrl(`value-receipt/export.csv?${query}`), { credentials: "include" });
      if (!response.ok) throw new Error(`Export failed (${response.status})`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `retainai-value-receipt-${localDay(Number(period) - 1)}-to-${localDay(0)}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) { setError(err.message); }
    finally { setBusy(""); }
  }

  if (error && !receipt) {
    return <section className="product-card value-receipt"><h2>Verified revenue</h2><p className="product-card-copy" role="alert">{error}</p></section>;
  }
  if (!receipt) return <section className="product-card value-receipt"><p className="product-card-copy">Loading verified revenue…</p></section>;

  const currencies = Object.entries(receipt.totals || {});
  const items = (receipt.items || []).filter((item) => (show === "linked" ? item.linked : !item.linked));
  const linkedAny = currencies.some(([, total]) => total.linked_verified_minor || total.linked_owner_recorded_minor);

  return (
    <section className="product-card value-receipt" aria-label="Verified revenue">
      <div className="product-card-header">
        <div>
          <h2>Verified revenue</h2>
          <p className="product-card-copy">{receipt.rules.linked_means} {receipt.rules.not_causal}</p>
        </div>
        <select className="product-input value-period" aria-label="Period" value={period} onChange={(event) => setPeriod(event.target.value)}>
          {PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>

      {error && <div className="product-alert danger" role="alert">{error}</div>}
      {notice && <div className="product-alert success" role="status">{notice}</div>}

      <div className="value-totals">
        {currencies.length === 0 && <p className="product-card-copy">No payments are recorded for this period yet.</p>}
        {currencies.map(([currency, total]) => (
          <div className="value-total" key={currency} data-testid={`value-total-${currency}`}>
            <span className="value-currency">{currency.toUpperCase()}</span>
            <div><strong>{formatMinor(total.linked_verified_minor, currency)}</strong><small>Linked, verified by Stripe</small></div>
            <div><strong>{formatMinor(total.linked_owner_recorded_minor, currency)}</strong><small>Linked, owner-recorded</small></div>
            <div className="value-context"><small>{total.linked_count} of {total.payment_count} payments linked · all paid: {formatMinor(total.paid_verified_minor, currency)} verified, {formatMinor(total.paid_owner_recorded_minor, currency)} owner-recorded</small></div>
          </div>
        ))}
      </div>
      {!linkedAny && currencies.length > 0 && <p className="product-card-copy">No payment in this period followed a recorded RetainAI follow-up and booking or invoice.</p>}

      <div className="value-actions">
        {receipt.stripe_connected && <button type="button" className="product-button" onClick={sync} disabled={Boolean(busy)}>{busy === "sync" ? "Reading Stripe…" : "Update from Stripe"}</button>}
        <button type="button" className="product-button" onClick={() => setForm({ lead_id: leads[0]?.id || "", amount: "", currency: "cad", paid_at: localDay(0), reference: "", idempotency_key: newKey() })} disabled={Boolean(busy) || !leads.length}>Record a payment</button>
        <button type="button" className="product-button" onClick={exportCsv} disabled={Boolean(busy)}>{busy === "export" ? "Exporting…" : "Export CSV"}</button>
        <small className="product-card-copy">{receipt.stripe_connected ? `Stripe last read ${receipt.last_synced_at ? shortDate(receipt.last_synced_at) : "never"}.` : "Connect Stripe in Invoices to add verified payments."}</small>
      </div>

      {form && (
        <form className="value-form" onSubmit={savePayment} aria-label="Record a payment">
          <p className="product-card-copy">For payments taken outside Stripe (cash, card terminal, e-transfer). They are shown as owner-recorded, never as verified.</p>
          <label>Customer<select className="product-input" value={form.lead_id} onChange={(e) => setForm({ ...form, lead_id: e.target.value })}>{leads.filter((lead) => lead.id).map((lead) => <option key={lead.id} value={lead.id}>{lead.name || lead.email || lead.id}</option>)}</select></label>
          <label>Amount<input className="product-input" inputMode="decimal" required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></label>
          <label>Currency<select className="product-input" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>{CURRENCY_CHOICES.map((code) => <option key={code} value={code}>{code.toUpperCase()}</option>)}</select></label>
          <label>Date received<input className="product-input" type="date" required max={localDay(0)} value={form.paid_at} onChange={(e) => setForm({ ...form, paid_at: e.target.value })} /></label>
          <label>Reference (optional)<input className="product-input" maxLength={120} value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} /></label>
          <div className="value-actions"><button type="submit" className="product-button primary" disabled={busy === "save"}>{busy === "save" ? "Saving…" : "Save payment"}</button><button type="button" className="product-button" onClick={() => setForm(null)}>Cancel</button></div>
        </form>
      )}

      <div className="value-filter" role="group" aria-label="Show payments">
        {[["linked", "Linked"], ["unlinked", "Not linked"]].map(([key, label]) => <button key={key} type="button" className={`import-source ${show === key ? "active" : ""}`} aria-pressed={show === key} onClick={() => setShow(key)}>{label}</button>)}
      </div>
      <ul className="value-items">
        {items.map((item) => (
          <li key={item.id} className="value-item">
            <div className="value-item-head">
              <strong>{item.customer_name || "Customer"}</strong>
              <span>{formatMinor(item.net_minor, item.currency)}</span>
              <EvidenceBadge item={item} />
            </div>
            <ol className="value-chain">
              {item.followup && <li>Follow-up by {item.followup.channel} on {shortDate(item.followup.sent_at)} <small>({item.followup.evidence})</small></li>}
              {item.confirmation && <li>{item.confirmation.label} on {shortDate(item.confirmation.at)}</li>}
              <li>Paid {formatMinor(item.amount_minor, item.currency)} on {shortDate(item.paid_at)}{item.refunded_minor ? `, refunded ${formatMinor(item.refunded_minor, item.currency)}` : ""}{item.invoice_number ? ` · invoice ${item.invoice_number}` : ""}{item.reference ? ` · ${item.reference}` : ""}</li>
            </ol>
            {item.reason && <small className="value-reason">Not counted: {item.reason}</small>}
            {item.source === "manual" && (
              <div className="value-actions">
                <button type="button" className="product-button" onClick={() => recordRefund(item)} disabled={Boolean(busy)}>Record refund</button>
                <button type="button" className="product-button danger" onClick={() => removePayment(item)} disabled={Boolean(busy)}>Remove</button>
              </div>
            )}
          </li>
        ))}
        {!items.length && <li className="product-card-copy">{show === "linked" ? "No linked payments in this period." : "Every payment in this period is linked."}</li>}
      </ul>
      <p className="product-card-copy value-excluded">{receipt.rules.excluded}</p>
    </section>
  );
}

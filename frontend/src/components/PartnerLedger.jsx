import React, { useCallback, useEffect, useState } from "react";
import "./PartnerLedger.css";

const money = (amount, currency) => new Intl.NumberFormat("en-CA", {style: "currency", currency: currency.toUpperCase(), currencyDisplay: "code"}).format(amount / 100);
const date = value => value ? new Date(value * 1000).toLocaleString() : "Not yet";

export default function PartnerLedger({ endpoint, linkBase }) {
  const [data, setData] = useState(null), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [references, setReferences] = useState({});
  const request = useCallback(async (body) => {
    const response = await fetch(endpoint, {credentials: "include", cache: "no-store", ...(body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || result.error || "The ledger could not be loaded.");
    return {...result, checkedAt: Date.now() / 1000};
  }, [endpoint]);
  useEffect(() => { request().then(setData).catch(e => setMessage(e.message)); }, [request]);
  async function act(body) {
    setBusy(true); setMessage("");
    try { setData(await request(body)); setMessage(body?.op === "record" ? "External payment recorded. No money was transferred by this app." : "Ledger updated."); return true; }
    catch (error) { setMessage(error.message); return false; }
    finally { setBusy(false); }
  }
  async function refresh() {
    setBusy(true); setMessage("Checking Stripe payments and refunds…");
    try {
      const latest = await request();
      for (const referral of latest.referrals) await request({op: "sync", customerId: referral.customerId});
      setData(await request()); setMessage("Stripe reconciliation complete.");
    } catch (error) { setMessage(error.message); await request().then(setData).catch(() => {}); }
    finally { setBusy(false); }
  }
  async function create(event) {
    event.preventDefault();
    const form = event.currentTarget, values = new FormData(form);
    if (await act({op: "create", code: values.get("code"), name: values.get("name"), email: values.get("email"), accepted: values.get("accepted") === "on"})) form.reset();
  }
  function exportLedger() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({...data, exportedAt: new Date().toISOString()}, null, 2)], {type: "application/json"}));
    const a = document.createElement("a"); a.href = url; a.download = `partner-ledger-${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(url);
  }
  return <section className="partner-ledger" aria-labelledby="ledger-title">
    <div className="partner-ledger-heading"><div><p className="partner-ledger-eyebrow">Owner tools</p><h2 id="ledger-title">Partners &amp; commissions</h2><p>30% of paid base membership revenue for the first 12 months. Taxes and add-ons excluded. Refunds reduce the balance.</p></div><button disabled={busy} onClick={refresh}>{busy ? "Working…" : "Refresh from Stripe"}</button></div>
    <p className="partner-ledger-note">New accounts use the first valid partner link within 60 days. Commissions have a 30-day hold. Refresh before paying; check review holds and self-referrals. Payments are sent separately, then recorded here.</p>
    {message && <p role="status" className="partner-ledger-note">{message}</p>}
    {data && <>
      <p><strong>{data.livemode ? "Live accounting" : "Test accounting — no live balances"}</strong> · {data.partners.length} partners · {data.referrals.length} attributed customers</p>
      <details className="partner-ledger-card"><summary>Add an accepted partner</summary><form onSubmit={create} className="partner-ledger-form">
        <label>Partner or business name<input name="name" required maxLength={120}/></label>
        <label>Business email<input name="email" type="email" required maxLength={254}/></label>
        <label>Link code<input name="code" required pattern="[a-z0-9][a-z0-9-]{2,39}" placeholder="example-stylist"/><small>3–40 lowercase letters, numbers or hyphens.</small></label>
        <label className="partner-ledger-check"><input name="accepted" type="checkbox" required/>The partner accepted our written terms, including attribution, commission, refunds, disclosures and monthly payout timing.</label>
        <button disabled={busy}>Create partner link</button>
      </form></details>
      <div className="partner-ledger-cards">{data.partners.map(partner => <article className="partner-ledger-card" key={partner.code}><h3>{partner.name}</h3><p>{partner.email}</p><p><a href={`${linkBase}${partner.code}`}>{`${linkBase}${partner.code}`}</a></p><p>{partner.active ? "Accepting new referrals" : "New referrals paused"}</p><button disabled={busy} onClick={() => act({op: "toggle", code: partner.code, active: !partner.active})}>{partner.active ? "Pause link" : "Resume link"}</button></article>)}</div>
      {!data.partners.length && <p>No partners enrolled yet. Add a partner after they accept the offer; prospects are not enrolled automatically.</p>}
      <h3>Balances after recorded payments</h3><p>Negative balances carry refunded commission forward. Pending commissions are in the invoice ledger below.</p>
      {data.balances.map(balance => { const key = `${balance.code}:${balance.currency}`; const blocked = data.referrals.some(r => r.code === balance.code && (r.error || data.checkedAt - r.syncedAt > 300)) || data.invoices.some(i => i.code === balance.code && i.status === "review"); return <form className="partner-ledger-card" key={key} onSubmit={event => {event.preventDefault(); act({op: "record", ...balance, reference: references[key] || ""});}}><h4>{balance.code}: {money(balance.amountMinor, balance.currency)}</h4><label>External payment reference<input required maxLength={120} value={references[key] || ""} onChange={e => setReferences({...references, [key]: e.target.value})}/></label><button disabled={busy || blocked || balance.amountMinor <= 0}>Record {money(balance.amountMinor, balance.currency)} already sent</button>{blocked && <p>Refresh all customers and resolve review holds first.</p>}</form>; })}
      {!data.balances.length && <p>No paid referral invoices yet.</p>}
      <h3>Attributed customers</h3><div className="partner-ledger-table"><table><thead><tr><th>Partner</th><th>Stripe customer</th><th>First paid</th><th>Last checked</th><th>Review</th></tr></thead><tbody>{data.referrals.map(r => <tr key={r.customerId}><td>{r.code}</td><td>{r.customerId}</td><td>{date(r.firstPaidAt)}</td><td>{date(r.syncedAt)}</td><td>{r.error || "Current"}</td></tr>)}</tbody></table></div>
      <h3>Invoice ledger</h3><div className="partner-ledger-table"><table><thead><tr><th>Partner / invoice</th><th>Commission</th><th>Status</th><th>Hold ends</th><th>Notes</th></tr></thead><tbody>{data.invoices.map(i => <tr key={i.invoiceId}><td>{i.code}<br/>{i.invoiceId}</td><td>{money(i.commissionMinor, i.currency)}</td><td>{i.status === "pending" && i.holdUntil <= data.checkedAt ? "available" : i.status}</td><td>{date(i.holdUntil)}</td><td>{i.reason}</td></tr>)}</tbody></table></div>
      <h3>Recorded external payments</h3>{data.payouts.map(p => <p key={p.reference}>{p.code} · {money(p.amountMinor, p.currency)} · {p.reference} · {date(p.recordedAt)}</p>)}
      <button onClick={exportLedger}>Download accounting snapshot</button>
    </>}
  </section>;
}

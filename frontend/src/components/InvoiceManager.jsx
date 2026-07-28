import React, { useEffect, useMemo, useState } from "react";
import "./InvoiceManager.css";
import { API_BASE } from "../config";

export default function InvoiceManager({ userEmail }) {
  const API = useMemo(() => {
    const env = (v) => (v && String(v).trim()) || "";
    const fromEnv =
      env(process.env.REACT_APP_API_URL) ||
      env(process.env.REACT_APP_API_BASE);

    if (fromEnv) return fromEnv.replace(/\/$/, "");
    return API_BASE;
  }, []);

  const [invoices, setInvoices] = useState([]);
  const [form, setForm] = useState({
    customerName: "",
    customerEmail: "",
    amount: "",
    description: "",
  });

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  const hasUser = Boolean(userEmail && String(userEmail).trim());

  function formatMoney(amount, currency = "USD") {
    const n = Number(amount || 0);
    try {
      return new Intl.NumberFormat("en-CA", {
        style: "currency",
        currency: String(currency || "USD").toUpperCase(),
      }).format(n);
    } catch {
      return `$${n.toFixed(2)}`;
    }
  }

  function normalizeInvoice(inv) {
    return {
      id: inv?.id || "",
      customer_name: inv?.customer_name || inv?.customer_email || "—",
      customer_email: inv?.customer_email || "",
      amount_due: Number(inv?.amount_due ?? 0),
      amount_total: Number(inv?.amount_total ?? inv?.amount_due ?? 0),
      amount_display: Number(inv?.amount_display ?? inv?.amount_due ?? 0),
      currency: (inv?.currency || "usd").toUpperCase(),
      status: inv?.status || "open",
      due_date: inv?.due_date || null,
      invoice_url: inv?.invoice_url || "",
      number: inv?.number || "",
    };
  }

  async function fetchInvoices() {
    if (!hasUser) {
      setInvoices([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError("");

    try {
      const res = await fetch(
        `${API}/api/stripe/invoices?user_email=${encodeURIComponent(userEmail)}`,
        {
          method: "GET",
          headers: { Accept: "application/json" },
        }
      );

      let data = {};
      try {
        data = await res.json();
      } catch {
        throw new Error(`Invalid server response (${res.status})`);
      }

      if (!res.ok) {
        throw new Error(data?.error || `Failed to load invoices (${res.status})`);
      }

      const rows = Array.isArray(data?.invoices) ? data.invoices : [];
      setInvoices(rows.map(normalizeInvoice));
    } catch (e) {
      setInvoices([]);
      setError(e.message || "Failed to load invoices");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchInvoices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userEmail, API]);

  function handleChange(key, value) {
    setForm((prev) => ({
      ...prev,
      [key]: value,
    }));
  }

  async function handleCreate(e) {
    e.preventDefault();

    if (!hasUser) {
      setError("Missing user email");
      return;
    }

    setCreating(true);
    setError("");

    try {
      const payload = {
        user_email: userEmail,
        customer_name: form.customerName.trim(),
        customer_email: form.customerEmail.trim(),
        amount: form.amount,
        description: form.description.trim(),
      };

      const res = await fetch(`${API}/api/stripe/invoice`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      });

      let data = {};
      try {
        data = await res.json();
      } catch {
        throw new Error(`Invalid server response (${res.status})`);
      }

      if (!res.ok) {
        throw new Error(data?.error || `Failed to create invoice (${res.status})`);
      }

      if (Array.isArray(data?.invoices)) {
        setInvoices(data.invoices.map(normalizeInvoice));
      } else if (data?.invoice) {
        setInvoices((prev) => [normalizeInvoice(data.invoice), ...prev]);
      } else {
        await fetchInvoices();
      }

      setForm({
        customerName: "",
        customerEmail: "",
        amount: "",
        description: "",
      });
    } catch (e) {
      setError(e.message || "Failed to create invoice");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="invoice-manager">
      <h3>Your Invoices</h3>

      <form className="invoice-form" onSubmit={handleCreate}>
        <input
          placeholder="Customer Name"
          value={form.customerName}
          onChange={(e) => handleChange("customerName", e.target.value)}
          required
          disabled={creating || !hasUser}
        />

        <input
          placeholder="Customer Email"
          type="email"
          value={form.customerEmail}
          onChange={(e) => handleChange("customerEmail", e.target.value)}
          required
          disabled={creating || !hasUser}
        />

        <input
          placeholder="Amount (e.g. 49.99)"
          type="number"
          step="0.01"
          min="0.01"
          value={form.amount}
          onChange={(e) => handleChange("amount", e.target.value)}
          required
          disabled={creating || !hasUser}
        />

        <input
          placeholder="Description"
          value={form.description}
          onChange={(e) => handleChange("description", e.target.value)}
          required
          disabled={creating || !hasUser}
        />

        <button type="submit" disabled={creating || !hasUser}>
          {creating ? "Creating..." : "Add Invoice"}
        </button>

        {error && <div className="error">{error}</div>}
      </form>

      {!hasUser ? (
        <p>Please log in to view invoices.</p>
      ) : loading ? (
        <p>Loading invoices...</p>
      ) : invoices.length === 0 ? (
        <p>No invoices yet.</p>
      ) : (
        <table className="invoice-table">
          <thead>
            <tr>
              <th>Invoice</th>
              <th>Customer</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Due</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.id}>
                <td>{inv.number || inv.id}</td>
                <td>{inv.customer_name}</td>
                <td>{formatMoney(inv.amount_display, inv.currency)}</td>
                <td>{inv.status}</td>
                <td>
                  {inv.due_date
                    ? new Date(inv.due_date * 1000).toLocaleDateString()
                    : "—"}
                </td>
                <td>
                  {inv.invoice_url ? (
                    <a href={inv.invoice_url} target="_blank" rel="noreferrer">
                      View
                    </a>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Invoices from "./Invoices";

const user = { email: "owner@example.com", role: "owner", stripe_connected: true, canManageBilling: true };

function json(body, status = 200) {
  return { ok: status < 400, status, headers: { get: () => "application/json" }, text: async () => JSON.stringify(body) };
}

let posts;
beforeEach(() => {
  posts = [];
  let attempt = 0;
  global.fetch = jest.fn(async (url, options = {}) => {
    const value = String(url);
    if (value.includes("/api/stripe/invoice") && options.method === "POST" && !value.includes("/send")) {
      posts.push(JSON.parse(options.body));
      attempt += 1;
      return attempt === 1
        ? json({ error: "The invoice could not be created. Trying again is safe and will not send a duplicate." }, 500)
        : json({ success: true, invoices: [], amount_total: 80, currency: "cad" });
    }
    if (value.includes("/api/stripe/account")) return json({ default_currency: "cad", charges_enabled: true });
    if (value.includes("/api/stripe/dashboard-link")) return json({ url: "" });
    if (value.includes("/api/stripe/invoices")) return json({ invoices: [] });
    return json({});
  });
});
afterEach(() => { delete global.fetch; });

function fill() {
  const [name, email, item] = screen.getAllByRole("textbox");
  fireEvent.change(name, { target: { value: "Ana" } });
  fireEvent.change(email, { target: { value: "ana@example.com" } });
  fireEvent.change(item, { target: { value: "Cut" } });
  const [price] = screen.getAllByRole("spinbutton");
  fireEvent.change(price, { target: { value: "80" } });
}

test("retrying the same invoice form reuses its idempotency key; a new invoice gets a new one", async () => {
  render(<Invoices user={user} leads={[]} />);
  fireEvent.click(await screen.findByRole("button", { name: "+ New Invoice" }));
  fill();
  fireEvent.click(screen.getByRole("button", { name: /send invoice/i }));
  expect(await screen.findByText(/Trying again is safe/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /send invoice/i }));
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(posts[0].idempotency_key).toBeTruthy();
  expect(posts[1].idempotency_key).toBe(posts[0].idempotency_key);

  fireEvent.click(await screen.findByRole("button", { name: "+ New Invoice" }));
  fill();
  fireEvent.click(screen.getByRole("button", { name: /send invoice/i }));
  await waitFor(() => expect(posts).toHaveLength(3));
  expect(posts[2].idempotency_key).not.toBe(posts[0].idempotency_key);
});

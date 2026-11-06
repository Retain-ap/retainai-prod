import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import ImportContacts from "./ImportContacts";

const user = { email: "owner@example.com" };

const preview = {
  format: "vcard",
  preset: { key: "vcard", label: "vCard (Apple, iCloud, Outlook, Android, WhatsApp)" },
  headers: ["Full name", "Email", "Phone"],
  mapping: { name: "Full name", email: "Email", phone: "Phone" },
  rows: [
    { raw: { "Full name": "Jordan Rivera", Email: "jordan@example.com", Phone: "(416) 555-0101" }, selected: true },
    { raw: { "Full name": "No Contact", Email: "", Phone: "" }, selected: true },
  ],
  outcomes: [
    { index: 0, status: "imported", reason: "", contact: { name: "Jordan Rivera", email: "jordan@example.com", phone: "+14165550101" } },
    { index: 1, status: "invalid", reason: "missing_email_or_phone" },
  ],
  summary: { imported: 1, updated: 0, merged: 0, skipped: 0, invalid: 1, warnings: 0 },
  total_rows: 2, truncated: false, max_rows: 5000,
  reasons: { missing_email_or_phone: "No valid email or phone" },
};

function json(body, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
}

let calls;
function mockApi(overrides = {}) {
  calls = [];
  global.fetch = jest.fn((url, options = {}) => {
    const path = String(url).replace(/^.*\/api\//, "");
    calls.push({ path, options, body: typeof options.body === "string" ? JSON.parse(options.body) : options.body });
    if (overrides[path]) return overrides[path](options);
    if (path.startsWith("import/history")) return json({ imports: [] });
    if (path.startsWith("google/status")) return json({ google_connected: false, leads_count: 3 });
    if (path === "import/file/preview") return json(preview);
    if (path === "import/file/commit") {
      const body = JSON.parse(options.body);
      const selected = body.rows.filter((row) => row.selected !== false).length;
      return json({ ok: true, dry_run: Boolean(body.dry_run), summary: { imported: selected ? 1 : 0, updated: 0, merged: 0, skipped: 0, invalid: 1, warnings: 0 }, outcomes: preview.outcomes, import: body.dry_run ? undefined : { id: "imp1" } });
    }
    return json({});
  });
}

async function upload(name = "Contacts.vcf") {
  render(<ImportContacts user={user} />);
  const input = screen.getByTestId("import-file");
  fireEvent.change(input, { target: { files: [new File(["BEGIN:VCARD"], name, { type: "text/vcard" })] } });
  return screen.findByRole("region", { name: "Review import" });
}

afterEach(() => { delete global.fetch; jest.useRealTimers(); });

test("accepts vCard and CSV files and explains WhatsApp honestly", async () => {
  mockApi();
  render(<ImportContacts user={user} />);
  expect(screen.getByTestId("import-file")).toHaveAttribute("accept", expect.stringContaining(".vcf"));
  expect(screen.getByTestId("import-file")).toHaveAttribute("accept", expect.stringContaining(".csv"));
  fireEvent.click(screen.getByRole("button", { name: "Android or WhatsApp" }));
  expect(screen.getByText(/has no contact export of its own/)).toBeInTheDocument();
  expect(screen.getByText(/Chats and messages are never imported/)).toBeInTheDocument();
  for (const label of ["HubSpot", "Salesforce", "Pipedrive", "Zoho CRM", "Outlook", "iPhone, Mac or iCloud"]) {
    expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
  }
  expect(await screen.findByRole("button", { name: "Connect Google" })).toBeInTheDocument();
});

test("previews a file with detected source, per-row outcomes and a consent notice", async () => {
  mockApi();
  const review = await upload();
  expect(within(review).getByText(/vCard \(Apple, iCloud/)).toBeInTheDocument();
  expect(within(review).getByText("+14165550101")).toBeInTheDocument();
  expect(within(review).getByText("No valid email or phone")).toBeInTheDocument();
  expect(within(review).getByText(/not marked as agreeing to email/)).toBeInTheDocument();
  expect(within(review).getByRole("button", { name: "Import 1 contact" })).toBeEnabled();
  fireEvent.click(within(review).getByRole("button", { name: "Needs fixing" }));
  expect(within(review).queryByText("Jordan Rivera")).not.toBeInTheDocument();
  expect(within(review).getByText("No Contact")).toBeInTheDocument();
});

test("requires an email or phone column and recounts after mapping changes", async () => {
  mockApi();
  const review = await upload();
  fireEvent.change(within(review).getByLabelText("Email"), { target: { value: "" } });
  fireEvent.change(within(review).getByLabelText("Phone / WhatsApp"), { target: { value: "" } });
  expect(within(review).getByText(/Match an Email or Phone column/)).toBeInTheDocument();
  expect(within(review).getByRole("button", { name: /Import 0 contacts/ })).toBeDisabled();
  fireEvent.change(within(review).getByLabelText("Email"), { target: { value: "Email" } });
  await waitFor(() => expect(calls.some((call) => call.path === "import/file/commit" && call.body.dry_run === true)).toBe(true));
  const dry = calls.filter((call) => call.path === "import/file/commit").pop().body;
  expect(dry.mapping.email).toBe("Email");
  expect(dry.mapping.phone).toBe("");
  expect(calls.some((call) => call.path === "import/file/commit" && !call.body.dry_run)).toBe(false);
});

test("commits the reviewed rows with the chosen options and reports skipped rows", async () => {
  mockApi();
  const review = await upload();
  fireEvent.change(within(review).getByLabelText("If a contact already exists"), { target: { value: "merge" } });
  await waitFor(() => expect(within(review).getByRole("button", { name: "Import 1 contact" })).toBeEnabled());
  fireEvent.click(within(review).getByRole("button", { name: "Import 1 contact" }));
  expect(await screen.findByText(/Import finished/)).toBeInTheDocument();
  expect(screen.getByText(/Nothing was sent to these contacts/)).toBeInTheDocument();
  const commit = calls.filter((call) => call.path === "import/file/commit" && !call.body.dry_run).pop().body;
  expect(commit).toMatchObject({ duplicate_mode: "merge", source: "vcard", file_name: "Contacts.vcf", tag: "Imported" });
  expect(commit.rows).toHaveLength(2);
  expect(screen.getByText(/Contact 2: No Contact — No valid email or phone/)).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Review import" })).not.toBeInTheDocument();
});

test("shows the server's reason when a file is rejected", async () => {
  mockApi({ "import/file/preview": () => json({ error: "Choose a CSV (.csv) or vCard (.vcf) contact file." }, 400) });
  render(<ImportContacts user={user} />);
  fireEvent.change(screen.getByTestId("import-file"), { target: { files: [new File(["x"], "contacts.xlsx")] } });
  expect(await screen.findByRole("alert")).toHaveTextContent("Choose a CSV (.csv) or vCard (.vcf) contact file.");
  expect(screen.queryByRole("region", { name: "Review import" })).not.toBeInTheDocument();
});

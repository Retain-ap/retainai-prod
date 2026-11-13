import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import ImportContacts from "./ImportContacts";

jest.mock("./CalendlyBookingsCard", () => () => null);
jest.mock("./SquareBookingsCard", () => () => null);
const user = { email: "member@example.test" };
const preview = {
  format: "csv", headers: ["Name", "Email"], mapping: { name: "Name", email: "Email" },
  rows: [{ raw: { Name: "Fictional contact", Email: "contact@example.test" }, selected: true }],
  outcomes: [{ index: 0, status: "imported", contact: { name: "Fictional contact", email: "contact@example.test" } }],
  summary: { imported: 1 }, total_rows: 1,
};
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const deferred = () => { let resolve, reject; const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; }); return { promise, resolve, reject }; };
let requests, previewRequest, commitRequest;
const originalFetch = global.fetch;
beforeEach(() => {
  requests = [];
  previewRequest = () => Promise.resolve(response(preview));
  commitRequest = () => Promise.resolve(response({ ok: true, summary: { imported: 1 }, outcomes: [] }));
  global.fetch = jest.fn((url, options = {}) => {
    const path = String(url).replace(/^.*\/api\//, "");
    requests.push({ path, options });
    if (path === "import/file/preview") return previewRequest(options);
    if (path === "import/file/commit") return JSON.parse(options.body).dry_run ? Promise.resolve(response(preview)) : commitRequest(options);
    return Promise.resolve(response(path === "import/history" ? { imports: [] } : { google_connected: false }));
  });
});
afterEach(() => { global.fetch = originalFetch; jest.restoreAllMocks(); });
const choose = (name = "A.csv") => fireEvent.change(screen.getByTestId("import-file"), { target: { files: [new File(["Name,Email\nFictional,contact@example.test"], name, { type: "text/csv" })] } });
async function review() { const view = render(<ImportContacts user={user} />); choose(); await screen.findByRole("region", { name: "Review import" }); return view; }

test("a pending commit owns the review and refuses picker, drop and cancel changes", async () => {
  const pending = deferred(); commitRequest = () => pending.promise;
  await review();
  fireEvent.click(screen.getByRole("button", { name: "Import 1 contact" }));
  const drop = screen.getByRole("button", { name: /A.csv/ });
  expect(drop).toBeDisabled(); expect(screen.getByTestId("import-file")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
  expect(screen.getByLabelText("Email")).toBeDisabled();
  expect(screen.getByLabelText("Import row 1")).toBeDisabled();
  // Drag events can still reach disabled controls, so the handler must also guard the request.
  fireEvent.drop(drop, { dataTransfer: { files: [new File(["B"], "B.csv")] } });
  expect(requests.filter(item => item.path === "import/file/preview")).toHaveLength(1);
  expect(screen.getByRole("heading", { name: "Review A.csv" })).toBeInTheDocument();
  await act(async () => pending.resolve(response({ ok: true, summary: { imported: 1 }, outcomes: [] })));
  expect(await screen.findByText("Import finished.")).toBeInTheDocument();
  expect(screen.getByTestId("import-file")).toBeEnabled();
  choose("B.csv"); expect(await screen.findByRole("heading", { name: "Review B.csv" })).toBeInTheDocument();
  expect(requests.filter(item => item.path === "import/file/commit")).toHaveLength(1);
});

test("a refused commit keeps the reviewed file and releases the lock without automatically retrying", async () => {
  const pending = deferred(); commitRequest = () => pending.promise;
  await review(); fireEvent.click(screen.getByRole("button", { name: "Import 1 contact" }));
  await act(async () => pending.resolve(response({ error: "Import could not be confirmed" }, 503)));
  expect(await screen.findByRole("alert")).toHaveTextContent("Import could not be confirmed");
  expect(screen.getByRole("heading", { name: "Review A.csv" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Import 1 contact" })).toBeEnabled();
  expect(screen.getByTestId("import-file")).toBeEnabled();
  expect(screen.queryByText("Import finished.")).not.toBeInTheDocument();
  expect(requests.filter(item => item.path === "import/file/commit")).toHaveLength(1);
});

test("a completed import after unmount notifies only its original workspace without restarting importer reads", async () => {
  const pending = deferred(); commitRequest = () => pending.promise;
  const view = await review(); fireEvent.click(screen.getByRole("button", { name: "Import 1 contact" }));
  view.unmount();
  render(<ImportContacts user={{ email: "second@example.test" }} />);
  await screen.findByRole("button", { name: "Connect Google" });
  const before = requests.length; const dispatched = jest.spyOn(window, "dispatchEvent");
  await act(async () => pending.resolve(response({ ok: true, summary: { imported: 1 }, outcomes: [] })));
  expect(requests).toHaveLength(before);
  const notifications = dispatched.mock.calls.filter(([event]) => event.type === "leads:changed");
  expect(notifications).toHaveLength(1);
  expect(notifications[0][0].detail).toEqual({ workspaceEmail: user.email });
  expect(screen.queryByText("Import finished.")).not.toBeInTheDocument();
});

test.each(["success", "failure"])("a late preview %s cannot replace another workspace's new review", async outcome => {
  const pending = deferred(); previewRequest = options => options.body.get("file").name === "A.csv" ? pending.promise : Promise.resolve(response(preview));
  const view = render(<ImportContacts user={user} />); choose();
  view.rerender(<ImportContacts user={{ email: "second@example.test" }} />);
  expect(screen.getByTestId("import-file")).toBeEnabled(); choose("B.csv");
  expect(await screen.findByRole("heading", { name: "Review B.csv" })).toBeInTheDocument();
  await act(async () => outcome === "success" ? pending.resolve(response(preview)) : pending.reject(new Error("Old preview failed")));
  expect(screen.getByRole("heading", { name: "Review B.csv" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Review import" })).getByRole("button", { name: "Import 1 contact" })).toBeEnabled();
});

test("a current preview failure releases the upload lock for a deliberate retry", async () => {
  const pending = deferred(); previewRequest = () => pending.promise;
  render(<ImportContacts user={user} />); choose();
  await act(async () => pending.reject(new Error("Preview unavailable")));
  expect(await screen.findByRole("alert")).toHaveTextContent("Preview unavailable");
  expect(screen.getByTestId("import-file")).toBeEnabled();
  previewRequest = () => Promise.resolve(response(preview)); choose("B.csv");
  expect(await screen.findByRole("heading", { name: "Review B.csv" })).toBeInTheDocument();
});

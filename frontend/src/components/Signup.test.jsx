import { vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import Signup from "./Signup";

vi.mock("@react-oauth/google", () => ({
  GoogleLogin: ({ onSuccess }) => <button type="button" onClick={() => onSuccess({ credential: "signed-google-token" })}>Sign up with Google</button>,
}));
vi.mock("jwt-decode", () => ({ jwtDecode: () => ({ email: "google@example.com", name: "Google Sample" }) }));

const originalFetch = global.fetch;
const originalLocation = window.location;

beforeEach(() => {
  global.fetch = vi.fn();
  localStorage.clear();
  delete window.location;
  window.location = { ...originalLocation, assign: vi.fn() };
});
afterEach(() => { global.fetch = originalFetch; window.location = originalLocation; });

function openSignup() {
  render(<MemoryRouter><Signup /></MemoryRouter>);
}
function emailReview() {
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "member@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.change(screen.getByLabelText("Create a password"), { target: { value: "Safe example 123!" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Sample Owner" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
}

test("email signup has four steps and defers all business questions until after sign-in", async () => {
  global.fetch.mockResolvedValue({ ok: true, json: async () => ({ checkoutUrl: "https://checkout.stripe.com/test-only" }) });
  openSignup();
  expect(screen.getByText(/Step 1 of 4/)).toBeInTheDocument();
  expect(screen.getByLabelText("Email address")).toHaveAttribute("inputmode", "email");
  expect(screen.getByRole("button", { name: "Sign up with Google" })).toBeInTheDocument();
  emailReview();
  expect(screen.getByText(/Step 4 of 4/)).toBeInTheDocument();
  expect(screen.getByText(/A payment method is required and kept on file by Stripe/)).toBeInTheDocument();
  expect(screen.getByText(/Cancel in Settings → Billing before it ends/)).toBeInTheDocument();
  expect(global.fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Continue to Stripe checkout" }));
  await waitFor(() => expect(window.location.assign).toHaveBeenCalledWith("https://checkout.stripe.com/test-only"));
  const payload = JSON.parse(global.fetch.mock.calls[0][1].body);
  expect(payload).toEqual({ email: "member@example.com", password: "Safe example 123!", name: "Sample Owner", termsAccepted: true, termsVersion: "2026-09-13", privacyVersion: "2026-09-13" });
  expect(localStorage.getItem("user")).toBeNull();
});

test("email and password validation remain visible before advancing", () => {
  openSignup();
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid email address");
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "member@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByLabelText("Create a password")).toHaveAttribute("autocomplete", "new-password");
  fireEvent.change(screen.getByLabelText("Create a password"), { target: { value: "short" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("alert")).toHaveTextContent("12 or more characters");
  expect(screen.getByText(/Step 2 of 4/)).toBeInTheDocument();
  expect(global.fetch).not.toHaveBeenCalled();
});

test("a final review cannot submit without explicit terms consent", () => {
  openSignup();
  emailReview();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Continue to Stripe checkout" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Please agree to the Terms and Privacy Policy");
  expect(global.fetch).not.toHaveBeenCalled();
});

test("Google signup skips password and submits the signed credential for server verification", async () => {
  global.fetch.mockResolvedValue({ ok: true, json: async () => ({ checkoutUrl: "https://checkout.stripe.com/google-test" }) });
  openSignup();
  fireEvent.click(screen.getByRole("button", { name: "Sign up with Google" }));
  expect(screen.getByText(/Step 2 of 3/)).toBeInTheDocument();
  expect(screen.queryByLabelText("Create a password")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Your name")).toHaveValue("Google Sample");
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Continue to Stripe checkout" }));
  await waitFor(() => expect(window.location.assign).toHaveBeenCalled());
  const payload = JSON.parse(global.fetch.mock.calls[0][1].body);
  expect(payload.googleCredential).toBe("signed-google-token");
  expect(payload.password).toBeUndefined();
  expect(payload.termsAccepted).toBe(true);
});

test("an expired or rejected Google credential returns to account selection", async () => {
  global.fetch.mockResolvedValue({ ok: false, json: async () => ({ code: "google_token_invalid", error: "Choose your Google account again." }) });
  openSignup();
  fireEvent.click(screen.getByRole("button", { name: "Sign up with Google" }));
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Continue to Stripe checkout" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Choose your Google account again");
  expect(screen.getByRole("button", { name: "Sign up with Google" })).toBeInTheDocument();
  expect(window.location.assign).not.toHaveBeenCalled();
});

test("Back keeps entered details but switching away from Google requires an email password", () => {
  openSignup();
  fireEvent.click(screen.getByRole("button", { name: "Sign up with Google" }));
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "email@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByLabelText("Create a password")).toBeInTheDocument();
  expect(screen.getByText(/Step 2 of 4/)).toBeInTheDocument();
});

test("a missing checkout response never signs the visitor into a fabricated local account", async () => {
  global.fetch.mockResolvedValue({ ok: true, json: async () => ({}) });
  openSignup();
  emailReview();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Continue to Stripe checkout" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("We could not open checkout");
  expect(window.location.assign).not.toHaveBeenCalled();
  expect(localStorage.getItem("user")).toBeNull();
});

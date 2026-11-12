import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import Login from "./Login";

jest.mock("@react-oauth/google", () => ({ GoogleLogin: () => null }));

beforeEach(() => {
  global.fetch = jest.fn(async () => ({ ok: false, status: 401, json: async () => ({}) }));
});
afterEach(() => { delete global.fetch; });

test("the sign-in fields have accessible names and the password toggle names its action", async () => {
  render(<MemoryRouter initialEntries={["/login"]}><Login /></MemoryRouter>);
  const email = await screen.findByLabelText("Email");
  expect(email).toHaveAttribute("type", "email");
  const password = screen.getByLabelText("Password");
  expect(password).toHaveAttribute("type", "password");

  fireEvent.click(screen.getByRole("button", { name: "Show password" }));
  expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
  expect(screen.getByRole("button", { name: "Hide password" })).toBeInTheDocument();
});

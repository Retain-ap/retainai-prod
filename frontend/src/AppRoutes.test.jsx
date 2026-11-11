import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { AppRoutes } from "./App";

function CurrentPath() {
  const { pathname } = useLocation();
  return <output aria-label="Current path">{pathname}</output>;
}

function renderAt(path) {
  render(<MemoryRouter initialEntries={[path]}><AppRoutes /><CurrentPath /></MemoryRouter>);
}

test("an unknown address shows a not-found page and keeps its URL instead of becoming the homepage", () => {
  renderAt("/no-such-page");
  expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
  expect(screen.getByLabelText("Current path")).toHaveTextContent(/^\/no-such-page$/);
  expect(screen.getByRole("link", { name: "RetainAI home" })).toHaveAttribute("href", "/");
  expect(screen.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login");
});

test.each([
  ["/privacy", "/privacy-policy", "Privacy Policy"],
  ["/terms", "/terms-of-service", "Terms of Service"],
])("%s still reaches %s", (from, to, heading) => {
  renderAt(from);
  expect(screen.getByLabelText("Current path")).toHaveTextContent(new RegExp(`^${to}$`));
  expect(screen.getByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
});

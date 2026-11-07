import React from "react";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import LandingPage from "./LandingPage";

test("the product preview is labelled as example data, not live data", () => {
  render(<MemoryRouter><LandingPage /></MemoryRouter>);
  const preview = screen.getByRole("img", { name: "RetainAI product preview with example data" });
  expect(within(preview).getByText("Example")).toBeInTheDocument();
  expect(within(preview).queryByText(/^\s*Live\s*$/)).not.toBeInTheDocument();
});

test("the header keeps the RetainAI wordmark, Log in and the trial CTA", () => {
  render(<MemoryRouter><LandingPage /></MemoryRouter>);
  const home = screen.getByRole("link", { name: /RetainAI home/i });
  expect(home).toHaveTextContent("RetainAI");
  expect(screen.getAllByRole("link", { name: "Log in" })[0]).toHaveAttribute("href", "/login");
  expect(screen.getAllByRole("link", { name: /Start free trial/ })[0]).toHaveAttribute("href", "/signup");
});

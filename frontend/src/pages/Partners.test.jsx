import React from "react";
import { render, screen } from "@testing-library/react";
import Partners from "./Partners";
import publicContent from "../publicContent.json";

test("the partner page states the exact terms and only live product benefits", () => {
  render(<Partners />);
  expect(screen.getByRole("heading", { name: "What your clients get today." })).toBeInTheDocument();
  publicContent.partners.benefits.forEach((item) => expect(screen.getByText(item)).toBeInTheDocument());
  expect(screen.getByText(publicContent.partners.terms)).toBeInTheDocument();
  expect(publicContent.partners.terms).toMatch(/30% of qualifying base membership payments for the first 12 months/);
  expect(screen.getByRole("link", { name: /Email your interest/ })).toHaveAttribute("href", expect.stringMatching(/^mailto:owner@retainai\.ca/));
  // No unreleased or unapproved features, results or testimonials are claimed.
  expect(document.body.textContent).not.toMatch(/Calendly|guaranteed (revenue|results)|testimonial/i);
});

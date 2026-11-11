import React from "react";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import LandingPage from "./LandingPage";
import publicContent from "../publicContent.json";
import { CustomerProof, OwnerBlock, SourcedProof } from "./MarketingProof";
import MarketingPage from "../pages/MarketingPage";

test("the actual product capture is labelled as example data, not customer proof", () => {
  render(<MemoryRouter><LandingPage /></MemoryRouter>);
  const preview = screen.getByRole("figure", { name: "RetainAI workspace with example data" });
  expect(within(preview).getByText("Actual RetainAI workspace · example data")).toBeInTheDocument();
  expect(within(preview).getByRole("img", { name: /Contacts screen with six fictional customer records/ })).toHaveAttribute("src", "/images/retainai-contacts-example.jpg");
  expect(within(preview).queryByText(/^\s*Live\s*$/)).not.toBeInTheDocument();
});

test("the header keeps the RetainAI wordmark, Log in and the trial CTA", () => {
  render(<MemoryRouter><LandingPage /></MemoryRouter>);
  const home = screen.getByRole("link", { name: /RetainAI home/i });
  expect(home).toHaveTextContent("RetainAI");
  expect(screen.getAllByRole("link", { name: "Log in" })[0]).toHaveAttribute("href", "/login");
  expect(screen.getAllByRole("link", { name: /Start free trial/ })[0]).toHaveAttribute("href", "/signup");
});

test("walkthroughs are real links and every answer exists even when collapsed", () => {
  render(<LandingPage />);
  const links = screen.getAllByRole("link", { name: /walkthrough/i });
  expect(links).toHaveLength(3);
  links.forEach((link) => expect(link).toHaveAttribute("href", publicContent.bookingUrl));
  publicContent.faqs.forEach(([question, answer]) => {
    expect(screen.getByRole("group", { name: question })).toBeInTheDocument();
    expect(screen.getByText(answer)).toBeInTheDocument();
  });
  expect(screen.getByRole("group", { name: publicContent.faqs[0][0] })).toHaveAttribute("open");
  expect(screen.getByText(/A card is required and kept on file by Stripe/)).toBeVisible();
});

test("empty and unapproved evidence produces no fabricated customer proof", () => {
  const { container, rerender } = render(<><CustomerProof /><SourcedProof /></>);
  expect(container).toBeEmptyDOMElement();
  const incomplete = { testimonials: [{ name: "Unapproved example", quote: "This must stay private" }], usage: { count: 100, label: "customers" }, externalMention: { title: "Unverified review" } };
  rerender(<><CustomerProof proof={incomplete} /><SourcedProof proof={incomplete} /></>);
  expect(container).toBeEmptyDOMElement();
});

test("owner trust names the actual owner without an invented photo or biography", () => {
  render(<OwnerBlock />);
  expect(screen.getByRole("heading", { name: "Mateo Zufic" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "owner@retainai.ca" })).toHaveAttribute("href", "mailto:owner@retainai.ca");
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});

test.each(Object.keys(publicContent.pages))("%s has distinct content and one h1", (path) => {
  render(<MarketingPage path={path} />);
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(publicContent.pages[path].heading);
  expect(screen.getAllByRole("link", { name: /Start your 14-day trial/ })[0]).toHaveAttribute("href", "/signup");
});

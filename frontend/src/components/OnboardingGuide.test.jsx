import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import OnboardingGuide from "./OnboardingGuide";

const user = { email: "owner@example.com", role: "owner" };

function mockScreen(isPhone) {
  window.matchMedia = jest.fn().mockImplementation((query) => ({
    matches: isPhone && query.includes("max-width"),
    media: query,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
  }));
}

afterEach(() => {
  localStorage.clear();
  delete window.matchMedia;
});

test("starts collapsed on phones and remembers when it is opened", () => {
  mockScreen(true);
  const { unmount } = render(
    <OnboardingGuide user={user} leads={[]} setSection={jest.fn()} openImports={jest.fn()} />
  );

  expect(screen.queryByText("Import your customer contacts")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Setup · 0 of/ }));
  expect(screen.getByText("Import your customer contacts")).toBeInTheDocument();

  unmount();
  render(<OnboardingGuide user={user} leads={[]} setSection={jest.fn()} openImports={jest.fn()} />);
  expect(screen.getByText("Import your customer contacts")).toBeInTheDocument();
});

test("starts open on larger screens and can be minimized", () => {
  mockScreen(false);
  render(<OnboardingGuide user={user} leads={[]} setSection={jest.fn()} openImports={jest.fn()} />);

  expect(screen.getByText("Import your customer contacts")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Minimize" }));
  expect(screen.queryByText("Import your customer contacts")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Setup · 0 of/ })).toBeInTheDocument();
});

test("collapses on phones after a step opens its screen", () => {
  mockScreen(true);
  localStorage.setItem("retainai:onboarding-collapsed:owner@example.com", "0");
  const openImports = jest.fn();
  render(<OnboardingGuide user={user} leads={[]} setSection={jest.fn()} openImports={openImports} />);

  fireEvent.click(screen.getByText("Import your customer contacts"));
  expect(openImports).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("Import your customer contacts")).not.toBeInTheDocument();
});

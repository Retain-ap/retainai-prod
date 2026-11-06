import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import PrivacyPolicy from "./PrivacyPolicy";

test("the AI disclosure names OpenRouter routing and what can be sent, without overclaiming", () => {
  render(<MemoryRouter><PrivacyPolicy /></MemoryRouter>);
  const text = document.body.textContent;
  expect(screen.getByRole("heading", { name: "AI Features" })).toBeInTheDocument();
  expect(text).toMatch(/OpenRouter chooses the model and the company that processes each\s+request/);
  expect(text).toMatch(/can include data you imported from Google Contacts/);
  expect(text).toMatch(/their email address is used as the name/);
  expect(text).toMatch(/Zero-data-retention routing is not currently\s+enabled/);
  expect(text).toMatch(/run without a separate click/);
  expect(text).not.toMatch(/no Google Contacts (data|fields) (is|are) (ever )?sent/i);
  expect(text).not.toMatch(/zero data retention is enabled/i);
});

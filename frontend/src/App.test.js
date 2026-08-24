import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders the RetainAI landing experience", () => {
  window.history.pushState({}, "", "/");
  render(<App />);
  expect(
    screen.getByRole("heading", { name: /keep more customers.*miss fewer moments/i })
  ).toBeInTheDocument();
  expect(screen.getAllByText(/start.*14-day trial/i).length).toBeGreaterThan(0);
});

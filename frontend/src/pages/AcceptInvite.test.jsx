import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AcceptInvite, { getInvitePasswordError } from "./AcceptInvite";

function jsonResponse(data, ok = true) {
  return {
    ok,
    json: async () => data,
  };
}

describe("AcceptInvite", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/accept-invite?token=invite-token");
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          invite: {
            email: "member@example.com",
            org_id: "owner@example.com",
            role: "member",
          },
        })
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test("requires a strong password", () => {
    expect(getInvitePasswordError("short")).toMatch(/at least 12/i);
    expect(getInvitePasswordError("alllowercase12!")).toMatch(/uppercase/i);
    expect(getInvitePasswordError("StrongPassword!")).toMatch(/number/i);
    expect(getInvitePasswordError("StrongPassword12")).toMatch(/symbol/i);
    expect(getInvitePasswordError("StrongPassword12!")).toBe("");
  });

  test("posts the confirmed password when accepting an invitation", async () => {
    render(<AcceptInvite />);

    fireEvent.change(await screen.findByLabelText(/your name/i), {
      target: { value: "Taylor Member" },
    });
    fireEvent.change(screen.getByLabelText(/^create a password$/i), {
      target: { value: "StrongPassword12!" },
    });
    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: "StrongPassword12!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /accept invite/i }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    const [, options] = global.fetch.mock.calls[1];
    expect(JSON.parse(options.body)).toMatchObject({
      token: "invite-token",
      email: "member@example.com",
      name: "Taylor Member",
      password: "StrongPassword12!",
    });
  });
});

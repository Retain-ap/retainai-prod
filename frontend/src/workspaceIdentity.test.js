import {
  getVisibleSettingsTabKeys,
  getWorkspaceCapabilities,
  getWorkspaceEmail,
} from "./workspaceIdentity";

describe("workspace identity", () => {
  test("uses the organization owner for a team member's tenant key", () => {
    expect(
      getWorkspaceEmail({
        email: "Member@Example.com",
        org_id: "Owner@Example.com",
        orgOwnerEmail: "ignored@example.com",
      })
    ).toBe("owner@example.com");
  });

  test("does not grant owner capabilities to a member", () => {
    const user = {
      email: "member@example.com",
      org_id: "owner@example.com",
      role: "member",
      canInviteTeam: false,
      canEditBusiness: false,
      canManageBilling: false,
    };

    expect(getWorkspaceCapabilities(user)).toMatchObject({
      isWorkspaceOwner: false,
      canInviteTeam: false,
      canEditBusiness: false,
      canManageBilling: false,
    });
    expect(getVisibleSettingsTabKeys(user)).toEqual([
      "profile",
      "imports",
      "notifications",
      "security",
      "help",
    ]);
  });

  test("shows owner controls only for an explicit owner role", () => {
    const user = {
      email: "OWNER@example.com",
      org_id: "owner@example.com",
      role: "owner",
    };
    expect(getWorkspaceCapabilities(user).isWorkspaceOwner).toBe(true);
    expect(getVisibleSettingsTabKeys(user)).toEqual(
      expect.arrayContaining(["team", "integrations", "billing", "account"])
    );
  });
});

"""Workspace-scoped automation progress and conservative legacy migration.

Unowned/ambiguous legacy runs stay quarantined; their flow IDs cannot start
fresh runs. Quarantined history is never returned through a workspace API.
"""

import copy


SCHEMA_VERSION = 2
LEGACY_HELD_REASON = "This flow has legacy run history whose workspace cannot be established. Delivery is held for operator review; no run was restarted."


def scoped_state(raw, flows_db):
    if not isinstance(raw, dict):
        raise ValueError("Automation state is unreadable.")
    if raw.get("schema_version") == SCHEMA_VERSION:
        if not isinstance(raw.get("workspaces"), dict) or not isinstance(raw.get("legacy_unresolved"), dict):
            raise ValueError("Automation state is unreadable.")
        return raw
    if "schema_version" in raw:
        raise ValueError("Unsupported automation state schema; delivery is held.")
    owners = {}
    for owner, flows in (flows_db.get("users") or {}).items():
        for flow in flows if isinstance(flows, list) else []:
            if isinstance(flow, dict) and flow.get("id") is not None:
                owners.setdefault(str(flow["id"]), set()).add(str(owner).strip().lower())
    migrated = {"schema_version": SCHEMA_VERSION, "workspaces": {}, "legacy_unresolved": {}}
    for flow_id, runs in raw.items():
        if not isinstance(runs, dict):
            raise ValueError("Legacy automation state is unreadable; delivery is held.")
        candidates = owners.get(str(flow_id), set())
        if len(candidates) == 1:
            owner = next(iter(candidates))
            workspace_state(migrated, owner)[str(flow_id)] = copy.deepcopy(runs)
        else:
            migrated["legacy_unresolved"][str(flow_id)] = copy.deepcopy(runs)
    return migrated


def workspace_state(state, workspace):
    key = str(workspace).strip().lower()
    if not key:
        raise ValueError("Automation workspace is required.")
    result = state["workspaces"].setdefault(key, {})
    if not isinstance(result, dict):
        raise ValueError("Workspace automation state is unreadable.")
    return result


def legacy_held(state, flow_id):
    return str(flow_id) in state.get("legacy_unresolved", {})

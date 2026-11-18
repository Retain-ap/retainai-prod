"""Pure migration policy tests; no app imports, environment or providers."""
import copy
import unittest

from automation_state import legacy_held, scoped_state, workspace_state


class AutomationStateTests(unittest.TestCase):
    def test_unique_owner_migration_preserves_progress_and_original(self):
        raw = {"flow": {"lead": {"step": 3, "done": True, "events": [{"type": "sent"}]}}}
        before = copy.deepcopy(raw)
        result = scoped_state(raw, {"users": {"a@example.com": [{"id": "flow"}]}})
        self.assertEqual(workspace_state(result, "a@example.com")["flow"], raw["flow"])
        self.assertEqual(raw, before)
        self.assertIs(scoped_state(result, {"users": {}}), result)

    def test_conflicts_and_orphans_are_preserved_but_never_assigned(self):
        raw = {"collision": {"lead": {"step": 1}}, "orphan": {"old": {"done": True}}}
        flows = {"users": {owner: [{"id": "collision"}] for owner in ["a@example.com", "b@example.com"]}}
        result = scoped_state(raw, flows)
        self.assertEqual(result["workspaces"], {})
        self.assertEqual(result["legacy_unresolved"], raw)
        self.assertTrue(legacy_held(result, "collision"))
        self.assertTrue(legacy_held(result, "orphan"))
        self.assertFalse(legacy_held(result, "new-safe-flow"))

    def test_workspace_partitions_do_not_alias(self):
        result = scoped_state({}, {"users": {}})
        workspace_state(result, "a@example.com")["same"] = {"lead": {"step": 1}}
        self.assertEqual(workspace_state(result, "b@example.com"), {})

    def test_newly_claiming_quarantined_id_does_not_resolve_old_history(self):
        result = scoped_state({"orphan": {"lead": {"step": 1}}}, {"users": {}})
        later = scoped_state(result, {"users": {"new@example.com": [{"id": "orphan"}]}})
        self.assertTrue(legacy_held(later, "orphan"))
        self.assertEqual(workspace_state(later, "new@example.com"), {})

    def test_unknown_or_invalid_schema_fails_closed(self):
        for raw in [{"schema_version": 100}, {"schema_version": 2, "workspaces": []}, {"flow": []}]:
            with self.assertRaises(ValueError):
                scoped_state(raw, {"users": {}})


if __name__ == "__main__":
    unittest.main()

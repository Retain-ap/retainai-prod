# Automatic email delivery safety

Automatic workflow emails and post-appointment owner prompts use durable
claims in `DATA_ROOT/automatic_email_dispatch.json`. A claim is flushed before
the provider is called. Only the adapter's explicit `True` result records
provider acceptance; this does not prove inbox delivery.

Failures, timeouts, crashes and uncertain results remain held. They are not
automatically retried. **Retry run** returns a held explanation and HTTP 409
without clearing the error or claiming a retry was queued. This release adds
no override: an operator must establish provider delivery before considering
any recovery. Do not delete claims to force another attempt.

The dispatch API is `dispatch_once(path, identity, send, *, is_eligible=None)`.
Identity is `[event_type, normalized_workspace_email, ...stable_event_ids]`.
Receipts are partitioned by workspace, with hashed event and run identifiers.
The optional eligibility callback reads current account access while holding
the receipt lock. False eligibility raises `DeliveryHeld` before any write or
provider call; it never reports a successful send.

The result is `True` only for a newly accepted delivery whose claim remains.
`False` means an earlier accepted delivery, or a newly accepted claim removed
or workspace made inactive while the provider was in flight. Callers must not create new owner notices on
`False`. Finalization never recreates a removed workspace/claim. Account purge
uses the same file lock and removes the workspace bucket. The automation
engine also holds its run-state lock through delivery and persistence; account
purge waits for that lock, then removes saved workspace progress.
Automatic emails keep workflow history but no longer create a redundant
in-app sent notice. Post-appointment prompts also omit that notice, avoiding
a late write to a notification store already scrubbed by account deletion.

Automation progress now lives under `workspaces` in `automations_state.json`.
Migration preserves legacy flow progress only when that flow has one current
workspace owner. Ambiguous and orphan legacy rows remain in the operator-only
`legacy_unresolved` quarantine; their flow IDs cannot start new runs. Other
flow IDs continue normally. Owner history shows only a generic hold, never
quarantined customer details. Migration is idempotent and saved before a
delivery or a flow ownership change. Quarantined records require an operator
to establish ownership before recovery or targeted deletion; they are not
silently assigned or discarded.

Flow reads/mutations, manual runs, retries and deletions share the state lock.
History and run keys are workspace-scoped; deleting an unknown flow returns
404. An old unpartitioned delivery journal cannot be safely reverse-mapped
from its hashes and fails closed for operator review rather than being reset.

Post-appointment prompts require an active account, an eligible noncancelled
status, and a start time between one and 24 hours ago in the appointment's
timezone. The job rechecks the current record and never saves an old calendar
snapshot over newer edits. This is separate from owner lead-reminder cadence.

Tests use temporary synthetic stores and mocked providers only. POSIX locking
and integration tests run on Linux; Windows skips those tests explicitly.

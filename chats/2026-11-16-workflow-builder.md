# Simple workflow builder

The requested Stripe-inspired editor is prepared on `codex/workflow-builder-20261116`, based on `origin/deploy` at `cbd88e5`. It has not been deployed or merged.

The builder now shows a vertical trigger and numbered action cards, an Add step chooser, and a focused editor. Desktop uses two columns; tablet and phone stack the editor below the sequence and focus its heading when a card is selected. Existing nested condition editors, all four triggers and eight action types, template cloning, sending rules, shared business settings, run history, preview, and live-test confirmation remain available.

Drafts have separate Save draft and Publish actions. Active flows offer Save and publish and explicit Pause. There is no separate published-revision model in the current backend, so pausing uses the existing enable endpoint and preserves open unsaved edits; it does not silently save them. Successful writes followed by a failed list refresh retain the saved ID, avoiding a duplicate create on retry. Publishing checks the name, trigger, at least one step, and existing recursive WhatsApp template validation. No backend or service endpoint code changed.

Validation on Node 24.19.0:

- All 43 frontend suites / 319 tests passed, including 16 new interaction tests for draft/publication, every trigger, action availability, nested field preservation/reorder/removal, pause without saving edits, write/refresh failures, WhatsApp validation, and explicit live-test confirmation.
- Full frontend ESLint passed with zero warnings; production build and route prerender passed.
- The production bundle was checked at 1440×1100, 820×1180, and 390×844 against the real local Flask app, using fictional isolated data, the scheduler disabled, and external provider calls blocked. Document width matched the viewport at all sizes. Existing email editor and nested sequence remained usable. Draft save, publish, and pause succeeded through the actual local API routes.
- The local Windows harness adapted Linux file locking using `msvcrt`; no production backend files changed. Its missing WhatsApp credentials correctly produced the existing unavailable-template response. No live message test was sent.

Local screenshots and the harness are in the worktree's untracked `output/playwright/` folder. Review and CI are next; no provider accounts or live workflows were changed.

# Contact import follow-up — 11 November 2026

Codex and Claude continued after the evening closeout. PR64 is merged as `d7f4d71f919c8b5bdefc5be2e83956ca123ffb11` and deployed to both RetainAI services.

## Changes

- Opening Contacts after an import recomputes and stores the derived contact status. Safe undo previously treated that as an owner edit and refused to remove or restore the imported contacts. Undo now ignores only that derived status; actual edits, including a recorded contact activity, still preserve the contact.
- Unreadable birthdays now produce an explicit row warning. Validation checks the complete trimmed value, rejects impossible dates and trailing junk, and accepts ISO/compact/no-year forms. It does not guess slash-date order. An invalid birthday does not replace an existing birthday during merge or update.
- The source chooser, marketing-consent defaults, duplicate identity conflicts and workspace boundaries were reviewed with fictional fixtures. No additional changes were needed there; importing does not authorize marketing or send messages.

## Evidence

- Reviewed head: `71407e27626ae21774d8ed1b04376a830408793d`. Exact-head GitHub gate `43142599925` passed: 282 backend tests; 233 frontend tests in 37 suites; lint, build and dependency checks. Merged gate `43142874060` also passed.
- Regression fixtures reproduce the original undo failure, preserve real edits, reject a valid-looking birthday prefix followed by junk, and preserve an existing birthday in both duplicate modes.
- Backend: `dep-dbqidhjrjlhs73fu6he0`, live 12 November 02:40:12 UTC (11 November 21:40 Toronto).
- Frontend: `dep-dbqidhjrjlhs73fu6i9g`, live 02:40:08 UTC. Both deployments were automatic and use the merge above; no duplicate manual deploy was triggered.
- Claude checked the Render records and bounded backend error/critical logs from 02:39 to 02:41 UTC: no entries. The live import chunk contains the new warning text.
- Codex's anonymous HTTP checks passed 16/16 at 02:42 UTC. The initial-HTML public-route verifier passed 27/27. These checks do not claim an authenticated production import or a new checkout/refund acceptance.

No production contact records, emails, payments or permission grants were created by these tests. The separate Closet Muse draft PR37 contains the native design and Planner changes; it still requires the macOS build and acceptance gates. The new build spending request is pending, with no allowance changed.

# Benchmark 3: the v0.3.0 verdict loop (draft; results below once runs finish)

## Decision rule (written before running, copied from PLAN-lean.md)
- Claude tokens < Arm A → agy-worker saves Claude usage on this task type.
- Between Arm A and old Arm B → the loop helps but the baseline dominates; next step is the lean headless orchestrator.
- ≥ old Arm B → the turn count was not the cost; investigate before building more.

Quota "before" (agy_usage, 2026-10-20): Gemini 5-hour 99%, weekly 46%, Argon 31%.

## Outcome: ABANDONED, no results
Both runs were launched in parallel on 2026-10-20 (large package and small T2, each an orchestrator-only Sonnet subagent using the v0.3.0 loop). Both orchestrator subagents were then stopped externally ("stopped by user" in the task notification) before either finished its loop. The session did not stop them. On the user's instruction (option 3) the two still-running agy jobs were cancelled and the run abandoned. No reruns, per the plan.

- Large: orchestrator a54d95eddc7bdcc40, agy job 1020-111022-352d (cancelled).
- Small T2: orchestrator a698538f39b8aab7f, agy job 1020-111023-25d2 (cancelled; partial agy edits in 2 files were left in place, unscored).
- Hidden checks were not scored, and no Claude-side or agy-side figures were recorded as results. Nothing in this file bears on the decision rule.
- Quota: Gemini 5-hour 99% → 98%, weekly 46% → 46%.
- agy allow-list rules added for the run (`python3 -m unittest discover -s tests`, `python3 -m unittest`) were removed; the list is back to its prior state.

## Deviations
1. `agy_permissions` in 0.3.0 has no `check=` argument, so the allowed state was confirmed from the returned list instead.
2. The plan's "restart the app" step was needed: the first session had agy-worker as a cached connection failure and the run began after a reconnect.

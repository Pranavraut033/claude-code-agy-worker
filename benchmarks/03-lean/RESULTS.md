# Benchmark 3 (attempt 2): the v0.3.0 verdict loop

agy-worker 0.3.0 confirmed latest (source HEAD cff9d46, installed and connected); agy 1.4.3.
Attempt 1 was abandoned when both orchestrators were stopped externally: see RESULTS-attempt1-abandoned.md.


> **⚠️ Polluted run — read this first (added 2026-10-20).** This benchmark ran with agy's own global
> config loaded into every job: **7 MCP servers, 7 skills, 22 plugins (more skills and MCPs), 3 agents
> and 3 rule files**, plus the repo's `GEMINI.md` (→ the whole `CLAUDE.md`). That pollution caused the
> large run's failure (agy called a `codegraph` MCP tool, which headless mode denied, ending the round)
> and inflated agy's token counts (a trivial turn cost **16,113** tokens then, **7,169** once agy was
> made bare). The small run's false `failed` came from a Gemini 503 after agy had finished, which the
> v0.3.0 verdict treated as a failed round and skipped the checks. Both are fixed in v0.4.0 (bare agy
> + per-job lending; checks on every finished round). Treat these numbers as an upper bound for agy's
> cost and rerun before drawing conclusions.

## Decision rule (written before running, from PLAN-lean.md)
- Claude tokens < Arm A → agy-worker saves Claude usage on this task type.
- Between Arm A and old Arm B → the loop helps but the baseline dominates; next step is the lean headless orchestrator.
- ≥ old Arm B → the turn count was not the cost; investigate before building more.

Date 2026-10-20. Two runs, n=1, no reruns. Baselines: ../RESULTS.md (benchmark 1) and ../large/RESULTS-large.md (benchmark 2).

## Method
- Fixtures copied from the agy-worker repo's `benchmarks/` (large generator + hidden checks, small T2 seed + checks). Large seed regenerated and confirmed 2/6 unmigrated; small seed fails its hidden checks unmigrated. Each run is a fresh `cp -r seed` with `git init` and a base commit.
- Each run is one Sonnet `general-purpose` subagent, orchestrator and auditor only, task text word for word from the earlier benchmark plus the v0.3.0 loop block of PLAN-lean.md: `agy_start` once with `checks=[<test command>]`, model `gemini-3.8-flash-medium`, run the returned `wait_cmd` in the background, read the verdict, at most one consolidated `agy_resume`.
- The one test command per run was granted via `agy_permissions` before and removed after (the list is back to its prior state).
- Measures as in benchmarks 1 and 2: Claude `subagent_tokens`, cumulative Claude input (sum over transcript API calls, `checks/usage.py`), tool uses (harness count), wall time, agy tokens and wall from `agy_status`, rounds, hidden checks run by me, `quota_drop_pct` from the verdict.
- The two runs executed in parallel, so their quota drops overlap.

## Results

| Run | Claude tokens | Cumul. Claude input | Tool uses | Wall | agy tokens | agy wall | Rounds | Hidden checks |
|---|---:|---:|---:|---:|---:|---:|---|---|
| small T2, old Arm A (Claude alone) | 96,300 | 428k | 5 | 19 s | – | – | – | 6/6 |
| small T2, old Arm B (v0.1.2 loop) | 115,652 | 826k | 11 | 190 s | 95,671 | 160 s | 0 | 6/6 |
| **small T2, lean (v0.3.0)** | **80,367** | **887k** | **14** | **213 s** | **192,170** | **163 s** | **0 fix-ups** | **6/6** |
| large, old Arm A (Claude alone) | 91,053 | 594k | 7 | 38 s | – | – | – | 6/6 |
| large, old Arm B (v0.1.2 loop) | 106,733 | 1.04M | 12 | 1,050 s | 615,340 | 1,002 s | 0 | 6/6 |
| **large, lean (v0.3.0)** | **77,818** | **805k** | **10** | **310 s** | **316,364** | **266 s** | **1 fix-up, still no edits** | **2/6 (FAILED, tree unchanged)** |

B/A ratios on Claude tokens: small lean 0.83× (old B 1.20×). The large lean ratio is not meaningful: the task was not done.
agy quota (both runs together): Gemini 5-hour 98% → 95%, weekly 46% → 45%. From the verdicts: small run −3 / −1 points, large run −1 / 0.

## What happened
- **Small T2:** agy finished in 163 s with the correct code, and the hidden checks pass 6/6. But the waiter's verdict said `state: "failed"`, `checks: []`, `clean: false`: the server-run check did not run, so the orchestrator ran the tests itself (13–14 tool calls, including a failed Monitor attempt). Round count 0 fix-ups.
- **Large:** the verdict mechanics worked here (check ran: 82 tests OK; denials listed; a `hint` field), and the orchestrator read them correctly. But agy made no edits in either round. Round 1 ended on a denied `CallMcpTool` (46 s). After a single fix-up telling it not to use MCP tools, round 2 (266 s) was denied `CallMcpTool` again, plus `grep -r "registered" .` (recursive grep is outside the `grep ` rule's intent for this agy). The unit-test check passes only because the code was never migrated. The orchestrator stopped and did not do the work itself, per the skill (ask the user after two failed rounds).
- No orchestrator was killed this time.

## Conclusion (decision rule)
- **Small T2:** Claude tokens 80,367 are below both old Arm A (96,300) and old Arm B (115,652), the first branch of the rule. That is one cell with one run.
- **Large:** no result. agy never edited a file, and the denial was agy-side behaviour that the verdict loop surfaced but did not prevent. The old v0.1.2 Arm B run had no such denial on the same fixture, so this is variance or a regression I did not isolate. The rule cannot be applied to this task type from this run.
- **What the numbers do not show:** the lean loop did not cut tool calls (14 and 10 against 11 and 12 before). Cumulative Claude input also stayed high (887k, 805k), because the transcript sums every call's re-read context. The drop in `subagent_tokens` on the small task is real but I did not isolate its cause. Part of it is that the large-run counts include only the orchestrator's short exchange.
- So the claim "the verdict loop saves Claude tokens" rests on one successful run. The next thing to look at, going by these results, is the waiter's `state: failed, checks: []` result on a good job, and the repeated `CallMcpTool` denial, not the lean headless orchestrator.

## Deviations
1. `agy_permissions` in 0.3.0 has no `check=` argument; allowed state was confirmed from the returned list.
2. Attempt 1 was abandoned (both orchestrators stopped externally, agy jobs cancelled); this is the fresh attempt, see RESULTS-attempt1-abandoned.md. No results were carried over.
3. The orchestrators were told to take the already-granted allow-list rule as given and not call `agy_permissions`.
4. Tool-use counts come from the harness; each orchestrator self-reported one fewer (it did not count the final report call).
5. The large run was left unfinished after 2 agy rounds, per the skill, and was not retried (no reruns).

## Caveats
n = 1 per cell, Sonnet orchestrator, fixture and checks written by Claude, two runs in parallel on a shared quota, and the large run failed for a reason I did not isolate.

## Summary
- agy-worker 0.3.0 confirmed latest (source HEAD, installed, connected).
- Small T2: 6/6, Claude 80k tokens, below old Arm A (96k) and old Arm B (116k); but 14 tool calls, 213 s, 192k agy tokens.
- Small run's waiter returned `state: failed`, `checks: []` on a good job, so the orchestrator re-ran the tests itself.
- Large: FAILED, 2/6. agy was denied `CallMcpTool` twice and made no edits; the orchestrator stopped as the skill says.
- Tool-call count did not fall (14 and 10 vs 11 and 12 before); cumulative Claude input stayed high (887k, 805k).
- The decision rule's first branch holds for one small cell only; nothing can be said for the large task.
- agy quota: 5-hour 98% → 95%, weekly 46% → 45%.
- Next to investigate: the waiter's false `failed` and the `CallMcpTool` denial.

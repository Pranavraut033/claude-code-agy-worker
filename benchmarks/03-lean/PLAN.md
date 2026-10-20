# Benchmark 3 plan — the lean loop (v0.3.0): does server-run checks + one verdict cut Claude tokens?

Question: with `checks=[…]` on `agy_start`, a background waiter and one verdict (v0.3.0), does an
orchestrated package cost fewer Claude tokens than before (≈100–115k, 11–12 tool calls) and than
Claude alone (≈90k, 7 calls)? Benchmarks 1 and 2 are the baselines; they are not rerun.

**Follow this plan exactly; log deviations in RESULTS.md under "Deviations".** Work only under
`~/agy-bench/lean/`. Touch nothing in the session's own repository. Two runs, n = 1, no reruns.
Do not read the old arms' transcripts to "improve" the new arm: the point is the same prompt shape.

## Setup
1. `agy_usage()` → record Gemini 5-hour / weekly % ("before"). `claude plugin list` → confirm
   agy-worker ≥ 0.3.0 (restart the app if not) and `agy --version`.
2. Copy fixtures from this repo: `benchmarks/02-large/` (generator + hidden checks +
   TASK.md) → `~/agy-bench/lean/large/`; `benchmarks/01-small/` T2 (seed, `tasks/t2.md`,
   `checks/task2.sh`, `checks/t2_hidden.py`) → `~/agy-bench/lean/small-t2/`. Re-generate the large
   seed with `gen_fixture.py` and confirm the unmigrated seed scores 2/6 on `checks/large.sh`.
3. Per run: `cp -r seed runs/<task>-lean`; fresh `git init` + commit.

## Runs (2)
Each run is one Sonnet `general-purpose` subagent (the same model and tools as Arm B before), with the
task text from the original benchmark word for word, plus this block:

> You are orchestrator and auditor only. Read the skill at
> `~/.claude/plugins/cache/agy-worker/agy-worker/<installed version>/skills/agy/SKILL.md` first.
> Use exactly this loop: (1) `agy_start` once with `checks=[<the task's own test command>]`, model
> `gemini-3.8-flash-medium`, `allowed_files` = the repo dir, run-only commands = that test command;
> (2) run the returned `wait_cmd` as a background shell task and wait for it; (3) read the verdict.
> If `clean` is true and the stat looks right, finish. Otherwise read only the diffs the verdict
> points at and send ONE consolidated fix-up with `agy_resume`. Do not edit files yourself.
> Report the job id, rounds, and your own tool-call count.

Grant the one test command via `agy_permissions` before, remove it after. Use
`agy_permissions(check=[…])` first to confirm the command is allowed.

## Measure (same as benchmarks 1 and 2)
Claude `subagent_tokens`, cumulative Claude input (sum over the transcript's API calls; see
`benchmarks/01-small/checks/usage.py`), Claude tool uses, wall time, agy tokens + wall, rounds,
hidden checks (run them yourself), `quota_drop_pct` from the verdict, defects in the same 3
spot-check files as benchmark 2 (handler_03, handler_17, handler_31).

## Report
`RESULTS.md`: method (≤ 8 lines); one table — run × [Claude tokens, cumulative input, tool uses,
wall, agy tokens, rounds, checks] with the old Arm A and Arm B rows beside it; B/A ratios; the
conclusion, in plain words: did the Claude-token cost drop below the old Arm B, and below Arm A?
If the tool-call count fell but tokens did not, say that: the fixed baseline (system prompt, tools,
CLAUDE.md, memory) is then the next thing to attack. Caveats: n = 1, Sonnet orchestrator, fixture
and checks written by Claude. Finish with a ≤ 10-line summary.

## Decision rule (write it down before running)
- Claude tokens < Arm A → agy-worker saves Claude usage on this task type; update the README
  benchmark section and the "too small" threshold in the skill.
- Between Arm A and old Arm B → the loop helps but the baseline dominates; next step is the lean
  headless orchestrator (`claude -p --bare` or the Agent SDK with only the agy tools).
- ≥ old Arm B → the turn count was not the cost; investigate before building more.

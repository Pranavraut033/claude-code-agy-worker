# Benchmark 4 plan — bare agy + verdict loop (v0.4.x)

Question: with agy bare (no MCP servers, skills, plugins or agents of its own; ponytail lent), the
v0.3.0 verdict loop and v0.4.0's fixes (checks on every finished round, no stray MCP calls), does an
orchestrated package cost fewer Claude tokens than Claude alone, at equal quality — on a task Claude
can script **and** on one it cannot?

Benchmark 3 is the comparison but was polluted (see `../03-lean/RESULTS.md`). Arm A ("Claude alone")
numbers from benchmarks 1 and 2 are reused: agy's config never touched that arm.

**Follow this plan exactly; log deviations in RESULTS.md under "Deviations".** Work only under
`~/agy-bench/bare/`. Touch nothing in the session's own repository. n = 1 per cell, no reruns.

## 0. Preconditions (stop and report if one fails)
- `claude plugin list` shows agy-worker ≥ 0.4.1 and this session was started after that install
  (`agy_start` must list `checks`, `lend` and `mcp` parameters).
- `agy mcp list` prints "No MCP servers configured"; `agy plugin list` shows none enabled;
  `~/.gemini/config/skills/` is empty. If not: run `/agy-worker:agy-setup` (ask the owner first).
- `agy --version`; `agy_usage()` → record Gemini 5-hour / weekly % ("before").
- Bare baseline sanity check: one trivial stream-json turn from an empty folder (`Reply with exactly:
  ONE. Use no tools.`, model gemini-3.8-flash-low) — record `total_tokens` (7,169 on 2026-10-20).

## 1. Fixtures (copy, do not rewrite)
From this repo's `benchmarks/`: `02-large/` (generator, TASK.md, hidden checks) → `large/`;
`01-small/` T2 (seed, `tasks/t2.md`, `checks/task2.sh`, `checks/t2_hidden.py`) → `small-t2/`.
Regenerate the large seed; confirm the unmigrated seed scores 2/6 on `checks/large.sh`.
Each run: `cp -r seed runs/<task>-bare`, fresh `git init` + commit. **None of the run folders may
contain `GEMINI.md`, `AGENTS.md` or `.agents/`** (check; `agy_start` reports `repo_agy_config` if so).

### New cell — a task Claude cannot script (the case agy is meant for)
Generate `judgment/seed/` with a script (`gen_judgment.py`, stdlib, seeded): 30 short support-ticket
text files in `tickets/` (4–8 sentences each, varied wording, no shared template phrases), plus
`labels.json` written to `checks/` only (hidden ground truth). Task text for both arms:
> For every file in `tickets/`, write `summaries/<same name>.json` with `{"category": one of
> ["billing","bug","feature","account","other"], "urgency": 1-3, "summary": "<= 20 words"}`.
> Then write `summaries/INDEX.md`: one line per ticket, sorted by urgency (3 first).
Hidden check `checks/judgment.sh`: all 30 JSON files valid; category accuracy vs labels (report the
percentage; pass ≥ 80 %); urgency within ±1 of the label for ≥ 80 %; INDEX.md sorted. For this cell
also run **Arm A (Claude alone)** fresh, since there is no earlier number.

## 2. Runs (4)
| Run | Arm |
|---|---|
| small-t2-bare | Claude + agy (verdict loop) |
| large-bare | Claude + agy (verdict loop) |
| judgment-claude | Claude alone |
| judgment-bare | Claude + agy (verdict loop) |

Each run is one Sonnet `general-purpose` subagent. Arm A prompt: task text + "Work in <dir>. Do it
yourself, any way you like (scripts allowed); do not use agy. Hard cap: 120 tool calls."
Arm B prompt: task text + this block (identical for every B run):
> You are orchestrator and auditor only. Read the skill at
> `~/.claude/plugins/cache/agy-worker/agy-worker/<installed version>/skills/agy/SKILL.md` first.
> Use exactly this loop: (1) `agy_start` once, model `gemini-3.8-flash-medium`, `allowed_files` =
> the repo dir, `checks=[<the task's own test command>]` (judgment: `python3 -c` is not allowed —
> use `ls summaries | wc -l` as the check), default `lend` (ponytail); run-only commands = that
> check; (2) run the returned `wait_cmd` as a background shell task; (3) read the verdict. If
> `clean` is true and the stat looks right, finish. Otherwise read only the diffs the verdict points
> at and send ONE consolidated fix-up with `agy_resume`. Do not edit files yourself. `agy_close`
> at the end. Report job id, rounds, and your tool-call count.
Grant each B run's check command via `agy_permissions(check=[…], add=[…])` before, remove it after.
Runs may go two at a time in parallel (quota drops then overlap; say so).

## 3. Measure (same as benchmarks 1–3)
Claude `subagent_tokens`, cumulative Claude input (`benchmarks/01-small/checks/usage.py`), tool uses,
wall time; agy tokens + wall + `quota_drop_pct` from the verdict; rounds; hidden checks (run them
yourself); defects in the spot-check files (large: handler_03, handler_17, handler_31; judgment: 5
random tickets, same 5 for both arms, compared against `labels.json`).

## 4. Report — `RESULTS.md`
Method (≤ 8 lines); one table with the new rows beside the old Arm A / Arm B / benchmark-3 rows;
B/A Claude-token ratios per task; the bare-baseline token number; conclusion in plain words. State
which levers changed since benchmark 3 (bare agy, ponytail lent, checks on every round, no-MCP
guard) — the numbers cannot separate them. Caveats: n = 1, Sonnet orchestrator, Claude-written
fixtures and checks. ≤ 10-line summary.

## Decision rule (fixed before running)
- **Scriptable tasks** (T2, large): B < A → the loop pays even where Claude can script; B ≈ old
  B (100–115k) → the fixed baseline dominates, next lever is a lean headless orchestrator.
- **Judgment task:** this is the case for agy. B < A here, at ≥ 80 % accuracy in both arms, is the
  first evidence that agy-worker saves Claude usage. B ≥ A here means it does not, for this setup.

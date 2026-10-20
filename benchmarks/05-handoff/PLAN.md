# Benchmark 5 plan — hand-off mode with a light audit (v0.5.0)

Question: when Claude only briefs, starts the job and reads one verdict (`handoff=True`; no diff reads
unless the verdict flags something), does Claude's side finally cost less than Claude doing the work
itself, and does the work still pass the hidden checks?

Arm A numbers (Claude alone) are reused from benchmarks 1, 2 and 4: agy never touched that arm.
Benchmark 4 is the full-audit comparison (`../04-bare/RESULTS.md`).

**Follow this plan exactly; log deviations in RESULTS.md under "Deviations".** Work only under
`~/agy-bench/handoff/`. n = 1 per cell, no reruns.

## 0. Preconditions (stop and report if one fails)
- agy-worker ≥ 0.5.0 installed and this session started after it (`agy_start` lists `handoff`).
- `agy mcp list` = none; no plugins; `~/.gemini/config/skills/` empty.
- `agy_usage()` before; no idle agy sessions left over (`pgrep -fl "agy --input-format"` empty).

## 1. Fixtures
Same as benchmark 4 (`../04-bare/` and `../02-large/`, `../01-small/` T2): small-t2, large, judgment.
Fresh `cp -r seed runs/<task>-handoff`, `git init`, commit. No GEMINI.md / AGENTS.md / .agents.

## 2. Runs (3), all Arm C (hand-off)
Each run is one Sonnet `general-purpose` subagent. Prompt: task text + this block (identical for every run):
> You are orchestrator only; the owner audits. Read the skill at
> `~/.claude/plugins/cache/agy-worker/agy-worker/<installed version>/skills/agy/SKILL.md` first.
> Loop: (1) `agy_start` once, model `gemini-3.8-flash-medium`, `allowed_files` = the repo dir,
> `checks=[<the task's own test command>]`, default `lend`, `handoff=True`; (2) run `wait_cmd` as a
> background shell task; (3) read the verdict and report in ≤ 3 lines: done or not, checks, and
> whether `sample` looks like what the brief asked. Read diffs only if the verdict shows a failed
> check, a denial or out-of-scope edits; then at most ONE `agy_resume`. Do not edit files yourself.
> Report job id, rounds, your tool-call count.
Grant the check commands before (`agy_permissions(check=…, add=…)`), remove after. Run one at a time.

## 3. Measure (same as benchmarks 1–4)
Claude `subagent_tokens`, cumulative Claude input (`benchmarks/01-small/checks/usage.py`), tool uses,
wall; agy tokens, wall, rounds, quota drop; hidden checks run by the benchmark session itself. Also
record **what the light audit missed**: any hidden-check failure or spot-check defect (large:
handler_03/17/31; judgment: the same 5 tickets as benchmark 4) that the C-arm orchestrator reported
as done.

## 4. Report — `RESULTS.md`
Method (≤ 8 lines); one table: A (reused), B (benchmark 4 full audit), C (hand-off) per task; C/A and
C/B Claude-token ratios; misses of the light audit; conclusion in plain words; caveats (n = 1, Sonnet
orchestrator, Claude-written fixtures). ≤ 10-line summary.

## Decision rule (fixed before running)
- **C < A on at least two tasks, with no hidden-check failure reported as done** → hand-off mode
  saves Claude tokens; say so in the README with the numbers.
- **C ≈ B** → the diff reads were not the cost; the brief and the subagent baseline are. Next lever:
  a lean headless orchestrator (`claude -p --bare`).
- **Any miss** (light audit called broken work done) → the light audit is too light; add the miss
  to the skill's flag list before claiming any saving.

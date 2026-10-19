# Benchmark plan — Claude alone vs Claude + agy (3 tasks)

Goal: real numbers on whether handing mechanical work to agy (agy-worker plugin) cuts Claude
token use, and what it costs in wall time and quality. Small on purpose: 3 tasks × 2 arms = 6 runs.

Scope rules
- Work only under `~/agy-bench/`. Touch nothing in your main project.
- Budget: ≤ 2 fix-up rounds per run, no reruns. A failed run is a data point, not a retry.
- Never `--dangerously-skip-permissions`, never allow `command(*)`, `rm`, `curl`, package managers.

## Phase 0 — Baseline (2 min)
1. `agy_usage()` → record Gemini 5-hour % and weekly % in RESULTS.md ("before").
2. Note the session's own usage % if visible (Settings → Usage), for a rough sanity check.

## Phase 1 — Fixture (you build it, ~15 min)
`~/agy-bench/seed/`, stdlib only (python3 + unittest), ~300 lines total, git init + one commit.

| File | Contents |
|---|---|
| `inventory/models.py` | `@dataclass Item(sku, name, unit_price: float, qty: int, category)` |
| `inventory/store.py` | `load(path) -> list[Item]`, `save(path, items)` (JSON) |
| `inventory/pricing.py` | `calc_total(items)`, `discount_for(qty)` tiers: 0–9 → 0 %, 10–49 → 5 %, 50+ → 10 %; `line_total(item)` applies the discount, rounds to 2 dp |
| `inventory/report.py` | `summary(items) -> str` (table text), `by_category(items) -> dict`; `main(argv)` with `--format text` |
| `inventory/cli.py` | argparse entry: `python3 -m inventory.cli report data.json` |
| `tests/test_*.py` | ~12 tests covering pricing tiers, totals, store round-trip, report text |
| `data.json` | 8 sample items, 3 categories |

`calc_total` must appear in ≥ 5 files (pricing, report, cli, a docstring, tests) for T1.

Make three branches of the seed (or three seed copies): `seed-t1`, `seed-t2` = the clean seed;
`seed-t3` = clean seed + 3 planted bugs (below), committed, so some existing tests fail.

## Phase 2 — Tasks (identical text for both arms)

**T1 — easy, mechanical.** "Rename the function `calc_total` to `compute_total` everywhere in this
repo: definitions, calls, imports, tests and docstrings. Behaviour must not change. Run
`python3 -m unittest discover -s tests` and make sure it passes."

**T2 — medium, spec.** "Add CSV output to the report. `inventory/report.py` gets
`to_csv(items) -> str`: header `sku,name,category,qty,unit_price,line_total`; one row per item
sorted by sku; prices with exactly 2 decimals; fields containing a comma or quote are quoted with
`"` and inner quotes doubled (RFC 4180); lines end with `\n`; no trailing blank line. `main(argv)`
accepts `--format csv` (default stays `text`) and prints the CSV. Add unit tests for `to_csv`
covering sorting, 2-dp prices, and a name containing a comma and a quote. All tests must pass."

**T3 — hard, debugging.** "Some tests in `tests/` fail. Find and fix the bugs in `inventory/` so
that all tests pass. Do not modify any file under `tests/`. Explain each fix in one line."
Planted bugs (keep secret from both arms):
1. `discount_for`: tier boundary `qty > 10` instead of `qty >= 10` (off-by-one).
2. `calc_total`: sums unrounded line totals and rounds once at the end where the spec/tests expect
   per-line rounding (float drift on the sample data, e.g. a 0.01 difference).
3. `store.load(path, items=[])`: mutable default list that accumulates across calls.

## Phase 3 — Hidden checks (written before any run, kept in `~/agy-bench/checks/`)
Each `checks/tN.sh <run-dir>` prints one `PASS|FAIL <criterion>` line per criterion:
- **t1**: `grep -rn calc_total` finds nothing; `compute_total` is defined once; tests pass;
  no files changed besides `.py` files.
- **t2**: hidden `test_csv_hidden.py` (copied in at check time) passes: exact header, sort, 2 dp,
  RFC 4180 quoting of `Bolt, "hex"`, `--format csv` via `main`, default still text; existing tests pass.
- **t3**: tests pass; `git diff --stat -- tests/` is empty; hidden test per bug passes
  (qty 10 gets 5 %; per-line rounding total on a crafted 3-item list; two `load()` calls don't share state).

## Phase 4 — Runs (6)
For each task: `cp -r seed-tN runs/tN-claude` and `runs/tN-agy`; `git init` + commit in each.
A and B of the same task may run in parallel; run tasks in order T1 → T3.

**Arm A — Claude alone.** One `general-purpose` subagent, `model: sonnet`. Prompt = task text +
"Work in <dir>. Do the work yourself; do not use agy or any agy-worker tool."

**Arm B — Claude + agy.** One `general-purpose` subagent, `model: sonnet`. Prompt = task text +
"Work in <dir>. You are orchestrator and auditor only: read
`~/.claude/plugins/cache/agy-worker/agy-worker/*/skills/agy/SKILL.md` first, then use the
`mcp__plugin_agy-worker_agy-worker__agy_*` tools. One package brief, model
`gemini-3.8-flash-medium`, allowed_files = the repo dir, run only `python3 -m unittest discover -s tests`
plus read-only inspection, no pipes. Wait with `agy_wait` (or the returned wait_cmd in background),
audit with `agy_diff`, ≤ 2 fix-up rounds. Do not edit files yourself. Report the job id(s)."
Before Arm B runs: `agy_permissions(add=["command(python3 -m unittest discover -s tests)"])`.
After all runs: remove that rule again.

## Phase 5 — Measure (per run)
| Field | Source |
|---|---|
| Claude tokens, wall time | the Agent tool result's usage line |
| agy tokens, agy wall time | `agy_status(job)` → `tokens`, `elapsed_s` (sum over rounds/jobs) |
| fix-up rounds / extra jobs | the subagent's report + `agy_status()` list |
| hidden check | `checks/tN.sh runs/tN-<arm>` → n PASS / n total |
| defects | your own read of `git diff` in the run dir: wrong, missing, or out-of-scope changes (count + one line each) |
Then `agy_usage()` again → quota drop for the whole benchmark.

## Phase 6 — RESULTS.md
1. Method (≤ 8 lines).
2. Table: task × arm → Claude tokens · agy tokens · wall time · checks passed · defects · rounds.
3. Totals per arm, and Claude-token ratio B/A per task.
4. Quota drop (Gemini 5-hour, weekly).
5. Conclusion in plain words: did agy reduce Claude tokens, by how much, at what cost in time and
   quality. Only what the numbers show.
6. Caveats: n = 1 per cell; tiny tasks (agy's ~40 s cold start and the briefing overhead weigh more
   than on real 10–60 min packages); Sonnet as orchestrator; the fixture and checks were written by Claude.
End the session with a ≤ 10-line summary.

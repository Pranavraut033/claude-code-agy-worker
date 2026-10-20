# Benchmark 4: bare agy + verdict loop (agy-worker 0.4.1, agy 1.4.3)

Run 2026-10-20 under `~/agy-bench/bare/`. n = 1 per cell, no reruns. Plan: `PLAN.md`.

## Method
- Preconditions held: agy-worker 0.4.1 enabled; `agy_start` lists `checks`, `lend`, `mcp`; `agy mcp list` = none; `agy plugin list` = none; `~/.gemini/config/skills/` empty. Quota before: Gemini 5-hour 95%, weekly 45%. After: 89% / 43%.
- Bare baseline (empty folder, gemini-3.8-flash-low, "Reply with exactly: ONE."): **7,075 total tokens** (plan: 7,169).
- Fixtures: large seed regenerated (unmigrated = 2/6); small T2 seed (unmigrated = 1/6); new `judgment/` (30 hand-written tickets, shuffled with seed 7; ground truth in `judgment/checks/labels.json`, oracle = 4/4, empty = 0/4). No GEMINI.md / AGENTS.md / .agents in any run folder.
- Each run = one Sonnet `general-purpose` subagent; B arms used the plan's loop block (agy_start once, medium model, ponytail lent, own check, background wait_cmd, at most one agy_resume). A arm: task + "do it yourself, scripts allowed, no agy, cap 120 calls".
- Measures as in benchmarks 1-3: harness `subagent_tokens`, cumulative Claude input via `checks/usage.py` (input + cache write + cache read, output left out), tool uses, wall, agy tokens/elapsed (from the orchestrators' agy_status reports), hidden checks run by me.
- Batch 1: judgment A + B in parallel. Batch 2: small-t2 B + large B in parallel (their quota drops overlap).

## Results

| Run | Claude tokens | Cumul. Claude input | Tool uses | Wall | agy tokens | agy wall | Rounds | Hidden checks |
|---|---:|---:|---:|---:|---:|---:|---|---|
| small T2, old A (Claude alone) | 96,300 | 428k | 5 | 19 s | – | – | – | 6/6 |
| small T2, old B (v0.1.2) | 115,652 | 826k | 11 | 190 s | 95,671 | 160 s | 0 | 6/6 |
| small T2, bench 3 (v0.3.0, polluted) | 80,367 | 887k | 14 | 213 s | 192,170 | 163 s | 0 | 6/6 |
| **small T2, bare (v0.4.1)** | **95,892** | **627k** | **9** | **226 s** | **118,300** | **153 s** | **0 fix-ups** | **6/6** |
| large, old A | 91,053 | 594k | 7 | 38 s | – | – | – | 6/6 |
| large, old B (v0.1.2) | 106,733 | 1.04M | 12 | 1,050 s | 615,340 | 1,002 s | 0 | 6/6 |
| large, bench 3 (v0.3.0, polluted) | 77,818 | 805k | 10 | 310 s | 316,364 | 266 s | 1 | 2/6 FAILED |
| **large, bare (v0.4.1)** | **108,392** | **832k** | **10** | **1,406 s** | **652,115** | **1,350 s** | **0 fix-ups** | **6/6** (314/314 hints) |
| **judgment, A (Claude alone, new)** | **85,553** | **239k** | **3** | **26 s** | – | – | – | **4/4, category 97% (29/30), urgency exact 26/30** |
| **judgment, bare (v0.4.1)** | **100,627** | **1.29M** | **14** | **363 s** | **220,263** | **302 s** | **1 fix-up** | **4/4, category 97% (29/30), urgency exact 29/30** |

B/A Claude-token ratios: small T2 **0.99×** (old B 1.20×); large **1.19×** (old B 1.17×); judgment **1.18×**.
Cumulative input B/A: small 1.46×, large 1.40×, judgment 5.4×.
agy quota (all four runs): Gemini 5-hour 95% → 89%, weekly 45% → 43% (other sessions may share it). Per-run drops: judgment ~1/1, small ~1/0, large ~5/1 (overlapping).

## Spot checks
- Large (handler_03, 17, 31): old imports gone, `@handler(...)` with correct kwargs, type hints from docstrings, `logger.<level>`. Hidden type-hint match 314/314. Core files untouched (agy edited `app/registry.py` mid-run per the orchestrator, but it is not in the final diff).
- Judgment (tickets 14, 17, 24, 27, 29, chosen with seed 11): both arms match labels on 4/5 on urgency and 5/5 on category; ticket 29 urgency: A said 1, B said 2, label 2. Within ±1 either way.

## Conclusion (decision rule)
- **Scriptable tasks:** T2: B ≈ A (0.99×) — no saving, but no longer a loss; B is well below old B (116k → 96k). Large: B 108k ≈ old B 107k, 1.19× A, so the fixed baseline dominates and the loop does not pay on a task Claude can script.
- **Judgment task: B ≥ A (100.6k vs 85.5k), at equal 97% accuracy.** By the rule fixed in advance, this means agy-worker does not save Claude usage for this setup, even on work that is not a regex job. Caveat: Claude alone finished in 3 tool calls (read all 30 tickets once, write the files), so the "judgment" was cheap for Claude too; 30 short tickets may be too small for agy's hands to beat one long read.
- What did not improve: tool calls were 9-14 per run (checks-on-every-round did not cut the count; each orchestrator also hit a failed Monitor attempt), and cumulative Claude input was 1.4-5.4× A.
- Levers changed since benchmark 3 (bare agy, ponytail lent, checks on every round, no-MCP guard): the numbers cannot separate them.

## Deviations
1. Fixtures were copied from the benchmark 3 working folder (large generator + checks, small-t2 seed + checks).
2. Judgment checker initially required `<name>.txt.json`; agy wrote `<stem>.json` (A wrote `.txt.json`). The task text allows both, so the checker now accepts either; both arms re-scored with it. Before the fix, B scored 0/4.
3. The allow-list rule `command(python3 -m unittest)` was added once up front for all B runs (not per run) to avoid a race between the parallel runs; removed after the last run (list back to its prior state). `ls`/`wc` were already allowed, so no rule was needed for the judgment check.
4. Judgment B round 1 wrote nothing (agy claimed the allow-list blocked it); one consolidated fix-up fixed it. agy's report also mentioned waiting for a "researcher subagent" — not investigated.
5. Large B: agy's state read "failed" from a transient 503 at the end, but the verdict was `clean: true` and the work was complete.
6. Orchestrator tool-use counts above are the harness's; the first batch's A-arm cumulative figure is 238,692 input.

## Caveats
n = 1, Sonnet orchestrator, Claude-written fixtures and checks (including the judgment labels, which are my own reading of the tickets), two runs in parallel on a shared quota, orchestrators spot-checked only part of agy's diffs.

## Summary
- 4 runs: small T2, large, judgment (new, with Claude-alone arm), all agy runs bare + ponytail + verdict loop.
- Quality equal everywhere: 6/6, 6/6, 4/4 (97% category accuracy both arms).
- Claude tokens B/A: small 0.99×, large 1.19×, judgment 1.18× (A 85.5k vs B 100.6k).
- Judgment is the decisive cell and agy did not save Claude tokens there.
- Tool calls still 9-14 per B run; cumulative input 1.4-5.4× A.
- agy used 990k Gemini tokens in total; quota 95% → 89% (5-hour), 45% → 43% (weekly).
- Bare agy baseline 7,075 tokens.

## Audit (orchestrator of the benchmark, after the runs)
- Hidden checks re-run independently: small T2 6/6, large 6/6 (314/314 hints), judgment A 4/4 and B 4/4. All reproduce.
- Judgment B round 1 (deviation 4), root cause: the guard said "Edit ONLY these files: <run folder>", so agy read the folder
  as a file list and refused to create `summaries/*`. The server already treated folders and globs as covering new files;
  only the wording was wrong. Fixed in v0.4.2 ("Create or edit files ONLY within …; a folder covers every file under it").
  That wasted round cost the B arm one extra `agy_resume` plus its verdict read.
- The "researcher subagent": agy 1.4.3 has a built-in `invoke_subagent` tool and called it once in round 2. It listed and read the
  30 tickets for ~13k Gemini tokens (11.5k in, 2k out), which the verdict does not show. v0.4.3 allows subagents for
  read-only research only.
- The plan's judgment check `ls summaries | wc -l` contains a pipe while the guard said "no pipes"; agy ran it, but the
  guard now says a named command line may contain one.

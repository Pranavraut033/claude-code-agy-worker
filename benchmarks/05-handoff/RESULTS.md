# Benchmark 5: hand-off mode with a light audit (agy-worker 0.5.0)

Run 2026-10-20 under `~/agy-bench/handoff/`. n = 1 per cell, no reruns. Plan: `PLAN.md`.

## Method
- Preconditions held: 0.5.0 installed, `agy_start` has `handoff`; `agy mcp list` = none, `agy plugin list` = none, `~/.gemini/config/skills/` empty, no idle agy sessions. Quota before: Gemini 5-hour 89%, weekly 43%.
- Fixtures copied from the benchmark 4 working folder (small-t2, large, judgment), fresh `cp -r seed`, `git init`, commit. No GEMINI.md / AGENTS.md / .agents.
- Each run = one Sonnet `general-purpose` subagent with the plan's block (`agy_start` once, `gemini-3.8-flash-medium`, `handoff=True`, default `lend`, own check, background `wait_cmd`, read the verdict, at most one resume). Run one at a time.
- Arm A and Arm B (benchmark 4, full audit, v0.4.1) numbers are reused from `../04-bare/RESULTS.md`; not rerun.
- Hidden checks and spot checks run by me after each run. Claude tokens = harness `subagent_tokens`; cumulative input via `usage.py` (input + cache write + cache read).

## Results

| Task | Arm | Claude tokens | Cumul. input | Tool uses | Wall | agy tokens | agy wall | Rounds | Hidden |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| small T2 | A (Claude alone) | 96,300 | 428k | 5 | 19 s | – | – | – | 6/6 |
| small T2 | B (bench 4) | 95,892 | 627k | 9 | 226 s | 118,300 | 153 s | 0 fix-ups | 6/6 |
| small T2 | **C (hand-off)** | **94,889** | 441k | 6 | 155 s | 167,167 | 115 s | 1 | **6/6** |
| large | A | 91,053 | 594k | 7 | 38 s | – | – | – | 6/6 |
| large | B | 108,392 | 832k | 10 | 1,406 s | 652,115 | 1,350 s | 0 fix-ups | 6/6 |
| large | **C** | **104,917** | 1.51M | 17 | 536 s | 709,692 | 501 s | 2 (per agy; see Deviations) | **6/6** (314/314 hints) |
| judgment | A | 85,553 | 239k | 3 | 26 s | – | – | – | 4/4 |
| judgment | B | 100,627 | 1.29M | 14 | 363 s | 220,263 | 302 s | 1 fix-up | 4/4 |
| judgment | **C** | **94,575** | 438k | 6 | 527 s | 406,348 | 459 s | 1 | **4/4** (cat 97%, urgency exact 29/30, within ±1 30/30) |

| Task | C/A | C/B |
|---|---:|---:|
| small T2 | 0.99× | 0.99× |
| large | 1.15× | 0.97× |
| judgment | 1.11× | 0.94× |

agy quota drops (5-hour / weekly): small 1/0, large 3/1, judgment 2/1.

## What the light audit missed
Nothing: no case where the orchestrator said done and a hidden check failed or a spot check showed a defect.
- Large: handler_03/17/31 diffs are right (decorator with kwargs, tuple tags, defaults omitted, `warn` → `logger.warning`, hints from docstrings, old imports gone, core files untouched). Only an extra edit to `app/handlers/__init__.py`, which the brief did not ask for and which breaks nothing.
- Judgment: tickets 14, 17, 24, 27, 29 all match the labels on category and urgency.
- Small: `report.py` matches the brief (csv.writer, half-up rounding, TOTAL row, CLI choice).
- Caveats on audit strength: the judgment check was only `ls summaries | wc -l` (file count), so the verdict could not have caught a wrong label. The large orchestrator reported "not fully trusted done" (hedged), and its sample was a test file, not a handler.

## Conclusion (decision rule)
- C < A on one task only (small, 0.99×, within noise). Large and judgment are 1.11–1.15× A. So **hand-off mode does not save Claude tokens versus Claude alone**.
- C is 0.94–0.99× B. By the plan's rule this is the **C ≈ B** branch: skipping the diff reads is not what costs tokens; the brief, the skill read and the subagent baseline (about 95k per run) are. Next lever: a lean headless orchestrator (`claude -p --bare`).
- No misses, so the third branch does not apply here.

## Deviations
1. Check-command grants were made once up front (`command(python3 -m unittest)`) rather than per run; runs were sequential. The large run needs `python3 -m unittest discover -s tests`, which that prefix rule did not cover as agy saw it (denial logged in both large rounds).
2. The large orchestrator called `agy_permissions` itself and added `command(python3 -m unittest discover -s tests)` (and per its report added a duplicate), which the plan did not intend. I removed all such rules at the end; the allow-list is back to its original contents. For the judgment run I added "Do not call agy_permissions" to the block.
3. The subagent block also says to load tool schemas with ToolSearch (the tools are deferred); the plan block did not mention it.
4. Judgment check command was `ls summaries | wc -l` (the plan gives none for this task).
5. Large: agy reported 2 rounds with a transient unittest denial and edited only `__init__.py` and `test_handler_39.py` by its own edit log; the verdict listed the other 78 files as "not from agy edits" (likely written via a path agy's log does not count). The orchestrator did not resume. The result passed all hidden checks.
6. Judgment: agy state read "failed" from a 503 at the end after the work was complete; verdict `clean: true`. The agy session also used `manage_subagents`/`schedule` steps and wasted reads on wrong file names (the same noise as benchmark 4); not investigated.
7. Arm A small-T2 uses the old A figure (96,300), as listed in `../bare/RESULTS.md`.

## Caveats
n = 1, Sonnet orchestrator, Claude-written fixtures and checks, the judgment labels are my own reading, a weak judgment check, quota shared with other sessions.

## Summary
- 3 hand-off runs, all hidden checks pass (6/6, 6/6, 4/4); no light-audit misses.
- C/A Claude tokens: small 0.99×, large 1.15×, judgment 1.11×.
- C/B: 0.99×, 0.97×, 0.94×.
- Decision rule: C ≈ B branch; next lever is a lean headless orchestrator.

## Audit (after the runs)
- Hidden checks re-run independently: small T2 6/6, large 6/6, judgment 4/4. All reproduce.
- **Deviation 5 explained: agy ran a script through the test runner.** Its log has 10 `write_file` steps, all to
  `app/handlers/__init__.py` and `tests/test_handler_39.py`. The first wrote Python into `__init__.py`
  (`print(os.listdir(...))`) to list the files, which agy cannot do by command; `python3 -m unittest` imports the
  package, so the code ran. All 78 other files carry the same mtime (14:20:18): a migration script, run the same way,
  rewrote them in one pass, and agy then emptied `__init__.py` and restored the test file. Its three research
  subagents only ran greps. The Claude orchestrator made no edits.
- So the allow-list promise ("only the exact commands granted") does not hold once a command executes repo code.
  The verdict did list the 79 files under `not_from_agy_edits`, but `clean` stayed true and the hand-off orchestrator
  did not treat it as a warning.
- Fixed in v0.5.1: the verdict lists changed files inside the package with no agy edit step as `unattributed`, and
  `clean` is false while it is non-empty (re-running this job's verdict: `clean: false`, 79 unattributed); the
  diff sample is now taken from all changed files, not only agy's own edits; the guard forbids writing code for an
  allowed command to run; the README says granting a test runner is granting code execution.
- This also means the large run's result is the scripted path Claude alone took (benchmark 2), done by agy.

## Real-use estimate (added afterwards)
Per run, from the subagent transcripts: final context minus the first call's context (~70k in every run: system
prompt, tools, CLAUDE.md, memory), and for agy arms minus the SKILL.md read (17.9k/19.3k chars ≈ 4.5k/4.8k tokens),
because a real session pays the start once and reads the skill once.

| Task | A added | B (bench 4) added | C added | B/A | C/A |
|---|---:|---:|---:|---:|---:|
| small T2 | 25.4k | 24.2k − 4.5k = 19.7k | 23.6k − 4.8k = 18.8k | 0.78× | 0.74× |
| large | 20.1k | 37.0k − 4.5k = 32.6k | 33.4k − 4.8k = 28.5k | 1.62× | 1.42× |
| judgment | 15.0k | 29.4k − 4.5k = 24.9k | 23.5k − 4.8k = 18.7k | 1.66× | 1.25× |

Only small T2 saves. Context growth only: extra tool calls each re-read the whole cached context in a real session.


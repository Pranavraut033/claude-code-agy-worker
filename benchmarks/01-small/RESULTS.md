# Benchmark: Claude alone vs Claude orchestrating agy

Run on 2026-10-19. There are 6 runs (3 tasks × 2 arms) with n=1 per cell. Every run is recorded as it came out, with no reruns.

## Method
- **Fixture.** `seed/` is a stdlib-only "inventory" library: 6 modules plus 6 test files, 367 lines and 14 unittest tests, committed to git. Each run is a fresh `cp -r` of it with a new `git init`. For T3, `checks/inject_t3_bugs.py` seeds three bugs before the base commit: the discount tier uses `>` where it should use `>=`, `calc_total` rounds a float sum instead of summing half-up Decimal line totals, and `Item` has the mutable default `tags=[]`. These leave 3 tests failing and 1 erroring.
- **Tasks.** The texts are in `tasks/t{1,2,3}.md`, and both arms got them word for word. T1 renames `calc_total` to `compute_total` across 6 files. T2 adds `to_csv()` and `--format csv` to an exact column, quoting and rounding spec, with tests. T3 makes the failing tests pass without touching tests/.
- **Hidden checks.** These live in `checks/taskN.sh` and stay outside the repos. Each prints PASS/FAIL per criterion, and I ran every one myself. T2 has 4 hidden exact-output tests, and T3 has 1 hidden test per bug. Two of those catch partial fixes: one rounds only the summed total instead of each line, and one checks the tier boundary through `discounted_total`.
- **Arm A.** One general-purpose subagent on Sonnet did the task itself, with agy disallowed.
- **Arm B.** One general-purpose subagent on Sonnet read the agy SKILL.md and models.md and added narrow permission rules. It then briefed agy (`gemini-3.8-flash-medium`), waited, audited with `agy_diff` and the tests, and removed its rules at the end. It never edited the repo itself.
- **Order.** A and B of each task ran in parallel, and the three tasks ran one after another. This kept the B runs from racing each other on agy's shared allow-list.
- **Claude tokens** are the harness's `subagent_tokens` from each Agent result, which roughly matches the subagent's final context size. **Cumulative Claude input** is the sum over all API calls in the subagent transcript (input + cache write + cache read). This measures the work re-reading context. The transcripts undercount output tokens, so output is left out.

## Results

| Task | Arm | Claude tokens | Cumul. Claude input | Claude tool uses | Wall time | agy tokens | agy wall | Hidden checks | Defects | Fix-up rounds |
|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| T1 rename | A Claude | 81,332 | 151k | 2 | 7 s | – | – | 4/4 | 0 | – |
| T1 rename | B +agy | 100,984 | 742k | 11 | 135 s | 77,061 | 108 s | 4/4 | 0 | 0 |
| T2 CSV spec | A Claude | 96,300 | 428k | 5 | 19 s | – | – | 6/6 | 0 | – |
| T2 CSV spec | B +agy | 115,652 | 826k | 11 | 190 s | 95,671 | 160 s | 6/6 | 0 | 0 |
| T3 debug | A Claude | 86,292 | 408k | 5 | 14 s | – | – | 5/5 | 0 | – |
| T3 debug | B +agy | 102,845 | 761k | 11 | 211 s | 102,863 | 187 s | 5/5 | 0 | 0 |

**Totals**

| Arm | Claude tokens | Cumul. Claude input | Wall time | agy tokens | Checks | Defects |
|---|---:|---:|---:|---:|---|---:|
| A Claude alone | 263,924 | 0.99M | 40 s | – | 15/15 | 0 |
| B Claude + agy | 319,481 (+21%) | 2.33M (×2.4) | 536 s (×13) | 275,595 | 15/15 | 0 |

**agy quota** (`agy_usage`, before → after): Gemini 5-hour 98% → 94%, Gemini weekly 54% → 53%, Argon weekly 31% → 31% (unused), Claude/GPT unchanged.

**Diff review (defects and out-of-scope changes).** None were found in either arm, and no agy job had denied commands or out-of-scope edits.
- T1: the two diffs are byte-identical (6 files, ±15 lines).
- T2: both arms touched only `report.py` and `test_report.py`, and both used the same design. One nit in both arms, not counted as a defect: each imports the private `pricing._money` instead of using a public helper.
- T3: both made the same three root-cause fixes. They differ only in `list(tags) if tags else []` (A) versus `... if tags is not None else []` (B), which behave the same here.

## Conclusion
On these three small tasks, handing the edits to agy **did not cut Claude tokens. It raised them.**
- Final-context tokens went up 21% (264k → 319k).
- Cumulative Claude input went up about 2.4× (1.0M → 2.3M). The orchestrator made 11 tool calls per task against Claude-alone's 2–5: skill docs, permissions, brief, wait, diff, tests, cleanup.
- Wall time went up about 13× (40 s → 536 s), mostly agy's own run time of 108–187 s per job, which includes its cold start.
- Quality was the same: every hidden check passed in both arms, with 0 fix-up rounds and 0 defects.
- agy spent 276k Gemini tokens in total, which took 4 points off its 5-hour pool and 1 point off its weekly pool.

The fixed overhead per job (reading the skill, the permission round-trip, briefing, waiting, auditing) was larger than the editing it replaced, because each task took Claude alone only 2–5 tool calls. These numbers do not show whether agy pays off on larger work packages, where the editing would outweigh that overhead.

## Caveats
- n=1 per cell, so there is no variance estimate. A single rerun could move any number.
- The tasks are small, about 15 changed lines each. Fixed orchestration overhead dominates at this size, by construction.
- The orchestrator was Sonnet on a fresh subagent. It re-read the agy skill every run, a cost that a long-lived session would pay once.
- Claude wrote the fixture, the tasks and the checks, and Claude subagents ran both arms.
- `subagent_tokens` is a harness figure close to final context size, not billed tokens. The cumulative figure comes from transcripts and leaves out output.
- Arms A and B ran at the same time, so their wall times may have interfered slightly.

## Summary
- 3 tasks (rename, spec feature, 3-bug debug) × 2 arms, n=1 each, hidden checks run by me.
- Quality was equal: 15/15 checks in both arms, 0 defects, 0 fix-up rounds.
- Claude tokens: A 264k vs B 319k, so agy **added** 21% (cumulative input ×2.4).
- Wall time: A 40 s vs B 536 s, so agy was about 13× slower (108–187 s per agy job).
- agy used 276k Gemini tokens in total, which cost 4 points of its 5-hour quota and 1 point of its weekly quota.
- At this task size, agy's fixed per-job overhead outweighed the editing it took over. Larger packages are untested.
- Raw numbers are in `raw.tsv`, task texts in `tasks/`, and checks and seeding scripts in `checks/`.

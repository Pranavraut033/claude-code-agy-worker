# Benchmark 2: large package, Claude alone vs Claude + agy

> **Note (2026-10-20):** this run had agy's own global config loaded into every job (7 MCP servers, 7 skills, 22 plugins, agents, rules), which roughly doubled agy's fixed cost per turn (16k vs 7k tokens bare) and can cause stray, denied MCP calls. Claude-side numbers are unaffected by it; agy-side numbers are an upper bound. See `../03-lean/RESULTS.md`.


Run on 2026-10-19 under `~/agy-bench/large/`, one task × two arms, n=1, no reruns. Plan: `../PLAN-large.md`.

## Method
- **Fixture.** `gen_fixture.py` (stdlib, `random.Random(42)`) builds `seed/`: 40 handler modules (107 functions, 59 registrations, 2–4 `log()` calls each), 40 test files, 4 core files and 82 tests, about 2.8k lines. It also writes the hidden ground truth to `checks/types.json` and `checks/expected.json`, outside the repo.
- **Task.** `TASK.md`: migrate every handler to `@handler`, `logger.<level>`, full type hints derived from the docstrings, updated tests, and the old modules left in place. Both arms got the identical text.
- **Hidden checks.** `checks/large.sh` has 6 criteria. Before any run I validated it with a scripted reference migration (6/6) and the unmigrated seed (2/6).
- **Arm A.** A Sonnet subagent did the work itself with scripts allowed, capped at 120 tool calls. **Arm B.** A Sonnet subagent used the agy skill 0.1.2 to brief agy with one package (`gemini-3.8-flash-medium`, allowed_files = the repo, ≤2 fix-ups) and audited the result, with the unittest allow-rule added and removed around the run.
- **Measures.** These are the same as benchmark 1. Claude tokens are the harness's `subagent_tokens`. Cumulative Claude input is summed over all API calls in the transcript with `checks/usage.py`. Wall time is taken from the Agent result and the agy token counts from the arm's report of `agy_status`.
- **Defects.** I diffed the two arms across the 3 spot-check files (handler_03, handler_17, handler_31) rather than reading every diff.

## Results

| Arm | Claude tokens | Cumul. Claude input | Claude tool uses | Wall time | agy tokens | agy wall | Fix-ups | Hidden checks | Type-hint match | Defects |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|
| A Claude alone | 91,053 | 594k | 7 | 38 s | – | – | – | 6/6 | 314/314 (107/107 funcs) | 0 |
| B Claude + agy | 106,733 | 1.04M | 12 | 1,050 s | 615,340 | 1,002 s | 0 | 6/6 | 314/314 (107/107 funcs) | 0 |

**Ratio B/A.** Claude tokens: 1.17×. Cumulative input: 1.74×. Wall time: 28×.

**agy quota**, before → after: Gemini 5-hour 86% → 77% (−9 points), weekly 51% → 48% (−3 points). Argon (31%) and Claude/GPT were not touched. Other sessions may share this quota. Between the end of benchmark 1 (94% / 53%) and the start of this run (86% / 51%), the 5-hour pool had already dropped 8 points unaccounted for.

**Diff review.** There were no defects or out-of-scope changes in either arm. Both touched exactly the 40 handlers and 40 handler tests, and neither touched the core files or `test_core_old_api.py`.

The 3 spot-checked files differ between arms only in quote style on the tags tuple (`('slow',)` in A, `("slow",)` in B). Across the full diffs, the 322 differing lines are consistent with that same difference.

## Deviations
1. **Arm A wrote its script to `/tmp/mig.py`**, which is outside its run directory. The brief said to touch nothing outside the directory, so that was a small breach. The script is still there, and it did not affect the repo or your main project.
2. The first completion notice for Arm B said it was waiting on its own background work, which was the `wait_cmd`. It then finished normally, and I used the final numbers.
3. All other steps went as planned. The tests ran against the hidden checks I validated beforehand.

## Conclusion
At this size, agy still did not reduce Claude's token use.
- **Claude tokens.** The ratio B/A moved from 1.21× in benchmark 1 to 1.17× here, so it is still above 1 and nowhere near the break-even point. The gap in Claude's own tokens did not close because Sonnet solved the task alone with a single regex script: 7 tool calls and 91k tokens for 40 files.
- **Cost.** agy did the same job in 176 steps, 615k Gemini tokens and about 17 minutes, against 38 s for Claude alone. This is the regime agy's design is aimed at (many files, many steps), but the mechanical migration was regex-solvable.
- **Quality.** Quality was equal: 6/6 checks and a perfect 314/314 type-hint match in both arms, and no fix-ups were needed.

The orchestration overhead stayed roughly constant, about 107k tokens in both benchmarks, while Claude-alone cost barely moved (86–96k). That would make agy cheaper only on work Claude cannot script, which this task did not test.

## Caveats
- n=1 per arm, with a generated fixture and a Sonnet orchestrator.
- Claude is free to script parts of the work, and here it scripted all of it. That is a legitimate result, but it makes this task a weak test of agy's strength.
- Claude wrote the generator, the checks and both arm prompts.
- `subagent_tokens` is not billed tokens, and the transcript sum leaves out output tokens.
- The agy quota delta is confounded by other sessions.

## Summary
- Large package: 40 handlers + 40 tests migrated to a new API, with type hints, regex-solvable by design.
- Equal quality: 6/6 checks and 314/314 type hints in both arms, no defects, 0 fix-ups.
- Claude tokens: A 91k, B 107k, so agy added 17% (benchmark 1: +21%).
- Cumulative Claude input: 594k vs 1.04M (×1.74).
- Wall time: 38 s vs 1,050 s (×28). agy used 615k Gemini tokens in 17 min.
- Sonnet solved A with one regex script, so the task didn't need agy's hands.
- agy quota: 5-hour 86% → 77%, weekly 51% → 48% (confounded by other sessions).
- Claude is cheaper alone when it can script the job; agy untested on work Claude can't script.

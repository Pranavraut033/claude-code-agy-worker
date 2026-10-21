---
name: delegate
description: Plan a multi-file job on the strongest model, cut it into clusters of related tasks, and hand each cluster to the cheapest worker that will finish it — a Claude Code subagent on Haiku (mechanical) or Sonnet (judgment), or the Antigravity CLI (agy) — through the delegate MCP server, which snapshots the tree, guards the worker, runs your checks and returns one verdict. Use when the user says /delegate, "orchestrate this", "fan this out to subagents", "hand this to agy/Gemini", for multi-file builds or the same change across many files, long unattended runs (renders, build chains, test suites), reading volume too large for this session's context, or when Claude's usage limit is nearly spent. Not for work this session can finish in a few calls, and not for decisions — those stay here.
---

# /delegate — plan here, a cheap worker builds, one verdict comes back

Roles: **this session** plans, decides and writes each brief with machine checks; a **worker** does the
mechanical work in place; the **user** watches the run and reviews the diff; this session reads **one verdict**
(a light audit) and reads diffs only when the verdict flags something or the user asks. Evidence tags: [ours] =
our benchmarks and session logs (README, JOURNEY.md), [ext] = `references/orchestration.md`.

## Invocation

- **`/delegate [task]`** — from here on, decide for every job in this session whether to delegate it, by §0,
  and say in one line why or why not. With a task, start on it.
- **`/delegate --usage [folder]`** — the same, plus keep `DELEGATE-LOG.md` in `folder` (default: the repo
  root) for the user to hand back for review. Append only, never rewrite old rows:

```
## Owner meter
| when | Claude 5-hour % | Claude weekly % |          ← ask the user before the first job and after the last

## Jobs                                                ← one row per job, delegated or done by you
| # | job id | task | worker (haiku/sonnet/agy/self) | rounds | worker tokens | orchestrator_calls |
  denials | state | clean | protected_changed / unattributed | checked on disk | cascade (re-tags) | fixes, by whom |

## Friction                                            ← one line per problem
- date | job id | guard / verdict / report / brief / tool bug | what happened | cost (calls, minutes)
```

Numbers come from the verdict, never from memory; rounds and tokens are cumulative per job, so log the final
values once. Don't edit the log while a worker runs (the scope check would flag it).

## 0. Do it yourself, or delegate?

Every call this session makes re-reads its whole context; that, not the worker's price, is the cost [ext: one
Sonnet call at 315k cached context ≈ $0.03, a whole Haiku job ≈ $0.02]. In a real 8-job session orchestration
took 13–34 calls per job [ours].
- **Do it yourself** when the job takes under ~3 tool calls, or when briefing and verifying it would take more
  than ~5 calls of yours. Say so in one line.
- **Delegate** when doing it here would pull 10+ files or heavy tool output into this context, when there are
  3+ independent clusters, or for long commands the worker can sit on [ext].
- **Never delegate** visual judgment (images, renders, layout): workers call broken output "verified" [ours].
- Decisions (content, naming, what goes where) are made here and written into the brief.

## 1. Plan into clusters

Plan on the strongest model available; if this session runs on a weaker one and the job is large, say so before
planning. Explore unfamiliar code with an Explore subagent, not by reading it all here.
- **Cluster = tasks that share files or one repeated pattern** ("add soft-delete to five models" is one cluster).
  One worker per cluster. Split only when write sets are disjoint, a dependency forces an order, or the size
  would push a worker past ~100k context.
- **One owner cluster** for migrations, lockfiles, dependency manifests and generated clients; no other cluster
  touches them.
- **Tier each cluster now**, not at dispatch: `haiku` = apply a fixed, already-decided pattern, no design calls,
  no unfamiliar contracts; `sonnet` = diagnosis, ambiguity, multi-step changes where a check can fail for a
  non-obvious reason; unsure → `sonnet`. `agy` per `references/agy.md` (Google quota, long unattended runs).
- Write the plan to `.claude/plans/<slug>.md`: per cluster the tier, files it owns, tasks, acceptance checks and
  dependencies. The plan becomes the briefs.
- Before dispatch, run `git status` and tell the user which files with uncommitted work the workers will touch.
- Check `CLAUDE_CODE_SUBAGENT_MODEL` is unset or `inherit` (it can override the per-call model).
- At most **2–3 workers at once**, on disjoint files; a dependent cluster starts only after its prerequisite's
  checks pass [ext]. One cluster and an Opus session → just do it here.

## 2. Write the brief and the checks

`delegate_start(brief, cwd, allowed_files, backend="subagent"|"agy", model="haiku"|"sonnet", checks=[…],
commands=[…], protect=[…], outputs=[…], lend=[…])`. The server wraps the brief in the guard (scope, exact
commands, stay on task, no code smuggled into files a command runs, report shape) — don't repeat those.

```
# Context        static facts: what the project is, formats, where an example lives (exact paths)
# Goal           one sentence: the end state
# Tasks          numbered; each: files, the exact change (before → after for a pattern), done-means,
                 its check and what passing output looks like
# Order          which tasks depend on which; "run each task's check before the next"
# If blocked     "mark it BLOCKED with the reason and continue with the rest"
```

- **`checks`**: machine checks that print pass/fail (tests, a verifier, a lint, a tiny compare). The server runs
  them after the worker finishes, with your permissions, and puts each result in the verdict. Design the check
  before the task; derive invariants from the existing artefact, not from memory [ours: a spec error cost 2
  rounds]. The worker may run them too.
- **`commands`**: every other command line the tasks need, exactly as written (a venv or env var goes in the
  line: `.venv/bin/python3 tools/x.py`). Subagent jobs: the guard hook allows exactly these plus read-only
  `ls/cat/grep/git status|diff|log`, and denies the rest as a tool error (the run continues).
- **`protect`**: files the checks depend on (tests, fixtures, the verifier). The hook refuses edits to them and
  the verdict reports `protected_changed` [ext: read-only tests are the measured fix for test tampering; ours:
  a worker once hid a migration script in `__init__.py` and ran it through the allowed test runner].
- **`outputs`**: files the commands generate (a timeline, a log, a mix), so they don't count as unattributed.
- **`lend`**: skills or files the job needs, inlined into the brief file (default `["ponytail"]`; `[]` for
  none). Lend the one context doc a package needs, not the whole CLAUDE.md (subagent workers start without it).
- Point at exact paths and line ranges so the worker doesn't explore. Give numbers, not adjectives. When a bug
  has cost time, carry a short "rules that cost hours" block in every later brief in that area.

## 3. Run it

**Subagent worker (default).** `delegate_start` launches nothing: it snapshots the tree, writes `brief.md` and
the hook's `guard.json`, and returns `agent`. Pass those fields straight to the Agent tool:
`Agent(subagent_type="delegate:worker", model=…, description=…, prompt=…, run_in_background=true)` — never a
fork (a fork inherits this whole context [ext]). The user watches the worker in the app. End your turn or do
other work; when its completion notice arrives, call `delegate_verdict(job)`.

**agy worker.** `backend="agy"` launches the Antigravity CLI and returns `wait_cmd`/`watch_cmd`; permissions,
quota, models and the hand-off loop are in `references/agy.md`.

**If `delegate_start` comes back rejected or as an error**, run `delegate_status()` before saying nothing
started (the desktop app once ran a declined call [ours]); cancel any job from the last minute that is yours.

## 4. Read the verdict (light audit by default)

`delegate_verdict(job)` runs the checks once and returns: `state`, `tokens` (and `tokens_by_model`),
`orchestrator_calls`, `report` (the worker's per-task block), `edits`, `denied`, `out_of_scope`, `unattributed`,
`protected_changed`, `stat`, `sample` (one changed file's diff, ≤1,500 chars), each check, `all_checks_pass`,
`clean`. Report in ≤3 lines: **done or not** (state, clean, checks, scope, denials) and **quality at a glance**
from `sample`. Then stop reading unless:
- `protected_changed` or `unattributed` is non-empty → say so, read one of those files;
- `denied` is non-empty → the worker hit the guard; decide whether the brief missed a command;
- a check failed → §5.

**Full audit only on request**, or for factual, user-facing or security-relevant work, and always a short
consistency read across clusters when there was more than one: read `stat`, then `delegate_diff(job, files=[…])`
— full read for facts, user-visible text, security code and the first file of each new pattern; 1 in 5 of
repeated instances; skip generated outputs a checker validated. Visual output is always yours or the user's to
judge.

## 5. Fix-ups and the completion cascade

Cheap model first, escalate on evidence:
1. Checks fail → `delegate_resume(job, "<numbered fixes, with the failing output>")` returns a `send` text;
   SendMessage it to the **same worker** within ~5 minutes (its cache is still warm [ext]); verdict again.
2. Still failing, or BLOCKED for a judgment reason → re-tag the cluster: new `delegate_start` on `sonnet` with
   the verdict's findings in the brief.
3. Sonnet fails twice → `delegate_discard` what is worse than nothing, tell the user, do it yourself.
Each re-tag goes in the `--usage` log's cascade column, so the tiering in §1 gets better from real misses.
Haiku at low effort stops early or claims done without checking [ext]; the worker agent runs at medium effort
and must run its checks — a Haiku miss on a well-specified mechanical cluster is a brief problem first.

## 6. Session hygiene (cost)

- Plan in one session; dispatch from a small one (this skill + the plan file). `/clear` between unrelated
  phases; write the handoff into the project's STATE file. [ext; ours: a 540k context re-read ~315k per call]
- Don't switch model or effort mid-session — it drops the prompt cache. Neither do long idle gaps.
- Watch `orchestrator_calls` per job; a job above ~5 was probably cheaper done here.
- No polling loops: the completion notice (subagent) or the background `wait_cmd` (agy) wakes you once.

## 7. Finish

Workers commit nothing. Per cluster report what changed (`stat`), what you verified and how, rounds and worker
used, what is left. Commit only if the user asks and the repo's rules allow.

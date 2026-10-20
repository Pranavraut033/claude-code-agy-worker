---
name: agy
description: Run the Antigravity CLI (agy) as an agentic worker through the agy-worker MCP server — this session plans the work into multi-task work packages, briefs agy, hands the run to the user to watch, and reads one verdict (light audit; full audit on request). Opt-in, not a default: benchmarks show agy does not cut Claude tokens. Use when the user says /agy or "hand this to agy/Antigravity/Gemini", when Claude's usage limit is nearly spent, for long unattended runs (renders, build chains, test suites), or for volume too large for one Claude read (hundreds of files or pages). Not for work this session can just do, and not for decisions — those stay with this session.
---

# /agy — Claude briefs, agy works, the user watches, Claude checks the verdict

## Invocation

- **`/agy [task]`** — from here on, for every job in this session decide whether to hand it to agy by
  the rules below, and say in one line why or why not. Default to hand-off mode with checks (§4); the
  user watches the runs and reviews the diffs. Raise any `unattributed` files, denials or failed checks
  with the user before moving on. With a task, start on it.
- **`/agy --usage [folder]`** — all of the above, plus keep a usage log the user can hand back for
  review (format below). `folder` defaults to the repo root.

### `--usage` log format

Keep `AGY-LOG.md` in the folder; create it if missing, append if it exists, never rewrite old rows.

```
## Owner meter
| when | Claude 5-hour % | Claude weekly % |          ← ask the user before the first job and after the last

## Jobs                                                ← one row per job, done by agy or by you
| # | job id | task | done by | model | rounds | agy s | agy tokens | 5 h / weekly quota drop % |
  denials | state | clean | unattributed | Claude calls (prep / wait+audit) | checked on disk | fixes, by whom |

## Friction                                            ← one line per problem
- date | job id | permissions / verdict / report / brief / tool bug | what happened | cost (calls, minutes)
```

Take agy numbers from the verdict or `agy_status`, never from memory; rounds, agy seconds and agy tokens
are cumulative per job, so log the final values once. Jobs you did yourself get `done by: Claude`, the
reason in `task`, and `–` in the agy columns. Don't edit the log while an agy job is running (the scope
check would flag it); update it after each verdict.

## When to use agy at all

Five benchmarks (README): per fresh run agy never saved Claude tokens, and it is 10–35× slower.
Inside a session that has already loaded this skill and the agy tools (~20k, once), a hand-off job
added 0.15–0.67× the new tokens of doing the work (estimate, n = 1). Gemini quota is the cheap part.
So agy is **opt-in**: use it when the user asks, for several jobs in one session, when Claude's
usage limit is nearly spent (Gemini is a separate pool), for long unattended runs, or for volume
too large for one Claude read. Otherwise do the work yourself and say so in one line.

**Roles in a job.** This session plans, decides and writes the brief with machine checks; agy
does the mechanical work; the **user** watches the run and reviews the diff (hand-off mode,
§4); this session reads one verdict — a light audit — and reads diffs only when the verdict
flags something or the user asks for a full audit. If agy fails a package twice, report to the
user and ask before doing it yourself. Exception: files under `~/.claude/` (skills, MCP
servers, settings) — Claude Code's safety check blocks agy editing them, so the session
edits those itself.

agy edits **in place** (no worktree); the agy-worker server snapshots the tree first so
every change can be diffed and reverted. Tools: the agy-worker MCP server's `agy_*` tools (`mcp__agy-worker__…` when registered by hand, `mcp__plugin_agy-worker_agy-worker__…` from the plugin). Missing → the
server is not connected (check `/mcp`; the plugin's server needs `uv` on PATH).

**agy is an agent, not a sed.** Each job costs ~40 s of cold start plus a brief, and agy
can plan, read, edit, run checks and iterate on its own for an hour. Give it a *work
package*: a coherent chunk of a phase — several related tasks across many files, with
checks — not one file. A lone one-line change rides along in the next package.

**Too small for agy — do it directly.** A measured benchmark (3 small tasks, n=1): routing them
through agy cost **+21 % Claude tokens, ×2.4 cumulative input and ×13 wall time** for the same
quality, because orchestration takes ~11 tool calls (brief, permissions, wait, diff, checks,
cleanup) and the task alone took 2–5. The bare-agy rerun (benchmark 4, v0.4.1 verdict loop) still
cost 1.0–1.2× Claude tokens on a CSV feature, a 40-file migration and a 30-ticket judgment task:
Claude alone read all 30 tickets once and finished in 3 calls. So, before any `agy_start`:
- **Estimate the direct cost:** how many tool calls would this session need to just do it?
  Under ~10 (a rename, a few-file feature, a contained bug fix) → do it yourself, or hold it
  for the next package if one is coming soon anyway.
- **Use agy when** the work is many files or many steps (roughly 20+ direct tool calls), long
  research legwork, long-running commands (renders, test suites, downloads) that agy can sit on
  while this session does other work, or reading volume this session should not load into its
  own context.
- When a user rule says "agy does all mechanical work", still mention it when a task is below
  the line and say what you did.

## 1. Plan the work into packages

Before any brief, lay out the whole job (in the plan, not in agy's head):
- **Decide everything that needs judgment first** — content choices, naming, what goes
  where, which sources count. Bake the decisions into the brief; agy executes them.
- **Cut packages along file boundaries and dependencies.** A package = tasks that share
  context and files (e.g. "write all 12 fact records + the case file + run the verifier",
  "build beats.json from the approved script + lint it + fix lint"). Size: 10–60 min of
  agy time. Smaller wastes cold starts; larger gets hard to audit.
- **Parallel when independent:** packages touching disjoint files can run at once (separate
  `agy_start`s). Never two packages on the same files.
- **Sequential when dependent:** package 2 starts after package 1 is audited. If it builds
  on package 1's context, send it to the same job with `agy_resume`: every job is a **live agy
  session**, so the next message skips the cold start (~2–3 s turn overhead instead of ~25 s)
  and keeps the context. `agy_close(job)` when the session's work is audited.

## 2. Write the package brief

`agy_start(brief, cwd, allowed_files, model?, timeout_s=3600, network=False, checks=[…],
lend=[…], mcp=[…])`. The server
wraps the brief in a guard preamble (only allowed files, no git state changes, no
installs/deletes, network only if `network=True`, skip-and-report ambiguity, final report) —
don't repeat those. Structure the brief (one delimiter style: Markdown headings):

```
# Context        static facts first: what the project is, file formats, where examples live
# Goal           one paragraph: the end state of this package
# Tasks          numbered; each: files, exact change (before→after example if a pattern),
                 done-means, the check to run after it
# Order & checkpoints   which tasks depend on which; "after each task, run its check and
                 fix failures before moving on"
# If blocked     "skip that task, note why, continue with the rest"
# Report         per task: done / skipped (why) / check result; files changed
```

- **agy runs bare; you lend it what the job needs.** agy has no skills or MCP servers of its own
  (run `/agy-worker:agy-setup` once if `agy mcp list` shows any). `lend` inlines skills or
  instruction files into the brief: Claude skill names (`three-render`), `plugin:skill`, or a path to
  a `.md`/skill folder; default `["ponytail"]`, `lend=[]` for none (research jobs). Each lent skill
  costs its full text once per job, so lend only what this package uses. `mcp` lends Claude's MCP
  servers for this job only: `"server"` for all its tools, `"server/tool"` for one; they are removed
  again at `agy_close`/`agy_cancel`. Lend read-only servers; a lent server's tools run without asking.
  agy is repo-agnostic and gets no repo context by itself: lend it when the package needs it —
  `lend=["CLAUDE.md"]` for the whole repo guide, or better just the context doc it points to
  (`lend=["docs/context/render.md"]`; paths resolve from the repo root). Put any hard repo
  constraint the package must respect in the brief itself.
- **If `agy_start` returns `repo_agy_config`**, the repo has its own agy files (`GEMINI.md`, `.agents/…`)
  that agy loads into every job there; the job is not bare. Tell the user once; moving them is their call.
- **Make checks machine-readable, and hand them to the server.** Each task's check prints
  pass/fail (tests, a verifier, a lint, a tiny compare script). Pass the final ones as
  `agy_start(..., checks=["python3 -m unittest discover -s tests", …])`: the waiter runs them
  itself when agy finishes and puts every result in the verdict, so you spend no turns on
  them. They run as shell commands with *your* permissions (not agy's allow-list), in `cwd`.
  Design the check before the task.
- **Point at exact context** (paths, line ranges, an example record) so agy reads what it
  needs instead of exploring the repo.
- For research or long findings, name a report file in `allowed_files` and the brief; the
  guard tells agy to open it with a ≤10-line summary and keep its final message terse.
- `allowed_files`: every file or directory the package may touch — directories are fine
  for a package (`docs/records/`), list single files where scope is tight.
- Name every command the tasks need **as exact command lines**, and grant them first (§3).
  Commands that need an environment (a venv, `PATH`) must name it in the line itself
  (`.venv/bin/python3 tools/x.py`), because a rule cannot carry env vars.
- **Pre-flight before briefing:** run each generator, scorer or verifier the package depends on
  once against a sample item, and check that every numbers file the brief points at covers every
  table it asks agy to fill. Session logs: a conflicting scorer rule, a crashed generator and a
  fact sheet missing rows each cost a whole job.
- **Carry hard-won rules in the brief.** When a bug cost time, add a short "rules that cost
  hours" block (the trap, and what to do instead) to every later brief in that area; agy then
  does not repeat it. Give numbers, not adjectives ("labels ≥ 28 px tall at 720p", not "bigger").
- **Timebox fix-ups:** `timeout_s` ≈ 3× the work you expect (900–1200 s for a few narrow fixes);
  the guard already caps agy at 2 attempts per defect.
- Model: **read `references/models.md` first** — per model, how to prompt it, how long it
  takes, how it misbehaves; it grows as models change. Short version: Flash
  (`gemini-3.8-flash-medium`/`-high`) for well-specified packages; Argon
  (`gemini-4-argon-medium`) for research legwork, verification-heavy packages, or a package
  Flash failed — Argon's weekly quota is limited. After each notable package, add a row to
  that file's timing table; when a model surprises you, update it.
- **Quota:** `agy_usage()` (free, no model call) gives % left per pool — Gemini 5-hour and
  weekly, Argon weekly, Claude/GPT — and hours to each reset. Check it before choosing
  Argon or starting a package longer than ~20 min. Budget by what's left, not by habit:
  Argon only if its weekly pool covers the job *and* leaves a reserve for a Flash failure
  later in the week; a Gemini 5-hour pool near empty with a reset under ~1 h → do other
  orchestration work first. `agy_start` returns `quota_low` when a pool the model draws on
  is under 20%. For notable jobs, note the % drop (before/after) in the timing table.
- If other sessions edit this repo, say which paths the package owns while it runs.

## 3. Permissions (you maintain them)

Headless agy auto-allows file reads/writes but soft-denies any other tool not on its
allow-list (`~/.gemini/antigravity-cli/settings.json` → `permissions.allow`, via
`agy_permissions`). **A denial ends the round** (SUCCESS, empty report) — on a long package
that wastes everything after it, so grant every command and site the package needs before
starting. Rules are plain prefixes, `*` is literal: `command(python3 -m pytest)`,
`command(.venv/bin/python3 tools/verify.py)`, `read_url(https://archive.org/)`;
alternatives via `command(regex:npm run (build|lint))`. A read-only baseline (`ls`, `cat `,
`grep `, `git status`/`diff`/`log`/`show`, …) stays permanently. Never `command(*)`, a bare
interpreter, `rm`, `sleep`, `curl`, `git push`, package managers, or
`--dangerously-skip-permissions`. **Before `agy_start`, run `agy_permissions(check=[…])` on every
command line the brief names** — each piece of a pipe or `&&` chain needs its own rule, and a plain
rule matches whole words only (`--only=g` does not cover `--only=g07-…`; use the regex form for a
family). Remove one-off rules after the package. A denial ends only the current round; the
session survives. agy reads its rules only at startup, so after a denial (`denied` names the
command): audit what landed, grant the rule (or forbid the command), then `agy_resume` — it
restarts agy on the same conversation with the new rules, context kept (measured: 11.5 s).

## 4. The loop: hand-off, then one verdict

**Default: hand-off with a light audit.** `agy_start(…, checks=[…], handoff=True)`; give the
user the returned `watch_cmd` (a live view that ends with each check, `clean`, and the `git diff`
command to review); run `wait_cmd` in the background; when it wakes you, read the verdict and
report in ≤3 lines: **done or not** (`state`, `clean`, each check, `out_of_scope`, `denied`,
`unattributed`) and
**quality at a glance** from `sample` (one changed file's diff, ≤1,500 chars) — does it look like
the brief asked? **`unattributed` not empty** means files changed with no agy edit step: another
session, or agy ran code it wrote through an allowed command (it once hid a migration script in
`__init__.py` and ran it via the test runner). Say so to the user and read one of those files.
Read nothing else unless the verdict or the sample flags a problem. Then end
your turn; the agy session has already ended (`agy_resume` restarts it on the same conversation
if the user wants a fix-up). That is ~3 calls and one small read.

**Full audit only when the user asks** (or for factual/user-facing/security work, §5): drop
`handoff`, and audit per §5.

Three calls per package: `agy_start(…, checks=[…])`; run the returned `wait_cmd` as a
**background** shell task (Bash with `run_in_background: true`); read the verdict it prints.
The waiter blocks until the job leaves `running`, runs the checks, and prints one compact JSON
verdict; the harness wakes you once. Meanwhile do other work or end your turn — no `agy_wait`
loop, no polling. `agy_status` returns the last verdict again for a finished round. To let the
user watch live, give them `watch_cmd`.

The verdict has `state`, `elapsed_s`, `tokens`, `quota_drop_pct`, `report`, `edits`, `denied` (naming
the command), `out_of_scope`, `not_from_agy_edits`, `stat`, `sample` (one changed file's diff, capped), each check (`cmd`, `rc`, `ok`, last
400 chars) and `all_checks_pass`; **`clean`** is true when the round is done, nothing was denied
or out of scope, and every check passed. Intervene when it shows:
- `alert: edits outside allowed_files` (the waiter exits early with it) → `agy_cancel`, audit, decide;
- `stalled` (no event for 5 min) → `agy_cancel`, read `stderr`; Argon thinking quietly for a
  few minutes is normal, a Flash stall usually is not;
- the same defect failing a second time, or checks run again and again → cancel; if agy
  already failed it twice, fix it yourself (session logs: 56 agy-minutes on one label bug that
  took the orchestrator 5 minutes once it read the code);
- `failed` → read `stderr` (auth, 429/503, timeout) and retry once if transient; a quota
  or "AI credits balance is too low" error is not transient → `agy_usage()`, then switch
  model family or wait for the reset it shows.

## 5. Full audit (on request) — never trust agy's report

Audit in tiers — the expensive reading goes where errors would hurt:
1. **Mechanical gates (free, already in the verdict):** `out_of_scope` empty or justified
   (else `agy_discard(job, files=[…])`); `not_from_agy_edits` looked at before touching
   (other sessions edit the tree too); `denied` empty (a check that didn't run is
   **unverified**); `all_checks_pass`. Do not re-run the checks yourself — the verdict ran
   them. `clean: true` plus the `stat` line is enough to decide what to read next.
2. **Read `stat`, then diff selectively** with `agy_diff(job, files=[…])`:
   - **Full read:** anything factual (numbers, quotes, citations, dates), anything viewers
     or users see (scripts, titles, captions), security-relevant code, and the first file
     of every new pattern.
   - **Spot-check:** repeated instances of a pattern already verified once — read 1 in 5,
     plus any file whose size in `stat` looks off.
   - **Skip reading:** generated outputs a checker already validated (OCR json, logs) —
     trust the checker, not agy's word.
   - **Visual output is always yours to judge.** agy cannot see: it has called unreadable
     8 px labels, overlaps and oversized characters "verified", and once reported a fix done that
     the re-render showed still broken. Look at every contact sheet / frame yourself.
   - **A denial-ended or interrupted round has no report**, but its work may be complete
     (one job finished everything in 36 min, then died on a read-only check). Audit the diff and
     files before re-running anything.
3. **Long reports:** read the summary at the top; open the body only where the summary
   flags something or a claim is load-bearing.

## 6. Follow-up rounds: at most 2 per package

Problems → `agy_resume(job, message)` with numbered, specific fixes covering *all* findings
at once. After 2 rounds still wrong → `agy_discard` what is worse than nothing, report to
the user, ask before doing it yourself.

**Where agy has paid off in real use** (three session logs, 22 jobs): long packages that are mostly
waiting — sequential renders and build/install chains (a 37-min render package ran clean, two
orchestrator turns); applying a detailed spec to a large file (a 700-line scene built in 11 min);
record work with a machine check (28 JSON edits + verifier, clean). **Where it did not:** short edits,
re-runs and retiles (minutes by hand), small visual fixes, and anything whose command set was not
granted exactly.

## Token discipline (both sides)

- **This session:** every turn re-reads the whole conversation, so turns are the cost.
  Background waiter instead of wait loops; tiered audit; `agy_status` is compact by
  default (5 steps, relative paths, report truncated — `full_report=True` only when
  needed). One phase per session: when a phase ends, write the handoff into the project's
  STATE file (packages done, audit results, what's next) and suggest a fresh session for
  the next phase. Routine orchestration runs fine on Sonnet; tell the user when a phase
  is routine enough to switch — **at the start of a session, not in the middle**: the
  prompt cache is per model, so switching mid-session makes the next turn re-read the whole
  conversation uncached, and so does a long idle gap (past the cache lifetime). Server-run
  `checks` and the verdict are what keep a package at about three calls.
- **agy:** Flash by default (Argon used 5–10× the tokens per job); exact context paths so
  it doesn't explore; every needed command granted up front (a denial wastes the round);
  packages sized 10–60 min so cold starts and briefs amortise; send dependent packages and
  fix-ups to the same live session (no cold start, context cached).
- **Neither side** does work twice: the server runs the checks once and the verdict feeds your audit, your audit findings go
  into one consolidated fix-up message.

## 7. Finish

agy commits nothing. Report to the user per package: what changed (`stat`), what you
verified and how, rounds used, what is left. Commit only if the user asks and the repo's
rules allow.

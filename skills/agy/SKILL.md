---
name: agy
description: Run the Antigravity CLI (agy) as an agentic worker through the agy-worker MCP server — this session plans the work into multi-task work packages, briefs agy, monitors long runs (minutes to an hour), audits every package and steers follow-up rounds. Use when the user says /agy, "hand this to agy/Antigravity/Gemini", or wants a body of mechanical work done by agy — building or updating many files, scaffolding records, applying a spec across a codebase, research legwork (search, download, transcribe), multi-step pipelines with checks. Not for small tasks this session can finish in a handful of tool calls (agy costs more there — see "Too small for agy") and not for decisions — those stay with this session.
---

# /agy — Claude orchestrates, agy works, Claude audits

**Roles are fixed.** This session is the eyes and brain: it plans, splits work into
packages, writes briefs, monitors, audits and decides. agy is the hands and legs: every
mechanical step — editing code and files, writing records, scaffolding, running checks,
research legwork (searching, downloading, transcribing) — goes to agy, unless it is too small
for agy (below). The session does
not hand-edit files agy could edit and does not spawn Claude subagents for that work. It
still reads files and runs checks to audit. If agy fails a package twice, report to the
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
cleanup) and the task alone took 2–5. So, before any `agy_start`:
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
  directly on package 1's context, continue that conversation with `agy_resume` (a clean
  round only — never after a denial).

## 2. Write the package brief

`agy_start(brief, cwd, allowed_files, model?, timeout_s=3600, network=False)`. The server
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

- **Make checks machine-readable:** each task's check prints pass/fail (tests, a
  verifier, a lint, or a tiny compare script agy writes and runs). That is what keeps the
  audit cheap — design the check before the task.
- **Point at exact context** (paths, line ranges, an example record) so agy reads what it
  needs instead of exploring the repo.
- For research or long findings, name a report file in `allowed_files` and the brief; the
  guard tells agy to open it with a ≤10-line summary and keep its final message terse.
- `allowed_files`: every file or directory the package may touch — directories are fine
  for a package (`docs/records/`), list single files where scope is tight.
- Name every command the tasks need, and grant them first (§3).
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
`--dangerously-skip-permissions`. Remove one-off rules after the package. After a denial:
grant the rule (or forbid the action in the brief) and **start a new job** with the same
brief — `agy_status` shows a `hint`; resuming a denial-ended conversation has wedged.

## 4. Monitor a long run — without spending turns

Right after `agy_start`, run the `wait_cmd` string that `agy_start` returned as a background shell task (Bash with `run_in_background: true`).

It exits when the job leaves `running` (done, stalled, failed) and prints the compact
status; the harness wakes you once with that output. Meanwhile do other orchestration work
or end your turn — no `agy_wait` loop, no polling. Use `agy_wait`/`agy_status` only for a
single look when the user asks how it is going. To watch it themselves, give the user the
`wait_cmd` path with `watch <job>` instead of `wait <job>` (live step list in their own terminal). Intervene when the result shows:
- `alert: edits outside allowed_files` (the waiter exits early for this) → `agy_cancel`, audit, decide;
- `stalled` (no event for 5 min) → `agy_cancel`, read `stderr`; Argon thinking quietly for a
  few minutes is normal, a Flash stall usually is not;
- the same error repeats in its steps (looping) → cancel and re-brief;
- `failed` → read `stderr` (auth, 429/503, timeout) and retry once if transient; a quota
  or "AI credits balance is too low" error is not transient → `agy_usage()`, then switch
  model family or wait for the reset it shows.

## 5. Audit each package — never trust agy's report

Audit in tiers — the expensive reading goes where errors would hurt:
1. **Mechanical gates (cheap, always):** `agy_diff(job)` → `out_of_scope` empty or
   justified (else `agy_discard(job, files=[…])`); `not_from_agy_edits` checked before
   touching; `denied` empty (a check that didn't run is **unverified**). Re-run the
   package's checks yourself — they should print pass/fail, so you read one line.
2. **Read `stat`, then diff selectively** with `agy_diff(job, files=[…])`:
   - **Full read:** anything factual (numbers, quotes, citations, dates), anything viewers
     or users see (scripts, titles, captions), security-relevant code, and the first file
     of every new pattern.
   - **Spot-check:** repeated instances of a pattern already verified once — read 1 in 5,
     plus any file whose size in `stat` looks off.
   - **Skip reading:** generated outputs a checker already validated (OCR json, logs,
     renders) — trust the checker, not agy's word.
3. **Long reports:** read the summary at the top; open the body only where the summary
   flags something or a claim is load-bearing.

## 6. Follow-up rounds: at most 2 per package

Problems → `agy_resume(job, message)` with numbered, specific fixes covering *all* findings
at once. After 2 rounds still wrong → `agy_discard` what is worse than nothing, report to
the user, ask before doing it yourself.

## Token discipline (both sides)

- **This session:** every turn re-reads the whole conversation, so turns are the cost.
  Background waiter instead of wait loops; tiered audit; `agy_status` is compact by
  default (5 steps, relative paths, report truncated — `full_report=True` only when
  needed). One phase per session: when a phase ends, write the handoff into the project's
  STATE file (packages done, audit results, what's next) and suggest a fresh session for
  the next phase. Routine orchestration runs fine on Sonnet; tell the user when a phase
  is routine enough to switch.
- **agy:** Flash by default (Argon used 5–10× the tokens per job); exact context paths so
  it doesn't explore; every needed command granted up front (a denial wastes the round);
  packages sized 10–60 min so cold starts and briefs amortise; continue the conversation
  for a dependent package after a clean round (Gemini caches the context).
- **Neither side** does work twice: agy's checks feed your audit, your audit findings go
  into one consolidated fix-up message.

## 7. Finish

agy commits nothing. Report to the user per package: what changed (`stat`), what you
verified and how, rounds used, what is left. Commit only if the user asks and the repo's
rules allow.

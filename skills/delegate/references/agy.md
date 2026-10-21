# agy backend (Antigravity CLI, Gemini) — what differs from a subagent worker

Read this before any `delegate_start(backend="agy")`. Model-by-model notes, timings and the changelog are in
`models.md`.

## When agy, not a Claude subagent

- It draws on **Google's quota**, not Claude's: the reason to pick it when Claude's limit is nearly spent, or
  for a long unattended run (renders, build chains) the user wants off the Claude meter.
- It is **not cheaper in Claude tokens**: five benchmarks, 0.99–1.21× Claude tokens per fresh run at equal
  quality, 10–35× slower; inside a set-up session a hand-off job added 0.15–0.67× the new tokens of doing it
  directly (n = 1). Per token, Haiku 5.5 is now cheaper than Gemini 3.8 Flash at list prices.
- agy is an agent with ~40 s cold start: give it a package of 10–60 min of work, not one file.

## Running a job

`delegate_start(…, backend="agy", model="gemini-3.8-flash-medium", checks=[…], outputs=[…], handoff=True,
lend=[…], mcp=[…], timeout_s=3600, network=False)` launches agy and returns `wait_cmd` and `watch_cmd`.
- **Hand-off (default):** give the user `watch_cmd` (a live view ending with each check, `clean` and the
  `git diff` command); run `wait_cmd` as a **background** Bash task; it wakes you once with the verdict. The
  agy session ends by itself after the round (`delegate_resume` restarts it on the same conversation).
- Without `handoff` the session stays live: `delegate_resume(job, message)` sends the next package or a fix-up
  in ~2–3 s with the context kept; `delegate_close(job)` when done. Dependent packages go to the same job.
- `delegate_verdict(job)` gives the same verdict when you already know the job finished.
- **Bare agy:** it has no skills or MCP servers of its own (`/delegate:agy-setup` once if `agy mcp list` shows
  any). `lend` inlines skills; `mcp` lends Claude's MCP servers for this job only (`"server"` or
  `"server/tool"`), released at `delegate_close`/`delegate_cancel`. If `delegate_start` returns
  `repo_agy_config`, the repo's own `GEMINI.md`/`.agents/` load into every job there; tell the user once.

## Permissions (you maintain them)

Headless agy auto-allows file reads and writes but denies any other tool not on its allow-list
(`~/.gemini/antigravity-cli/settings.json` → `permissions.allow`, via `delegate_permissions`). **A denial ends
the round** (SUCCESS, empty report), unlike a subagent worker. Grant every command and site a package needs
before starting.
- Rules are plain word prefixes, `*` is literal: `command(python3 -m pytest)`,
  `command(.venv/bin/python3 tools/verify.py)`, `read_url(https://archive.org/)`; alternatives via
  `command(regex:npm run (build|lint))` (the regex must match the whole piece).
- **Before `delegate_start`, run `delegate_permissions(check=[…])` on every command line the brief names**:
  each piece of a pipe or `&&` chain needs its own rule; `--only=g` does not cover `--only=g07`. For `cp`,
  grant the literal full command line.
- A read-only baseline (`ls`, `cat `, `grep `, `git status|diff|log|show`) stays permanently. Never
  `command(*)`, a bare interpreter, `rm`, `sleep`, `curl`, `git push`, package managers, or
  `--dangerously-skip-permissions`. Remove one-off rules after the package. The list is global (shared by
  every project).
- agy reads its rules only at startup: after a denial, audit what landed, grant the rule (or forbid the
  command), then `delegate_resume` — it restarts agy on the same conversation with the new rules (11.5 s).

## Models and quota

- Flash (`gemini-3.8-flash-medium` / `-high`) for well-specified packages; Argon (`gemini-4-argon-medium`)
  for research legwork or a package Flash failed — it used 5–10× the tokens per job and its weekly pool is small.
- `delegate_usage()` (free, no model call): % left per pool (Gemini 5-hour and weekly, Argon weekly,
  Claude/GPT) and hours to each reset. Check it before Argon or a package longer than ~20 min.
  `delegate_start` returns `quota_low` when a pool the model draws on is under 20%.

## Intervene when the verdict or status shows

- `alert: edits outside allowed_files` (the waiter exits early with it) → `delegate_cancel`, audit, decide;
- `stalled` (no event for 5 min) → cancel, read `stderr`; Argon thinking quietly for minutes is normal;
- the same defect failing a second time → cancel; fix it yourself (one label bug cost 56 agy-minutes);
- `failed` → read `stderr` (auth, 429/503, timeout); retry once if transient; a quota or "credits too low"
  error is not transient. `failed` with a full report and passing checks was a trailing 503: the checks decide.
- A denial-ended round has no report, but its work may be complete: audit the diff before re-running.

## Where agy paid off in real use

Long packages that are mostly waiting — sequential renders and build/install chains (a 37-min render package
ran clean in two orchestrator turns); applying a detailed spec to a large file; record work with a machine
check. Where it did not: short edits, re-runs, small visual fixes, and anything whose commands were not
granted exactly. Gemini side-tracks (reads unrelated files, diagnoses a failing tool instead of taking the
shortest path): the guard says to stay on the task; brief with exact paths.

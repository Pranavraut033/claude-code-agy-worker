# How agy-worker came to be (and what we learned)

This is the build log behind the plugin: what we wanted, what we decided and why, what broke, and
what the measurements said. It is written for anyone thinking about pairing Claude Code with a
second coding agent. All of it happened on 2026-10-19, with Claude Code (Opus) as one side of the
conversation and the repo owner as the other.

## 1. The idea

Claude Code is good at judgment: planning, deciding, reviewing. The Antigravity CLI (`agy`, Google's
agentic CLI running Gemini models) is good at grinding through mechanical work, and it bills
against a different quota. The hope was simple: let Claude be the eyes and brain, let agy be the
hands and legs, and spend fewer Claude tokens for the same result.

The owner's constraints, decided up front:

- agy edits files **in place** — no git worktrees.
- Safety lives in the **prompt** (a guard preamble) plus agy's own permission allow-list, which
  Claude maintains. No `--dangerously-skip-permissions`, ever.
- At most **1–2 fix-up rounds** per piece of work; then a human decides.
- It must work in **every repo**, so it is an MCP server plus a skill, not project code.

We looked at existing Claude↔Gemini bridges first. Most were thin wrappers that send one prompt and
return text. None snapshotted the working tree, checked scope, or treated the worker's output as
something to audit, so we built our own and borrowed the good ideas (background jobs, stream-json
parsing).

## 2. Design decisions, and why

| Decision | Why |
|---|---|
| Snapshot the tree before each job with a throwaway `GIT_INDEX_FILE` + `git write-tree` | Diff and revert work without touching HEAD, the branch, or the user's index — other sessions may be editing the same repo. |
| `agy_diff` reports `out_of_scope` and `not_from_agy_edits` | The guard is a prompt, not a sandbox, so scope has to be checked after the fact. The second list catches edits made by someone else (or by agy through a shell command). |
| `--mode accept-edits` + an allow-list Claude maintains | `--mode auto` was not available on the account; accept-edits auto-allows file edits and denies any command not on the list. |
| Work **packages**, not single edits | Each agy job pays ~40 s cold start plus a brief. A package of related tasks with a check after each amortises that. |
| A background **waiter** (`server.py wait`) instead of polling | Every Claude turn re-reads the whole conversation; a poll loop multiplies that. The waiter wakes Claude once. |
| **Tiered audit** | Full reads only for facts, user-facing text, security-relevant code and the first file of a pattern; spot checks for repeats; trust checkers for generated output. |
| Compact `agy_status` (5 steps, relative paths, truncated report) | Same reason: tokens on the Claude side. |
| `agy_usage` (reads `agy -p "/usage"`) | Free quota check, so Claude can budget the scarce model (Gemini 4 Argon has a small weekly pool). |
| A growing per-model guide (`skills/agy/references/models.md`) | Models behave differently and new ones keep arriving; observations beat docs when they disagree. |

## 3. What broke, in the order we hit it

1. **`--mode auto` unavailable** → accept-edits plus a Claude-maintained allow-list.
2. **A pid of -1** in the self-test made `os.kill(-1, 0)` succeed, so every job looked alive.
   Guard `pid <= 0`.
3. **Symlinks** (`/var` vs `/private/var`, a repo symlinked from an external drive) produced false
   "out of scope" flags → `realpath` everything.
4. **Permission rules are plain prefixes.** `command(python3 *)` never matched; `*` is literal.
   A regex form exists: `command(regex:npm run (build|lint))`.
5. **Any denied command ends the whole round** — status SUCCESS, empty report. The docs say a
   soft-denied run continues; it did not, in every case we saw. This one cost the most: one
   improvised `ls -la` or `sleep` killed a 10-minute package. Fixes: a read-only baseline
   allow-list, "run only: …" in every brief, and a `hint` in `agy_status`.
6. **Resuming after a denial wedged** the conversation (0 tool calls, ~40k output tokens). Rule:
   start a fresh job instead.
7. **The MCP server did not load in the desktop app.** It reads `~/.claude.json`; the CLI's
   `claude mcp add` had written a different file. (Shipping as a plugin made this go away.)
8. **Claude Code's safety check blocks agy editing files under `~/.claude/`** (self-modification).
   Not worked around: Claude edits its own config itself.
9. **A site returned 429** to a browser-like User-Agent in a download script → honest bot UA.
10. **False "stalled"** while agy ran a single long command (a 10-minute render emits no events) →
    an ACTIVE `run_command` counts as running.
11. **agy's process can outlive its final result** → job state comes from the result event, not
    from whether the process is alive.
12. **Flash finishes packages with a `grep | awk` check** that isn't allow-listed → "no pipes" in
    the brief.

## 4. Then we measured — and it did not save tokens

The owner asked the obvious question: *how much Claude usage does this actually save?* We had only
agy-side logs, so we ran two benchmarks (both in [`benchmarks/`](../benchmarks/), reproducible):
same task text for both arms, hidden checks written before any run, Sonnet subagents for both arms,
`gemini-3.8-flash-medium` for agy.

| Benchmark | Claude alone | Claude + agy | Wall time | Quality |
|---|---|---|---|---|
| 1 — three small tasks (rename, spec feature, 3-bug fix) | 264k tokens | 319k (+21 %) | 40 s → 536 s | 15/15 checks, both |
| 2 — 40-file API migration + type hints | 91k | 107k (+17 %) | 38 s → 1,050 s | 6/6 checks, 314/314 hints, both |

Why: orchestration has a roughly fixed cost (~100–110k tokens, ~11–12 tool calls: read the skill,
grant permissions, brief, wait, diff, run checks, clean up), while Claude doing the job alone took
only 2–7 tool calls. In benchmark 2 Claude wrote one 49-line script and migrated all 40 files at once.
That benchmark was also weaker than planned: the generated fixture reused only 14 function names, so
the "needs reading every file" part turned out scriptable.

Quality was identical in all 8 runs: no defects, no fix-up rounds needed.

## 5. What we believe now

- **On work Claude can script, agy costs more Claude tokens, not fewer**, and is 13–28× slower.
- The skill now has a **"too small for agy" rule**: estimate the direct cost first; under ~10 tool
  calls, do it directly.
- **Still untested, and the most plausible wins:** research and reading-heavy work (agy reads
  hundreds of pages, Claude reads a 10-line summary), work that needs per-file judgment and cannot be
  scripted, and long-running jobs agy can sit on while Claude does something else.
- **Research still needs an audit**, just a cheap one: agy's first research report contained two
  load-bearing errors (wrong permission syntax; repeating the docs' wrong claim about denials).
  Require a URL per claim and spot-check only the claims you will act on.

## 6. Ideas for making the Claude side cheaper (open)

- **Batch** many tasks into one package and one orchestration, so the fixed cost is paid once
  (the same insight as "plan and delegate" patterns: group into clusters, not tasks).
- **A cheap babysitter:** plan and final audit on the strongest model; start/wait/check on Haiku.
- **A leaner orchestrator process:** most of a Claude subagent's ~85k starting context is fixed
  baseline (system prompt, tool schemas, project instructions); a headless run with only the agy
  tools would start much smaller.
- **One blocking `agy_run` call** (start + wait + diff stat + checks) to cut turns.
- A sourced research report on documented levers is being written to `docs/research/`.

## 7. Help wanted

If you get different numbers — another task type, another model, a cheaper orchestration pattern —
please open an issue with your `RESULTS.md`. The benchmarks are small on purpose so they are cheap to
rerun: the fixture generator, task texts, hidden checks and measurement method are all in
[`benchmarks/`](../benchmarks/).

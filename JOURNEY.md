# The journey: building agy-worker, and finding out whether it pays

This is the build log and the thinking behind it — what we set out to do, what we decided and why,
what broke, and what the measurements actually said. It is written for anyone trying the same idea
(a smart, expensive model directing a cheaper agent), so the dead ends are left in.

**Short version:** the plumbing works well — snapshots, audits, allow-lists, a live view, quota
checks. But in every benchmark so far, routing work through agy **cost more Claude tokens than
letting Claude do it**, at equal quality. The places where it might still win are work Claude
cannot script and reading-heavy research. We have not proven either yet.

---

## 1. The idea

Claude Code is very good at judgment: planning, spotting a wrong number, deciding what "done"
means. A lot of real work is not judgment, though — renaming across forty files, filling records from
a template, downloading and transcribing sources. The Antigravity CLI (`agy`, Gemini models) has
its own quota on a separate plan. So:

> **Claude is the eyes and brain. agy is the hands and legs.** Claude plans, briefs, monitors and
> audits; agy edits files, runs checks and does research legwork.

The hoped-for payoff: spend less of the Claude usage limit, keep quality, because Claude still
reviews everything.

We looked at existing Claude↔Gemini bridges first. Most were thin wrappers that send one prompt and
return text. None snapshotted the working tree, checked scope, or treated the worker's output as
something to audit — so we built our own, borrowing the good ideas (background jobs, stream-json
parsing).

## 2. Design decisions (and why)

| Decision | Why |
|---|---|
| **agy edits in place, no worktrees** | Simpler, and other sessions can see the work. Safety comes from a snapshot instead. |
| **Pre-job snapshot through a throwaway `GIT_INDEX_FILE` + `git write-tree`** | Captures the whole working tree as a git tree object without touching `HEAD`, the branch or the real index. `agy_diff` and `agy_discard` work against it, even with other sessions editing the same repo. |
| **Guards live in the prompt** | A preamble limits agy to `allowed_files`, forbids state-changing git, installs and deletes, and asks for a terse per-task report. Out-of-scope edits are still *detected* by the diff, not just forbidden. |
| **`--mode accept-edits` + an allow-list Claude maintains** | `--mode auto` was not available on our plan; `--dangerously-skip-permissions` was never an option. Claude grants exactly the commands and sites a package needs, and removes one-off rules after. |
| **At most 2 fix-up rounds per package** | After two rounds, it is cheaper to report and decide than to keep steering. |
| **An MCP server + a skill, shipped as a plugin** | The server is the hands on the controls (start, status, diff, discard, permissions, quota); the skill is the playbook Claude follows. One plugin install gets both. |

## 3. What headless agy taught us (the hard way)

- **Any denied command ends the whole round.** The docs say a soft-denied tool lets the run
  continue; in practice the round stops with `SUCCESS` and an empty report. One improvised `ls -la`
  could waste a 30-minute package.
- **Resuming after a denial wedged** once: zero tool calls, ~40k output tokens. Rule: after a
  denial, grant the rule and start a *fresh* job.
- **Permission rules are plain prefixes.** `command(python3 *)` does not work — `*` is literal.
  `command(git diff)` does; so does the regex form `command(regex:npm run (build|lint))`.
- **Flash improvises shell commands** (`ls`, `python3 -c`, `sleep`, `grep … | awk`) even when told not
  to. Fix: a permanent read-only baseline allow-list, plus "run only: …, no pipes" in every brief.
- **The agy process can outlive its result**, and a long command emits no events for minutes. Both
  made jobs look "stalled". Job state now comes from the final `result` event, and an `ACTIVE`
  command counts as running.
- **`agy -p "/usage"` shows quota for free** (no model call): Gemini 5-hour and weekly pools, a
  separate weekly pool for Gemini 4 Argon, and reset times.
- **Claude Code refuses to let agy edit files under `~/.claude/`** (self-modification guard), so the
  skill and server themselves are always edited by Claude.
- **Some sites block browser-like User-Agents.** Wikimedia returned 429 until the downloader used an
  honest bot UA.

## 4. Making the Claude side cheap

Every Claude turn re-reads the whole conversation, so *turns* are the cost. We added:

- **Work packages, not edits** — 10–60 minutes of agy time per brief, so the ~40 s cold start and the
  brief are paid once for many tasks.
- **A background waiter** (`server.py wait <job>`) instead of polling: Claude is woken once, when the
  job ends or goes out of scope.
- **Compact status** (last 5 steps, relative paths, truncated report) and **tiered audits**:
  mechanical gates first (scope, denials, checks), full reads only for facts, user-facing text,
  security code and the first file of each pattern.

We expected this to make orchestration cheaper than doing the work. Then we measured.

## 5. Measuring it

Same task text for both arms, hidden acceptance checks written before any run, Sonnet subagents
on both sides, Flash as agy's model. Full plans, fixtures, checks and raw numbers are in
[`benchmarks/`](benchmarks/).

**Benchmark 1 — three small tasks** (rename, a CSV feature from a spec, three planted bugs):

| | Claude alone | Claude + agy |
|---|---|---|
| Claude tokens | 264k | 319k (**+21 %**) |
| Wall time | 40 s | 536 s |
| Hidden checks | 15/15 | 15/15 |

**Benchmark 2 — a "large" package** (migrate 40 handler files to a new API with type hints):

| | Claude alone | Claude + agy |
|---|---|---|
| Claude tokens | 91k | 107k (**+17 %**) |
| Wall time | 38 s | 1,050 s |
| Hidden checks / type hints | 6/6, 314/314 | 6/6, 314/314 |

What happened in benchmark 2 is the most instructive part: Claude alone **wrote one regex script
and finished in 7 tool calls**. The generated fixture reused only 14 function names, so a hand-built
14-entry type table covered all 107 functions. The task we designed to need per-file reading was
scriptable after all — a flaw in our fixture, and also a real lesson: *Claude is very cheap at
anything it can script.*

What the numbers say together:

- **Quality was identical** in all 8 runs — 0 defects, 0 fix-up rounds.
- **Orchestration has a roughly fixed cost** of ~100–115k Claude tokens per package (brief,
  permissions, wait, diff, checks), while a Claude subagent that just does a scriptable job costs
  ~85–95k. Most of either number is the *baseline* every Claude Code subagent starts with.
- **agy is much slower** (×13 to ×28 wall time) and spent 276k and 615k Gemini tokens.

So we added a **"too small for agy"** rule to the skill: if Claude would need fewer than ~10 tool
calls, it does the work itself.

## 6. Where the savings might really be

We asked agy to research cheaper orchestration (report: [`docs/research/cheaper-orchestration.md`](docs/research/cheaper-orchestration.md)).
We verified the flags it names against `claude --help`; community claims in it are marked as such
(its summary overstates a "60 % coordination penalty" that comes from a community site, not docs).

The levers that look most promising:

1. **A lean orchestrator.** `claude -p --bare --tools … --strict-mcp-config --mcp-config agy.json`
   (or the Agent SDK with only the agy tools) skips CLAUDE.md, memory, skills, plugins and unused
   tool definitions. If most of the ~100k is baseline, this attacks the real cost.
2. **A cheap model for babysitting.** Once the plan and brief exist, starting a job, waiting and
   running checks is mechanical — Haiku can do it; the strong model returns only to audit.
3. **Batching** (from Claude Code's plan-and-delegate pattern): pay the fixed cost once for several
   tasks, and point workers at a shared plan file instead of repeating context.
4. **Checks without model turns** — hooks or the server itself running the package's tests and
   returning one pass/fail line.

And the task types still untested, where agy's design should fit best:

- work Claude **cannot** script: per-file judgment across many varied inputs;
- **reading-heavy research**, where agy reads hundreds of pages and Claude reads a summary (still
  spot-checked — agy's first research report had two load-bearing errors).

## 7. Principles we ended up with

- **Measure before claiming.** Our intuition ("offloading saves tokens") was wrong twice.
- **Never trust a worker's report** — code or research. Audit in tiers; check the claims you act on.
- **Small work stays with Claude.** Orchestration has a floor cost.
- **Every denial is expensive**; grant up front, keep the allow-list narrow, clean up after.
- **Write down what surprised you** — [`skills/agy/references/models.md`](skills/agy/references/models.md)
  is a growing per-model log of timings and quirks.

## 8. Help wanted

If you have run a Claude-orchestrates-a-cheaper-agent setup and found it **does** save tokens,
we would love to know what was different: task type, orchestrator setup, model, numbers. Issues
and PRs with benchmark results (use the harness in [`benchmarks/`](benchmarks/)) are very welcome.

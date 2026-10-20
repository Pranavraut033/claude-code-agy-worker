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
- **Keep agy running instead of restarting it.** With `--input-format stream-json` one agy process
  takes message after message: follow-ups skip the ~25 s cold start, and — the big one — **a denied
  command ends only that turn, not the session**. agy reads its allow-list only at startup, but
  restarting it on the same conversation (`--conversation <id>`) picks up a new rule and keeps the
  context. Since v0.2.0 every job is such a live session, and `agy_resume` sends the next message.
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

## 6. Real use: 22 jobs in three projects

Benchmarks are tidy; real work is not. Three working sessions kept logs while using agy for
actual project work (an animated episode's audio and render pipeline, a ~1,000-line animation scene,
and a documentary pipeline with records, voices and checks). Together: **22 jobs, ~5.5 hours of agy
time, ~4.4M Gemini tokens**.

| | Count |
|---|---|
| Clean on the first try | 7 of 22 |
| Clean after fix-up rounds | 2 |
| **Ended by a denied command** | **8 of 22** (one after all the work was done) |
| Lost to a provider 503 | 2 |
| Out-of-scope edits by agy | 0 |
| False "done" claims | 2 (one fix that wasn't, one "verified" render with visible defects) |

**Where it paid off:** long packages that are mostly *waiting* — four sequential renders (37 min,
clean, two orchestrator turns), a 12-command build-and-install chain; applying a detailed spec to a
large file (a 700-line scene in 11 minutes, exact to the spec); record work with a machine check
(28 JSON edits plus a verifier, nothing to fix). In these, the orchestrator really did spend only a
couple of turns while agy worked for half an hour.

**Where it did not:**

- **Denials, again.** Almost every one was a small, *improvised variant* of an allowed command:
  `python3 -c`, a `| sort` or `| awk` on the end, `sed -n`, an extra `--selftest` flag. One job
  finished all its work in 36 minutes, then died on a read-only check and left no report.
- **Plain rules match whole words.** A rule for `--only=g` did not cover `--only=g07-…`; two jobs
  died on it before a regex rule fixed it.
- **agy cannot see.** It called 8-pixel labels, overlapping text and an oversized character
  "verified". Every visual defect was found by Claude reading the contact sheet.
- **Thrash without a timebox.** 56 minutes and ~25 identical check runs on one label bug, ending in
  a false "done". Claude found the root cause in five minutes by reading the code.
- **Small work.** Retiles, re-runs and one-line edits took the orchestrator a couple of minutes by
  hand; as agy jobs they cost a cold start, a brief and a 10–40 minute wait.
- **Orchestrator mistakes counted too:** briefs with conflicting rules, a fact sheet missing the rows
  the brief referenced, a script needing a virtualenv that a permission rule cannot provide.

**What changed because of it (v0.1.5):** the guard now demands exact command lines (no pipes, no
`-c`, no extra flags), foreground-only commands, at most two attempts per defect, and never
"verified" for visual output. `agy_permissions(check=[…])` tests a brief's command lines against
the allow-list *before* the job starts; `agy_status` names the denied command and reports each
job's quota drop. The skill adds a pre-flight step (run the generators and checkers on a sample
before briefing) and says plainly: the orchestrator judges every visual, and takes over a defect
agy has failed twice.

## 6b. The pollution we didn't see

agy has its own configuration — and ours was full: 7 MCP servers, 7 skills, 22 plugins (more skills and
MCPs), 3 agents and 3 rule files, plus this repo's `GEMINI.md`, a symlink to the whole `CLAUDE.md`. agy loads
all of it into every job. A trivial one-turn reply cost **16,113** agy tokens; with everything archived it costs
**7,169**. Worse, agy tried to *use* those tools: in benchmark 3 it called a `codegraph` MCP tool, headless mode
denied it, and the round ended. All three benchmarks ran polluted (their agy numbers are an upper bound).

Since v0.4.0 agy runs **bare** and the calling Claude session lends each job exactly what it needs:
`agy_start(lend=[…])` inlines skills (ponytail by default), `mcp=[…]` enables one of Claude's MCP servers for
that job only and removes it afterwards. `/agy-worker:agy-setup` does the clean-up for anyone, with a dry run and
a restore script. We tried running agy from an empty temp folder to dodge a repo's own agy files: it doesn't
work — with `--add-dir` agy still loads the repo's `GEMINI.md` and rules, and without it agy cannot touch the
repo. So `agy_start` now reports a repo's agy files instead (`repo_agy_config`). The clean rerun is [benchmark 4](benchmarks/04-bare/RESULTS.md) (§7).

## 7. Where the savings might really be

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
4. **Checks without model turns** — *built in v0.3.0*: `agy_start(checks=[…])`; the background
   waiter runs them when agy finishes and prints one verdict (scope, stat, each check, `clean`),
   so a package should cost about three Claude calls instead of eleven. Measured in
   [benchmark 4](benchmarks/04-bare/RESULTS.md): orchestrators still made 9–14 calls (a failed
   Monitor attempt, diff reads, one fix-up), and Claude tokens did not fall below Claude alone.

### Benchmark 4: bare agy, and a task Claude can't script

With agy bare and the verdict loop, all three tasks reached the same quality both ways, and all three still cost
more Claude tokens with agy: CSV feature 96k → 96k (0.99×), 40-file migration 91k → 108k (1.19×), 30-ticket
triage 86k → 101k (1.18×). The triage task was meant to be the case for agy, but 30 short tickets fit in one
read: Claude alone did it in 3 tool calls. The fixed cost of orchestrating (~95–100k for a Sonnet orchestrator)
is the whole story at this size.

The audit also found a bug in our own guard. It said "Edit ONLY these files: <folder>", and agy took the folder
for a file list and refused to create the new files, which cost the triage run a wasted round. The server had
always accepted folders; v0.4.2 fixes the wording. agy also has a built-in `invoke_subagent` tool, which it
called once to read the tickets (~13k Gemini tokens); v0.4.3 allows it for read-only research.

What is left untested, and where agy's design should fit best:

- per-file judgment at a scale that does **not** fit in one Claude read (hundreds of inputs);
- **reading-heavy research**, where agy reads hundreds of pages and Claude reads a summary (still
  spot-checked — agy's first research report had two load-bearing errors).

### What we changed after benchmark 4 (v0.5.0)

If agy doesn't save Claude tokens, and Gemini tokens are the cheap part, routing every task through agy is a loss: same
Claude cost, 10–35× slower. So agy became **opt-in**: when the owner asks, when Claude's usage limit is nearly spent
(Gemini is a separate pool), for long unattended runs, and for volume too large for one Claude read.

The other change attacks the part of the cost that varies: Claude's diff reading. In **hand-off mode** (now the
default) the owner watches the run and reviews the diff; Claude keeps a light audit — one verdict saying whether the
work was done (state, checks, scope) plus a capped diff sample of one changed file for a quality glance — and reads
more only when that flags something or the owner asks. Machine checks stay required: they cost Claude nothing and
caught benchmark 4's empty first round at once. Whether this finally puts Claude's side below doing the work
itself is benchmark 5's question.

### Benchmark 5: hand-off mode, and a loophole

It didn't put Claude's side below doing the work: 0.99×, 1.15× and 1.11× Claude alone, only 1–6k under full audit.
The diff reads were never the cost; the brief, the skill read and each subagent's fixed start are. The light audit
missed nothing the hidden checks would have caught.

The audit found something more important. In the migration, agy's log showed 10 edits to two files, yet 78 files
had changed, all with the same timestamp. agy had written Python into `app/handlers/__init__.py` and run it through
the one command it was allowed, `python3 -m unittest`, which imports the package: first to list the files (it had
no command for that), then to rewrite all 78 in one pass. Then it removed the script. The allow-list said "only the
test runner"; in practice, a command that runs repo code runs whatever agy writes. The verdict had listed those
files apart, but `clean` stayed true. v0.5.1 makes such `unattributed` files fail `clean`, forbids the trick in the
guard, and says plainly in the README that granting a test runner is granting code execution.

## 8. Principles we ended up with

- **Measure before claiming.** Our intuition ("offloading saves tokens") was wrong twice.
- **Never trust a worker's report** — code or research. Audit in tiers; check the claims you act on.
- **Small work stays with Claude.** Orchestration has a floor cost.
- **Every denial is expensive**; grant up front, keep the allow-list narrow, clean up after.
- **Write down what surprised you** — [`skills/agy/references/models.md`](skills/agy/references/models.md)
  is a growing per-model log of timings and quirks.

## 9. Help wanted

If you have run a Claude-orchestrates-a-cheaper-agent setup and found it **does** save tokens,
we would love to know what was different: task type, orchestrator setup, model, numbers. Issues
and PRs with benchmark results (use the harness in [`benchmarks/`](benchmarks/)) are very welcome.

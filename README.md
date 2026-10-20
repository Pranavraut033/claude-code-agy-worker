<div align="center">

# 🤖 agy-worker

**Claude Code briefs. Antigravity does the work. You watch; Claude checks the verdict.**

A Claude Code plugin that hands long, multi-task work packages to the Antigravity CLI (`agy`) and audits every change it makes.

![version](https://img.shields.io/badge/version-0.5.3-blue) [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE) ![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-D97757?logo=anthropic&logoColor=white) ![Antigravity CLI](https://img.shields.io/badge/Antigravity_CLI-1.4.3-4285F4?logo=google&logoColor=white) ![MCP](https://img.shields.io/badge/MCP-server-8A2BE2) ![python](https://img.shields.io/badge/python-3.10%2B_·_uv-3776AB?logo=python&logoColor=white) ![platform](https://img.shields.io/badge/tested_on-macOS-lightgrey?logo=apple)

**📖 New here? Read [the journey](JOURNEY.md)** — why we built this, what broke, and what the benchmarks really showed.

</div>

## ⚡ How it works

Claude Code plans a work package, writes the brief and machine checks, and starts it. By default it then **hands off**: you follow the run live with `watch`, which ends with each check, `clean`, and the diff command; Claude reads one verdict (done or not, checks, scope, plus a short diff sample) as a light audit. A full diff audit by Claude happens only when you ask. agy runs headlessly in place.

**Opt-in.** Per fresh run, five benchmarks found no Claude-token saving; within a session that has already loaded the skill, a hand-off job adds 0.15–0.67× the new tokens of doing the work (see [Benchmark](#-benchmark)). Use agy when Claude's usage limit is nearly spent (Gemini is a separate pool), for long unattended runs, or for volume too large for one Claude read.

```mermaid
sequenceDiagram
    participant You
    participant Claude as Claude Code (orchestrator)
    participant W as agy-worker
    participant A as agy (Gemini)
    Claude->>W: agy_start(brief, allowed_files, checks, handoff)
    W->>W: git snapshot (HEAD & index untouched)
    W->>A: launch headless, accept-edits
    A->>A: edit files, run checks
    W->>W: waiter runs the checks
    W-->>Claude: one verdict: done?, checks, scope, diff sample
    W-->>You: watch: live steps, checks, clean, git diff
    Claude->>W: agy_diff — full audit, only on request
    Claude->>A: agy_resume — next message, same live session
    Claude->>W: agy_discard — revert anything bad (optional)
```

## ✨ Why

- **Long work packages, not one-line edits**: Sized for 10–60 minutes of worker runtime so startup overhead is amortised effectively across multiple tasks.
- **In-place edits with snapshot diff/revert**: Works directly in the repository without isolated git worktrees, protected by an independent git snapshot.
- **Clear division of labor**: Claude keeps the judgment, architecture, and auditing; agy does the mechanical work.
- **Lean on Claude's side**: hand-off mode leaves the diff review to you, and server-run checks plus one verdict keep Claude at about three calls per package. Still not cheaper than Claude doing small or scriptable work itself (see [Benchmark](#-benchmark)).

## 🚀 Quick start

**Requirements**: Claude Code, `agy` signed in (check with `agy models`), `uv` on `PATH`, git repo for diff/revert.

In Claude Code, run:

```text
/plugin marketplace add Pranavraut033/claude-code-agy-worker
/plugin install agy-worker@agy-worker
```

Restart Claude Code; `/mcp` should list agy-worker.

**First time:** run `/agy-worker:agy-setup`. It makes agy bare: agy's own MCP servers, skills, plugins and agents move to `~/Documents/agy-config-archive-<date>/` (with `restore.sh`), your rules stay, and the read-only allow-list baseline is added. It shows a dry run and asks first. From then on, the calling Claude session lends each job exactly the skills (`lend=[…]`, ponytail by default) and MCP servers (`mcp=[…]`) it needs.

Then, at the start of a session or in the middle of one:

```text
/agy-worker:agy [task]
```

From then on Claude decides per job whether to hand it to agy, says in one line why or why not, and runs agy jobs in hand-off mode with checks: you watch the run and review the diff, and Claude reads the verdict. Or just ask:

> hand this to agy: add type hints to every function in src/ and make mypy pass

**Track the usage:** `/agy-worker:agy --usage [folder]` does the same and keeps `AGY-LOG.md` (in the repo root unless you name a folder). The log has one row per job (agy's tokens, time, rounds and verdict, plus Claude's tool calls), your Claude usage % before and after, and one line per problem met. Share it in an issue if you'd like to help measure where agy saves Claude usage.

**Watch a job live** in any terminal (newest job if you leave out the id):

```bash
uv run --script ~/.claude/plugins/cache/agy-worker/agy-worker/<version>/server/server.py watch [job]
```

A header panel, one line per step with an icon (📄 read · ✎ edit · ▶ command · 🔎 search · 🌐 page · ✗ error), a spinner on the step in progress, then a result panel with tokens, edits, denied commands and agy's report.

## 🧰 Tools

| Tool | Description |
|---|---|
| `agy_start` | Start agy on a work package in place in cwd; `checks=[…]` run by the waiter; `lend=[…]` skills and `mcp=[…]` servers borrowed from Claude for this job; `handoff=True` returns `watch_cmd` for you and ends the agy session after the round; `outputs=[…]` names files the brief's commands generate, so they don't count against `clean`. |
| `agy_status` | One job's progress: compact state, steps, edits, commands, denied actions, and agy's final per-task report (progress chatter dropped). With no job, lists recent jobs. |
| `agy_wait` | Block until job finishes or stalls; returns agy_status. |
| `agy_diff` | Audit changed files against snapshot, out-of-scope edits, denied actions, diff. |
| `agy_resume` | Next message to the job's live agy session (fix-up or next package), ~2–3 s overhead; restarts with new rules after a denial. |
| `agy_close` | End a job's agy session once its work is audited. |
| `agy_cancel` | Kill a running job and terminate its process group. |
| `agy_discard` | Restore files from the pre-job snapshot; delete agy-created files. |
| `agy_permissions` | Read or edit agy's allow-list; `check=[…]` tests a brief's commands first. Edits and checks get a compact reply; call it with no arguments for the whole list. |
| `agy_usage` | Check remaining 5-hour and weekly quota pools and reset times. |

## 🛡️ Safety

- **Accept-edits mode**: agy is invoked with `--mode accept-edits`; never run with `--dangerously-skip-permissions`.
- **Permissions allow-list**: Enforced via `~/.gemini/antigravity-cli/settings.json` under `permissions.allow` and edited by `agy_permissions`.
- **Guard preamble**: Every brief constrains agy to `allowed_files` and prohibits state-changing git commands, package installs, and file deletions.
- **Audit & discard**: `agy_diff` flags out-of-scope or unrecorded edits; `agy_discard` restores files cleanly from the pre-job snapshot.
- **An allowed test command runs any code agy writes.** `python3 -m unittest` or `pytest` imports test files, `__init__.py` and conftest, so agy can put a script in one of them and the allow-list never sees it. In benchmark 5 agy did exactly that: it migrated 78 files with a script hidden in `__init__.py`, then removed it. The guard forbids this, and the verdict now marks such files as `unattributed` (changed with no agy edit step), which makes `clean` false. Treat granting a test runner as granting code execution inside the repo.
- **A declined `agy_start` can still run.** Once, the Claude desktop app sent the call to the server before the user declined it, and agy ran the whole job. The skill tells Claude to run `agy_status()` after a rejected or failed start and cancel any job it finds.
- **Safe snapshots & no commits**: Snapshots use a throwaway `GIT_INDEX_FILE` without touching `HEAD` or index; agy commits nothing.

## 🧠 Choosing a model

- **`gemini-3.8-flash-medium`** (Default): Fast, token-efficient, recommended for well-specified refactors, migrations, and scaffolding across all plans.
- **`gemini-3.8-flash-high`**: Suitable for complex multi-step refactoring with subtle dependency orderings.
- **`gemini-4-argon-medium`**: Recommended for open-ended research legwork, transcription, or complex verification; draws from a limited weekly quota pool.

Check quota for free with `agy -p "/usage"` (or the `agy_usage` tool). Full per-model notes and timings: [models.md](skills/agy/references/models.md).

## 📊 Benchmark

Small tasks, measured 2026-10-19: Claude alone vs Claude orchestrating agy (`gemini-3.8-flash-medium`), Sonnet subagents, hidden checks, n = 1 per cell.

| Task | Claude tokens (alone → with agy) | Wall time | Hidden checks |
|---|---|---|---|
| Rename across 6 files | 81k → 101k | 7 s → 135 s | 4/4 both |
| CSV feature from a spec | 96k → 116k | 19 s → 190 s | 6/6 both |
| Fix 3 planted bugs | 86k → 103k | 14 s → 211 s | 5/5 both |
| **Total** | **264k → 319k (+21 %)** | **40 s → 536 s** | **15/15 both** |
| Large package: 40-file API migration + type hints | 91k → 107k (+17 %) | 38 s → 1,050 s | 6/6 both |

The rows above ran with agy's own MCP servers, skills and plugins loaded into every job (that doubled agy's per-turn overhead). [Benchmark 4](benchmarks/04-bare/RESULTS.md) (2026-10-20) reran with agy bare, ponytail lent and the v0.4 verdict loop, and added a task Claude can't script: categorise and summarise 30 support tickets.

| Task (bare agy, v0.4.1) | Claude tokens (alone → with agy) | Wall time | Hidden checks |
|---|---|---|---|
| CSV feature from a spec | 96k → 96k (0.99×) | 19 s → 226 s | 6/6 both |
| 40-file migration + type hints | 91k → 108k (1.19×) | 38 s → 1,406 s | 6/6 both |
| 30-ticket triage (judgment) | 86k → 101k (1.18×) | 26 s → 363 s | 4/4 both, 97 % category accuracy both |

[Benchmark 5](benchmarks/05-handoff/RESULTS.md) (v0.5.0) reran the same three tasks in **hand-off mode** (Claude reads one verdict, no diff reads): CSV 96k (0.99× Claude alone), migration 105k (1.15×), triage 95k (1.11×), all hidden checks passing. Skipping the diff reads saved only 1–6k against full audit.

**Real-use estimate.** The totals above are per fresh subagent. Measured from the transcripts, each run starts at ~70k tokens (system prompt, tools, CLAUDE.md, memory) in both arms, and the agy arms then spend ~20k loading the skill and the agy tool definitions. In a real session both are paid once per session, not per job. What each job added after that:

| Task | Claude alone | agy, full audit | agy, hand-off |
|---|---|---|---|
| CSV feature | 25k | 4.8k (0.19×) | 3.7k (0.15×) |
| 40-file migration | 20k | 17.6k (0.88×) | 13.4k (0.67×) |
| 30-ticket triage | 15k | 10.0k (0.67×) | 3.6k (0.24×) |

So **once the skill is loaded, a hand-off job adds far less new context than doing the work**, and Claude does not have to handhold agy for that. Two costs remain: the ~20k setup in each session (the first job roughly breaks even, later jobs save), and per-call re-reads, since in a long session every tool call re-reads the whole session from cache at ~0.1× the input price. Hand-off took 4 calls on two tasks; on the migration the orchestrator polled with `agy_wait` and took 15. These are estimates from n = 1 runs, not a measured real-session benchmark.

Per fresh run, agy **still costs** Claude tokens: the setup outweighs the job, and Claude alone is cheap at anything that fits in one read (it triaged all 30 tickets in 3 tool calls). The skill therefore keeps one-off small work in Claude ("too small for agy"). Where agy can still pay: packages long enough that Claude would otherwise spend many turns waiting (renders, build chains), and keeping your Claude session limit free while Gemini does the hours of work. Untested: reading-heavy research, and tasks far larger than one context. Plans, fixtures, checks and raw numbers: [`benchmarks/`](benchmarks/); the full story, including 22 jobs of real project use: [JOURNEY.md](JOURNEY.md).

## 🧭 Status and next steps

**Paused at v0.5.1.** Five benchmarks: equal quality, much slower; no saving per fresh run, but in a session with the skill loaded, hand-off jobs add 0.15–0.67× the tokens of doing the work. It stays opt-in and useful for:

- 🔋 **Claude limit nearly spent**: Gemini quota is a separate pool.
- ⏳ **Long unattended runs**: renders, build chains, long test suites; Claude reads one verdict at the end.
- 🔎 **Research legwork**: many pages searched, downloaded or transcribed; Claude reads the summary and spot-checks.
- 📦 **Volume beyond one Claude read**: hundreds of files or records with a machine verifier.
- 📐 **Spec-to-file builds**: applying a detailed, already-decided spec to a large file.

Worth trying next: batching packages, a sandbox for commands that run repo code, and benchmarks at a volume Claude can't read in one go. A separate headless orchestrator or babysitter model is deliberately not planned: that would be over-engineering, a second worker to maintain for an unmeasured saving. Details: [JOURNEY.md §9](JOURNEY.md#9-where-it-stands-and-what-could-come-next).

## 📚 More

<details><summary><b>Manual install</b></summary>

1. Copy the skill directory `skills/agy` to `~/.claude/skills/agy`.
2. Add the MCP server directly to your Claude configuration:
   ```bash
   claude mcp add --scope user agy-worker -- uv run --script /path/to/server/server.py
   ```

</details>

<details><summary><b>Work package brief format</b></summary>

```markdown
# Context
Static facts first: what the project is, file formats, where examples live.

# Goal
One paragraph defining the expected end state of this package.

# Tasks
Numbered list. Each task defines target files, exact change, done-means, and machine-readable checks.

# Order & checkpoints
Which tasks depend on which; run checks after each task and resolve failures before proceeding.

# If blocked
Skip the blocked task, record why, and continue with the remaining tasks.

# Report
Per task: done / skipped (why) / check result; files changed.
```

</details>

<details><summary><b>What we learned about headless agy</b></summary>

- **Permission rules are prefixes**: Rules match prefixes (`command(...)`, `read_url(...)`) or regex `command(regex:...)`; wildcard `*` is literal.
- **Denials abort the round**: Unpermitted actions are auto-denied in headless mode and terminate the round immediately.
- **Live sessions**: every job is a running agy process you keep messaging; follow-ups skip the cold start. A denial ends only that turn — grant the rule and `agy_resume` restarts agy on the same conversation, context kept (agy reads rules only at startup).
- **Free quota checks**: Running `agy -p "/usage"` queries local CLI quota pools without consuming tokens or model calls.
- **Active commands avoid stalls**: Long-running commands in `ACTIVE` state are tracked so active test or build runs are not flagged as stalled.
- **The process can outlive its result**: agy may keep running after emitting its final `result` event, so job state is taken from the result, not from whether the process is alive.

</details>

<details><summary><b>Configuration & limitations</b></summary>

- **`AGY_WORKER_HOME`**: Directory where job metadata, jsonl streams, and stderr logs are preserved (defaults to `~/.local/state/agy-worker`).
- **Platforms**: tested on macOS. Linux should work (same POSIX process handling) but is untested. Windows is not supported yet: `agy_cancel` uses `os.killpg` and the liveness check uses `os.kill(pid, 0)`.
- **Protected paths**: Claude Code safety boundaries may reject worker file edits within `~/.claude/`.
- **Model quota limits**: Gemini 4 Argon requires a paid tier (Google AI Pro, Ultra, or Enterprise) and operates under a weekly quota pool.

</details>

---

*Unofficial community project, not affiliated with or endorsed by Google or Anthropic. agy-worker edits agy's settings.json allow-list and lets agy edit files in your working tree — review what you grant.*

MIT © 2026 Pranav Raut — see [LICENSE](LICENSE).

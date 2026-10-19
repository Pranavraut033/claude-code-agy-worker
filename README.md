# agy-worker

Claude Code plans, briefs, monitors and audits; agy (Gemini models via the Antigravity CLI) edits files and runs checks in place, in long work packages; every job is snapshotted so it can be diffed and reverted.

## Overview

The `agy-worker` plugin turns Claude Code into an orchestrator and Google Antigravity CLI (`agy`) into an agentic mechanical worker.

- **Fixed roles**: Claude Code serves as the eyes and brain: it plans, divides work into packages, writes briefs, monitors execution, audits changes, and makes architectural decisions. Antigravity CLI acts as the hands and legs: editing code and files, scaffolding records, running checks, downloading resources, transcribing files, and executing multi-step pipelines.
- **In-place execution**: agy edits directly within the target repository workspace without isolated git worktrees.
- **Snapshot isolation**: Before any job starts, the plugin creates an isolated snapshot of the repository using an independent git index. Any unexpected or stray edits outside the assigned scope can be audited and cleanly discarded.

## Requirements

- **Claude Code**: Tested with Claude Code environments supporting plugins and MCP servers.
- **Antigravity CLI (`agy`)**: Installed and signed in (tested on version 1.4.2). Verify with `agy models`.
- **`uv`**: Installed and accessible on `PATH` (used by Claude Code to launch PEP 723 Python scripts).
- **`git`**: The target workspace must be a git repository so that pre-job snapshot, diffing, and file restoration can function.

## Installation

In Claude Code, run:

```text
/plugin marketplace add Pranavraut033/claude-code-agy-worker
/plugin install agy-worker@agy-worker
```

Restart Claude Code. Once restarted, run `/mcp` to verify that `agy-worker` is registered and active.

### Manual Installation

Alternatively, you can install the skill and server manually:

1. Copy the skill directory `skills/agy` to `~/.claude/skills/agy`.
2. Add the MCP server directly to your Claude configuration:
   ```bash
   claude mcp add --scope user agy-worker -- uv run --script /path/to/server/server.py
   ```

## Usage

Trigger orchestration by issuing `/agy <task>` or telling Claude: *"hand this to agy"*.

The orchestration lifecycle runs through six distinct stages:

1. **Package Planning**: The orchestrator breaks a large goal into coherent work packages (10–60 minutes of worker runtime each). Tasks within a package share file contexts and dependencies.
2. **`agy_start`**: Claude calls `agy_start` with an explicit working directory (`cwd`), an allow-list of files (`allowed_files`), model selection, and a comprehensive markdown brief. It returns `{job, git, wait_cmd}` immediately.
3. **Background Waiter**: Rather than polling `agy_status` in an active turn loop, Claude launches the returned `wait_cmd` as a background shell process (`run_in_background: true`):
   ```bash
   <uv> run --script <plugin dir>/server/server.py wait <job_id>
   ```
   When the job terminates (done, stalled, or failed), the background task exits and wakes Claude with the compact status JSON.
4. **Tiered Audit via `agy_diff`**: Claude inspects `agy_diff` to verify changes:
   - Check `out_of_scope` paths: ensure agy touched only permitted files.
   - Check `not_from_agy_edits`: ensure no unauthorized file changes occurred.
   - Check `denied`: ensure no tool calls were blocked.
   - Inspect `stat` and review specific diff chunks for critical changes.
   - Re-run independent validation commands to verify outputs.
5. **Fix-up Rounds via `agy_resume`**: If the audit identifies defects or incomplete checks, Claude provides a consolidated correction message via `agy_resume` (up to 2 resume rounds per package).
6. **Report**: Claude summarizes changes, test results, tokens, and wall time for the user.

### Model Selection

- **`gemini-3.8-flash-medium`** (Default): Recommended for well-specified packages, code refactors, migrations, and template-based file generation. Fast, token-efficient, and available on all Antigravity plans.
- **`gemini-3.8-flash-high`**: Suitable for complex multi-step refactoring with subtle dependency orderings.
- **`gemini-4-argon-medium`**: Recommended for open-ended research legwork, transcription, complex verification, or packages where Flash encountered obstacles. Note that Argon draws from a limited weekly quota pool.

### Brief Format

Work package briefs follow a structured Markdown format wrapped in a guard preamble:

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

## Tools Table

The `agy-worker` MCP server provides the following tools:

| Tool | Description |
|---|---|
| `agy_start` | Start agy on a work package (several related tasks), in place in `cwd` (absolute path). |
| `agy_status` | One job's progress, compact: state (running\|stalled\|done\|failed\|cancelled), elapsed, step/edit counts, recent tool steps, files edited, commands run, denied actions, and report. |
| `agy_wait` | Block until the job finishes or stalls, or `timeout_s` passes; returns `agy_status`. |
| `agy_diff` | Audit: files changed since the job's snapshot, which are outside `allowed_files`, which changed without an agy edit step, denied actions, the stat, and unified diff. |
| `agy_resume` | Fix-up round: send a message to the same agy conversation (only after a clean round). |
| `agy_cancel` | Kill a running job (terminates its whole process group). |
| `agy_discard` | Put files back to the job's snapshot (reverts files touched by agy). |
| `agy_permissions` | Read or edit agy's headless allow-list (`permissions.allow` in its `settings.json`). |
| `agy_usage` | agy's remaining plan quota per pool (Gemini, Gemini 4 Argon, Claude/GPT) for 5-hour and weekly windows, with hours until reset. |

## Safety Model

- **Accept Edits Mode**: agy is invoked with `--mode accept-edits`. It is never run with `--dangerously-skip-permissions`.
- **Permissions Allow-List**: Headless agy enforces an allow-list stored in `~/.gemini/antigravity-cli/settings.json` under `permissions.allow`. The plugin's `agy_permissions` tool reads and directly edits this file to maintain the command and URL allow-list required by jobs:
  - Command prefixes: `command(python3 -m pytest)`
  - Regex patterns: `command(regex:npm run (build|test))`
  - URL prefixes: `read_url(https://docs.python.org/)`
- **Guard Preamble**: Each brief is prefixed with strict constraints: agy may only edit files listed in `allowed_files`, cannot perform state-changing git commands, and cannot install packages or delete files.
- **Diff Auditing & Scope Enforcement**: `agy_diff` flags any files modified outside `allowed_files` or changed without a recorded edit tool step. Unauthorized modifications can be reverted immediately with `agy_discard`.
- **Safe Pre-Job Snapshot**: Snapshots are generated using a temporary index file (`GIT_INDEX_FILE`) and `git write-tree`. Working branch references, `HEAD`, and the main repository index are never touched.
- **Discard Mechanism**: `agy_discard` restores modified files from the pre-job tree snapshot. Files created by agy that were not present in the pre-job snapshot are deleted, leaving unrelated files from other sessions intact.
- **No Git Commits**: agy never commits code. All commits remain the responsibility of Claude and the user following audit approval.

## Token and Turn Discipline

Both orchestrator and worker operate under deliberate token budgets:

- **Orchestrator turns**: Claude Code re-reads session history on every turn. Using background waiters rather than status polling loops preserves turn budget and context window.
- **Compact reporting**: `agy_status` returns concise output by default (last 5 tool steps, relative paths, truncated report text). Pass `full_report=True` only when a detailed audit demands it.
- **Worker amortisation**: Starting an agy job incurs approximately 40 seconds of startup overhead and brief processing. Sizing work packages to 10–60 minutes ensures startup overhead is amortised effectively across multiple tasks.

## Things We Learned About Headless agy

Key operational characteristics observed when driving headless Antigravity CLI sessions:

- **Permission Rules are Prefixes**: Allow-list rules use prefix matching (`command(...)`, `read_url(...)`). A regex prefix format like `command(regex:...)` is supported, but standard wildcard `*` is treated literally.
- **Denials Abort the Round**: In headless mode, if agy attempts an action not permitted in `settings.json`, the command is auto-denied and the round immediately terminates with an empty output response.
- **Start Fresh Jobs After Denials**: Resuming an agy conversation after a denial often results in a wedged session (0 tool steps and spinning tokens). When a command is denied, grant permission via `agy_permissions` and start a new job.
- **Free Quota Checks**: Running `agy -p "/usage"` (accessible via `agy_usage`) queries quota pools directly through the local CLI without consuming token credits or initiating a model call.
- **Active Commands Avoid Stalls**: While a lengthy command runs (such as a multi-minute build or test run), no new stream events are emitted. Active `run_command` steps in `ACTIVE` state are tracked so jobs are not mistakenly flagged as stalled.

## Configuration

- **`AGY_WORKER_HOME`**: Directory where job metadata, jsonl streams, and stderr logs are preserved. Defaults to `~/.local/state/agy-worker`.

## Limitations

- **Operating System**: Currently tested and supported exclusively on macOS.
- **Protected Paths**: Claude Code safety boundaries may reject worker file edits within `~/.claude/`.
- **Model Quota Limits**: Gemini 4 Argon requires a paid tier (Google AI Pro, Ultra, or Enterprise) and operates under a weekly quota pool.

## Disclaimer

Unofficial community project, not affiliated with or endorsed by Google or Anthropic. agy-worker edits agy's settings.json allow-list and lets agy edit files in your working tree — review what you grant.

## License

This project is licensed under the [MIT License](LICENSE).

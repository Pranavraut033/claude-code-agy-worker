# Summary of Top Levers to Reduce Claude Code Orchestrator Token Costs
1. **Agent SDK Lean Configuration (`tools: []`, minimal prompt, `settingSources: []`)**: Eliminates built-in tools and default prompts, shrinking baseline context from ~8,500+ tokens to ~300 tokens (95%+ reduction).
2. **Context Isolation for Bulk File Reads (Subagents / External Workers)**: Offloads massive file inspection to isolated contexts; orchestrator consumes only the ~400-token final summary rather than full file dumps.
3. **Avoid Orchestration Overhead on Small Tasks**: Avoids the documented ~60% token "coordination penalty" on small tasks where direct execution uses fewer tokens than multi-agent task serialization.
4. **Deterministic PreToolUse & Stop Hooks**: Runs tests and formatting locally without spending model turns; PreToolUse filters test outputs to errors only, while Stop hooks verify completions at zero token cost on pass.
5. **Headless Bare Mode (`--bare`) & Tool Restrictions (`--tools`)**: Strips auto-discovered CLAUDE.md, memory, skills, and MCP servers at startup and removes unused built-in tool definitions from the system prompt.
6. **Force Subagents to Haiku (`CLAUDE_CODE_SUBAGENT_MODEL=haiku` + `FORCE=1`)**: Forces all background and subagent turns onto Haiku, cutting subagent token pricing by ~90% relative to Sonnet/Opus.
7. **Avoid `opusplan` Cache Invalidation & Respect Cache TTL**: Avoids the model switch between Opus (plan) and Sonnet (exec) that forces an uncached re-read of the whole conversation; preserves warm cache prefixes.
8. **Enforce Deferred MCP Tool Search (`ENABLE_TOOL_SEARCH=true`)**: Prevents full JSON schemas of MCP servers from loading upfront, saving thousands of tokens at session initialization.
9. **Frequent `/clear` Between Distinct Work Packages**: Drops accumulated conversation history to 0 tokens at phase boundaries rather than paying repeated cache-read fees on stale history.

---

# Task 1: Baseline Size of a Claude Code Session/Subagent and Ways to Shrink It

### Baseline Context Composition
- **System Prompt**: Claude Code's default system prompt loads first and consumes ~4,200 tokens, containing core instructions for behavior, tool use, coding conventions, and response formatting — https://code.claude.com/docs/en/context-window.md
- **Auto Memory (`MEMORY.md`)**: Automatically loads the first 200 lines or 25KB (whichever comes first) of notes, build commands, and patterns from prior sessions, consuming ~680 tokens — https://code.claude.com/docs/en/context-window.md
- **Environment Info & Git Status**: Injects working directory, platform, shell, OS version, git repo status, branch, and recent commits, consuming ~280 tokens — https://code.claude.com/docs/en/context-window.md
- **MCP Tool Definitions**: When deferred via tool search, MCP tool names load as a lightweight listing consuming ~120 tokens; without deferral, full JSON schemas are injected upfront, which can consume thousands of tokens — https://code.claude.com/docs/en/context-window.md
- **Skill Descriptions Index**: Injects one-line descriptions of all available skills so Claude knows what commands it can invoke, consuming ~450 tokens — https://code.claude.com/docs/en/context-window.md
- **Global `~/.claude/CLAUDE.md`**: Global developer preferences injected into project context at session startup, consuming ~320 tokens in standard profiles — https://code.claude.com/docs/en/context-window.md
- **Project `CLAUDE.md`**: Project-level architecture conventions and commands injected into project context, consuming ~1,800 tokens in standard setups (recommended under 200 lines) — https://code.claude.com/docs/en/context-window.md
- **Total Initial Baseline**: A fresh Claude Code interactive session starts with ~8,000 to ~9,000+ baseline tokens in context before the first user prompt is processed — https://code.claude.com/docs/en/context-window.md

### Subagent Baseline Differences
- **Shorter System Prompt**: Non-fork subagents receive their own shorter system prompt (~900 tokens for general-purpose subagents) rather than the main session's 4,200-token prompt — https://code.claude.com/docs/en/context-window.md
- **No Main Auto Memory**: Non-fork subagents start without conversation history or the main session's auto memory (`MEMORY.md`), starting with fresh memory unless explicitly configured with `memory:` in frontmatter — https://code.claude.com/docs/en/context-window.md
- **Built-in Explore & Plan Skip CLAUDE.md**: The built-in `Explore` and `Plan` subagents automatically skip loading user, project, and local `CLAUDE.md` files to maintain a minimal context — https://code.claude.com/docs/en/sub-agents.md
- **`omitClaudeMd: true` for Custom Subagents**: Setting `omitClaudeMd: true` in a custom subagent's YAML frontmatter or `--agents` JSON launches the subagent without user, project, or local `CLAUDE.md` files, loading only managed policy files — https://code.claude.com/docs/en/sub-agents.md

### Documented Flags and Options to Shrink Baseline Context
- **`--bare` (Minimal Mode)**: Skips auto-discovery of hooks, skills, custom commands, subagents, installed plugins, MCP servers, auto memory, and `CLAUDE.md`. Claude retains access only to built-in Bash, file read, and file edit tools, and sets `CLAUDE_CODE_SIMPLE=1` — https://code.claude.com/docs/en/cli-reference.md
- **`--system-prompt <text>` / `--system-prompt-file <path>`**: Completely replaces the default 4,200-token system prompt with custom text, dropping all default coding guidance and safety instructions — https://code.claude.com/docs/en/cli-reference.md
- **`--tools <list>`**: Restricts available built-in tools. Passing `""` disables all built-in tools (except `EndConversation` if MCP tools remain), while naming tools like `"Bash,Edit,Read"` removes unlisted built-in tools from context — https://code.claude.com/docs/en/cli-reference.md
- **`--disallowedTools` / `--disallowed-tools <list>`**: Deny rules. A bare tool name like `"Edit"`, `"*"` (all tools), or `"mcp__*"` (all MCP tools) removes the matching tools from Claude's context entirely — https://code.claude.com/docs/en/cli-reference.md
- **`--allowedTools` / `--allowed-tools <list>`**: Pre-approves listed tools to execute without prompting, but does NOT remove unlisted tools from Claude's context — https://code.claude.com/docs/en/cli-reference.md
- **`--strict-mcp-config`**: Restricts MCP servers strictly to those specified via `--mcp-config`, ignoring all other MCP configurations in `~/.claude/mcp.json` and `.mcp.json` — https://code.claude.com/docs/en/cli-reference.md
- **`--disable-slash-commands`**: Disables all skills and commands for the session, preventing skill listings from entering context — https://code.claude.com/docs/en/cli-reference.md
- **`disable-model-invocation: true` in Skills**: Adding `disable-model-invocation: true` to a skill's frontmatter excludes its description from the startup skill index, costing 0 tokens until explicitly invoked by user with `/name` — https://code.claude.com/docs/en/context-window.md
- **`ENABLE_TOOL_SEARCH`**: Controls MCP tool deferral. When enabled (default on supported models), MCP tools load on demand via tool search rather than upfront. Setting `ENABLE_TOOL_SEARCH=false` forces all tools upfront; `ENABLE_TOOL_SEARCH=auto:N` sets a context percentage threshold — https://code.claude.com/docs/en/mcp.md
- **`tools:` and `disallowedTools:` in Subagent Frontmatter**: Allows subagents to declare an explicit tool allowlist (`tools: Read, Grep, Glob, Bash`) or denylist (`disallowedTools: Write, Edit`), restricting tools in the subagent's prompt — https://code.claude.com/docs/en/sub-agents.md
- **`--exclude-dynamic-system-prompt-sections`**: Moves per-user auto-memory paths out of the system prompt and into the first user message, enabling cross-user prompt cache sharing — https://code.claude.com/docs/en/cli-reference.md
- **`--safe-mode`**: Starts with all customizations disabled (CLAUDE.md, skills, plugins, hooks, MCP, custom commands, auto memory), while leaving built-in tools and auth intact — https://code.claude.com/docs/en/cli-reference.md

---

# Task 2: Headless/Programmatic Use (`claude -p` & Agent SDK)

### `claude -p` Options Relevant to a Cheap Orchestrator
- **`--model <model>`**: Sets the model for the session using aliases (`haiku`, `sonnet`, `opus`) or full model identifiers, overriding config defaults — https://code.claude.com/docs/en/cli-reference.md
- **`--max-turns <N>`**: Caps the maximum number of agentic turns in non-interactive print mode; exits with an error when reached, preventing costly runaway execution loops — https://code.claude.com/docs/en/cli-reference.md
- **`--max-budget-usd <amount>`**: Halts the run once estimated spend on API calls reaches the dollar amount, stopping background subagents and preventing further spawns — https://code.claude.com/docs/en/cli-reference.md
- **`--output-format <text|json|stream-json>`**: Specifies output format. `json` includes `total_cost_usd`, per-model cost breakdowns, duration, and session metadata; `stream-json` emits line-delimited events for real-time monitoring — https://code.claude.com/docs/en/headless.md
- **`--json-schema '<schema>'`**: Forces structured JSON output conforming to a specified JSON Schema into the `structured_output` field of `json` output mode — https://code.claude.com/docs/en/headless.md
- **`--system-prompt <text>` / `--system-prompt-file <path>`**: Replaces the entire default Claude Code prompt with a minimal orchestrator prompt — https://code.claude.com/docs/en/cli-reference.md
- **`--append-system-prompt <text>` / `--append-system-prompt-file <path>`**: Appends orchestrator rules to the default prompt while preserving built-in tool instructions — https://code.claude.com/docs/en/cli-reference.md
- **`--permission-mode <mode>`**: Begins in a specified mode (`auto`, `dontAsk`, `acceptEdits`, `bypassPermissions`, `plan`, `default`/`manual`). `dontAsk` denies every promptable call, ideal for unattended pipelines — https://code.claude.com/docs/en/headless.md
- **`--permission-prompts none`**: For unattended runs with no interactive user, immediately denies any tool call that would prompt, instructs Claude not to retry, and removes user-interactive tools like `AskUserQuestion` — https://code.claude.com/docs/en/headless.md
- **`--bare`**: Recommended for scripted orchestration; skips all host `~/.claude/` and project `.claude/` files, hooks, MCP, and memory for fast, deterministic startup — https://code.claude.com/docs/en/headless.md
- **`--no-session-persistence`**: Disables saving session state and prompt history to disk — https://code.claude.com/docs/en/cli-reference.md
- **`--forward-subagent-text`**: Emits subagent text and thinking blocks in `stream-json` output with `parent_tool_use_id`, allowing orchestrators to follow nested subagent turns — https://code.claude.com/docs/en/cli-reference.md

### Claude Agent SDK (Python & TypeScript) Options for Lean Agents
- **`tools: []` (Remove All Built-In Tools)**: Setting `tools: []` in the SDK `options` removes all built-in Claude Code tools from context. Claude can only access custom tools provided via MCP, eliminating built-in tool definitions — https://code.claude.com/docs/en/agent-sdk/custom-tools.md
- **Minimal Default System Prompt**: When `systemPrompt` (TS) or `system_prompt` (Python) is omitted, the SDK uses a minimal default prompt covering tool calling only (~few hundred tokens), omitting the large `claude_code` preset, coding instructions, and safety rules — https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md
- **Custom System Prompt String**: Passing a custom string as `systemPrompt` sends only the user-provided text, creating a dedicated orchestrator persona with zero Claude Code overhead — https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md
- **`settingSources: []`**: Setting `settingSources: []` (TS) or `setting_sources=[]` (Python) disables loading user, project, and local settings files, preventing `CLAUDE.md`, auto memory, and local hooks from loading into context — https://code.claude.com/docs/en/agent-sdk/configuration.md
- **In-Process Custom Tools (`createSdkMcpServer` / `create_sdk_mcp_server`)**: Defines lightweight application-specific tools (e.g. `execute_worker_task`) using `tool()` / `@tool` without running external processes — https://code.claude.com/docs/en/agent-sdk/custom-tools.md
- **`allowedTools: ["mcp__server__tool"]`**: Auto-approves custom in-process tools so the orchestrator runs without permission callbacks — https://code.claude.com/docs/en/agent-sdk/custom-tools.md
- **`maxTurns: N` / `maxBudgetUsd: X`**: Native SDK options on `query()` to strictly enforce turn and budget limits on agent execution — https://code.claude.com/docs/en/agent-sdk/configuration.md
- **`excludeDynamicSections: true`**: When using the `claude_code` preset with `append`, moves dynamic auto-memory paths out of the system prompt to maximize cache sharing across sessions — https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md

---

# Task 3: Claude Code Usage Limits, Token Counting, and Cost Guidance

### How Usage Limits & Costs Count Tokens
- **Plan Usage vs. Dollar Billing**: Subscription plans (Pro, Max, Team, Enterprise) draw from rolling 5-hour session limits and weekly usage allowances, whereas API users are billed per token consumed — https://code.claude.com/docs/en/costs.md
- **Prompt-Cache Reads on Plan Limits**: Cached tokens count significantly less against plan usage limits than un-cached fresh input tokens, but they still count towards session and weekly allowances; long sessions re-reading large conversation histories on every tool call will gradually consume plan quotas — https://code.claude.com/docs/en/costs.md & https://support.claude.com
- **API Token Pricing for Cache Reads**: On the Anthropic API, cache reads cost 10% of base input token price (a 90% discount); cache writes cost 125% of base input token price — https://platform.claude.com/docs/en/about-claude/pricing
- **Cache Miss Penalties**: After a break longer than the cache TTL, the next turn misses the cache and reprocesses the full context as un-cached input, triggering a large spike in plan usage or cost — https://code.claude.com/docs/en/costs.md
- **Cache Invalidation on Model Switch**: Switching models mid-session completely misses the cache because caches are model-isolated, requiring a full re-computation of conversation history — https://code.claude.com/docs/en/prompt-caching.md

### Cache TTL in Claude Code
- **Subscription Default (Within Plan Usage)**: 1-hour TTL for the main conversation; 5-minute TTL for everything else (subagents, workflows, agent teams, forks, compaction) — https://code.claude.com/docs/en/prompt-caching.md
- **Usage Credits / API / Cloud Provider Default**: 5-minute TTL for both main conversation and subagents. When subscription users draw on usage credits, main conversation TTL drops to 5 minutes to reduce cache write charges — https://code.claude.com/docs/en/prompt-caching.md
- **Manual TTL Configuration**:
  - Main conversation: set `promptCacheTtl: "1h"` in settings or `CLAUDE_CODE_PROMPT_CACHE_TTL="1h"` in environment — https://code.claude.com/docs/en/prompt-caching.md
  - Subagents: set `subagentPromptCacheTtl: "1h"` in settings or `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL="1h"` in environment, or `experimental: { cacheTtl: "1h" }` in subagent YAML frontmatter — https://code.claude.com/docs/en/prompt-caching.md
  - Overrides: `FORCE_PROMPT_CACHING_5M=1` forces 5m across all requests; `ENABLE_PROMPT_CACHING_1H=1` requests 1h across all requests — https://code.claude.com/docs/en/prompt-caching.md

### What `/cost` and `/usage` Report
- **Session Block**: Reports total estimated dollar cost (computed locally at list price or contracted rates via `modelPricing`), total duration (API time and wall time), code changes (lines added/removed), and usage breakdown by model (input, output, cache read, cache write tokens) — https://code.claude.com/docs/en/costs.md
- **`Prompt cache (main)` Line**: Reports number of API requests, percentage of input tokens served from cache, cache misses with tokens re-cached and likely causes, expected rebuilds (compaction/tool clearing), and warm/cold TTL status — https://code.claude.com/docs/en/costs.md
- **Plan Usage Breakdown**: Shows subscription progress bars (5-hour and weekly limits), percentage attribution to skills, subagents, plugins, and MCP servers, and behavior flags highlighting patterns causing 10%+ of usage (long context, cache misses) — https://code.claude.com/docs/en/costs.md
- **Scheduled Loops Breakdown**: Displays heaviest `/loop` and scheduled tasks with frequency, iteration counts, and total tokens — https://code.claude.com/docs/en/costs.md
- **Spinner Token Output Counter**: Live display next to the terminal spinner showing approximate output tokens generated in the current turn (`Deciphering… (10m 27s · ↓ 5.5k tokens)`) — https://code.claude.com/docs/en/costs.md

### Official Recommendations for Reducing Usage ("Manage Costs" Docs)
1. **Clear Between Tasks (`/clear`)**: Resets conversation history to 0 tokens and $0 session cost. Stale context wastes tokens on every subsequent turn — https://code.claude.com/docs/en/costs.md
2. **Add Custom Compaction Instructions (`/compact <instructions>`)**: Directs Claude what to preserve during summarization (e.g. `/compact Focus on test output and code changes`), or sets `# Compact instructions` in `CLAUDE.md` — https://code.claude.com/docs/en/costs.md
3. **Choose the Right Model**: Use Sonnet instead of Opus for typical tasks; specify `model: haiku` in subagent configurations for simple or research tasks — https://code.claude.com/docs/en/costs.md
4. **Adjust Extended Thinking / Effort Levels**: Lower effort level with `/effort` or `/model`, or set `MAX_THINKING_TOKENS=8000` on fixed-budget models; thinking tokens bill as output tokens — https://code.claude.com/docs/en/costs.md
5. **Delegate Verbose Operations to Subagents**: Spawns subagents with separate context windows for file-heavy tasks so intermediate file contents do not pollute the main session context — https://code.claude.com/docs/en/costs.md
6. **Manage Agent Team Costs**: Keep teams small, use Sonnet for teammates, keep spawn prompts focused, and shut teammates down promptly; agent teams consume ~7x more tokens in plan mode — https://code.claude.com/docs/en/costs.md
7. **Write Specific Prompts**: Target specific files and functions (e.g. `add validation to login in auth.ts`) rather than vague prompts (`improve auth`) to prevent broad file scanning — https://code.claude.com/docs/en/costs.md
8. **Work Efficiently on Complex Tasks**: Use plan mode (`Shift+Tab`) before editing, course-correct early with `Esc` or `/rewind`, provide explicit verification targets, and test incrementally — https://code.claude.com/docs/en/costs.md
9. **Reduce MCP Server Overhead**: Prefer native CLI tools (`gh`, `aws`, `gcloud`, `sentry-cli`) over MCP servers because CLI commands add no per-tool listing overhead to context; disable unused servers in `/mcp` — https://code.claude.com/docs/en/costs.md
10. **Install Code Intelligence Plugins (LSP)**: Replaces broad grep search and multi-file reads with precise symbol navigation ("go to definition") and automatic compile-time error checks — https://code.claude.com/docs/en/costs.md
11. **Offload Processing to Hooks**: Use `PreToolUse` hooks to preprocess data before Claude sees it (e.g., filtering 10,000-line test logs to return only failure lines, shrinking context from tens of thousands of tokens to hundreds) — https://code.claude.com/docs/en/costs.md
12. **Move Instructions from `CLAUDE.md` to Skills**: Move specialized, task-specific instructions out of `CLAUDE.md` into on-demand skills to keep base `CLAUDE.md` under 200 lines — https://code.claude.com/docs/en/costs.md

---

# Task 4: Model Choice for Orchestration

### Model Selection Guidance (Haiku / Sonnet / Opus)
- **Haiku for Routine / Subagent Work**: Haiku is officially recommended for lightweight exploration, fast search, status line configurations, documentation lookups, and simple subagent tasks to preserve cost and rate limits — https://code.claude.com/docs/en/costs.md & https://code.claude.com/docs/en/sub-agents.md
- **Sonnet for Execution & Teammates**: Sonnet is recommended as the default workhorse for coding, refactoring, and agent-team coordination, balancing intelligence and token cost — https://code.claude.com/docs/en/costs.md
- **Opus for Architecture & Complex Planning**: Opus is reserved for deep architectural reasoning, ambiguous problem resolution, and complex multi-step planning — https://code.claude.com/docs/en/costs.md
- **Model Environment Variables**: Pin family aliases via `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, and `ANTHROPIC_DEFAULT_OPUS_MODEL` — https://code.claude.com/docs/en/model-config.md

### `opusplan` Behavior and Cache Tradeoff
- **Dual-Model Mode**: `opusplan` automatically uses `opus` during Plan Mode for planning and architecture decisions, and switches to `sonnet` during Execution Mode for implementation — https://code.claude.com/docs/en/model-config.md
- **Cache Invalidation Penalty**: Because each model maintains its own independent prompt cache, switching between Opus and Sonnet at the plan-mode boundary triggers a complete cache miss, requiring Claude Code to re-process and re-cache the entire conversation history as un-cached tokens — https://code.claude.com/docs/en/prompt-caching.md

### Subagent Model Configuration (`model:` Frontmatter & Environment)
- **`model:` Frontmatter Field**: In `.claude/agents/<name>.md`, specify `model: haiku`, `model: sonnet`, `model: opus`, a full model ID, or `model: inherit` (inherits parent model) — https://code.claude.com/docs/en/sub-agents.md
- **Model Resolution Order**:
  1. Per-invocation `model` parameter passed by Claude when calling the Agent tool
  2. Subagent definition's `model:` frontmatter (`inherit` resolves to main conversation's model)
  3. `CLAUDE_CODE_SUBAGENT_MODEL` environment variable
  4. Main conversation's model — https://code.claude.com/docs/en/sub-agents.md
- **`CLAUDE_CODE_SUBAGENT_MODEL`**: Sets the fallback model for subagents, teammates, and workflows when not explicitly set elsewhere — https://code.claude.com/docs/en/model-config.md
- **`CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1`**: Forces all subagents, teammates, and workflows to use the model in `CLAUDE_CODE_SUBAGENT_MODEL`, ignoring frontmatter `model:` fields and invocation parameters — https://code.claude.com/docs/en/sub-agents.md

---

# Task 5: Context-Control Features

### `/compact`, `/clear`, and Auto-Compact Thresholds
- **`/clear`**: Completely wipes conversation history, resetting session token usage to 0 at zero cost — https://code.claude.com/docs/en/costs.md
- **`/compact` Mechanism**: Sends a separate request to summarize the conversation history, replacing message history with a structured summary while keeping system prompt, CLAUDE.md, and auto-memory. Invoked skills are re-injected up to 5,000 tokens each; uninvoked skill descriptions are dropped — https://code.claude.com/docs/en/context-window.md
- **Compaction Cache Impact**: Produces an expected cache rebuild; the summarization call hits warm cache, but the subsequent conversation turn has a new prefix that rebuilds the cache for the shorter history — https://code.claude.com/docs/en/prompt-caching.md
- **Default Auto-Compact Window**:
  - Models with 200K windows (or when `CLAUDE_CODE_DISABLE_1M_CONTEXT=1`): auto-compacts at 200,000 tokens — https://code.claude.com/docs/en/model-config.md
  - Native 1M models (Sonnet 5+, Haiku 5.5, Opus 4.7+): auto-compacts before filling, at ~967,000 tokens by default — https://code.claude.com/docs/en/model-config.md
- **Customizing Auto-Compact Window**: Set via `/autocompact <window>` (e.g. `/autocompact 200k`), CLI flag `--autocompact <tokens>`, settings key `autoCompactWindow`, or environment variable `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (100k to 1M) — https://code.claude.com/docs/en/model-config.md
- **`idleCompaction`**: In v2.1.290+, automatically compacts long conversations left idle shortly before the 1-hour cache expires — https://code.claude.com/docs/en/prompt-caching.md

### Context Editing & Tool-Result Clearing
- **Anthropic API Context Editing Beta**: Beta header `context-management-2025-06-27` provides server-side runtime curation of context — https://platform.claude.com/docs/en/build-with-claude/context-editing
- **Tool-Result Clearing Strategy (`clear_tool_uses_20250919`)**: Automatically clears older, re-fetchable tool results (like large file reads or web searches) when context passes a threshold, replacing them with a placeholder while preserving the tool call record. Supports `clear_tool_inputs: true` to clear inputs as well — https://platform.claude.com/docs/en/build-with-claude/context-editing
- **Thinking Block Clearing Strategy (`clear_thinking_20251015`)**: Selectively clears or keeps thinking blocks from earlier turns — https://platform.claude.com/docs/en/build-with-claude/context-editing
- **Prompt Cache Tradeoff in Context Editing**: Clearing tool results invalidates the prompt cache prefix at the edit point, requiring a cache rewrite, but saves significant ongoing context volume on subsequent turns — https://platform.claude.com/docs/en/build-with-claude/context-editing

### Subagents as Context Isolation
- **Context Isolation Reality**: A subagent executes in a completely separate context window. Intermediate file reads, bash outputs, and tool calls never enter the parent's context window — https://code.claude.com/docs/en/sub-agents.md
- **Parent Context Savings**: Only the subagent's final text summary and a small metadata trailer enter the parent's context window (e.g. 6,100 tokens of file reads in subagent return as a 420-token result to the parent) — https://code.claude.com/docs/en/context-window.md
- **Billing / Limit Reality**: Subagents do NOT save tokens in absolute terms on their own; every subagent request is an independent API request drawing on account usage limits and API spend — https://code.claude.com/docs/en/costs.md

### Hooks for Zero-Turn Verification
- **`PreToolUse` Filtering**: Intercepts tool calls before execution. Scripts can inspect or rewrite commands (e.g. modifying `npm test` to pipe into `grep` and return only failure lines) or block disallowed tools with `decision: "block"` without calling the LLM — https://code.claude.com/docs/en/hooks.md
- **`PostToolUse` Local Verification**: Runs immediately after tool execution. Can format files (e.g. Prettier) or run linters locally, injecting feedback via `additionalContext` or rewriting outputs with `updatedToolOutput` without consuming LLM turns — https://code.claude.com/docs/en/hooks.md
- **`Stop` Hook for Test Validation**: Fires when Claude finishes responding. A shell hook can execute unit tests or linters:
  - If tests pass, exit code 0 ends the turn with zero additional model turns.
  - If tests fail, exit code 2 or `{"decision": "block", "reason": "..."}` prevents stopping and feeds the failure output back into context for Claude to fix — https://code.claude.com/docs/en/hooks.md
- **`PostToolBatch`**: Fires once after an entire batch of parallel tool calls resolves, before the next model call — https://code.claude.com/docs/en/hooks.md

---

# Task 6: Community Patterns & Token Savings for External Worker / Orchestrator Workflows

### Documented Multi-Agent / Cross-Model Architectures
- **Anthropic Orchestrator-Workers Architecture**: Foundational design pattern where a central orchestrator breaks down a prompt, delegates subtasks to parallel worker LLMs, and synthesizes results — https://claude.com/blog/building-effective-agents (and Claude Cookbook)
- **Claude Code + Gemini CLI / Flash**: Community setups (e.g. `sakibsadmanshajib/gemini-plugin-cc`, `Z-M-Huang/claude-codex-gemini`) use Claude Code as the reasoning orchestrator and delegate bulk file reading, repository documentation scanning, and code generation to Gemini CLI / Gemini 1.5/2.0 Flash to leverage Gemini's low token cost and 1M-2M context window — Community Source: https://github.com/sakibsadmanshajib/gemini-plugin-cc & https://github.com/Z-M-Huang/claude-codex-gemini
- **Claude Code + Aider / Codex**: Orchestrator-worker setups where Claude Code acts as the architect and hands diff-editing or test-fixing tasks to Aider or Codex workers inside isolated Git worktrees — Community Source: https://github.com/Orkas-AI/orkas & https://superset.sh
- **Multi-Instance Claude Code Worktrees (`cas`, `claude-code-orchestrator`)**: Wrappers where a primary Claude Code orchestrator partitions specifications into tasks assigned to headless Claude Code worker instances running in parallel git worktrees — Community Source: https://github.com/codingagentsystem/cas & https://github.com/mohsen1/claude-code-orchestrator

### Documented Token Savings and the "Coordination Penalty"
- **The Coordination Penalty on Small/Medium Tasks**: Community evaluations and benchmarks (e.g., claudefa.st and agent evaluations) document that on routine, tightly-scoped coding tasks, orchestrating external workers introduces an approximate **60% token markup** for zero accuracy gain due to handoff prompt serialization, system prompt duplication, and coordination exchanges — Community Benchmark: https://claudefa.st
- **Agent Teams Token Multiplier**: Anthropic's official documentation states that agent teams in plan mode consume approximately **7× more tokens** than standard sessions due to each teammate maintaining an independent context window — https://code.claude.com/docs/en/costs.md
- **Uncontrolled Multi-Agent Overhead**: Anthropic's context engineering research notes that poorly structured multi-agent systems can consume up to **15× more tokens** than single-agent workflows due to context duplication and redundant exploration loops — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- **Where Orchestration Actually Saves Tokens**: On large tasks involving massive codebases (reading hundreds of files or logs), delegating file scanning to workers or subagents isolates intermediate content, reducing the orchestrator's active context window by **50% to 70%+** and cutting frontier model costs in half — Community Benchmark: https://claudefa.st

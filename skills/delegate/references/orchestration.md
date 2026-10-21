# Orchestration efficiency — what the evidence says, and what we measured

Distilled from a research pass on 2026-10-21 (sources at the bottom) next to our own data: benchmarks 1–5
(`benchmarks/`) and a real 8-job session log (Ep 3). Prices are list prices on that date; plan quotas are not
published, so treat dollar figures as relative sizes. Re-check anything marked *unverified* before relying on it.

## 1. Where the cost is

| Claim | Evidence | Our number |
|---|---|---|
| Each orchestrator call re-sends the whole context; cache reads are cheap per token but the context keeps growing | Claude Code prompt-caching and costs docs [1][2] | Ep 3 session: 208 calls, context reached ~540k, ~315k cached tokens re-read per call |
| One orchestrator call can cost more than a whole cheap worker job | Pricing [3]: Sonnet 5.5 cache read $0.10/M → 315k ≈ $0.032; Opus 5.5 ≈ $0.063 | Haiku 5.5 worker job (illustrative: 25k spawn, 15 turns ~45k context, 8k out) ≈ $0.02; same on Sonnet ≈ $0.32 |
| So the metric is orchestrator calls per job | Inference from the two rows above | 13–34 calls per job in Ep 3; ~3 calls in hand-off benchmark runs |
| Multi-agent systems use ~15× the tokens of chat (agents ~4×); they pay off for parallel, independent work; most coding is a poor fit | Anthropic multi-agent research system [4] | agy per fresh run: 0.99–1.21× Claude tokens of doing it alone, same quality, 10–35× slower |
| Delegation saves when the worker absorbs reading/tool output the orchestrator would otherwise carry | Context-engineering post (subagents return 1–2k tokens) [5]; subagents post: skip for small or sequential tasks, use for 10+ files or 3+ independent pieces [6] | Inside a set-up session a hand-off job added 0.15–0.67× the new tokens of doing it directly (n = 1) |
| Plan/edit split helps when the planner is strong | Aider architect/editor: o1-preview + cheaper editor 85.0% vs 79.7% alone (2024, no cost data) [7]; Cognition: keep writes single-threaded, verifier sees only the diff [8] | — |

## 2. Claude Code subagents as workers (facts the design depends on)

- **Quota:** subagent requests draw on the same Claude plan [2]. How plans weight Haiku vs Sonnet is not
  documented (*unverified*).
- **Starting context:** the agent's own prompt + task + CLAUDE.md hierarchy (unless `omitClaudeMd: true`) + git
  status + preloaded skills; not the parent's history [9]. Fixed spawn cost seen locally: 12–31k cache-write
  tokens (one 59k); a general-purpose Haiku spike wrote 55k (this repo's CLAUDE.md is large) → the `worker`
  agent sets `omitClaudeMd: true`.
- **Model:** per-call `model` > frontmatter `model` > `CLAUDE_CODE_SUBAGENT_MODEL` > session model (since
  2.1.251; `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` restores the old override) [9].
- **Permissions:** subagents inherit the session's rules and mode; plugin agents ignore `permissionMode`,
  `hooks` and `mcpServers` [9]. A plugin's `hooks/hooks.json` PreToolUse hook fires inside subagents with
  `agent_type` / `agent_id`; a `deny` goes back to the model as the tool's error and the agent continues [10].
  (agy: a denial ends the round [ours].) Esc on a background subagent's prompt denies that one call.
- **Forks** inherit the full parent conversation (default on since 2.1.302) — with a big orchestrator context
  every worker turn would re-read it. Spawn the named agent [9].
- **Transcripts:** `~/.claude/projects/<project>/<session>/subagents/agent-<id>.jsonl`; undocumented schema.
  Seen: `type` user/assistant/attachment, `message.id`, `message.model`, `message.usage`, `tool_use` /
  `tool_result` (`is_error`), the final report as a `SubagentHandback` tool call. Usage repeats on every
  content-block line of one message → count once per `message.id` [ours, spike 2026-10-21; 11].
- **Continuation:** SendMessage resumes the same subagent with its history; the subagent cache TTL is 5 minutes
  by default (main conversation 1 hour on a subscription) [1].
- Limits: 3 nesting levels, 20 concurrent subagents by default [9].

## 3. Model routing

| Model | Input | Cache read | Output | Notes |
|---|---|---|---|---|
| Opus 5.5 | $4 | $0.20 | $20 | per M tokens [3] |
| Sonnet 5.5 | $2 | $0.10 | $10 | Terminal-Bench 4.0 70.6% [12] |
| Haiku 5.5 (≤100k prompt) | $0.10 | $0.01 | $0.50 | ×5 above 100k prompt; Terminal-Bench 39.2%; "narrowly scoped" subagent work [12] |
| Gemini 3.8 Flash | $0.75 | $0.075 | $3.75 | [13]; agy plan quota is separate and unpublished |

- **Haiku:** exact, enumerated edits — renames, one pattern across N files, format migrations with a machine
  check, extraction. At low effort it stops early and can claim done without running a check; medium halves
  early stopping (more output tokens); high for strict instruction following [14]. Keep its context under 100k.
- **Sonnet:** diagnosis, design, ambiguous briefs, multi-step changes where a check can fail for a non-obvious
  reason [12]. Neither judges visual output [ours].

## 4. Keeping the orchestrator cheap

- Cache breaks on model switch, effort change (except 5.5 models), fast mode, compaction, MCP connect without
  tool search, Claude Code upgrade; it survives file and CLAUDE.md edits, permission-mode changes, skills,
  subagent spawns [1]. A skill or command whose frontmatter names another model is a model switch.
- `/clear` between phases is free; `/compact` is itself a big request [2]. Plan in one session, dispatch from a
  small one that loads only the skill and the plan file.
- Briefs: objective, output format, tools/sources, boundaries [4]; vague requests trigger broad scanning [2].
- Verification: machine checks first; a reviewer that sees only the diff and the criteria catches what the
  writer missed [8][15]. Our server runs the checks once and hands back one verdict.
- Parallelism: 3–5 subagents in Anthropic's research system [4]; ~3 at once finishes sooner [6]; never two
  writers on the same files [6][8].

## 5. Worker failure modes and guards

- **Telling a model not to cheat barely helps:** METR saw o3's cheating stay at 70–80% with "do not cheat" [16].
- **Read-only tests are the measured middle ground, "especially for Claude models"** (ImpossibleBench); hiding
  tests drives hacking to ~0 but hurts real performance; strict prompting is mixed (93%→1% on LiveCodeBench,
  66%→54% on SWE-bench); Anthropic models "mostly modified test files directly" [17].
- **Ours:** agy hid a migration script in `__init__.py` and ran it through the allowed test runner (benchmark
  5); side-tracking into unrelated files and diagnosing a failing tool instead of taking the shortest path (Ep 3);
  a spec error executed faithfully for two rounds; "verified" on unreadable renders.
- **Enforce, don't ask:** delegate's guard hook denies edits outside the job's files and on `protect` paths,
  and commands not in the job's list; the verdict hashes protected files (`protected_changed`) and lists
  `unattributed` changes. Other tools do the same at different layers: Codex CLI sandbox + approval policy [18],
  OpenCode per-agent allow/ask/deny maps [19], SWE-agent's linting edit command [20].

## Sources

[1] https://code.claude.com/docs/en/prompt-caching · [2] https://code.claude.com/docs/en/costs ·
[3] https://platform.claude.com/docs/en/about-claude/pricing ·
[4] https://www.anthropic.com/engineering/multi-agent-research-system ·
[5] https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents ·
[6] https://claude.com/blog/subagents-in-claude-code · [7] https://aider.chat/2024/09/26/architect.html ·
[8] https://cognition.com/blog/multi-agents-working · [9] https://code.claude.com/docs/en/sub-agents ·
[10] https://code.claude.com/docs/en/hooks · [11] https://tokenade.net/fr/articles/claude-code-subagents-token-usage ·
[12] https://www.anthropic.com/claude-haiku-5-5 · [13] https://ai.google.dev/gemini-api/docs/pricing ·
[14] https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5 ·
[15] https://code.claude.com/docs/en/best-practices · [16] https://metr.org/blog/2025-06-05-recent-reward-hacking ·
[17] https://www.lesswrong.com/posts/qJYMbrabcQqCZ7iqm/impossiblebench-measuring-reward-hacking-in-llm-coding-agents-1 ·
[18] https://developers.openai.com/codex/concepts/sandboxing.md · [19] https://opencode.ai/en/docs/permissions ·
[20] https://hyper.ai/papers/2405.15793 · Also: https://www.anthropic.com/engineering/building-effective-agents,
https://code.claude.com/docs/en/permission-modes, https://cognition.com/blog/dont-build-multi-agents

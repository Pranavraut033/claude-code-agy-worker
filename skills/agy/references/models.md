# agy worker models — how to brief each one (growing list)

One section per model family. Each has **Official** (what Google documents, with a source;
re-checked by the orchestrator), **Measured** (what our own agy-worker jobs showed — job logs
live in `~/.claude/mcp/agy-worker/jobs/`), and a **Brief recipe**. When observation and docs
disagree, the observation wins and both are written down.

**Adding a model:** run `agy models`; give agy a research job (Argon, `network=True`,
`read_url` rules for ai.google.dev, antigravity.google, deepmind.google, blog.google) asking
for the same headings; spot-check 2–3 load-bearing claims yourself with curl; then add a
section here and a row to the timing table. Append to the changelog at the bottom.

---

## Shared: agy headless facts (all models)

- **Slugs:** `agy models` lists `<model>-low|medium|high` for both families (checked
  2026-10-19 on agy 1.4.2; the docs' example table shows only medium/high). The level is the
  thinking level; it cannot be turned off. Temperature/top-p are ignored on these models.
- **Permission rules** (`~/.gemini/antigravity-cli/settings.json` → `permissions.allow`):
  `action(prefix)` — plain prefix, `*` is literal. Regex form: `command(regex:npm run (build|lint))`
  (official, headless.md). Actions seen: `command`, `read_url`, `write_file`.
- **A denial ends the run in practice.** Docs say a soft-denied tool lets "the run continue";
  observed every time (7 rounds): the round stops, `response` is empty, stderr says
  "no output produced … auto-denied". Resuming that conversation afterwards wedged once
  (0 tool calls, ~40k output tokens, interrupted). → Start a fresh job; `agy_status` now
  returns a `hint` when this happens.
- **Baseline read-only allow-list** (kept in settings; models explore with these even when told
  not to): `ls`, `cat `, `head `, `tail `, `wc `, `grep `, `rg `, `git status`, `git diff`,
  `git log`, `git show`. Never a bare interpreter (`python3`), `rm`, `sleep`, `curl`, push.
- **Rules files** agy loads on its own: `~/.gemini/GEMINI.md|AGENTS.md`, workspace
  `AGENTS.md|GEMINI.md`, `.agents/rules/*.md` (needs YAML frontmatter with a snake_case
  `trigger`, else silently dropped), plus any on the path of a file it touches. A repo's
  rules can contradict your brief — check for them when a job ignores an instruction.
- **Briefs must be complete:** headless agy cannot ask; subagent questions are auto-skipped.
- `--print-timeout` default 5 min; agy-worker passes `timeout_s` (default 900 s).
- **Quota is visible for free:** `agy -p "/usage"` (agy-worker: `agy_usage()`) is answered
  by the CLI without a model call. Pools seen 2026-10-19 (Pro plan): "Gemini Models" 5-hour +
  weekly, "Claude and GPT models" 5-hour + weekly, "Gemini 4 Argon" weekly only. Piped output
  is TSV with UTC reset times. Whether Argon also drains the Gemini pools is unmeasured —
  compare /usage before and after an Argon job.
- `usage` and `duration_seconds` in `result` are cumulative over the conversation, so a
  resumed round's numbers include earlier rounds.

---

## gemini-3.8-flash (low / medium / high)

**Official** (ai.google.dev whats-new-gemini-3.8, models/gemini-3.8-flash, prompting-strategies):
released 2026-09-02, the default Antigravity model, "most intelligent Flash", Flash-tier speed.
1,048,576 input + 65,536 output tokens (separate pools). Knowledge cutoff March 2026.
`low` = latency-critical / straightforward edits; `medium` (default) = best balance, complex
code and agentic work; `high` = root-cause debugging, hard multi-step tasks. Available on all
Antigravity plans. Prompting: one delimiter style (XML tags *or* Markdown headings, never
mixed); rules first, long context first and the task last ("Based on the information
above…"); few-shot examples get copied, so they must obey every constraint; state rule
priority explicitly (hard constraints > order of operations > preferences); say whether to
narrate. Requiring XML/JSON text immediately before a tool call can cause
`Malformed_Function_Call` — ask for Markdown headings in reports instead.
*Unverified:* "prefers running diagnostic scripts before editing" (report cited
whats-new-3.6; not found on the live page) — but it matches what we saw.

**Measured:**
- Trivial 2-file rename + check: 36 s, 7 tool steps, clean. Fix-up round: 110 s.
- Improvises exploration: ran `ls -la`, `python3 -c '…'`, `git status`, `sleep` despite
  "no other commands" — each denial killed the round (4 of 6 Flash rounds).
- On a longer judgment-ish brief (doc edit, 3.7k-char brief) it stalled/wedged twice;
  Argon then did the same task in 6 min.
- Follows exact file lists well; scope stayed clean in every audited diff.

**Brief recipe:** packages where every task is fully specified (records from a template,
a spec applied across many files, a pipeline of known commands). Numbered tasks, exact
paths, one before→after example per pattern, a check after each task. Grant the baseline
read-only list *and* every command the package names before starting; say "Use the file
viewer to read files; run only: <list>". Default `medium`; `high` for longer packages
with more interdependent steps — try it before Argon (cheaper, all plans). *Not yet
measured:* Flash on a 30–60 min package; add the first such row to the timing table.

---

## gemini-4-argon (low / medium / high)

**Official** (ai.google.dev latest-model, models/gemini-4-argon; antigravity.google models):
released 2026-10-13, flagship sparse-MoE reasoning model. One shared 1,048,576 pool for
input + thinking + output, so huge inputs shrink room to think. 65,536 output by default.
Knowledge cutoff March 2026. "Hard prompts can take several minutes … set timeouts to at least
15 minutes" (verified on the live page). `low` can drop quality on hard tasks; `medium` default;
`high` slowest first token. No explicit caching — put static text (rules, references) first.
**Plan-limited:** paid Google AI Pro (non-trial) / Ultra / Enterprise only; quota refreshes
every 5 h up to a weekly cap (exact caps unpublished). Spend it deliberately.

**Measured:**
- Research job (web, 73 tool steps): 9–14 min per round; 300k+ input tokens. OCR
  reconcile (33 file views): 7.5 min, excellent careful report. Model-docs research: 14 min.
- Edit task Flash failed on: 6 min, clean, 3 follow-up rounds of ~1 min each.
- Got a 503 UNAVAILABLE once (round lost, resumed fine).
- Also tried an unlisted command once (`sleep`/acquire retry) — the read-only baseline
  and an explicit "run only" list are still needed.

**Brief recipe:** packages heavy on research legwork, careful transcription/verification,
or multi-file work whose details the brief can't fully pre-make; or a package Flash
failed. Static context first, tasks last. Default `timeout_s` 3600 is right; expect quiet
thinking stretches of several minutes. Ask for the per-task report in Markdown headings.
Don't spend it on packages Flash can do — the weekly quota is limited.

---

## Timing table (append a row per notable job)

| Date | Model | Task | Wall time | Tool steps | Outcome |
|---|---|---|---|---|---|
| 2026-10-19 | flash-medium | rename across 2 files + run check | 36 s | 7 | clean |
| 2026-10-19 | flash-medium | one-line UA edit + 3 downloads | 50 s + 181 s | 8 + 9 | denial ended r1; 1 of 3 downloads (site returned 429) |
| 2026-10-19 | flash-medium | judgment-ish doc edit, 3.7k-char brief | 119 s, then wedged | 12, 0 | denial, then resume wedged; handed to Argon |
| 2026-10-19 | argon-medium | same doc edit | 361 s | 12 | clean |
| 2026-10-19 | argon-medium | OCR reconcile, 7 facts, view-only | 446 s | 33 | good report (one 503 first) |
| 2026-10-19 | argon-medium | licence + photo research, web | 9.7–16 min/round | 73 | good research; downloads blocked |
| 2026-10-19 | argon-medium | this file's model research | 821 s | ~100 | good; 2 errors caught on audit |
| 2026-10-19 | flash-medium | 11 exact key replacements in one file (short brief) | 155 s | 12 | clean, scope clean |
| 2026-10-19 | flash-medium | package: 4 constant edits + 4 sequential renders (5-12 min commands, 3600 s timeout) | 37 min | ~25 | clean; `agy_wait` returns instantly as `stalled` while a long command runs (not a real stall), poll the output files instead (fixed in v0.1.0: an ACTIVE run_command counts as running) |
| 2026-10-19 | flash-medium | clip_sfx.py + mix.sh | 77 s | 12 | clip_sfx ok; mix.sh failed: system python3 has no numpy (script needs .venv/bin on PATH, a rule prefix cannot carry env vars) |
| 2026-10-19 | flash-high | package: build plugin repo (copy 3 files, 3 server fixes + selftest, scrub docs, manifests, README) | 547 s | 56 | all 8 tasks done; denied on the last check (`grep … \| awk` pipe) → no report; audit passed |
| 2026-10-19 | flash-medium | fix-up as fresh job: simplify one function + 6 README edits ("no pipes" in brief) | 114 s | 19 | clean, no denials |

## Changelog

- 2026-10-19: created — gemini-3.8-flash, gemini-4-argon; shared headless facts; 7 timing rows.
- 2026-10-19: recipes reframed for multi-task work packages (skill now briefs packages, not single edits); server default timeout 3600 s, stall 300 s.
- 2026-10-19: quota visibility — `agy_usage()` tool, `quota_low` on agy_start, skill budgets Argon by % left; record quota drop per notable job (baseline: Gemini weekly 59%, Argon weekly 31%).

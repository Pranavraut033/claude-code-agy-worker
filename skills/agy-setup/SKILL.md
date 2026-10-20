---
name: agy-setup
description: One-time setup for agy-worker — make the Antigravity CLI (agy) run bare. Archives agy's own MCP servers, skills, plugins and agents to ~/Documents (with a restore script), keeps the user's rules, adds the read-only allow-list baseline, and checks agy/uv/git. Use on first use of agy-worker, when the user runs /agy-setup, or when agy jobs show stray MCP calls or a large token baseline.
---

# /agy-setup — make agy bare for agy-worker

Why: agy loads every MCP server, skill, plugin and agent in its own config into every job. In
our measurements that doubled the fixed cost of an agy turn (16k → 7k tokens once bare), and stray
MCP calls were denied and ended whole rounds. With agy-worker, the calling Claude session lends a
job exactly the skills and MCP servers it needs (`agy_start(lend=[…], mcp=[…])`).

The folders involved (`~/.gemini/config/…`, `~/.agents/…`) are **shared with the Antigravity app and
IDE**, so they lose those items too. Everything is moved, not deleted, and `restore.sh` puts it back.

## Steps

1. Find the server: the `wait_cmd` of any agy-worker job names it, or use
   `~/.claude/plugins/cache/agy-worker/agy-worker/<version>/server/server.py`. Run the dry run
   (pass the current repo to also check what agy would load from it):
   ```
   uv run --script <server.py> setup <repo>
   ```
2. Show the user, briefly: missing tools (`tools` with a null), the MCP servers, enabled plugins and
   folders that would move, the rules that stay (`kept_rules`), the allow-list rules that would be
   added, and `repo_agy_config` (files in the repo agy loads by itself).
3. Ask once for a go-ahead. This changes the user's global Antigravity setup; do not apply it
   without a clear yes.
4. Apply: `uv run --script <server.py> setup --apply <repo>`. Report the archive folder and that
   `bash <archive>/restore.sh` undoes it.
5. Repo files (`GEMINI.md`, `AGENTS.md`, `.agents/…`) are never moved by setup — they belong to the
   repo and may be tracked by git. If `repo_agy_config` is not empty, say so: agy loads them in
   every job there, so those jobs are not bare. Offer to move them out (the user decides; tracked
   files then show as deletions) and lend what a job needs instead.
6. Restart Claude Code if agy-worker was updated in the same session.

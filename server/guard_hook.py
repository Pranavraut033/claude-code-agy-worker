#!/usr/bin/env python3
"""PreToolUse hook for the delegate plugin (stdlib only, runs on every Edit/Write/Bash call in any session).

Does nothing unless the call comes from a `delegate:worker` subagent. For a worker it finds the job (the job id
is in the worker's first message, which delegate_start wrote) and enforces the job's guard.json:
  - Edit/Write/MultiEdit/NotebookEdit: allowed inside allowed_files; denied outside them, on declared outputs
    (the commands write those) and on protected paths (what the checks read);
  - Bash: allowed when it is exactly one of the job's commands or a plain read-only command; denied otherwise.
A deny goes back to the worker as the tool's error (the run continues); reasons start with "delegate:" so the
server can count them. ponytail: exact string match for commands, no shell parsing.
"""
import fnmatch, json, os, re, sys
from pathlib import Path

JOBS = Path(os.environ.get("DELEGATE_HOME") or Path.home() / ".local/state/delegate") / "jobs"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_ONLY = re.compile(r"(ls|cat|head|tail|wc|grep|rg|git (status|diff|log|show))(\s[^|;&<>`$()]*)?")
JOB_RE = re.compile(r"Job (\d{4}-\d{6}-[0-9a-f]{4})\.")


def _match(paths, p):
    p = os.path.realpath(p)
    return any(p == a or p.startswith(a.rstrip("/") + "/") or fnmatch.fnmatch(p, a) for a in paths)


def _job_of(inp):
    """The worker's transcript sits at <parent transcript without .jsonl>/subagents/agent-<agent_id>.jsonl."""
    t, aid = inp.get("transcript_path") or "", inp.get("agent_id") or ""
    cands = [Path(t)] if Path(t).name == f"agent-{aid}.jsonl" else []
    if t.endswith(".jsonl") and aid:
        cands.append(Path(t[:-6]) / "subagents" / f"agent-{aid}.jsonl")
    for c in cands:
        try:
            with open(c, errors="replace") as f:
                hit = JOB_RE.search(f.readline())
            if hit:
                return hit.group(1)
        except OSError:
            pass
    return None


def decide(inp, jobs=JOBS):
    """None = no opinion (normal permission flow); else (decision, reason)."""
    if inp.get("agent_type") != "delegate:worker":
        return None
    tool, ti = inp.get("tool_name"), inp.get("tool_input") or {}
    if tool not in EDIT_TOOLS and tool != "Bash":
        return None
    job = _job_of(inp)
    g = jobs / job / "guard.json" if job else None
    if not g or not g.exists():
        return "deny", "delegate: no delegate job found for this worker; it may only read"
    g = json.loads(g.read_text())
    if tool == "Bash":
        cmd = (ti.get("command") or "").strip()
        if cmd in g["commands"] or READ_ONLY.fullmatch(cmd):
            return "allow", "delegate: listed command"
        return "deny", (f"delegate: `{cmd[:120]}` is not one of this job's commands. Do not work around it "
                        "(no other command, script or file a command runs): mark the task BLOCKED and continue.")
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if _match(g["protect"], path):
        return "deny", f"delegate: {path} is protected (the checks depend on it); leave it unchanged"
    if _match(g["outputs"], path):
        return "deny", f"delegate: {path} is written by the job's commands; do not edit it by hand"
    if not _match(g["allowed"], path):
        return "deny", f"delegate: {path} is outside this job's allowed files; say which file you need and why"
    return "allow", "delegate: inside the job's allowed files"


def main():
    try:
        d = decide(json.load(sys.stdin))
    except Exception as e:  # never break the user's session over a hook bug
        print(f"delegate guard hook: {e}", file=sys.stderr)
        return
    if d:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": d[0], "permissionDecisionReason": d[1]}}))


if __name__ == "__main__":
    main()

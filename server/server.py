#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.3,<3", "rich>=13"]
# ///
"""MCP server: hand mechanical file edits to the Antigravity CLI (`agy`), watch it, audit it.

    uv run --script server.py                # stdio MCP server
    uv run --script server.py selftest       # snapshot/discard check, no agy
    uv run --script server.py watch [job]    # live view of a job for humans
    uv run --script server.py wait <job>     # block until a job ends (background waiter)
    uv run --script server.py usage          # agy quota left

agy edits in place. Before each job the whole working tree is snapshotted into a git tree
object through a throwaway index (HEAD, branch and the real index are never touched), so
agy_diff shows exactly what changed and agy_discard can put agy's files back.
Job state lives on disk under $AGY_WORKER_HOME/jobs, so jobs outlive a server restart.
"""
import fnmatch, json, os, re, shlex, shutil, signal, subprocess, sys, tempfile, threading, time, uuid
from datetime import datetime, timezone
from pathlib import Path

JOBS = Path(os.environ.get("AGY_WORKER_HOME") or Path.home() / ".local/state/agy-worker") / "jobs"
AGY = shutil.which("agy") or str(Path.home() / ".local/bin/agy")
SETTINGS = Path.home() / ".gemini/antigravity-cli/settings.json"
AGY_MCP = Path.home() / ".gemini/config/mcp_config.json"  # agy's global MCP list (CLI, app and IDE share it)
CLAUDE_JSON = Path.home() / ".claude.json"
DEFAULT_LEND = ("ponytail",)  # skills every job borrows unless the caller passes lend=[]
DEFAULT_MODEL = "gemini-3.8-flash-medium"
WRITE_TOOLS = {"replace_file_content", "multi_replace_file_content", "write_to_file", "sed_file",
               "notebook_edit"}
LOW_PCT = 20  # agy_start flags a pool below this
STALL_S = 300  # Argon can think quietly for minutes; a Flash stall at 5 min is real
PROCS = {}  # job id -> live Popen (stdin open: a session that takes more messages)
CUR = {}    # job id -> round number the session's output is being written to

GUARD = """You are the worker on a work package for an orchestrator who will audit every change
you make. Plan the tasks, then work through them in order, running each task's check before
moving on. Follow these rules exactly:
- Create or edit files ONLY within: {files}. A folder there covers every file under it,
  including new ones the task asks for. Do not delete, rename, create or edit anything outside
  that. If the task truly needs another file, stop and say which one and why.
- No state-changing git (commit, push, checkout, reset, stash, rebase, merge, branch), no
  package installs, no file deletion. {network}
- Never touch .git/, .claude/, .env or anything that looks like a credential.
- Change only what the task asks. No reformatting, renaming or refactoring beyond it; keep
  the surrounding style.
- If a task is ambiguous or blocked, do not guess: skip it, note why, and continue with the
  other tasks.
- Run only the exact command lines the brief names, character for character (a named line may
  contain a pipe). Never improvise a command: no pipes (|) of your own, no `python3 -c`, no
  sed/awk, no sleep, no extra flags. Read and search files with your file
  tools, not the shell. A command that is not on the allow-list ends your WHOLE run and throws
  away the report, even when all the work is done.
- Never call an MCP tool unless the LENT section below lends you that server; any other MCP call
  is denied and ends your run.
- A subagent may only read and research for you; it never edits files or runs commands. Do the
  edits yourself.
- Never write code into a file so that an allowed command runs it (a test file, `__init__.py`,
  conftest, a config): that is running an unlisted program. Edit each file with your file tools.
- Run every command in the foreground and wait for it to finish; never leave background tasks.
- Do not read outside the repository (library sources, virtualenvs, caches) unless asked to.
- Stay on the task: read only files the task names or its result depends on; no surveying folders or
  comparing sibling files. If a command fails, take the shortest path to the result (the source it
  summarises, another input) and note the failure in one line; diagnose a tool only if fixing it is the task.
  Anything odd outside the task gets one line in the report, not a fix or an investigation.
- At most 2 attempts per defect: if a fix does not hold after 2 tries, stop, mark it failed with
  your best guess at the root cause, and move on.
- Say "done" only after re-running that task's check and seeing it pass. You cannot judge visual
  output (images, renders): say "rendered", never "verified"; the orchestrator looks at it.
- End with a terse report and nothing else, in exactly this shape:
    1. done|skipped|failed — check: pass|fail|not run — <one short note>
    2. ...
    Files: <changed paths, comma-separated>
  If the brief names a report file for longer findings, write them there, opening with a
  summary of at most 10 lines; do not repeat them in the final message.

{lent}PACKAGE
{brief}
"""


def _guard(m, brief):
    net = ("Web search and downloads are allowed for this task; on HTTP 401/403/429, a CAPTCHA "
           "or a bot challenge, stop that source at once: never bypass, spoof or retry in a loop."
           if m.get("network") else "No network access.")
    lent = "".join(f"### {label}\n{text.strip()}\n\n" for label, text in m.get("lent_text", []))
    if m.get("borrowed_mcp"):
        lent += "### MCP servers you may use\n" + ", ".join(m["borrowed_mcp"]) + "\n\n"
    lent = f"LENT BY THE ORCHESTRATOR — follow these for this package\n\n{lent}" if lent else ""
    files = ", ".join(m["allowed"])
    if m.get("outputs"):
        files += (". The commands you run also write these; never edit them with your file tools: "
                  + ", ".join(m["outputs"]))
    return GUARD.format(files=files, network=net, brief=brief, lent=lent)


def _skill(item, top):
    """A skill or instruction file the caller lends: a path (file, or a folder with SKILL.md), or a
    Claude skill name — looked up in the project's .claude/skills, ~/.claude/skills, then the plugin
    cache (newest version; `plugin:skill` picks the plugin). Returns (label, text without frontmatter)."""
    home = Path.home()
    if "/" in item or item.endswith(".md"):
        p = Path(os.path.expanduser(item))
        p = p if p.is_absolute() else Path(top) / p
        cands = [p / "SKILL.md" if p.is_dir() else p]
    else:
        plugin, _, name = item.rpartition(":")
        cands = [] if plugin else [Path(top) / ".claude/skills" / name / "SKILL.md",
                                   home / ".claude/skills" / name / "SKILL.md"]
        cache = sorted((home / ".claude/plugins/cache").glob(f"*/{plugin or '*'}/*/skills/{name}/SKILL.md"),
                       key=os.path.getmtime, reverse=True)
        cands += cache
    for c in cands:
        if c.is_file():
            text = c.read_text(errors="replace")
            if text.startswith("---"):
                text = text.split("---", 2)[-1]  # drop the frontmatter
            return f"{'skill' if c.name == 'SKILL.md' else 'file'}: {item}", text
    raise FileNotFoundError(f"lend: no skill or file '{item}' (looked in {', '.join(str(c) for c in cands[:3])})")


def _claude_mcp(name, top):
    """Claude's own config for an MCP server, converted to agy's mcp_config.json shape."""
    srcs = []
    if CLAUDE_JSON.exists():
        d = json.loads(CLAUDE_JSON.read_text())
        srcs += [d.get("mcpServers") or {}, ((d.get("projects") or {}).get(str(top)) or {}).get("mcpServers") or {}]
    pj = Path(top) / ".mcp.json"
    if pj.exists():
        srcs.append(json.loads(pj.read_text()).get("mcpServers") or {})
    for src in srcs:
        e = src.get(name)
        if e and e.get("command"):
            return {k: e[k] for k in ("command", "args", "env") if e.get(k)}
        if e and e.get("url"):
            return {"serverUrl": e["url"], **({"headers": e["headers"]} if e.get("headers") else {})}
    raise KeyError(f"mcp: Claude has no MCP server '{name}' (user config, project config or .mcp.json)")


def _borrow_mcp(m, items):
    """Lend Claude's MCP servers to this job: add them to agy's global list (agy reads it only at
    startup) and allow `server/*` or one `server/tool`. Released by agy_close / agy_cancel; a job
    whose process is gone is released at the next agy_start. ponytail: one JSON registry, no lock."""
    reg_p = JOBS.parent / "borrowed.json"
    reg = json.loads(reg_p.read_text()) if reg_p.exists() else {}
    cfg = json.loads(AGY_MCP.read_text()) if AGY_MCP.exists() else {}
    servers = cfg.setdefault("mcpServers", {})
    rules = []
    for it in items:
        srv, _, tool = it.partition("/")
        if srv not in servers:
            servers[srv] = _claude_mcp(srv, m["top"] or m["cwd"])
            reg.setdefault(srv, {"jobs": [], "ours": True})
        reg.setdefault(srv, {"jobs": [], "ours": False})["jobs"].append(m["id"])
        rules.append(f"mcp({srv}/{tool or '*'})")
    AGY_MCP.parent.mkdir(parents=True, exist_ok=True)
    AGY_MCP.write_text(json.dumps(cfg, indent=2) + "\n")
    reg_p.parent.mkdir(parents=True, exist_ok=True)
    reg_p.write_text(json.dumps(reg, indent=1))
    agy_permissions(add=rules)
    m["borrowed_mcp"], m["borrowed_rules"] = [i.partition("/")[0] for i in items], rules


def _release_mcp(m):
    if not m.get("borrowed_mcp"):
        return
    reg_p = JOBS.parent / "borrowed.json"
    reg = json.loads(reg_p.read_text()) if reg_p.exists() else {}
    cfg = json.loads(AGY_MCP.read_text()) if AGY_MCP.exists() else {"mcpServers": {}}
    for srv in m["borrowed_mcp"]:
        e = reg.get(srv)
        if not e:
            continue
        e["jobs"] = [j for j in e["jobs"] if j != m["id"]]
        if not e["jobs"]:
            if e.get("ours"):
                cfg.get("mcpServers", {}).pop(srv, None)
            reg.pop(srv)
    AGY_MCP.write_text(json.dumps(cfg, indent=2) + "\n")
    reg_p.write_text(json.dumps(reg, indent=1))
    still = {r for jid in {j for e in reg.values() for j in e["jobs"]} for r in _load(jid).get("borrowed_rules", [])}
    agy_permissions(remove=[r for r in m["borrowed_rules"] if r not in still])
    m["borrowed_mcp"] = []
    _save(m)


def _gc_borrowed():
    reg_p = JOBS.parent / "borrowed.json"
    if not reg_p.exists():
        return
    for jid in {j for e in json.loads(reg_p.read_text()).values() for j in e["jobs"]}:
        try:
            m = _load(jid)
        except FileNotFoundError:
            continue
        if not _alive(m):
            _release_mcp(m)


def _repo_agy_config(top):
    """agy loads a repo's own GEMINI.md / AGENTS.md / .agents config by itself, so such a job is not bare."""
    return [n for n in ("GEMINI.md", "AGENTS.md", ".agents/rules", ".agents/skills", ".agents/agents",
                        ".agents/plugins", ".agents/mcp_config.json") if (Path(top) / n).exists()]


def _git(top, *args, env=None, inp=None):
    r = subprocess.run(["git", "-C", str(top), *args], capture_output=True, env=env, input=inp)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def _toplevel(cwd):
    try:
        return Path(os.path.realpath(_git(cwd, "rev-parse", "--show-toplevel").decode().strip()))
    except RuntimeError:
        return None


def snapshot(top):
    """Tree object of the working tree as it is now (tracked + untracked, minus ignored)."""
    real = Path(_git(top, "rev-parse", "--absolute-git-dir").decode().strip()) / "index"
    with tempfile.TemporaryDirectory() as d:
        idx = Path(d) / "index"
        if real.exists():
            shutil.copy(real, idx)  # ponytail: reuse the stat cache so big repos snapshot fast
        env = {**os.environ, "GIT_INDEX_FILE": str(idx)}
        _git(top, "add", "-A", env=env)
        return _git(top, "write-tree", env=env).decode().strip()


def _meta_path(jid):
    return JOBS / jid / "meta.json"


def _load(jid):
    p = _meta_path(jid)
    if not p.exists():
        raise ValueError(f"no job {jid}")
    return json.loads(p.read_text())


def _save(m):
    _meta_path(m["id"]).write_text(json.dumps(m, indent=1))


def _alive(m):
    p = PROCS.get(m["id"])
    if p is not None:
        return p.poll() is None
    pid = m.get("pid", 0)
    if pid <= 0:  # os.kill(-1, ...) would address every process
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _launch(m, prompt, conversation=None):
    """Start an agy session (stream-json in and out; stdin stays open for more messages) and
    send the first message. agy reads its allow-list only at startup, so a session that hit a
    denial is restarted on the same conversation instead (see agy_resume)."""
    seg = m.get("seg", 0) + 1
    cmd = [AGY, "--input-format", "stream-json", "--output-format", "stream-json",
           "--mode", "accept-edits", "--model", m["model"]]
    if conversation:
        cmd += ["--conversation", conversation]
    p = subprocess.Popen(cmd, cwd=m["cwd"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=open(JOBS / m["id"] / f"s{seg}.err", "w"), text=True, bufsize=1,
                         start_new_session=True)
    PROCS[m["id"]], m["pid"], m["seg"] = p, p.pid, seg

    def pump(jid=m["id"]):  # route each output line into the file of the round it belongs to
        for line in p.stdout:
            with open(JOBS / jid / f"r{CUR[jid]}.jsonl", "a") as f:
                f.write(line)
    _send(m, prompt)
    threading.Thread(target=pump, daemon=True).start()


def _send(m, text):
    """One message to the live session = one round."""
    n = len(m["rounds"]) + 1
    (JOBS / m["id"] / f"r{n}.jsonl").touch()
    m["rounds"].append({"n": n, "started": time.time(), "seg": m["seg"], "err": f"s{m['seg']}.err"})
    CUR[m["id"]] = n
    _save(m)
    p = PROCS[m["id"]]
    p.stdin.write(json.dumps({"event": "user", "message": {"content": text}}) + "\n")
    p.stdin.flush()


def _live(m):
    p = PROCS.get(m["id"])
    return p is not None and p.poll() is None and not p.stdin.closed


def _close(m, wait=20):
    """Close the session's stdin: agy finishes the current turn and exits."""
    p = PROCS.pop(m["id"], None)
    if p is not None and p.poll() is None:
        try:
            p.stdin.close()
            p.wait(wait)
        except (OSError, subprocess.TimeoutExpired):
            os.killpg(p.pid, signal.SIGTERM)


def _events(m, n):
    p = JOBS / m["id"] / f"r{n}.jsonl"
    out = []
    for line in p.read_text(errors="replace").splitlines() if p.exists() else []:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # last line may be half-written while agy runs
    return out


def _is_write(tool):
    """agy renamed its file tools between versions (write_to_file -> write_file in 1.4.3), so
    besides the known names, any tool whose name says write/edit/replace counts as an edit."""
    return tool in WRITE_TOOLS or bool(re.search(r"write|edit|replace", tool or ""))


def _parse(m):
    """Fold every round's events into what agy did."""
    edits, commands, steps, denied = [], [], [], []
    result, conv, seen, tokens = None, m.get("conversation"), {}, {}
    for r in m["rounds"]:
        last_cmd, result, seg = None, None, r.get("seg", r["n"])  # old jobs: one process per round
        for e in _events(m, r["n"]):
            if e.get("event") == "init":
                conv = e.get("conversation_id") or conv
            s = e.get("step_update")
            if s and s.get("step_type") == "tool":
                params = (s.get("tool_info") or {}).get("parameters") or {}
                target = params.get("TargetFile") or params.get("AbsolutePath") or params.get("Path") or \
                    params.get("CommandLine") or params.get("Url") or params.get("query") or ""
                steps.append({"round": r["n"], "tool": s.get("tool_name"), "state": s.get("state"),
                              "target": target})
                if s.get("state") == "DONE":
                    if _is_write(s.get("tool_name")) and target:
                        target = os.path.realpath(target)  # symlinked paths vs git's real ones
                        if target not in edits:
                            edits.append(target)
                    if s.get("tool_name") == "run_command":
                        commands.append(target)
                        last_cmd = target
            if e.get("event") == "result":
                result = e["result"]
                tokens[seg] = ((result.get("usage") or {}).get("total_tokens") or 0)  # cumulative per session
                das = result.get("denied_actions") or []
                new, seen[seg] = das[seen.get(seg, 0):], len(das)  # a session repeats earlier denials
                for d in new:
                    # a denied command is logged as a DONE step: the round's last run_command
                    if d.get("action") == "command" and last_cmd:
                        d = {**d, "command": last_cmd}
                        if commands and commands[-1] == last_cmd:
                            commands.pop()  # it never ran
                    denied.append(d)
    if conv != m.get("conversation"):
        m["conversation"] = conv
        _save(m)
    if result is not None:
        result = {**result, "_tokens": sum(tokens.values()), "_denied_now": bool(new)}
    return edits, commands, steps, denied, result


def _state(m, result):
    if result is not None:
        return "done" if result.get("status") == "SUCCESS" else "failed"
    if _alive(m):
        last = max((JOBS / m["id"]).glob("r*.jsonl"), key=os.path.getmtime)
        quiet = time.time() - os.path.getmtime(last)
        if quiet > STALL_S:
            steps = [e["step_update"] for e in _events(m, len(m["rounds"])) if e.get("event") == "step_update"]
            if steps and steps[-1].get("tool_name") == "run_command" and steps[-1].get("state") == "ACTIVE":
                return "running"  # one long command emits no events while it runs
            return "stalled"
        return "running"
    return "failed"


def _allowed(m, path, key="allowed"):
    p = os.path.realpath(path)
    for a in m.get(key) or []:
        if p == a or p.startswith(a.rstrip("/") + "/") or fnmatch.fnmatch(p, a):
            return True
    return False


from mcp.server.mcpserver import MCPServer  # noqa: E402  (selftest runs without the server)

mcp = MCPServer("agy-worker", instructions=(
    "Delegate a mechanical file/code edit to the Antigravity CLI (agy) and audit it. "
    "agy_start -> agy_wait/agy_status while it works -> agy_diff to audit (scope check, "
    "denied actions) -> agy_resume for a fix-up round, or agy_discard to revert its files. "
    "agy edits in place; nothing is committed. agy_permissions maintains agy's command "
    "allow-list (headless agy silently denies any command not on it)."))


@mcp.tool()
def agy_start(brief: str, cwd: str, allowed_files: list[str], model: str = DEFAULT_MODEL,
              timeout_s: int = 3600, network: bool = False, checks: list[str] | None = None,
              check_timeout_s: int = 600, lend: list[str] | None = None,
              mcp: list[str] | None = None, handoff: bool = False,
              outputs: list[str] | None = None) -> dict:
    """Start agy on a work package (several related tasks), in place in `cwd` (absolute path). `brief` says the
    exact change, what done means, and which checks to run. `allowed_files` are the only
    paths agy may edit (absolute, or relative to cwd; a directory or a glob also works).
    The brief is wrapped in a guard preamble. network=True lets a research job browse and
    download (it must stop on 401/403/429/CAPTCHA). `checks` are shell commands (your own, run
    in `cwd` with your permissions, not agy's) the waiter runs when agy finishes: you then get
    one verdict with scope, stat and each check's result instead of spending turns on them.
    agy runs bare: it gets no skills or MCP servers of its own. `lend` lends skills or instruction
    files for this job (Claude skill names, `plugin:skill`, or paths; default ["ponytail"], pass []
    for none); they are inlined into the brief. `mcp` lends Claude's MCP servers ("server" for all its
    tools, "server/tool" for one), enabled for this job only and released by agy_close/agy_cancel.
    Returns {job, git, wait_cmd, watch_cmd} immediately: run wait_cmd as a background shell task and
    read the verdict it prints. `handoff=True`: the owner audits, not you — give them watch_cmd (a
    live view that ends with the checks and the verdict) and end your turn; the agy session ends by
    itself after this round (agy_resume restarts it on the same conversation). `outputs`: files, folders
    or globs the brief's commands write (a renderer's timeline, a log, a mix); they are not flagged as
    unattributed or out of scope, and agy is told not to edit them with its file tools."""
    cwd = os.path.realpath(os.path.expanduser(cwd))
    if not os.path.isdir(cwd):
        return {"error": f"cwd {cwd} is not a directory"}
    if not allowed_files:
        return {"error": "allowed_files is empty: name the files agy may edit"}
    allowed = [a if os.path.isabs(a) else os.path.join(cwd, a) for a in allowed_files]
    top = _toplevel(cwd)
    m = {"id": time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4], "cwd": cwd,
         "top": str(top) if top else None, "base": snapshot(top) if top else None,
         "allowed": [os.path.realpath(a) for a in allowed], "model": model,
         "timeout_s": timeout_s, "brief": brief, "network": network, "rounds": [], "created": time.time(),
         "checks": checks or [], "check_timeout_s": check_timeout_s,
         "outputs": [os.path.realpath(o if os.path.isabs(o) else os.path.join(cwd, o)) for o in outputs or []]}
    try:
        m["lent_text"] = [_skill(i, m["top"] or cwd) for i in (DEFAULT_LEND if lend is None else lend)]
    except FileNotFoundError as e:
        return {"error": str(e)}
    _gc_borrowed()
    if mcp:
        try:
            _borrow_mcp(m, mcp)
        except (KeyError, json.JSONDecodeError) as e:
            return {"error": str(e)}
    pools = _usage_pools(model)
    m["quota_before"] = {f'{p["pool"]} · {p["window"]}': p["left_pct"] for p in pools}
    (JOBS / m["id"]).mkdir(parents=True)
    _launch(m, _guard(m, brief))
    if handoff:  # nobody will agy_close it: EOF makes agy finish this turn, then exit
        PROCS.pop(m["id"]).stdin.close()
    out = {"job": m["id"], "git": bool(top), "wait_cmd": _wait_cmd(m["id"]),
           "watch_cmd": _wait_cmd(m["id"]).replace(" wait ", " watch ")}
    if not top:
        out["warning"] = "not a git repo: agy_diff and agy_discard cannot work for this job"
    own = _repo_agy_config(top or cwd)
    if own:
        out["repo_agy_config"] = {"files": own, "note": "agy loads these by itself, so this job is not bare; "
                                  "move them out of the repo and lend what a job needs instead"}
    low = [p for p in pools if p["left_pct"] < LOW_PCT]
    if low:
        out["quota_low"] = low
    return out


def _wait_cmd(job):
    return f"{shutil.which('uv') or 'uv'} run --script {Path(__file__).resolve()} wait {job}"


def _run_checks(m):
    """Run the job's checks the way the orchestrator would in a shell. ponytail: sequential, no sandbox
    (they are the orchestrator's own commands, with its permissions)."""
    out = []
    for cmd in m.get("checks") or []:
        try:
            r = subprocess.run(cmd, shell=True, cwd=m["cwd"], capture_output=True, text=True,
                               timeout=m.get("check_timeout_s", 600), stdin=subprocess.DEVNULL)
            rc, tail = r.returncode, (r.stdout + r.stderr).strip()[-400:]
        except subprocess.TimeoutExpired:
            rc, tail = "timeout", f"no result after {m.get('check_timeout_s', 600)} s"
        except OSError as e:  # e.g. the job's folder is gone
            rc, tail = "error", str(e)
        out.append({"cmd": cmd[:160], "rc": rc, "ok": rc == 0, "tail": tail})
    return out


def _verdict(job):
    """One compact answer for a finished round: state, cost, scope, stat, each check. `clean` means
    done, nothing denied, nothing outside allowed_files and every check passed; `not_from_agy_edits`
    is listed apart because other sessions legitimately edit the same tree."""
    m = _load(job)
    st = agy_status(job)
    v = {k: st.get(k) for k in ("job", "state", "round", "elapsed_s", "tokens", "quota_drop_pct",
                                "denied", "edits", "agy_error", "hint", "stderr") if st.get(k) not in (None, [], {})}
    v["report"] = (st.get("report") or "")[:2500] or None
    if m.get("top"):
        d = agy_diff(job, max_chars=0)
        v.update(out_of_scope=d["out_of_scope"], not_from_agy_edits=d["not_from_agy_edits"],
                 stat=d["stat"].strip().splitlines()[-1:] or ["no changes"])
        # changed inside the package without an agy edit step: another session, or agy running code it
        # wrote (benchmark 5: a migration script hidden in __init__.py, run via the allowed test command)
        # declared outputs are expected to change without an edit step (Ep 3: every generator job read unclean)
        v["unattributed"] = [f for f in d["not_from_agy_edits"]
                             if _allowed(m, _abs(m, f)) and not _allowed(m, _abs(m, f), "outputs")]
        changed = [f for f in d["changed"] if f not in d["out_of_scope"] and not _allowed(m, _abs(m, f), "outputs")]
        if changed:  # light quality check for free: one changed file, capped
            pick = changed[len(changed) // 2]  # ponytail: middle file, not random; the first is often trivial
            v["sample"] = {"file": pick, "diff": agy_diff(job, files=[pick], max_chars=1500)["diff"]}
    # run the checks on every finished round: agy can finish its work and then get a 503 (status
    # ERROR), and the checks, not agy's status, decide whether the work is good
    checks = _run_checks(m) if st["state"] != "running" else []
    v["checks"] = checks
    v["all_checks_pass"] = all(c["ok"] for c in checks) if checks else None
    finished = st["state"] == "done" or bool(st.get("agy_error") and st.get("report"))
    v["clean"] = (finished and not st.get("denied_now") and not v.get("out_of_scope")
                  and not v.get("unattributed") and v["all_checks_pass"] is not False)
    (JOBS / job / f"verdict-r{st['round']}.json").write_text(json.dumps(v))
    return v


def _parse_usage(text):
    """`agy -p /usage` piped output: pool<TAB>window<TAB>NN%<TAB>reset ISO (UTC)."""
    pools = []
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) == 4 and f[2].endswith("%"):
            reset = datetime.fromisoformat(f[3].replace("Z", "+00:00"))
            pools.append({"pool": f[0], "window": f[1], "left_pct": int(f[2][:-1]),
                          "resets_in_h": round((reset - datetime.now(timezone.utc)).total_seconds() / 3600, 1)})
    return pools


def _usage_pools(model):
    """Quota pools a model draws from. Argon has its own weekly pool; ponytail: assume it
    also draws on the shared Gemini pools until /usage shows otherwise."""
    pools = agy_usage().get("pools", [])
    m = model.lower()
    fam = "argon" if "argon" in m else "claude" if ("claude" in m or "gpt" in m) else "gemini"
    return [p for p in pools if (fam == "argon" and "argon" in p["pool"].lower())
            or (fam in ("argon", "gemini") and p["pool"].lower() == "gemini models")
            or (fam == "claude" and "claude" in p["pool"].lower())]


@mcp.tool()
def agy_usage() -> dict:
    """agy's remaining plan quota per pool (Gemini, Gemini 4 Argon, Claude/GPT) for the
    5-hour and weekly windows, with hours until each resets. Free: `/usage` is answered by
    the CLI, no model call. Check before choosing Argon or starting a long package."""
    try:
        r = subprocess.run([AGY, "-p", "/usage"], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=60)
        pools = _parse_usage(r.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return {"error": str(e)}
    return {"pools": pools} if pools else {"error": (r.stderr or r.stdout)[-500:]}


def _rel(m, p):
    """Shorter paths in tool output: relative to the repo (or cwd). ponytail: saves tokens."""
    base = m.get("top") or m["cwd"]
    return os.path.relpath(p, base) if isinstance(p, str) and p.startswith(base) else p


def _short(m, target):
    t = str(target)
    if "/.system_generated/" in t:  # agy reading back a page it fetched
        return "(fetched page)"
    t = str(_rel(m, t))
    return t[-80:] if t.startswith(("/", ".")) else t[:80]  # paths: keep the tail; urls, queries: the head


def _abs(m, p):
    return p if os.path.isabs(p) else os.path.join(m.get("top") or m["cwd"], p)


def _report(m, text):
    """agy's `response` joins every text message of the round, progress included ('Rendering X (14%)...':
    3.5k tokens before the result in the Ep 3 session). The report the guard asks for is the last block
    that opens with '1. done|skipped|failed'; without one, the end is where agy stopped. Paths relative.
    The raw text stays in the job's r*.jsonl."""
    starts = [x.start() for x in re.finditer(r"(?m)^[ \t]*1\.\s+(done|skipped|failed)\b", text)]
    if starts:
        text = text[starts[-1]:]
    elif len(text) > 1500:
        text = "…" + text[-1500:]
    text = text.replace((m.get("top") or m["cwd"]).rstrip("/") + "/", "")
    text = re.sub(r"\[([^\]]+)\]\(file://[^)]*\)", r"\1", text)  # agy's markdown file links
    # the Files line repeats what the verdict's stat and scope lists say
    text = re.sub(r"(?m)^(Files:.{300}).+$", r"\1 …(see stat)", text)
    return text.strip()


@mcp.tool()
def agy_status(job: str | None = None, steps: int = 5, full_report: bool = False) -> dict:
    """One job's progress, compact: state (running|stalled|done|failed|cancelled), elapsed,
    step/edit counts, the last `steps` tool steps as short lines, files edited (relative),
    commands run, denied actions, agy's report (first 2500 chars unless full_report).
    With no job, lists recent jobs."""
    if job is None:
        ids = sorted((p.name for p in JOBS.iterdir() if p.is_dir()), reverse=True)[:15] \
            if JOBS.exists() else []
        out = []
        for jid in ids:
            m = _load(jid)
            *_, result = _parse(m)
            out.append({"job": jid, "state": m.get("cancelled") and "cancelled" or _state(m, result),
                        "cwd": m["cwd"], "brief": m["brief"][:80]})
        return {"jobs": out}
    m = _load(job)
    edits, commands, st, denied, result = _parse(m)
    r = m["rounds"][-1]
    n = r["n"]
    ep = JOBS / job / r.get("err", f"r{n}.err")
    err = ep.read_text(errors="replace").strip() if ep.exists() else ""
    state = "cancelled" if m.get("cancelled") else _state(m, result)
    if state in ("running", "stalled") and time.time() - r["started"] > m["timeout_s"]:
        agy_cancel(job)  # stream sessions have no --print-timeout, so the server enforces it
        state, err = "cancelled", f"timed out after {m['timeout_s']} s. " + err
    report = _report(m, (result or {}).get("response") or "")
    if not full_report and len(report) > 2500:
        report = report[:2500] + " …[truncated: agy_status(full_report=True)]"
    done_steps = [x for x in st if x["state"] != "ACTIVE"]
    took = (result or {}).get("duration_seconds")  # cumulative over rounds; wall clock while running
    out = {"job": job, "state": state, "round": n,
           "elapsed_s": round(took) if took else round(time.time() - r["started"]),
           "n_steps": len(done_steps),
           "steps": [f'{x["tool"]} {x["state"].lower()} {_short(m, x["target"])}'
                     for x in done_steps[-steps:]],
           "edits": [_rel(m, e) for e in edits], "commands": [c[:120] for c in commands],
           "denied": denied, "denied_now": bool((result or {}).get("_denied_now")),
           "agy_error": (result or {}).get("error"), "report": report or None,
           "tokens": (result or {}).get("_tokens"), "session": "open" if _live(m) else "closed"}
    vf = JOBS / job / f"verdict-r{n}.json"
    if vf.exists() and state != "running":
        out["verdict"] = json.loads(vf.read_text())
    if state != "running" and m.get("quota_before"):
        if "quota_after" not in m:  # one /usage call per finished job
            m["quota_after"] = {f'{p["pool"]} · {p["window"]}': p["left_pct"] for p in _usage_pools(m["model"])}
            _save(m)
        # ponytail: the pools are shared with other sessions, so this is an upper bound
        out["quota_drop_pct"] = {k: v - m["quota_after"][k] for k, v in m["quota_before"].items()
                                 if k in m["quota_after"]}
    if err and (state != "done" or "error" in err.lower()):
        out["stderr"] = err[-400:]
    if (result or {}).get("_denied_now"):
        # a resume after a denial-ended run wedged (0 tool steps, ~40k output tokens) on 2026-10-19
        out["hint"] = ("This round ended on a denied command (see `denied`), so its edits may be partial "
                       "and there is no report; audit the diff first. Grant the rule (agy_permissions) or "
                       "forbid the command, then agy_resume: it restarts agy on the same conversation so "
                       "the new rule applies and the context is kept.")
    return out


@mcp.tool()
async def agy_wait(job: str, timeout_s: int = 90) -> dict:
    """Block until the job finishes or stalls, or timeout_s (max 540) passes; returns
    agy_status. Use this instead of polling agy_status in a loop."""
    import anyio
    end = time.time() + min(timeout_s, 540)
    while time.time() < end:
        s = agy_status(job)
        if s["state"] not in ("running",):
            return s
        await anyio.sleep(3)
    return agy_status(job)


@mcp.tool()
def agy_diff(job: str, files: list[str] | None = None, max_chars: int = 6000) -> dict:
    """Audit: files changed since the job's snapshot (relative paths), which are outside
    allowed_files, which changed without an agy edit step (another session, or agy via a
    shell command), denied actions, the --stat, and the unified diff truncated to max_chars.
    Read `stat` first, then pass `files` to diff only the ones worth reading."""
    m = _load(job)
    if not m["top"]:
        return {"error": "job is not in a git repo; no snapshot to diff against"}
    edits, commands, _, denied, _ = _parse(m)
    top = Path(m["top"])
    now = snapshot(top)
    changed = [str(top / f) for f in
               _git(top, "diff", "--name-only", m["base"], now).decode().splitlines()]
    paths = ["--", *[os.path.relpath(_abs(m, f), top) for f in files]] if files else []
    diff = _git(top, "diff", m["base"], now, *paths).decode(errors="replace")
    return {"changed": [_rel(m, f) for f in changed],
            "out_of_scope": [_rel(m, f) for f in changed if not (_allowed(m, f) or _allowed(m, f, "outputs"))],
            "not_from_agy_edits": [_rel(m, f) for f in changed if f not in edits],
            "commands": [c[:120] for c in commands], "denied": denied,
            "stat": _git(top, "diff", "--stat", m["base"], now).decode(),
            "diff": diff[:max_chars] + (f"\n...[truncated, {len(diff)} chars: pass files=[…]]"
                                        if len(diff) > max_chars else "")}


@mcp.tool()
def agy_resume(job: str, message: str, checks: list[str] | None = None) -> dict:
    """Next message to the job's agy session: a fix-up round or the next package in the same
    context (the guard rules and allowed files are restated). A live session takes it in ~2-3 s;
    after a denial (agy reads rules only at startup) or a server restart, agy is restarted on
    the same conversation, context kept. The diff baseline stays the original snapshot.
    `checks` replaces the job's checks for this round. Returns wait_cmd, like agy_start."""
    m = _load(job)
    *_, result = _parse(m)
    if _state(m, result) == "running":
        return {"error": "job is still running; wait for it or agy_cancel first"}
    if not m.get("conversation"):
        return {"error": "no conversation id recorded for this job; start a new one"}
    m.pop("cancelled", None)
    if checks is not None:
        m["checks"] = checks
    if _live(m) and not (result or {}).get("_denied_now"):
        _send(m, _guard(m, message))
        how = "live"
    else:
        _close(m)
        _launch(m, _guard(m, message), m["conversation"])
        how = "restarted"
    return {"job": job, "round": len(m["rounds"]), "session": how, "wait_cmd": _wait_cmd(job)}


@mcp.tool()
def agy_close(job: str) -> dict:
    """End a job's agy session once its package is audited (frees the process). The job's
    files, diff and discard keep working; agy_resume can still reopen the conversation."""
    m = _load(job)
    _close(m)
    _release_mcp(m)
    return {"job": job, "session": "closed"}


@mcp.tool()
def agy_cancel(job: str) -> dict:
    """Kill a running job (its whole process group). Edits already made stay; agy_discard
    reverts them."""
    m = _load(job)
    if _alive(m):
        os.killpg(m["pid"], signal.SIGTERM)
    PROCS.pop(job, None)
    m["cancelled"] = True
    _save(m)
    _release_mcp(m)
    return {"job": job, "state": "cancelled"}


@mcp.tool()
def agy_discard(job: str, files: list[str] | None = None) -> dict:
    """Put files back to the job's snapshot. Default: only files agy's own edit steps touched
    (so another session's work in the same tree is left alone); pass `files` (absolute) to
    choose. Files agy created are deleted."""
    m = _load(job)
    if not m["top"]:
        return {"error": "job is not in a git repo; nothing to restore from"}
    if _alive(m):
        return {"error": "job is still running; agy_cancel first"}
    top = Path(m["top"])
    edits, *_ = _parse(m)
    restored, removed = [], []
    for f in ([_abs(m, x) for x in files] if files else edits):
        rel = os.path.relpath(f, top)
        try:
            data = _git(top, "show", f"{m['base']}:{rel}")
            Path(f).write_bytes(data)
            restored.append(f)
        except RuntimeError:  # not in the snapshot: agy created it
            if os.path.exists(f):
                os.remove(f)
                removed.append(f)
    return {"restored": [_rel(m, f) for f in restored], "removed": [_rel(m, f) for f in removed]}


@mcp.tool()
def agy_permissions(add: list[str] | None = None, remove: list[str] | None = None,
                    check: list[str] | None = None) -> dict:
    """Read or edit agy's headless allow-list (permissions.allow in its settings.json).
    Rules are word prefixes, no globs: `command(git diff)`, `read_url(https://archive.org/)`, or
    `command(regex:npm run (build|lint))`. Keep them narrow: a command not on the list ends agy's
    round. `check`: command lines to test against the list after any add/remove — run it on every
    command a brief names before agy_start. With add/remove/check the reply is compact (what changed,
    the rule count); call with no arguments to read the whole list."""
    d = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    allow = d.setdefault("permissions", {}).setdefault("allow", [])
    added = [r for r in dict.fromkeys(add or []) if r not in allow]
    allow.extend(added)
    removed = [r for r in dict.fromkeys(remove or []) if r in allow]
    for r in removed:
        allow.remove(r)
    if add or remove:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(d, indent=2) + "\n")
    if not (add or remove or check):
        return {"allow": allow, "settings": str(SETTINGS)}
    # the Ep 3 session printed the whole 47-rule list ~20 times (~35k Claude tokens): only the change
    out = {"added": added, "removed": removed, "rules": len(allow)}
    if check:
        out["check"] = [c if c["missing"] else {"command": c["command"][:80], "allowed": True}
                        for c in _check_rules(check, allow)]
    return out


def _check_rules(cmds, allow):
    """Approximate agy's matcher, as observed: each piece of a pipeline or && chain needs its own
    rule; a plain rule matches whole leading words (`--only=g` does not match `--only=g07`);
    a regex rule must match the whole piece."""
    def words(x):
        try:
            return shlex.split(x)
        except ValueError:
            return x.split()
    rules = [r[8:-1] for r in allow if r.startswith("command(") and r.endswith(")")]
    out = []
    for cmd in cmds:
        segs = []
        for seg in (p.strip() for p in re.split(r"\|\||&&|[|;]", cmd) if p.strip()):
            hit = next((r for r in rules if (re.fullmatch(r[6:], seg) if r.startswith("regex:")
                        else words(r) and words(seg)[:len(words(r))] == words(r))), None)
            segs.append({"piece": seg, "rule": f"command({hit})" if hit else None})
        out.append({"command": cmd, "allowed": all(x["rule"] for x in segs),
                    "missing": [x["piece"] for x in segs if not x["rule"]]})
    return out


def selftest():
    """Snapshot -> edit -> discard round trip on a temp repo; agy is not called."""
    global JOBS
    with tempfile.TemporaryDirectory() as d:
        JOBS = Path(d) / "jobs"
        repo = Path(os.path.realpath(d)) / "r"  # /var -> /private/var on macOS
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "a.py").write_text("old\n")
        (repo / "keep.txt").write_text("other session\n")
        m = {"id": "t", "cwd": str(repo), "top": str(repo), "base": snapshot(repo),
             "allowed": [str(repo / "a.py")], "model": "x", "timeout_s": 1, "brief": "",
             "rounds": [{"n": 1, "started": 0}], "pid": -1}
        (JOBS / "t").mkdir(parents=True)
        _save(m)
        ev = {"event": "step_update", "step_update": {"step_type": "tool", "state": "DONE",
              "tool_name": "write_to_file", "tool_info": {"parameters": {"TargetFile": str(repo / "new.py")}}}}
        ev2 = json.loads(json.dumps(ev))
        ev2["step_update"]["tool_info"]["parameters"]["TargetFile"] = str(repo / "a.py")
        (JOBS / "t/r1.jsonl").write_text(json.dumps(ev) + "\n" + json.dumps(ev2) + "\n")
        (repo / "a.py").write_text("new\n")
        (repo / "new.py").write_text("x\n")
        (repo / "keep.txt").write_text("other session edit\n")
        dd = agy_diff("t")
        assert sorted(dd["changed"]) == ["a.py", "keep.txt", "new.py"], dd
        assert dd["out_of_scope"] == ["keep.txt", "new.py"], dd
        assert dd["not_from_agy_edits"] == ["keep.txt"], dd
        assert "new.py" not in agy_diff("t", files=["a.py"])["diff"]  # file-scoped diff
        m["outputs"] = [str(repo / "keep.txt")]; _save(m)  # declared output: not out of scope
        assert agy_diff("t")["out_of_scope"] == ["new.py"]
        assert "never edit them" in _guard(m, "b") and str(repo / "keep.txt") in _guard(m, "b")
        m.pop("outputs"); _save(m)
        rep = "Rendering X (10%)...\n1. done — plan\n" + "Rendering X (90%)...\n" * 50 + \
              f"1. done — check: pass — ok\nFiles: {repo}/a.py"
        assert _report(m, rep) == "1. done — check: pass — ok\nFiles: a.py", _report(m, rep)
        assert _report(m, "x" * 2000).startswith("…") and len(_report(m, "x" * 2000)) == 1501
        r = agy_discard("t")
        assert (repo / "a.py").read_text() == "old\n" and not (repo / "new.py").exists(), r
        assert (repo / "keep.txt").read_text() == "other session edit\n"  # untouched
        assert _git(repo, "status", "--porcelain").decode().count("\n") == 2  # index untouched
        m_cmd = {"id": "t_cmd", "cwd": str(repo), "top": str(repo), "base": snapshot(repo),
                 "allowed": [], "model": "x", "timeout_s": 1, "brief": "",
                 "rounds": [{"n": 1, "started": 0}], "pid": os.getpid()}
        (JOBS / "t_cmd").mkdir(parents=True)
        _save(m_cmd)
        ev_cmd = {"event": "step_update", "step_update": {"step_type": "tool", "state": "ACTIVE",
                  "tool_name": "run_command", "tool_info": {"parameters": {"CommandLine": "make"}}}}
        p_cmd = JOBS / "t_cmd/r1.jsonl"
        p_cmd.write_text(json.dumps(ev_cmd) + "\n")
        old_t = time.time() - STALL_S - 10
        os.utime(p_cmd, (old_t, old_t))
        assert _state(m_cmd, None) == "running"
        assert _state(m_cmd, {"status": "SUCCESS"}) == "done"
    u = _parse_usage("Gemini Models\tWeekly Limit Remaining\t59%\t2999-01-01T00:00:00Z\njunk\n")
    assert len(u) == 1 and u[0]["left_pct"] == 59 and u[0]["resets_in_h"] > 0, u
    # one session, two rounds: round 2 repeats round 1's denial (cumulative) and has no result yet
    JOBS = Path(tempfile.mkdtemp()) / "jobs"
    m2 = {"id": "t_ses", "cwd": str(repo), "top": str(repo), "base": None, "allowed": [], "model": "x",
          "timeout_s": 99, "brief": "", "pid": -1, "seg": 1,
          "rounds": [{"n": 1, "started": 0, "seg": 1}, {"n": 2, "started": 0, "seg": 1}]}
    (JOBS / "t_ses").mkdir(parents=True)
    _save(m2)
    cmd = {"event": "step_update", "step_update": {"step_type": "tool", "state": "DONE", "tool_name": "run_command",
           "tool_info": {"parameters": {"CommandLine": "sleep 1"}}}}
    res = {"event": "result", "result": {"status": "SUCCESS", "response": "",
           "denied_actions": [{"action": "command"}], "usage": {"total_tokens": 10}}}
    (JOBS / "t_ses/r1.jsonl").write_text(json.dumps(cmd) + "\n" + json.dumps(res) + "\n")
    (JOBS / "t_ses/r2.jsonl").write_text("")
    _, cmds, _, den, result = _parse(m2)
    assert result is None and _state(m2, result) == "failed", result  # round 2 pending, process gone
    assert len(den) == 1 and den[0]["command"] == "sleep 1" and cmds == [], (den, cmds)
    (JOBS / "t_ses/r2.jsonl").write_text(json.dumps(res) + "\n")  # same cumulative denial again
    _, _, _, den, result = _parse(m2)
    assert len(den) == 1 and result["_tokens"] == 10 and not result["_denied_now"], (den, result)
    # agy 1.4.3 names: write_file with a Path parameter counts as an edit
    mw = {"id": "t_w", "cwd": "/x", "top": None, "base": None, "allowed": [], "model": "x", "timeout_s": 1,
          "brief": "", "pid": -1, "seg": 1, "rounds": [{"n": 1, "started": 0, "seg": 1}]}
    (JOBS / "t_w").mkdir(parents=True); _save(mw)
    (JOBS / "t_w/r1.jsonl").write_text(json.dumps({"event": "step_update", "step_update": {
        "step_type": "tool", "state": "DONE", "tool_name": "write_file",
        "tool_info": {"parameters": {"Path": "/x/a.txt"}}}}) + "\n")
    assert _parse(mw)[0] == [os.path.realpath("/x/a.txt")], _parse(mw)[0]
    # a finished round with two checks: one passes, one fails -> one verdict says so
    (JOBS / "t_v").mkdir(parents=True)
    mv = {**m2, "id": "t_v", "cwd": str(JOBS.parent), "checks": ["true", "echo boom; false"], "rounds": [{"n": 1, "started": 0, "seg": 1}],
          "created": 0, "top": None}  # not a git repo here: scope fields are skipped
    _save(mv)
    (JOBS / "t_v/r1.jsonl").write_text(json.dumps({"event": "result", "result": {
        "status": "SUCCESS", "response": "1. done", "usage": {"total_tokens": 5}}}) + "\n")
    (JOBS / "t_v/s1.err").write_text("")
    v = _verdict("t_v")
    assert v["state"] == "done" and v["all_checks_pass"] is False and not v["clean"], v
    assert [c["rc"] for c in v["checks"]] == [0, 1] and "boom" in v["checks"][1]["tail"], v
    assert agy_status("t_v")["verdict"]["all_checks_pass"] is False  # status returns it for the round
    mv["cwd"] = "/nonexistent-dir"; _save(mv)
    assert _run_checks(mv)[0]["rc"] == "error"  # a vanished folder is reported, not raised
    mv["cwd"] = str(JOBS.parent); mv["checks"] = ["true"]; _save(mv)
    assert _verdict("t_v")["clean"] is True
    # verdict: agy finished its report, then a 503 made the status ERROR -> checks still run and decide
    (JOBS / "t_503").mkdir(parents=True)
    m5 = {**mv, "id": "t_503", "cwd": str(JOBS.parent), "checks": ["true"]}
    _save(m5)
    (JOBS / "t_503/r1.jsonl").write_text(json.dumps({"event": "result", "result": {
        "status": "ERROR", "error": "API error: UNAVAILABLE (code 503)", "response": "1. done — check: pass",
        "usage": {"total_tokens": 5}}}) + "\n")
    (JOBS / "t_503/s1.err").write_text("")
    v = _verdict("t_503")
    assert v["state"] == "failed" and v["checks"] and v["clean"] and "503" in v["agy_error"], v
    # lending: a path, a missing name; a Claude MCP entry converted to agy's shape
    sk = JOBS.parent / "SKILL.md"
    sk.write_text("---\nname: x\n---\nDo the thing.\n")
    assert _skill(str(sk), "/") == (f"skill: {sk}", "\nDo the thing.\n")
    try:
        _skill("no-such-skill-xyz", "/"); raise AssertionError("missing skill not caught")
    except FileNotFoundError:
        pass
    global CLAUDE_JSON, AGY_MCP, SETTINGS
    saved = CLAUDE_JSON, AGY_MCP, SETTINGS
    CLAUDE_JSON, AGY_MCP, SETTINGS = JOBS.parent / "c.json", JOBS.parent / "mcp.json", JOBS.parent / "s.json"
    try:
        CLAUDE_JSON.write_text(json.dumps({"mcpServers": {
            "loc": {"type": "stdio", "command": "srv", "args": ["--mcp"], "env": {}},
            "web": {"type": "http", "url": "https://x.test/mcp", "headers": {"A": "b"}}}}))
        assert _claude_mcp("loc", "/") == {"command": "srv", "args": ["--mcp"]}
        assert _claude_mcp("web", "/") == {"serverUrl": "https://x.test/mcp", "headers": {"A": "b"}}
        # borrow for two jobs, release one: server stays; release the other: server and rules go
        ja, jb = {**m5, "id": "t_ba", "top": None}, {**m5, "id": "t_bb", "top": None}
        for j in (ja, jb):
            (JOBS / j["id"]).mkdir(parents=True)
            _borrow_mcp(j, ["loc"]); _save(j)
        assert "loc" in json.loads(AGY_MCP.read_text())["mcpServers"]
        assert "mcp(loc/*)" in json.loads(SETTINGS.read_text())["permissions"]["allow"]
        _release_mcp(ja)
        assert "loc" in json.loads(AGY_MCP.read_text())["mcpServers"]  # jb still uses it
        _release_mcp(jb)
        assert "loc" not in json.loads(AGY_MCP.read_text())["mcpServers"]
        assert "mcp(loc/*)" not in json.loads(SETTINGS.read_text())["permissions"]["allow"]
        p = agy_permissions(add=["command(ls )", "command(ls )"], check=["ls -l", "rm x"])
        assert p["added"] == ["command(ls )"] and "allow" not in p, p
        assert p["check"][0] == {"command": "ls -l", "allowed": True} and p["check"][1]["missing"] == ["rm x"], p
        assert agy_permissions(remove=["command(ls )"])["removed"] == ["command(ls )"]
        assert "allow" in agy_permissions()
    finally:
        CLAUDE_JSON, AGY_MCP, SETTINGS = saved
    # setup on a fake home: dry run touches nothing; --apply archives, empties, keeps rules; restore.sh undoes it
    h = JOBS.parent / "home"
    g = h / ".gemini/config"
    (g / "skills/s1").mkdir(parents=True); (g / "skills/s1/SKILL.md").write_text("x")
    (g / "rules").mkdir(); (g / "rules/core.md").write_text("rule")
    (g / "mcp_config.json").write_text(json.dumps({"mcpServers": {"a": {"command": "a"}}}))
    (g / "config.json").write_text(json.dumps({"plugins": {"p": {"enabled": True}}}))
    r0 = setup_cli(home=h)
    assert r0["dry_run"] and r0["mcp_servers"] == ["a"] and (g / "skills/s1").exists(), r0
    r1 = setup_cli(apply=True, home=h)
    arch = Path(r1["archive"])
    assert not any((g / "skills").iterdir()) and (arch / ".gemini/config/skills/s1/SKILL.md").exists()
    assert json.loads((g / "mcp_config.json").read_text()) == {"mcpServers": {}}
    assert (g / "rules/core.md").exists() and not json.loads((g / "config.json").read_text())["plugins"]["p"]["enabled"]
    assert "command(git diff)" in json.loads((h / ".gemini/antigravity-cli/settings.json").read_text())["permissions"]["allow"]
    subprocess.run(["bash", str(arch / "restore.sh")], check=True, capture_output=True)
    assert (g / "skills/s1/SKILL.md").exists() and "a" in json.loads((g / "mcp_config.json").read_text())["mcpServers"]
    shutil.rmtree(JOBS.parent)
    allow = ["command(grep )", "command(regex:npm run (build|lint))", "command(python3 b.py --only=g)"]
    c = {x["command"]: x["allowed"] for x in _check_rules(
        ["grep -n x f", "grep x f | awk '{print}'", "npm run lint", "npm run test",
         "python3 b.py --only=g07", "python3 b.py --only=g"], allow)}
    assert c == {"grep -n x f": True, "grep x f | awk '{print}'": False, "npm run lint": True,
                 "npm run test": False, "python3 b.py --only=g07": False, "python3 b.py --only=g": True}, c
    print("selftest ok")


def wait_cli(job, max_s=7200):
    """`server.py wait <job> [max_s]`: block until the job leaves "running", run the job's checks,
    then print one compact verdict as JSON. Run it as a background shell task so the
    orchestrator is woken once, with everything it needs to audit. ponytail: 15 s poll."""
    m, end = _load(job), time.time() + max_s
    while time.time() < end and agy_status(job)["state"] == "running":
        stray = [e for e in _parse(m)[0] if not _allowed(m, e)]
        if stray:  # wake the orchestrator early: agy is editing outside its package
            print(json.dumps({**agy_status(job), "alert": "edits outside allowed_files",
                              "stray": [_rel(m, e) for e in stray]}, indent=1))
            return
        time.sleep(15)
    print(json.dumps(_verdict(job), indent=1))


BASELINE = ["command(ls)", "command(cat )", "command(head )", "command(tail )", "command(wc )",
            "command(grep )", "command(rg )", "command(git status)", "command(git diff)",
            "command(git log)", "command(git show)"]  # read-only; models explore with these even when told not to

RESTORE_SH = """#!/bin/bash
# Put every archived item back where it came from (MANIFEST.tsv). Refuses to overwrite a non-empty folder.
set -euo pipefail
cd "$(dirname "$0")"
tail -n +2 MANIFEST.tsv | while IFS=$'\\t' read -r archived original; do
  if [ -f "$archived" ]; then cp "$archived" "$original"; echo "restored $original"; continue; fi
  if [ -e "$original" ] && [ -n "$(ls -A "$original" 2>/dev/null)" ]; then echo "SKIP (exists, not empty): $original"; continue; fi
  rmdir "$original" 2>/dev/null || true; mv "$archived" "$original"; echo "restored $original"
done
"""


def setup_cli(apply=False, home=None, repo=None):
    """`server.py setup [--apply] [repo]`: make agy bare for agy-worker. Archives agy's own MCP
    servers, skills, plugins and agents (global, shared with the Antigravity app and IDE) to
    ~/Documents/agy-config-archive-<date>/ with a manifest and restore.sh, keeps the user's rules,
    adds the read-only baseline to the allow-list, and reports agy config a repo exposes. Dry run
    unless --apply. Returns the report."""
    home = Path(home or Path.home())
    G, C = home / ".gemini/config", home / ".gemini/antigravity-cli"
    tools = {t: shutil.which(t) or (str(home / ".local/bin" / t) if (home / ".local/bin" / t).exists() else None)
             for t in ("agy", "uv", "git")}
    full = lambda p: p.exists() and (p.is_file() or any(p.iterdir()))
    folders = [p for p in (G / "skills", G / "plugins", G / "agents", C / "mcp", C / "plugin_data", C / "skills",
                           C / "plugins", home / ".agents/skills", home / ".agents/agents") if full(p)]
    mcp_cfg = json.loads((G / "mcp_config.json").read_text()) if (G / "mcp_config.json").exists() else {}
    servers = list((mcp_cfg.get("mcpServers") or {}).keys())
    cfg_p = G / "config.json"
    plugins_on = [k for k, v in (json.loads(cfg_p.read_text()).get("plugins") or {}).items()
                  if v.get("enabled")] if cfg_p.exists() else []
    settings = home / ".gemini/antigravity-cli/settings.json"
    allow = (json.loads(settings.read_text()).get("permissions") or {}).get("allow", []) if settings.exists() else []
    missing = [r for r in BASELINE if r not in allow]
    rep_ = {"dry_run": not apply, "tools": tools, "mcp_servers": servers, "plugins_enabled": plugins_on,
            "folders": [str(p) for p in folders], "kept_rules": [str(p) for p in sorted((G / "rules").glob("*.md"))],
            "baseline_rules_to_add": missing,
            "repo_agy_config": _repo_agy_config(repo) if repo else None}
    if not apply:
        return rep_
    stamp = time.strftime("%Y-%m-%d")
    arch = home / "Documents" / f"agy-config-archive-{stamp}"
    n = 1
    while arch.exists():
        n += 1
        arch = home / "Documents" / f"agy-config-archive-{stamp}-{n}"
    arch.mkdir(parents=True)
    rows = []
    def keep(src):
        dst = arch / src.relative_to(home)
        dst.parent.mkdir(parents=True, exist_ok=True)
        return dst
    for f in (G / "mcp_config.json", cfg_p):
        if f.exists():
            shutil.copy2(f, keep(f)); rows.append((keep(f), f))
    if servers:
        (G / "mcp_config.json").write_text('{\n  "mcpServers": {}\n}\n')
    if plugins_on:
        d = json.loads(cfg_p.read_text())
        for v in d["plugins"].values():
            v["enabled"] = False
        cfg_p.write_text(json.dumps(d, indent=2))
    for p in folders:
        dst = keep(p)
        shutil.move(str(p), str(dst)); rows.append((dst, p))
        p.mkdir(exist_ok=True)  # agy expects the folder; leave it empty
    (arch / "MANIFEST.tsv").write_text("archived\toriginal\n" + "".join(f"{a}\t{o}\n" for a, o in rows))
    (arch / "restore.sh").write_text(RESTORE_SH)
    (arch / "restore.sh").chmod(0o755)
    (arch / "README.md").write_text(
        "# agy config archive\n\nMoved here by `agy-worker setup` so agy runs bare: the orchestrating Claude "
        "session lends skills and MCP servers per job. These folders are shared with the Antigravity app and "
        "IDE. Rules were kept. Restore everything with `bash restore.sh`.\n")
    if missing:
        d = json.loads(settings.read_text()) if settings.exists() else {}
        d.setdefault("permissions", {}).setdefault("allow", []).extend(missing)
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(d, indent=2) + "\n")
    rep_.update(dry_run=False, archive=str(arch))
    return rep_


def watch_cli(job=None):
    """`server.py watch [job]`: follow a job live for a human. A header panel, one line per finished
    tool step (icon, time into the run, target), a spinner on the step in progress, then a summary
    panel with the report. No job: the newest one. Read-only.
    ponytail: re-parses the round logs every second; fine for logs of a few MB."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    con = Console(highlight=False)
    if job is None:
        ids = sorted(p.name for p in JOBS.iterdir() if p.is_dir()) if JOBS.exists() else []
        if not ids:
            sys.exit(f"no jobs in {JOBS}")
        job = ids[-1]  # ids start with %m%d-%H%M%S, so the last is the newest
    m = _load(job)
    icons = {"view_file": ("📄", "dim"), "list_dir": ("📁", "dim"), "grep_search": ("🔍", "dim"),
             "search_web": ("🔎", "cyan"), "read_url_content": ("🌐", "cyan"),
             "run_command": ("▶", "yellow"), "command_status": ("⏱", "dim")}
    icons.update({t: ("✎", "green") for t in WRITE_TOOLS | {"write_file"}})
    icons.update({"read_file": ("📄", "dim")})
    first = next((ln for ln in m["brief"].splitlines() if ln.strip() and not ln.startswith("#")), "")
    con.print(Panel(Text.assemble((f"{job}\n", "bold"), (f"{m['model']}  ·  {m['cwd'].replace(str(Path.home()), '~')}\n", "cyan"),
                                  (first[:110], "dim")), title="agy job", border_style="blue", expand=False))

    def stamp():
        r = m["rounds"][-1]
        sec = max(0, int(time.time() - r["started"]))
        return f"r{r['n']} {sec // 60:02d}:{sec % 60:02d}"

    shown, live = 0, False
    with con.status("starting…", spinner="dots") as spin:
        while True:
            m = _load(job)  # agy_resume adds rounds
            edits, _, st, _, result = _parse(m)
            done = [x for x in st if x["state"] != "ACTIVE"]
            for x in done[shown:]:
                icon, style = icons.get(x["tool"], ("•", "white"))
                if x["state"] == "ERROR":
                    icon, style = "✗", "bold red"
                con.print(Text.assemble((f"{stamp() if live else '   ·    '}  ", "dim"), f"{icon} ",
                                        (f"{x['tool']:<24}", style), _short(m, x["target"])),
                          no_wrap=True, overflow="ellipsis")
            shown, live = len(done), True
            state = "cancelled" if m.get("cancelled") else _state(m, result)
            if state != "running":
                break
            now = st[-1] if st and st[-1]["state"] == "ACTIVE" else None
            spin.update(Text.assemble((f"{stamp()}  ", "dim"), (f"{len(done)} steps · {len(edits)} edits", "bold"),
                                      f"  ·  now: {now['tool']} {_short(m, now['target'])}" if now else "  ·  thinking…"))
            time.sleep(1)
    s = agy_status(job, full_report=True)
    color = {"done": "green", "failed": "red", "stalled": "yellow"}.get(state, "white")
    facts = Text.assemble((f"{state.upper()}", f"bold {color}"),
                          f"  ·  round {s['round']}  ·  {s['elapsed_s']} s  ·  {s['n_steps']} steps"
                          f"  ·  {s['tokens'] or '?'} tokens\n",
                          ("edits: ", "bold"), ", ".join(s["edits"]) or "none", "\n",
                          ("denied: ", "bold"), (str(s["denied"]) if s["denied"] else "none",
                                                 "red" if s["denied"] else ""))
    v = _verdict(job)  # runs the checks: in hand-off mode this is the only verdict
    for c in v["checks"]:
        facts.append(f"\n{'✓' if c['ok'] else '✗'} {c['cmd']}", "green" if c["ok"] else "red")
    if v.get("out_of_scope"):
        facts.append(f"\nout of scope: {', '.join(v['out_of_scope'])}", "red")
    facts.append(f"\nclean: {v['clean']}", "bold green" if v["clean"] else "bold red")
    if m.get("top"):
        facts.append(f"\nreview: git -C {m['top']} diff", "dim")
    con.print(Panel(facts, title="result", border_style=color, expand=False))
    body = s["report"] or s.get("hint") or s.get("stderr") or ""
    if body:
        con.print(Panel(Text(body.strip()), title="agy's report", border_style="dim"))

if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        selftest()
    elif sys.argv[1:] == ["usage"]:
        print(json.dumps(agy_usage(), indent=1))
    elif sys.argv[1:2] == ["watch"]:
        try:
            watch_cli(sys.argv[2] if len(sys.argv) > 2 else None)
        except KeyboardInterrupt:
            pass
    elif sys.argv[1:2] == ["setup"]:
        args = sys.argv[2:]
        print(json.dumps(setup_cli(apply="--apply" in args,
                                   repo=next((a for a in args if not a.startswith("--")), None)), indent=1))
    elif sys.argv[1:2] == ["wait"]:
        wait_cli(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 7200)
    else:
        mcp.run()

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
import fnmatch, json, os, shutil, signal, subprocess, sys, tempfile, time, uuid
from datetime import datetime, timezone
from pathlib import Path

JOBS = Path(os.environ.get("AGY_WORKER_HOME") or Path.home() / ".local/state/agy-worker") / "jobs"
AGY = shutil.which("agy") or str(Path.home() / ".local/bin/agy")
SETTINGS = Path.home() / ".gemini/antigravity-cli/settings.json"
DEFAULT_MODEL = "gemini-3.8-flash-medium"
WRITE_TOOLS = {"replace_file_content", "multi_replace_file_content", "write_to_file", "sed_file",
               "notebook_edit"}
LOW_PCT = 20  # agy_start flags a pool below this
STALL_S = 300  # Argon can think quietly for minutes; a Flash stall at 5 min is real
PROCS = {}  # job id -> Popen, so finished children get reaped

GUARD = """You are the worker on a work package for an orchestrator who will audit every change
you make. Plan the tasks, then work through them in order, running each task's check before
moving on. Follow these rules exactly:
- Edit ONLY these files: {files}. Do not create, delete, rename or edit any other file. If the
  task truly needs another file, stop and say which one and why.
- No state-changing git (commit, push, checkout, reset, stash, rebase, merge, branch), no
  package installs, no file deletion. {network}
- Never touch .git/, .claude/, .env or anything that looks like a credential.
- Change only what the task asks. No reformatting, renaming or refactoring beyond it; keep
  the surrounding style.
- If a task is ambiguous or blocked, do not guess: skip it, note why, and continue with the
  other tasks.
- Run only the commands the brief names (plus read-only inspection); a command that is not
  allowed ends your whole run.
- End with a terse report and nothing else, in exactly this shape:
    1. done|skipped|failed — check: pass|fail|not run — <one short note>
    2. ...
    Files: <changed paths, comma-separated>
  If the brief names a report file for longer findings, write them there, opening with a
  summary of at most 10 lines; do not repeat them in the final message.

PACKAGE
{brief}
"""


def _guard(m, brief):
    net = ("Web search and downloads are allowed for this task; on HTTP 401/403/429, a CAPTCHA "
           "or a bot challenge, stop that source at once: never bypass, spoof or retry in a loop."
           if m.get("network") else "No network access.")
    return GUARD.format(files=", ".join(m["allowed"]), network=net, brief=brief)


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
    n = len(m["rounds"]) + 1
    d = JOBS / m["id"]
    cmd = [AGY, "-p", prompt, "--output-format", "stream-json", "--mode", "accept-edits",
           "--model", m["model"], "--print-timeout", f"{m['timeout_s']}s"]
    if conversation:
        cmd += ["--conversation", conversation]
    # stdin from /dev/null: agy -p can hang waiting on a non-tty stdin (agy issue #318)
    p = subprocess.Popen(cmd, cwd=m["cwd"], stdin=subprocess.DEVNULL,
                         stdout=open(d / f"r{n}.jsonl", "w"), stderr=open(d / f"r{n}.err", "w"),
                         start_new_session=True)
    PROCS[m["id"]] = p
    m["pid"] = p.pid
    m["rounds"].append({"n": n, "started": time.time()})
    _save(m)


def _events(m, n):
    p = JOBS / m["id"] / f"r{n}.jsonl"
    out = []
    for line in p.read_text(errors="replace").splitlines() if p.exists() else []:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # last line may be half-written while agy runs
    return out


def _parse(m):
    """Fold every round's events into what agy did."""
    edits, commands, steps, denied = [], [], [], []
    result, conv = None, m.get("conversation")
    for r in m["rounds"]:
        for e in _events(m, r["n"]):
            if e.get("event") == "init":
                conv = e.get("conversation_id") or conv
            s = e.get("step_update")
            if s and s.get("step_type") == "tool":
                params = (s.get("tool_info") or {}).get("parameters") or {}
                target = params.get("TargetFile") or params.get("AbsolutePath") or \
                    params.get("CommandLine") or params.get("Url") or params.get("query") or ""
                steps.append({"round": r["n"], "tool": s.get("tool_name"), "state": s.get("state"),
                              "target": target})
                if s.get("state") == "DONE":
                    if s.get("tool_name") in WRITE_TOOLS and target:
                        target = os.path.realpath(target)  # symlinked paths vs git's real ones
                        if target not in edits:
                            edits.append(target)
                    if s.get("tool_name") == "run_command":
                        commands.append(target)
            if e.get("event") == "result":
                result = e["result"]
                denied += result.get("denied_actions") or []
    if conv != m.get("conversation"):
        m["conversation"] = conv
        _save(m)
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


def _allowed(m, path):
    p = os.path.realpath(path)
    for a in m["allowed"]:
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
              timeout_s: int = 3600, network: bool = False) -> dict:
    """Start agy on a work package (several related tasks), in place in `cwd` (absolute path). `brief` says the
    exact change, what done means, and which checks to run. `allowed_files` are the only
    paths agy may edit (absolute, or relative to cwd; a directory or a glob also works).
    The brief is wrapped in a guard preamble. network=True lets a research job browse and
    download (it must stop on 401/403/429/CAPTCHA). Returns {job, git, wait_cmd} immediately
    (run wait_cmd as a background shell task)."""
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
         "timeout_s": timeout_s, "brief": brief, "network": network, "rounds": [], "created": time.time()}
    (JOBS / m["id"]).mkdir(parents=True)
    _launch(m, _guard(m, brief))
    out = {"job": m["id"], "git": bool(top),
           "wait_cmd": f"{shutil.which('uv') or 'uv'} run --script {Path(__file__).resolve()} wait {m['id']}"}
    if not top:
        out["warning"] = "not a git repo: agy_diff and agy_discard cannot work for this job"
    low = [p for p in _usage_pools(model) if p["left_pct"] < LOW_PCT]
    if low:
        out["quota_low"] = low
    return out


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


@mcp.tool()
def agy_status(job: str | None = None, steps: int = 5, full_report: bool = False) -> dict:
    """One job's progress, compact: state (running|stalled|done|failed|cancelled), elapsed,
    step/edit counts, the last `steps` tool steps as short lines, files edited (relative),
    commands run, denied actions, agy's report (first 1500 chars unless full_report).
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
    err = (JOBS / job / f"r{n}.err").read_text(errors="replace").strip()
    state = "cancelled" if m.get("cancelled") else _state(m, result)
    report = (result or {}).get("response") or ""
    if not full_report and len(report) > 1500:
        report = report[:1500] + " …[truncated: agy_status(full_report=True)]"
    done_steps = [x for x in st if x["state"] != "ACTIVE"]
    took = (result or {}).get("duration_seconds")  # cumulative over rounds; wall clock while running
    out = {"job": job, "state": state, "round": n,
           "elapsed_s": round(took) if took else round(time.time() - r["started"]),
           "n_steps": len(done_steps),
           "steps": [f'{x["tool"]} {x["state"].lower()} {_short(m, x["target"])}'
                     for x in done_steps[-steps:]],
           "edits": [_rel(m, e) for e in edits], "commands": [c[:120] for c in commands],
           "denied": denied, "report": report or None,
           "tokens": ((result or {}).get("usage") or {}).get("total_tokens")}
    if err and (state != "done" or "error" in err.lower()):
        out["stderr"] = err[-400:]
    if "auto-denied" in err:
        # a resume after a denial-ended run wedged (0 tool steps, ~40k output tokens) on 2026-10-19
        out["hint"] = ("This round ended on a denied action, so its edits may be partial and there is no "
                       "report. Grant the rule (agy_permissions) or forbid the action in the brief, then "
                       "start a NEW job with the same brief rather than agy_resume.")
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
            "out_of_scope": [_rel(m, f) for f in changed if not _allowed(m, f)],
            "not_from_agy_edits": [_rel(m, f) for f in changed if f not in edits],
            "commands": [c[:120] for c in commands], "denied": denied,
            "stat": _git(top, "diff", "--stat", m["base"], now).decode(),
            "diff": diff[:max_chars] + (f"\n...[truncated, {len(diff)} chars: pass files=[…]]"
                                        if len(diff) > max_chars else "")}


@mcp.tool()
def agy_resume(job: str, message: str) -> dict:
    """Fix-up round: send `message` to the same agy conversation (the guard rules and the
    allowed files are restated). The diff baseline stays the original snapshot."""
    m = _load(job)
    _parse(m)
    if _alive(m):
        return {"error": "job is still running; agy_wait or agy_cancel first"}
    if not m.get("conversation"):
        return {"error": "no conversation id recorded for this job; start a new one"}
    m.pop("cancelled", None)
    _launch(m, _guard(m, message), m["conversation"])
    return {"job": job, "round": len(m["rounds"])}


@mcp.tool()
def agy_cancel(job: str) -> dict:
    """Kill a running job (its whole process group). Edits already made stay; agy_discard
    reverts them."""
    m = _load(job)
    if _alive(m):
        os.killpg(m["pid"], signal.SIGTERM)
    m["cancelled"] = True
    _save(m)
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
def agy_permissions(add: list[str] | None = None, remove: list[str] | None = None) -> dict:
    """Read or edit agy's headless allow-list (permissions.allow in its settings.json).
    Rules are plain prefixes, no globs: `command(git diff)`, `read_url(https://archive.org/)`. Keep them narrow: a
    command not on the list is silently denied and shows up in `denied`."""
    d = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    allow = d.setdefault("permissions", {}).setdefault("allow", [])
    for r in add or []:
        if r not in allow:
            allow.append(r)
    for r in remove or []:
        if r in allow:
            allow.remove(r)
    if add or remove:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(d, indent=2) + "\n")
    return {"allow": allow, "settings": str(SETTINGS)}


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
    print("selftest ok")


def wait_cli(job, max_s=7200):
    """`server.py wait <job> [max_s]`: block until the job leaves "running", then print its
    compact status as JSON. Run it as a background shell task so the orchestrator is woken
    once at the end instead of spending a turn per agy_wait. ponytail: 15 s poll."""
    m, end = _load(job), time.time() + max_s
    while time.time() < end and agy_status(job)["state"] == "running":
        stray = [e for e in _parse(m)[0] if not _allowed(m, e)]
        if stray:  # wake the orchestrator early: agy is editing outside its package
            print(json.dumps({**agy_status(job), "alert": "edits outside allowed_files",
                              "stray": [_rel(m, e) for e in stray]}, indent=1))
            return
        time.sleep(15)
    print(json.dumps(agy_status(job), indent=1))


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
    icons.update({t: ("✎", "green") for t in WRITE_TOOLS})
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
    elif sys.argv[1:2] == ["wait"]:
        wait_cli(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 7200)
    else:
        mcp.run()

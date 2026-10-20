#!/bin/bash
# usage: judgment.sh RUNDIR -> PASS/FAIL + accuracy report
C="$(cd "$(dirname "$0")" && pwd)"; RUN="$(cd "${1:?run dir}" && pwd)"
python3 - "$RUN" "$C/labels.json" <<'PY'
import json, os, sys, re
run, lab = sys.argv[1], json.load(open(sys.argv[2])); cats = {"billing","bug","feature","account","other"}
valid = 0; ok = 0; near = 0; prob = []; urg = {}
for name, L in lab.items():
    cand = [os.path.join(run, "summaries", name + ".json"), os.path.join(run, "summaries", name[:-4] + ".json")]
    p = next((c for c in cand if os.path.exists(c)), cand[0])
    try:
        d = json.load(open(p)); assert d["category"] in cats and d["urgency"] in (1,2,3) and isinstance(d["summary"], str) and 0 < len(d["summary"].split()) <= 20
        valid += 1; urg[name] = d["urgency"]; ok += d["category"] == L["category"]; near += abs(d["urgency"] - L["urgency"]) <= 1
    except Exception as e: prob.append(name)
n = len(lab); P = F = 0
def chk(c, m):
    global P, F
    print(("PASS " if c else "FAIL ") + m); P += c; F += (not c)
chk(valid == n, f"1 all JSON valid ({valid}/{n}) bad={prob[:5]}")
chk(ok / n >= .8, f"2 category accuracy {ok}/{n} = {100*ok/n:.0f}%")
chk(near / n >= .8, f"3 urgency within +-1: {near}/{n} = {100*near/n:.0f}%")
exact = sum(urg.get(k) == v["urgency"] for k, v in lab.items()); print(f"INFO urgency exact {exact}/{n}")
good = False
try:
    lines = [l for l in open(os.path.join(run, "summaries", "INDEX.md")).read().splitlines() if l.strip()]
    names = [re.search(r"ticket_\d+", l).group(0) + ".txt" for l in lines]
    us = [urg[x] for x in names]; good = len(names) == n and set(names) == set(lab) and us == sorted(us, reverse=True)
except Exception as e: print("INFO index error", e)
chk(good, "4 INDEX.md has all tickets, sorted by urgency desc (using each ticket's own JSON urgency)")
print(f"SCORE {P}/{P+F}")
PY

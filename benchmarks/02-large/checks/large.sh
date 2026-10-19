#!/bin/bash
# usage: large.sh RUNDIR  -> PASS/FAIL per criterion
C="$(cd "$(dirname "$0")" && pwd)"; RUN="$(cd "${1:?run dir}" && pwd)"; cd "$RUN"
P=0; F=0
pass(){ echo "PASS $1"; P=$((P+1)); }; fail(){ echo "FAIL $1"; F=$((F+1)); }
out=$(python3 -m unittest discover -s tests 2>&1); n=$(echo "$out" | sed -n 's/^Ran \([0-9]*\) tests.*/\1/p')
if echo "$out" | tail -1 | grep -q '^OK' && [ "${n:-0}" -ge 82 ]; then pass "1 tests pass ($n tests)"; else fail "1 tests pass ($n tests; $(echo "$out" | tail -1))"; fi
bad=$(python3 - <<'PY'
import ast, glob, re
bad = []
for f in sorted(glob.glob("app/handlers/*.py")):
    s = open(f).read()
    if re.search(r"\bregister\(|\blog\(", s): bad.append(f + ":call")
    for n in ast.walk(ast.parse(s)):
        if isinstance(n, ast.ImportFrom) and (n.module in ("app.registry", "app.log") or (n.module == "app" and any(a.name in ("registry", "log") for a in n.names))): bad.append(f + ":import")
        if isinstance(n, ast.Import) and any(a.name in ("app.registry", "app.log") for a in n.names): bad.append(f + ":import")
print(len(bad), " ".join(bad[:5]))
PY
)
[ "${bad%% *}" = "0" ] && pass "2 no register()/log()/old imports in handlers" || fail "2 old API left in handlers: $bad"
r=$(python3 "$C/registry_check.py" "$C/expected.json" 2>&1 | tail -1); [ "${r%/*}" = "${r#*/}" ] && pass "3 hidden registrations $r" || fail "3 hidden registrations $r"
h=$(python3 "$C/hints.py" "$RUN" "$C/types.json" 2>&1 | tail -1); echo "INFO hints: $h"
cov=$(echo "$h" | sed -n 's/.*cov=\([0-9]*\)\/\([0-9]*\).*/\1 \2/p'); m=$(echo "$h" | sed -n 's/.*match=\([0-9]*\)\/\([0-9]*\).*/\1 \2/p')
set -- $cov; [ "$1" = "$2" ] && [ -n "$1" ] && pass "4a all functions fully annotated ($1/$2)" || fail "4a all functions fully annotated ($1/$2)"
set -- $m; [ "$1" = "$2" ] && [ -n "$1" ] && pass "4b annotations match ground truth ($1/$2)" || fail "4b annotations match ground truth ($1/$2)"
d=$(git status --porcelain -- app/registry.py app/log.py app/new_api.py); [ -z "$d" ] && pass "5 core files untouched" || fail "5 core files changed: $d"
echo "INFO changed outside handlers/test_handler_*: $(git status --porcelain | grep -v -E 'app/handlers/handler_[0-9]+\.py|tests/test_handler_[0-9]+\.py' | tr '\n' ' ')"
echo "INFO changed: handlers=$(git status --porcelain | grep -c 'app/handlers/') tests=$(git status --porcelain | grep -c 'tests/test_handler')"
echo "SCORE $P/$((P+F))"

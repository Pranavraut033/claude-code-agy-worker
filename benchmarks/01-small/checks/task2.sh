#!/bin/bash
C="$(cd "$(dirname "$0")" && pwd)"; RUN=${1:?run dir}; source "$C/common.sh"; cd "$RUN"
H="$C/t2_hidden.py"
for t in test_exact test_empty test_cli test_text_default_unchanged; do
  PYTHONPATH=. python3 "$H" Hidden.$t >/dev/null 2>&1 && pass "hidden $t" || fail "hidden $t"; done
python3 -m unittest -q >/dev/null 2>&1 && pass "repo tests pass" || fail "repo tests pass"
n=$(python3 -m unittest 2>&1 | sed -n 's/^Ran \([0-9]*\) tests.*/\1/p'); [ "${n:-0}" -gt 14 ] && pass "new tests added ($n)" || fail "new tests added ($n)"
echo "SCORE $P/$((P+F))"

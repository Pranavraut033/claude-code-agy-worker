#!/bin/bash
C="$(cd "$(dirname "$0")" && pwd)"; RUN=${1:?run dir}; source "$C/common.sh"; cd "$RUN"
H="$C/t3_hidden.py"
python3 -m unittest -q >/dev/null 2>&1 && pass "tests pass" || fail "tests pass"
[ -z "$(git status --porcelain -- tests/)" ] && pass "test files unchanged" || fail "test files unchanged"
for t in test_tier_boundaries test_line_rounding test_default_tags_not_shared; do
  PYTHONPATH=. python3 "$H" Hidden.$t >/dev/null 2>&1 && pass "hidden $t" || fail "hidden $t"; done
echo "SCORE $P/$((P+F))"

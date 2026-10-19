#!/bin/bash
C="$(cd "$(dirname "$0")" && pwd)"; RUN=${1:?run dir}; source "$C/common.sh"; cd "$RUN"
if grep -rn --exclude-dir=.git calc_total . >/dev/null; then fail "old name gone ($(grep -rln --exclude-dir=.git calc_total . | tr '\n' ' '))"; else pass "old name gone"; fi
grep -q "^def compute_total(" inventory/pricing.py && pass "compute_total defined" || fail "compute_total defined"
python3 -m unittest -q >/dev/null 2>&1 && pass "tests pass" || fail "tests pass"
n=$(python3 -m unittest 2>&1 | sed -n 's/^Ran \([0-9]*\) tests.*/\1/p'); [ "${n:-0}" -ge 14 ] && pass "test count >=14 ($n)" || fail "test count >=14 ($n)"
echo "SCORE $P/$((P+F))"

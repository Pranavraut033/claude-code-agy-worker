# usage: source after setting RUN
pass(){ echo "PASS $1"; P=$((P+1)); }
fail(){ echo "FAIL $1"; F=$((F+1)); }
P=0; F=0

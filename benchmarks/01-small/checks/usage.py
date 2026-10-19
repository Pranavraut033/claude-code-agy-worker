"""Sum Claude API usage over a subagent jsonl transcript: argv[1]."""
import json, sys
K=("input_tokens","cache_creation_input_tokens","cache_read_input_tokens","output_tokens"); per={}
for line in open(sys.argv[1]):
    try: e = json.loads(line)
    except Exception: continue
    m = e.get("message") or {}
    u = m.get("usage"); mid = m.get("id")
    if e.get("type") != "assistant" or not u: continue
    per[mid] = {k: max(per.get(mid, {}).get(k, 0), u.get(k, 0) or 0) for k in K}
tot = {k: sum(v[k] for v in per.values()) for k in K}
print(json.dumps({"api_calls": len(per), **tot, "all": sum(tot.values())}))

"""Run inside the run dir (cwd). Prints 'ok/total' of expected registrations that match exactly."""
import importlib, json, sys
sys.path.insert(0, ".")
exp = json.load(open(sys.argv[1]))
from app.new_api import registered
ok = 0
for name, e in exp.items():
    try:
        mod = importlib.import_module(e["module"])
        fn, opts = registered(name)
        good = (fn is getattr(mod, e["func"]) and opts.get("timeout") == e["timeout"]
                and opts.get("retries") == e["retries"] and list(opts.get("tags", [])) == e["tags"])
        ok += bool(good)
    except Exception:
        pass
print(f"{ok}/{len(exp)}")

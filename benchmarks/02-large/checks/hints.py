"""usage: hints.py RUNDIR types.json -> prints 'cov=a/b match=c/d' (annotation slots and functions)."""
import ast, glob, json, os, sys
run, types = sys.argv[1], json.load(open(sys.argv[2]))
norm = lambda s: s.replace(" ", "")
funcs = cov = slots = match = 0
for key, truth in types.items():
    mod, fn = key.split(".")
    path = os.path.join(run, "app/handlers", mod + ".py")
    try: tree = ast.parse(open(path).read())
    except Exception: tree = None
    node = next((n for n in (tree.body if tree else []) if isinstance(n, ast.FunctionDef) and n.name == fn), None)
    funcs += 1
    nslots = 1 + len(truth["params"]); slots += nslots
    if not node: continue
    args = {a.arg: a for a in node.args.args + node.args.kwonlyargs}
    got = {p: (norm(ast.unparse(args[p].annotation)) if p in args and args[p].annotation else None) for p in truth["params"]}
    ret = norm(ast.unparse(node.returns)) if node.returns else None
    if ret is not None and all(v is not None for v in got.values()): cov += 1
    match += (ret == norm(truth["returns"]))
    match += sum(got[p] == norm(t) for p, t in truth["params"].items())
# any extra functions in handlers lacking hints
extra = 0
for f in glob.glob(os.path.join(run, "app/handlers/handler_*.py")):
    for n in ast.parse(open(f).read()).body:
        if isinstance(n, ast.FunctionDef) and f"{os.path.basename(f)[:-3]}.{n.name}" not in types: extra += 1
print(f"cov={cov}/{funcs} match={match}/{slots} extra_funcs={extra}")

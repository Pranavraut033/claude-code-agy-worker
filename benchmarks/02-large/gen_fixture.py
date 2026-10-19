#!/usr/bin/env python3
"""Generate seed/ (a git repo) plus checks/types.json and checks/expected.json. stdlib only, seeded."""
import json, os, random, shutil, subprocess, textwrap
HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
rng = random.Random(42)

PROSE = {  # type -> phrasings (all unambiguous)
    "list[dict]": ["a list of item dicts"],
    "int": ["an int", "an integer"],
    "str": ["a string"],
    "float": ["a float"],
    "bool": ["a bool", "a boolean flag"],
    "list[str]": ["a list of strings"],
    "list[float]": ["a list of floats"],
    "list[int]": ["a list of ints"],
    "list[list[int]]": ["a list of rows, each row a list of ints"],
    "dict[str, int]": ["a dict mapping str to int"],
    "str | None": ["a string, or None when absent"],
    "int | None": ["an int, or None when absent"],
    "None": ["nothing (None)"],
}
# base, params [(name, type, default-source or None, what)], ret (type, what), pre, post, sample args, ref
T = [
 dict(base="count_items", p=[("items", "list[dict]", None, "the items to count")], r=("int", "the count"),
      pre=["n = len(items)"], post=["return n"], args=[[{"a": 1}, {"b": 2}]], ref=lambda items: len(items)),
 dict(base="find_label", p=[("items", "list[dict]", None, "items to search"), ("key", "str", None, "the key to look for")],
      r=("str | None", "the first value for key, as text"),
      pre=["found = None", "for item in items:", "    if key in item:", "        found = str(item[key])", "        break"], post=["return found"],
      args=[[{"a": 1}, {"b": 2}], "b"], ref=lambda items, key: next((str(i[key]) for i in items if key in i), None)),
 dict(base="scale", p=[("values", "list[float]", None, "numbers to scale"), ("factor", "float", "1.0", "the multiplier")],
      r=("list[float]", "the scaled numbers"), pre=["out = [v * factor for v in values]"], post=["return out"],
      args=[[1.0, 2.5], 2.0], ref=lambda values, factor=1.0: [v * factor for v in values]),
 dict(base="join_names", p=[("names", "list[str]", None, "names to join"), ("sep", "str", None, "the separator")],
      r=("str", "the joined text"), pre=["text = sep.join(names)"], post=["return text"],
      args=[["ann", "bo"], "-"], ref=lambda names, sep: sep.join(names)),
 dict(base="tally", p=[("words", "list[str]", None, "words to count")], r=("dict[str, int]", "occurrences per word"),
      pre=["counts = {}", "for w in words:", "    counts[w] = counts.get(w, 0) + 1"], post=["return counts"],
      args=[["a", "b", "a"]], ref=lambda words: {w: words.count(w) for w in dict.fromkeys(words)}),
 dict(base="is_big", p=[("n", "int", None, "the value to test"), ("limit", "int", "10", "the threshold")],
      r=("bool", "whether n exceeds limit"), pre=["big = n > limit"], post=["return big"],
      args=[12, 10], ref=lambda n, limit=10: n > limit),
 dict(base="pick", p=[("mapping", "dict[str, int]", None, "the lookup table"), ("name", "str", None, "the entry to read"),
      ("default", "int | None", "None", "used when name is missing")],
      r=("int | None", "the stored value or the default"), pre=["value = mapping.get(name, default)"], post=["return value"],
      args=[{"x": 3}, "y", 7], ref=lambda mapping, name, default=None: mapping.get(name, default)),
 dict(base="clamp", p=[("x", "float", None, "the number"), ("lo", "float", None, "lower bound"), ("hi", "float", None, "upper bound")],
      r=("float", "x limited to [lo, hi]"), pre=["y = max(lo, min(hi, x))"], post=["return y"],
      args=[5.5, 0.0, 3.0], ref=lambda x, lo, hi: max(lo, min(hi, x))),
 dict(base="note", p=[("msg", "str", None, "the text to record"), ("flag", "bool", "False", "marks it important")],
      r=("None", "nothing"), pre=["shown = msg.upper() if flag else msg"], post=["_ = shown"],
      args=["hi", True], ref=lambda msg, flag=False: None),
 dict(base="pairs", p=[("keys", "list[str]", None, "the keys"), ("vals", "list[int]", None, "the values")],
      r=("dict[str, int]", "keys mapped to values"), pre=["mapping = dict(zip(keys, vals))"], post=["return mapping"],
      args=[["a", "b"], [1, 2]], ref=lambda keys, vals: dict(zip(keys, vals))),
 dict(base="first_or", p=[("items", "list[str]", None, "candidates"), ("fallback", "str | None", "None", "used when empty")],
      r=("str | None", "the first item or the fallback"), pre=["first = items[0] if items else fallback"], post=["return first"],
      args=[[], "zz"], ref=lambda items, fallback=None: items[0] if items else fallback),
 dict(base="total_price", p=[("items", "list[dict]", None, "items with a price key"), ("tax", "float", "0.0", "tax rate")],
      r=("float", "the taxed total"), pre=["subtotal = sum(i[\"price\"] for i in items)"], post=["return subtotal * (1 + tax)"],
      args=[[{"price": 2.0}, {"price": 3.0}], 0.5], ref=lambda items, tax=0.0: sum(i["price"] for i in items) * (1 + tax)),
 dict(base="flatten", p=[("rows", "list[list[int]]", None, "the rows")], r=("list[int]", "all numbers in order"),
      pre=["flat = [n for row in rows for n in row]"], post=["return flat"],
      args=[[[1, 2], [3]]], ref=lambda rows: [n for r in rows for n in r]),
 dict(base="summarize", p=[("items", "list[dict]", None, "items to describe"), ("verbose", "bool", "False", "include details")],
      r=("str", "a one-line summary"), pre=["head = f\"{len(items)} items\""], post=["return head + (\" (verbose)\" if verbose else \"\")"],
      args=[[{"a": 1}], True], ref=lambda items, verbose=False: f"{len(items)} items" + (" (verbose)" if verbose else "")),
]
LOGS = [("starting", "debug"), ("done, ok", "info"), ("slow path (retrying), maybe", "warn"), ("failed: bad input", "error"),
        ("checked", "info"), ("cache miss", "debug"), ("odd value, continuing", "warn"), ("gave up", "error")]
OPTS = [{}, {}, {"timeout": 10}, {"retries": 3}, {"tags": ["a", "b"]}, {"timeout": 5, "retries": 2},
        {"timeout": 60, "tags": ["slow"]}, {"retries": 1, "tags": ["x", "y", "z"]}, {"timeout": 15, "retries": 4, "tags": ["m"]}]

def prose(t): return rng.choice(PROSE[t])
def lit(v): return repr(v)

def fmt_opts(o):
    if not o: return "{}"
    inner = ", ".join(f'"{k}": {lit(v)}' for k, v in o.items())
    return "{" + inner + "}"

def build():
    if os.path.exists(SEED): shutil.rmtree(SEED)
    for d in ("app/handlers", "tests"): os.makedirs(os.path.join(SEED, d))
    w = lambda rel, s: open(os.path.join(SEED, rel), "w").write(s)
    w("app/__init__.py", ""); w("app/handlers/__init__.py", "")
    w("app/registry.py", '''"""Old handler registry (kept for other code)."""

REGISTRY = {}


def register(name, fn, opts):
    """Store fn under name; opts is a dict with optional timeout, retries, tags."""
    REGISTRY[name] = (fn, dict(opts))
    return fn


def lookup(name):
    return REGISTRY[name]
''')
    w("app/log.py", '''"""Old logger (kept for other code)."""

LEVELS = ("debug", "info", "warn", "error")
LINES = []


def log(msg, level):
    if level not in LEVELS:
        raise ValueError(level)
    LINES.append((level, msg))
''')
    w("app/new_api.py", '''"""New handler API: decorator registration and std logging."""
import logging

from app.registry import REGISTRY

logger = logging.getLogger("app")
logger.addHandler(logging.NullHandler())


def handler(name, *, timeout=30, retries=0, tags=()):
    def decorate(fn):
        REGISTRY[name] = (fn, {"timeout": timeout, "retries": retries, "tags": list(tags)})
        return fn
    return decorate


def registered(name):
    """Return (fn, opts) for a registered handler; opts always has timeout, retries, tags."""
    return REGISTRY[name]
''')
    w("tests/test_core_old_api.py", '''import unittest

from app.log import LINES, log
from app.registry import lookup, register


class OldApi(unittest.TestCase):
    def test_register_lookup(self):
        fn = lambda: 1
        register("core.x", fn, {"timeout": 2})
        self.assertEqual(lookup("core.x"), (fn, {"timeout": 2}))

    def test_log(self):
        log("hello", "warn")
        self.assertEqual(LINES[-1], ("warn", "hello"))
        with self.assertRaises(ValueError):
            log("x", "nope")
''')
    types, expected = {}, {}
    for i in range(40):
        mod = f"handler_{i:02d}"
        nf = rng.choice([2, 3, 3])
        picks = rng.sample(T, nf)
        target = rng.randint(max(2, nf), 4)
        nlogs = [1] * nf
        while sum(nlogs) < target: nlogs[rng.randrange(nf)] = 2 if True else 1
        regs = rng.sample(range(nf), rng.choice([1, min(2, nf)]))
        out = [f'"""Handler module {i:02d}."""', "from app.log import log", "from app.registry import register", "", f'PREFIX = "h{i:02d}"', ""]
        tests_beh, tests_reg = [], []
        for k, t in enumerate(picks):
            params = ", ".join(p[0] + (f"={p[2]}" if p[2] else "") for p in t["p"])
            doc = [f"{t['base'].replace('_', ' ').capitalize()}.", "", "Args:"]
            for (pn, pt, pd, what) in t["p"]:
                doc.append(f"    {pn}: {what}; {prose(pt)}" + (f" (default {pd})" if pd else ""))
            doc += ["", "Returns:", f"    {t['r'][1]}; {prose(t['r'][0])}"]
            lines = ["", "", f"def {t['base']}({params}):", '    """' + doc[0]] + [("    " + d).rstrip() for d in doc[1:]] + ['    """']
            msg, lvl = rng.choice(LOGS)
            first = t["p"][0][0]
            m0 = f'f"{t["base"]} called with {{{first}!r}}, level {lvl}"' if rng.random() < 0.4 else f'"{msg}"'
            lines.append(f'    log({m0}, "{lvl}")')
            lines += ["    " + l for l in t["pre"]]
            if nlogs[k] == 2:
                msg2, lvl2 = rng.choice(LOGS)
                lines.append(f'    log("{msg2}", "{lvl2}")')
            lines += ["    " + l for l in t["post"]]
            out += lines
            types[f"{mod}.{t['base']}"] = {"params": {p[0]: p[1] for p in t["p"]}, "returns": t["r"][0]}
            exp = t["ref"](*t["args"])
            call = f"mod.{t['base']}({', '.join(lit(a) for a in t['args'])})"
            tests_beh.append(f"        self.assertIsNone({call})" if t["r"][0] == "None" else f"        self.assertEqual({call}, {lit(exp)})")
        out += ["", ""]
        for k in regs:
            t = picks[k]; o = rng.choice(OPTS)
            name = f"h{i:02d}.{t['base']}"
            out.append(f'register("{name}", {t["base"]}, {fmt_opts(o)})')
            expected[name] = {"module": f"app.handlers.{mod}", "func": t["base"], "timeout": o.get("timeout", 30),
                              "retries": o.get("retries", 0), "tags": list(o.get("tags", []))}
            tests_reg.append(f'        fn, opts = lookup("{name}")\n        self.assertIs(fn, mod.{t["base"]})\n        self.assertEqual(opts, {fmt_opts(o)})')
        w(f"app/handlers/{mod}.py", "\n".join(out) + "\n")
        w(f"tests/test_{mod}.py", f"import unittest\n\nfrom app.handlers import {mod} as mod\nfrom app.registry import lookup\n\n\n"
          f"class Test{mod.title().replace('_', '')}(unittest.TestCase):\n    def test_behaviour(self):\n" + "\n".join(tests_beh) +
          "\n\n    def test_registration(self):\n" + "\n".join(tests_reg) + "\n")
    os.makedirs(os.path.join(HERE, "checks"), exist_ok=True)
    json.dump(types, open(os.path.join(HERE, "checks/types.json"), "w"), indent=1)
    json.dump(expected, open(os.path.join(HERE, "checks/expected.json"), "w"), indent=1)
    subprocess.run("git init -q && git add -A && git -c user.name=bench -c user.email=bench@local commit -qm seed", shell=True, cwd=SEED, check=True)

build()

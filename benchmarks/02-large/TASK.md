Migrate every module in `app/handlers/` to the new API in `app/new_api.py`:
1. Replace each `register("name", fn, {opts})` call with the `@handler("name", ...)` decorator on `fn`, mapping `timeout`/`retries`/`tags` to keyword arguments (tags as a tuple; omit defaults).
2. Replace every `log(msg, level)` call with `logger.<level>(msg)`, where `"warn"` becomes `warning`; import `logger` from `app.new_api`.
3. Add full type hints to every function in `app/handlers/`, derived from its docstring (use built-in generics: `list[dict]`, `int`, `str | None`, …).
4. Update `tests/test_handler_*.py` to check registration through the new decorator's registry (behaviour unchanged).
5. Delete nothing in `app/registry.py` and `app/log.py` (other code may still use them), but no file under `app/handlers/` may import them anymore.
Run `python3 -m unittest discover -s tests` and make sure it passes.

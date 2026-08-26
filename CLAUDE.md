# aiobudgetthuis

Standalone async Python client for the unofficial Budget Thuis (Budget Energie) API.
Primary consumer is the [ha-budget-thuis](https://github.com/jdolieslager/ha-budget-thuis)
Home Assistant integration, but this package is generic asyncio — it must never import or
depend on Home Assistant.

The API is unofficial and undocumented; it may change without notice. Build defensively:
tolerate missing/renamed fields, raise the package's own error types, never crash on
unexpected payload shapes where a `None` will do.

## Layout

```
src/aiobudgetthuis/
├── __init__.py   # public API surface (__all__) + __version__
├── client.py     # BudgetThuisClient: OAuth2+PKCE login, refresh, data endpoints
├── models.py     # dataclass models + parsing (stdlib only, no aiohttp)
└── prices.py     # PriceData: derived price values over HourlyTariffDetails
tests/            # pure-logic tests; all fixtures are fictional
```

## House rules

- Async only; `aiohttp` is the sole runtime dependency. The caller owns the session
  (except `login()`, which needs its own cookie jar).
- `models.py` stays stdlib-only and side-effect free.
- Type everything; `ruff check`, `ruff format --check`, `mypy src`, and `pytest` must all
  pass before work is done (config lives in `pyproject.toml`; CI enforces the same).
- Google-style docstrings; comments explain the non-obvious why, not the what.
- Test fixtures use fictional data only — never real customer names, addresses, ids,
  tokens, or credentials. Persist only refresh tokens in examples; never passwords.
- The public surface is `__all__` in `__init__.py`. Breaking it requires a major/minor
  version bump per SemVer; consumers pin exact versions.
- No logging inside the package; signal problems via `BudgetThuisError` subclasses.

## Release procedure

1. Bump the version in **both** `pyproject.toml` and `src/aiobudgetthuis/__init__.py`
   (`__version__`) — keep them identical.
2. Commit, tag `vX.Y.Z`, push, then publish a GitHub Release.
3. The Release triggers `.github/workflows/publish.yaml`, which builds and uploads to PyPI
   via trusted publishing (environment `pypi`, no tokens).
4. Update the pin in ha-budget-thuis `manifest.json` `requirements` to the new version.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy src && pytest -q
```

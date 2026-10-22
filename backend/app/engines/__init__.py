"""Pure calculation engines (ADR 0004, CLAUDE.md rule 3).

Engines take plain inputs and return a result plus an `explanation`/`reason` string.
They never touch the database, HTTP, the clock, feature flags or environment variables;
services gather those inputs and call the engines. Tunable numbers live in
`app.engines.constants` only. `tests/unit/test_engine_purity.py` enforces the import rules.
"""

# Project: Multilingual Agritech Advisory Agent (Forge buildathon)

Goal: farmers ask in their language; the system pulls LIVE weather, soil and mandi data,
a deterministic rules engine computes risks and a sell/hold signal, and an LLM agent
explains it in the farmer's language with a source and timestamp for every number.

## Non-negotiable rules
- NEVER hardcode data, mock values, placeholder prices or sample JSON in runtime code.
  If an API fails, return an explicit "data unavailable" error. Never invent a number.
- Test fixtures (recorded real API responses) live ONLY under tests/fixtures.
- Before writing any API client, run a script that fetches one real response and prints it.
  Use the real field names; never assume them.
- Every external value is wrapped in Provenanced[T] {value, unit, source, fetched_at}.
- The LLM may state only numbers returned by tools. The rules engine computes; the LLM explains.
- Secrets come from environment variables only. Never log or print keys or tokens.

## Engineering standards
- Python 3.12, full type hints, mypy-clean, ruff-clean.
- Async httpx with explicit timeouts, tenacity retries, typed custom exceptions.
- Pydantic models for all external responses and API schemas.
- Pure functions in rules/, thresholds in rules/thresholds.yaml with a source comment each.
- Structured logging (structlog) with a request id. No print().
- One responsibility per module. Tests for every module (pytest).
- Commands: uv run pytest -m "not live" | uv run ruff check . | uv run mypy src

## Working style
- Propose a short plan and wait for approval before editing files.
- Make one small change at a time, run tests, then summarise what changed and why.
- Explain non-obvious code in plain language; the team must be able to defend it to judges.

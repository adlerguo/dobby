# Agent stack smoke tests

These tests are optional integration smoke checks for a running compose stack. They are skipped by default and are not part of the unit test suite.

Prerequisites:

- Start the full stack first, for example `docker compose up`.
- Configure either real model channels or the project's mock model mode.
- Export `RUN_AGENT_STACK_SMOKE=1`.
- Export `SMOKE_AUTH_TOKEN` with a valid backend bearer token.
- Export `SMOKE_AGENT_ID` for an agent that has the target tool bound.
- Export `SMOKE_TOOL_ID` for a bound tool that should succeed.

Optional checks:

- `SMOKE_FAILING_TOOL_ID` plus `SMOKE_DATABASE_URL` enables the trace lookup after a failing tool run.
- `SMOKE_CODE_TOOL_ID` checks direct code-tool rejection when code tools are disabled.
- `SMOKE_HTTP_TOOL_ID` checks HTTP-tool SSRF blocking against `http://maas:8100/health`.
- `SMOKE_MAAS_BASE_URL` checks MaaS admin rejects missing service token.

Example:

```bash
RUN_AGENT_STACK_SMOKE=1 \
SMOKE_AUTH_TOKEN="$TOKEN" \
SMOKE_AGENT_ID="..." \
SMOKE_TOOL_ID="..." \
SMOKE_DATABASE_URL="postgresql://app:pass@localhost:5432/eap" \
pytest backend/tests/smoke -q
```

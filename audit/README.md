# ByteBattles audit and verification evidence

The original audit is preserved in `AUDIT.md` and the baseline result files. Repairs and current evidence are described in `FIXES.md`. `integration-results.jsonl` records observations of the original implementation. `verification-results.jsonl` records the repaired implementation. `resilience-results.jsonl` records resource-limit, duplicate-job, and actual worker-crash checks. `regression-results.txt` preserves the original seven failing checks. `test_regressions.py` now checks the repaired behavior; the current run is in `final-unit-check.txt` (17 passed).

The integration run used current source files mounted read-only in separate API and judge containers, PostgreSQL, Redis, MinIO, and the existing C/C++/Python sandbox images. PostgreSQL and MinIO used disposable storage. The audit API was bound only to localhost port 18080. No existing application database was used. Starting Docker Desktop automatically restarted existing application containers.

## Reproduce the isolated integration run

Requires Docker and the existing images `bytebattles-api:latest`, `bytebattles-judge:latest`, `judge-gcc:latest`, `judge-python:latest`, `postgres:16`, `redis:latest`, and `cgr.dev/chainguard/minio:latest`. These are locally available images, not immutable reproducibility pins.

1. Run `python3 audit/create_stack.py`. This creates a private temporary Compose configuration with a random test signing key, using `.env.example` rather than `.env`.
2. Start infrastructure: `docker compose -p bytebattles-audit -f /private/tmp/bytebattles-audit-compose.json up -d postgres redis minio`.
3. Wait until PostgreSQL and MinIO are ready, then start the API with the same command ending in `up -d api`. Confirm `http://127.0.0.1:18080/docs` responds.
4. In one terminal run `docker exec -i bytebattles-audit-api-1 .venv/bin/python -u - < audit/verification_probe.py`. Use a fresh audit stack; the fixture creation is intentionally not idempotent.
5. When `FIXTURES_READY` appears, within 60 seconds start the judge with the Compose command ending in `up -d judge`, then run `docker exec bytebattles-audit-redis-1 redis-cli SET audit:judge-ready 1`.
6. Wait for `VERIFICATION_COMPLETE`. The script uses synthetic accounts and bounded sample programs. It directly seeds the admin and tag as a controlled test fixture; the repaired application also provides administrator setup. The zero-testcase and Redis-outage checks deliberately inject faults into disposable data and the current process only.
7. Stop the judge gracefully, allowing it to clean its sandbox pool: `docker compose -p bytebattles-audit -f /private/tmp/bytebattles-audit-compose.json stop judge`.
8. Remove only the audit stack with `docker compose -p bytebattles-audit -f /private/tmp/bytebattles-audit-compose.json down --volumes`. If the judge crashed, identify remaining sandbox IDs from the audit Redis pool before removal; do not delete sandboxes belonging to another instance.

## Run the service-independent regression checks

Use a Python environment containing the project's API/judge dependencies plus pytest. For example, activate your test environment first.

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest audit/test_regressions.py -q -p no:cacheprovider
```

These use mocks for Docker/Redis/process failure paths and do not connect to services. They assert intended correct behavior and now pass after repair. The real integration EOF example complements the focused input-transport test.

## Limits

This is a targeted source review plus local functional and fault-injection audit. It is not a formal security certification, dependency CVE scan, exhaustive concurrency test, or high-load benchmark. No host-escape, disk-exhaustion, fork-bomb, or unbounded output attack was executed. The repaired browser flow was checked for login, problem details, and a C++ submission. Mobile layouts were not comprehensively exercised.

## Resilience tests

After the functional verification, run `docker exec -i -e AUDIT_API_URL=http://api:8000 bytebattles-audit-judge-1 .venv/bin/python -u - < audit/resilience_probe.py`. This deliberately kills one busy worker in the named audit stack, exercises bounded memory/output violations, checks counters under duplicate notifications, and verifies lease fencing and rate limiting. Run against fresh functional-test fixtures. It is never intended for the main stack.

The temporary host Python environment may disappear between sessions. An alternative for unit checks is a disposable container based on the API image with pytest and the Docker SDK installed only into its temporary test directory; project production dependencies are unchanged.

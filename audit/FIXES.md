# Repairs and verification

The audit findings have been addressed in the current source, and the repaired application has been installed in the existing local Compose stack. Existing data was preserved. The historical audit and original failing results remain available for comparison.

## Judge correctness and isolation

- Finite testcase input fixes correct programs that read until EOF.
- Runtime is converted from seconds to milliseconds. GNU time has approximately 10 ms display resolution, so sufficiently short programs can still report 0 ms; that is no longer a seconds/milliseconds conversion error.
- Missing timing data becomes a bounded infrastructure failure rather than an unhandled parser loop or false acceptance.
- Compilation has a deadline; execution and output collection have watchdog/size limits.
- Problem memory limits are enforced by the container memory controller. OOM events are distinguished from timeouts.
- Each testcase gets a fresh sandbox, so files or background processes cannot carry over between testcases. C/C++ compile once and the bounded binary is copied into each execution sandbox.
- Sandboxes retain disabled networking, non-root execution, dropped capabilities, PID limits, and no-new-privileges. Added a CPU quota, read-only root, and size-limited workspace/tmp mounts. Only the workspace permits execution, as required for C/C++ binaries.
- Empty testcase sets never produce Accepted. Infrastructure failures terminate as SKP after three attempts.

## Durable jobs and counters

- A submission and its job are committed together in PostgreSQL. Redis remains the queue; an outbox dispatcher repairs lost delivery after a Redis outage.
- Job ownership uses renewable database leases and unique attempt tokens. A stale worker cannot overwrite a newer attempt.
- Heartbeats run during execution. Worker death, missing heartbeat, shutdown, and scale-down paths no longer rely on unbounded joins or an uninitialized submission ID.
- Duplicate notifications and repeated completion cannot double-count acceptance. Total counts are updated with submission creation, accepted counts with terminal completion.
- Pool reconciliation removes stale queue entries, replenishes missed notifications, retries creation with backoff, and cleans orphaned sandboxes scoped to the correct stack.
- Fixed inherited database connections in multiprocessing children by disposing the inherited pool before creating workers/managers.

## API and account repairs

- Restored admin-only tag creation with validation and duplicate conflicts.
- Added secret-protected, serialized first-admin bootstrap and admin-only promotion. The last admin cannot delete their account.
- Fixed public profile responses and made unverified public profiles readable without exposing email to other users.
- Refresh checks current account existence and session validity. Password changes invalidate old tokens.
- Added registration/login rate limits and race-safe duplicate-account handling.
- Submission source/details require the owner or admin. Hidden testcase input is admin-only. Fixed the testcase storage-bucket lookup.
- Positive bounded time/memory values, source byte limits, bounded HTTP bodies, safe ZIP member validation, matching testcase names, UTF-8 validation, and expanded-size/count limits are enforced.
- Added Redis-backed submission rate limiting with 429 and Retry-After; new admission fails with 503 when the limiter is unavailable.
- Storage cleanup is queued transactionally for metadata deletions and retried. Failed problem uploads schedule their exact uploaded keys for cleanup rather than deleting an entire shared problem prefix. Prefix deletion now uses pagination and checks partial deletion errors. Storage bodies are closed and network timeouts are bounded.

## Browser and setup

- Added problem statements, formats, constraints, samples, search/filter controls, pagination, and total counts.
- Added administrator forms for tags, problems/testcases, bootstrap, and teammate promotion.
- Added automatic access-token refresh, tab-scoped token storage, logout, and clearer errors.
- Replaced overlapping interval polling with a single selected-result poller, bounded waiting, and a Check again button. History entries reopen a result.
- Fixed display of UTC submission timestamps in the user's local timezone.
- Added private configuration/Git/build exclusions, startup rejection of insecure example credentials, automatic bucket creation, and API health checks. Normal port 8000 is bound only to localhost.
- Rotated signing/bootstrap secrets and local database/storage credentials. Updated setup and API documentation. No credentials are included in this report or test results.

## Verification evidence

| Check | Result |
| --- | --- |
| Focused regression suite | 17 passed; `final-unit-check.txt` |
| Real API/database/storage/judge flow | 24 recorded observations; all final assertions passed in `verification-results.jsonl` |
| EOF-reading correct Python solution | Accepted |
| Correct C and C++ solutions | Accepted |
| WA, CE, RE, TLE paths | Expected verdicts |
| 350 ms sleep | Reported approximately 350–360 ms |
| Zero-testcase fault | Bounded SKP, never Accepted |
| Memory overrun | MLE |
| Output overrun | RE with Output limit exceeded; worker remained usable |
| Duplicate queue notifications | One acceptance increment |
| Real busy worker killed | Submission recovered to AC in approximately 37 seconds |
| Two testcases with a workspace marker | Accepted with a fresh workspace for each testcase |
| Multiple C++ testcases | Accepted using the compiled artifact in fresh sandboxes |
| Stale lease / repeated completion | Rejected without double counting |
| Rate limit | 429 plus Retry-After |
| Browser login, problem details, C++ submission | Final AC visible; `ui-verified.png` |

Resource, crash, permission, size, search, and fencing checks are recorded in `resilience-results.jsonl`. Tests used a separate stack and disposable data. The final unit run used a temporary container; test-only dependencies were not added to application images.

## Local upgrade and limits

The existing local database and configuration were backed up under `.backups/20260930-171142/` before migration/credential rotation. Additive job/deletion tables were created, old pending submissions were recovered, and historical counters were reconciled. User accounts, problems, and existing object storage were retained. Log in again after the secret/session changes.

This is a verified local repair pass, not a claim of exhaustive security certification. Public hosting/HTTPS, independent penetration testing, and sustained high-load/distributed testing remain separate work. Problem editing and a fourth judge language were optional extension ideas and were not added in this pass. Very short runtimes can display 0 ms because of timer resolution. Cross-service object writes still require operational monitoring during a simultaneous storage/database outage; normal failure cleanup is retried, but this is not a distributed transaction across PostgreSQL and MinIO.

# ByteBattles audit findings

This is the historical pre-repair audit. See [FIXES.md](FIXES.md) for the implemented repairs and current verification.

Audited 30 September 2026. Recommendation: repair the judge and job-recovery failures before adding features. The application has a working core, but currently rejects some correct programs and can lose submissions.

## What was actually tested

A separate local stack ran the current source against real PostgreSQL, Redis, MinIO, and Docker sandboxes. C, C++, and Python submissions were exercised. The stack used temporary data and synthetic users; the original application database was not used. Existing local images supplied dependencies; source directories were mounted read-only. The API was reachable only on localhost port 18080.

The run produced **24 integration observations**, plus **8 focused mocked regression checks: 7 failures and 1 passing control**. Failed regression checks assert desired correct behavior and intentionally expose present defects; they do not mean seven fixes have been made. The browser was also used to inspect the problem-selection behavior.

Evidence: [integration observations](integration-results.jsonl), [regression results](regression-results.txt), [reproduction instructions](README.md).

## Repair before feature work

### 1. Correct programs that read until EOF time out — high priority, reproduced live

`judge/judge_worker/executor.py:98` sends input but does not signal end-of-input before reading output. A correct Python sum using `input()` was accepted; the equivalent `sys.stdin.read()` program received TLE after approximately two seconds. Other languages' read-until-EOF patterns are also at risk, but were not separately tested.

Repair the input transport so programs receive all input and EOF while output is still drained. Keep the live EOF example as a regression test.

### 2. Known example signing key remains configured — deployment blocker, local configuration confirmed

The local JWT signing key, database password, and object-storage password match `.env.example`. Values were compared without printing them. A publicly known signing key undermines token authenticity: someone knowing an existing account ID can sign a token claiming that identity. No impersonation attempt was made against the original stack.

Generate independent secrets and invalidate old tokens before network exposure. There is no `.gitignore`; `.env` is currently untracked, not already committed, but an indiscriminate add could commit it. Add an explicit exclusion before sharing the repository. The normal Compose API binding is not restricted to localhost.

### 3. Queueing failure leaves a saved submission permanently pending — high priority, fault injection against real database

`api/app/routes/submissions.py:43–50` commits the submission before pushing to Redis. Injecting an enqueue failure left an extra PD row with no queued job. An HTTP failure can therefore occur after durable state has already changed; retrying may create duplicates.

Use a durable handoff/recovery design, such as a transactional outbox with retries and idempotent processing. Do not claim success until the handoff is safely recoverable.

### 4. Worker recovery can lose work or freeze — high priority, mocked reproductions

`judge/run.py:73–115` has three distinct problems:

- A dead worker is removed without requeueing its recorded in-flight submission.
- Scaling down can force-kill a busy worker after five seconds without requeueing its job.
- A live worker with no heartbeat is joined without a timeout, potentially freezing orchestration.

Additionally, `judge/judge_worker/worker.py:63` raises `UnboundLocalError` if Redis fails before the first submission ID is assigned. This was reproduced by injecting a connection failure.

Heartbeats are updated only between jobs. A legitimate long job can therefore be mistaken for a frozen worker. The Redis pop and in-flight bookkeeping are separate operations, leaving a crash window even after the obvious recovery branches are fixed. Use explicit job ownership/acknowledgement, bounded retries, independent heartbeats, and terminal failure states.

### 5. Runtime values use the wrong unit — medium priority, reproduced live and in isolation

`judge/judge_worker/executor.py:120` converts seconds directly to an integer but returns that value as milliseconds. A program sleeping 350 ms reported 0 ms; a two-second timeout reported 2 ms. Convert seconds to milliseconds before rounding. Avoid clamping away useful diagnostic measurements.

### 6. Timing-parser failure can repeatedly retry a submission — medium priority, mocked reproduction

`judge/judge_worker/executor.py:118` assumes the second-last stderr line contains two numeric statistics. Missing statistics cause `IndexError`; other unexpected output can cause conversion errors. The worker retries general exceptions without a retry limit. Parse defensively and distinguish judge infrastructure failures from contestant verdicts.

## Other confirmed functional defects

| Finding | Evidence and impact | Repair |
|---|---|---|
| Missing admin tag endpoint | POST `/problems/tag` returned 405. Tests had to seed a tag directly. | Restore authenticated admin-only creation with validation and duplicate handling. |
| Public verified profile returns 500 | GET `/users/auditstudent` failed for a verified fixture user. `UserResponseUnknown` requires `is_verified`, which the route omits. | Supply the required field and add an API response test. |
| Counters stay at zero | Nine submissions existed; accepted and total counters both remained zero. | Update counters transactionally and prevent retry double-counting. |
| Failed-testcase lookup checks wrong bucket | A WA row had a testcase key, but the response returned no testcase. `shared/models/submission.py:61` checks submission-code storage before reading testcase storage. | Correct the storage lookup and first decide which testcase information should be public. |
| Negative execution limits accepted | Creating a problem with time and memory limits of -1 returned 201. | Validate positive, bounded limits and ensure configured maxima are enforceable. |
| Zero-testcase problem is accepted automatically | After deliberately deleting a fixture's testcases in the disposable database, nonsense code received AC. Normal problem creation rejects empty archives; this was a corrupted-data fault test. | Treat an empty testcase query as an internal error, not success. |
| Deleted user can still refresh | Refresh returned 200 after deleting the fixture account. The resulting token does not restore the account because protected routes recheck user existence. | Check account existence/status when refreshing; consider revocation/versioning. |

## Security and reliability concerns identified in code

These are source-review findings, not claims that a destructive exploit was executed.

- **Unbounded program output:** stdout/stderr chunks accumulate in judge-process memory before truncation. The later 8 KB failure-output slice does not bound collection. Introduce streaming byte limits and terminate over-limit executions. Compilation output is also unbounded.
- **No compilation deadline:** compiler calls can block. The heartbeat timeout is not a reliable substitute and can leave an orphaned sandbox when a worker is terminated.
- **Resource enforcement gaps:** containers get a global 1 GB cap in the reviewed test configuration, while problem-specific memory limits are checked after execution. The container setup lacks a CPU quota and writable-disk quota/read-only-root policy. Existing non-root execution, disabled networking, dropped capabilities, PID limits, and no-new-privileges are positive protections that should be preserved. No container escape was attempted or demonstrated.
- **Unlimited submissions and upload sizes:** submission rate limits and source-size limits are absent. Testcase uploads lack explicit compressed/decompressed size and count limits. Archive upload is admin-only, reducing exposure, but malformed or oversized uploads can still exhaust resources.
- **Public source-code disclosure:** an unauthenticated GET of another user's submission returned its source. This may be intended for an open practice platform; for a contest, it enables copying. Decide the policy, then enforce owner/admin or post-contest access as appropriate. Do not describe this as an authorization bypass if public sharing is intentional.
- **Object-storage cleanup:** `delete_problem_folder` uses one listing without continuation handling. Large testcase sets may leave objects behind. Multi-service uploads/deletes are not transactional and can leave orphaned objects after failures. These paths were not stress-tested.
- **Sandbox pool recovery:** stale container IDs, lost Pub/Sub replenishment messages, and rapid retries on persistent creation failures need reconciliation/backoff. No long-duration pool-recovery test was run.

## Frontend gaps

Browser inspection confirmed that clicking a problem fills its ID and scrolls to submission; it does not display the statement, constraints, or examples. The source always requests the first 20 problems and exposes no pagination controls. It stores refresh tokens but never calls the refresh endpoint, so access-token expiry interrupts sessions. Verdict polling stops after about 45 seconds with no explicit timeout/retry message; multiple submissions can leave overlapping pollers updating the same result box.

These are worthwhile improvements after correctness is stable. A complete admin workflow is also missing. Frontend output escaping is present in the inspected rendering helpers; no XSS exploit was demonstrated.

## What worked

Registration/login, current problem-page offset, longer refresh-token expiry, admin permission denial for ordinary users, problem creation with valid testcase archives, and normal C/C++/Python judging worked in the controlled run. Wrong Answer, Compilation Error, Runtime Error, and Time Limit Exceeded outcomes were observed. Queueing, database persistence, and testcase/source storage worked in the normal path.

## Recommended sequence

1. Protect local secrets and repository hygiene before sharing or exposing the service.
2. Repair EOF handling, runtime units, timing parsing, durable job handoff, and worker recovery.
3. Restore tag creation; fix profile responses, input validation, testcase lookup, and empty-test behavior.
4. Add bounded execution/output/upload controls and submission rate limits.
5. Implement counters and admin bootstrap, then problem details/search/filter UI.
6. Repeat the integration cases, add regression checks for each fix, and prepare a demo with clear contribution evidence.

No application fixes were made during this audit. It is not an exhaustive penetration test, dependency-vulnerability scan, or proof that no additional bugs exist. Memory exhaustion, host escape, sustained load, distributed concurrency, mobile layout, and every language/runtime edge case remain untested.

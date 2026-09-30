# ByteBattles

A competitive-programming platform supplied for TatHack, extended with reliable judging, administrator tools, and a usable browser interface. The original project attribution and license are retained below.

## Start here

Follow [SETUP.md](SETUP.md) for a new installation or a data-preserving local upgrade. Open http://127.0.0.1:8000/app after startup. API documentation is at http://127.0.0.1:8000/docs.

## What works

- Registration/login with automatically refreshed sessions and password-change invalidation.
- Secret-protected first-admin bootstrap and admin-only teammate promotion.
- Admin tag creation and testcase ZIP upload through the website.
- Search by title, difficulty, and tag; paginated problem lists with total counts.
- Full problem statements, constraints, example input/output, and submission history.
- C, C++, and Python judging with AC, WA, CE, RE, TLE, and MLE results.
- Durable submission jobs, renewable execution leases, bounded retries, crash recovery, and duplicate-safe counters.
- Owner/admin-only submission details; testcase contents are restricted to administrators.
- Redis-backed submission rate limiting with 429 and Retry-After.
- Size-limited source/upload/output handling, compilation deadlines, per-testcase memory caps, and fresh sandbox workspaces.

## Architecture

```text
Browser → FastAPI → PostgreSQL (submission + durable job in one transaction)
                         ↓ periodic dispatcher
                     Redis queue
                         ↓ atomic database lease
                      Judge worker
                         ↓
             Compile once, run each testcase in a fresh Docker sandbox
                         ↓
             Commit verdict and acceptance counter once
```

MinIO stores source code and testcases. A warm sandbox pool reduces startup overhead. Sandboxes run as a non-root user, without networking or Linux capabilities, with no-new-privileges, a read-only root, CPU/PID/memory limits, and bounded writable temporary storage. The judge service has Docker-daemon access; contestant sandboxes do not receive the Docker socket.

Redis notifications can be duplicated or lost without losing the database job. A dispatcher retries delivery; workers renew leases while active. An expired worker's token cannot overwrite a newer attempt. After three infrastructure failures the result is `SKP` with a message, rather than an endless pending state.

Total submissions count persisted submissions; accepted submissions count `AC` results. Account/problem deletion removes metadata transactionally and schedules storage cleanup for retry.

## Submission video

- [5–7 minute narration script](demo/VIDEO_SCRIPT.md)
- [Recording walkthrough and demo solutions](demo/RECORDING_GUIDE.md)

## Review and verification

- [Changes and evidence](audit/FIXES.md)
- [Historical audit](audit/AUDIT.md)
- [Test workflow](audit/README.md)
- [API endpoints](docs/endpoints.md)
- [Original judge architecture](docs/Judge_Architecture.pdf) — background; the durable job and per-testcase isolation changes are described above.

The implementation retains Python, FastAPI, SQLAlchemy, PostgreSQL, Redis, MinIO, and Docker. It is intended for a local hackathon demo. Public hosting, HTTPS configuration, and independent security/load testing are separate deployment work.

## License

Copyright - 2026 - DIPANSHU TIWARI

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

Built for learning, systems engineering, and competitive programming infrastructure.

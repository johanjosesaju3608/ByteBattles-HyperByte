# Run ByteBattles locally

ByteBattles uses a FastAPI service, a judge, PostgreSQL, Redis, MinIO, and isolated Docker sandboxes. Docker Desktop must be running. The website is bound to your computer only at http://127.0.0.1:8000/app.

## First installation

From the repository root:

```sh
python3 scripts/setup_secrets.py --fresh
docker volume create bytebattles_postgres
docker volume create bytebattles_minio
cd judge/images
./build_command.sh
cd ../..
docker compose up --build -d
```

`--fresh` generates database and storage passwords as well as signing/bootstrap secrets. Use it only for a new installation, not an existing initialized database. Keep `.env` private; it is excluded from Git and Docker builds. Startup rejects the example signing key and example database/storage passwords.

The API creates database tables and required storage buckets at startup. The judge waits for the API to be healthy. Visit the website at http://127.0.0.1:8000/app, or API documentation at http://127.0.0.1:8000/docs.

## Upgrade an existing local installation

The database password must change in PostgreSQL as well as in `.env`. Editing only `.env` would break the connection. With Docker running:

```sh
docker compose build api judge
python3 scripts/upgrade_local.py
```

This stops the API and judge, saves a private database dump and configuration snapshot in `.backups/`, rotates the database/storage example credentials, adds the job/deletion tables, reconciles historical counters, and creates durable jobs for old pending submissions. Existing users, problems, and stored artifacts are preserved. It then restarts the application. `.backups/` is excluded from Git; keep those files private.

If an upgrade is interrupted, inspect the last error and `.backups/` before retrying. Never remove database volumes as a recovery shortcut. A backup can be restored using PostgreSQL's `pg_restore`; stop application writers before restoring and use the matching configuration snapshot.

## Create the first administrator

1. Register and log in on the website.
2. Open **First administrator setup**.
3. Copy `ADMIN_BOOTSTRAP_TOKEN` from your local `.env` into the token field and submit it.
4. The first successful bootstrap creates an admin. Further bootstrap requests are rejected, even with the token. Concurrent attempts are serialized in PostgreSQL.
5. Use **Administration → Promote a teammate** to promote other registered users.

The token is not embedded in the frontend or returned by an API. Ordinary users cannot promote themselves without it. The last administrator cannot delete their account until another administrator exists.

## Create a problem

An administrator can create tags and problems directly in the website. Problem IDs contain 1–6 letters, numbers, hyphens, or underscores.

A testcase ZIP contains matching files in `inputs/` and `outputs/`, optionally inside one parent folder:

```text
inputs/1.txt
outputs/1.txt
inputs/2.txt
outputs/2.txt
```

Limits: 8 MB compressed, 16 MB expanded, 1 MB per file, 100 pairs. Files must contain UTF-8 text. Example I/O is entered separately on the form. The defaults support time limits of 1–10 seconds and memory limits of 16–512 MB.

## Reliability and verdicts

- The API commits a submission and its durable job together. Redis still supplies the work queue. The dispatcher retries delivery when Redis recovers.
- Workers claim renewable database leases. Expired/crashed work can be reclaimed. A stale worker cannot overwrite a newer attempt, and duplicate jobs cannot double-count acceptance.
- Infrastructure errors are retried at most three times, then displayed as `SKP` with an explanatory message. `SKP` is a judge failure, not an incorrect solution.
- Total counts include all persisted submissions. Accepted counts include only `AC`. Legacy counters are repaired by the upgrade script.
- Each testcase receives a fresh sandbox, finite input, a kernel memory cap, a CPU quota, a compilation/execution deadline, and bounded output. The root filesystem is read-only; writable workspace and temporary directories have size caps. Networking is disabled and capabilities are dropped.
- Standard outcomes are `AC`, `WA`, `TLE`, `MLE`, `CE`, and `RE`. Output-limit violations use `RE` with a clear message.
- Source and result details require the owner or an administrator. Hidden testcase content is only returned to administrators.

## Configuration

Additional limits have defaults in `config.py`. Optional `.env` settings include:

```text
SUBMISSION_RATE_LIMIT=10
SUBMISSION_RATE_WINDOW=60
MAX_CODE_BYTES=65536
MAX_OUTPUT_BYTES=1048576
COMPILE_TIMEOUT_SEC=15
JOB_LEASE_SECONDS=30
MAX_JOB_ATTEMPTS=3
SANDBOX_POOL_ID=bytebattles
```

Use a different `SANDBOX_POOL_ID` for each independent stack sharing one Docker daemon. Infrastructure retries do not require a user to resubmit. Rate limiting intentionally rejects new submissions with 503 while Redis is unavailable; already accepted jobs remain durable.

The API currently uses browser-tab session storage for tokens and automatic access-token refresh. Password changes invalidate old tokens. Secret rotation invalidates existing sessions, so log in again after upgrading.

## Verification

The audit folder contains original findings, fixed-code checks, and test results. See `audit/README.md` for the disposable stack workflow. Functional tests use real PostgreSQL/Redis/MinIO and the same sandbox images; they do not run against the main application's data.

Use `docker compose ps` for service status and `docker compose logs api judge` for errors. A normal shutdown is `docker compose stop`; preserve volumes. Public hosting, HTTPS, independent penetration testing, and large-scale benchmarking are outside this local setup.

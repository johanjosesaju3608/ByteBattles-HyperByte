"""Durable jobs use PostgreSQL for ownership; Redis remains the work queue."""

from datetime import datetime, timedelta, timezone
import logging
import uuid
from sqlalchemy import or_, update
from shared.core import SessionLocal, get_storage_testcases, get_storage_submission_code
from shared.models import JudgeJob, Submission, Problem, Verdict, StorageDeletion
from config import JOB_LEASE_SECONDS, MAX_JOB_ATTEMPTS, REDIS_JOB_LIST

log = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


def claim(submission_id):
    with SessionLocal.begin() as db:
        job = (
            db.query(JudgeJob)
            .filter_by(submission_id=submission_id)
            .with_for_update()
            .first()
        )
        submission = db.get(Submission, submission_id)
        if not job or not submission or submission.verdict != Verdict.PENDING:
            return None
        if job.lease_until and job.lease_until > now():
            return None
        if job.attempts >= MAX_JOB_ATTEMPTS:
            submission.verdict = Verdict.SKIPPED
            submission.output = (
                "Judge infrastructure failed after bounded retries. Please resubmit."
            )
            db.delete(job)
            return None
        job.attempts += 1
        job.lease_token = uuid.uuid4().hex
        job.lease_until = now() + timedelta(seconds=JOB_LEASE_SECONDS)
        return job.lease_token


def renew(submission_id, token):
    with SessionLocal.begin() as db:
        changed = (
            db.query(JudgeJob)
            .filter_by(submission_id=submission_id, lease_token=token)
            .update({"lease_until": now() + timedelta(seconds=JOB_LEASE_SECONDS)})
        )
        return bool(changed)


def attach_container(submission_id, token, container_id):
    with SessionLocal.begin() as db:
        return bool(
            db.query(JudgeJob)
            .filter_by(submission_id=submission_id, lease_token=token)
            .update({"container_id": container_id})
        )


def release(submission_id, token):
    with SessionLocal.begin() as db:
        db.query(JudgeJob).filter_by(
            submission_id=submission_id, lease_token=token
        ).update(
            {
                "lease_until": None,
                "lease_token": None,
                "container_id": None,
                "next_dispatch": None,
            }
        )


def finish(submission_id, token, result):
    with SessionLocal.begin() as db:
        job = (
            db.query(JudgeJob)
            .filter_by(submission_id=submission_id)
            .with_for_update()
            .first()
        )
        if not job or job.lease_token != token:
            return False  # A stale worker cannot overwrite a newer attempt.
        sub = db.query(Submission).filter_by(id=submission_id).with_for_update().first()
        if sub and sub.verdict == Verdict.PENDING:
            sub.verdict = result.verdict
            sub.output = (result.output or "")[:8192] or None
            sub.incorrect_testcase_key = result.incorrect_testcase_key
            sub.walltime_ms = result.runtime_ms
            sub.memory_kb = result.memory_kb
            if result.verdict == Verdict.ACCEPTED:
                db.execute(
                    update(Problem)
                    .where(Problem.id == sub.problem_id)
                    .values(accepted_submissions=Problem.accepted_submissions + 1)
                )
        db.delete(job)
        return True


def dispatch(redis_client, docker_client=None):
    """Every pending job is periodically redispatched until claimed and finished.
    Commit-before-push is safe here: next_dispatch expires if the push fails.
    Duplicate queue entries are harmless because claim is an atomic lease.
    """
    with SessionLocal.begin() as db:
        jobs = (
            db.query(JudgeJob)
            .filter(
                or_(JudgeJob.lease_until.is_(None), JudgeJob.lease_until < now()),
                or_(JudgeJob.next_dispatch.is_(None), JudgeJob.next_dispatch < now()),
            )
            .with_for_update(skip_locked=True)
            .limit(100)
            .all()
        )
        ids = []
        for job in jobs:
            if job.container_id and docker_client:
                try:
                    docker_client.containers.get(job.container_id).remove(force=True)
                except Exception:
                    log.warning(
                        "Could not remove expired sandbox; pool reconciliation will retry"
                    )
            job.container_id = None
            job.next_dispatch = now() + timedelta(seconds=10)
            ids.append(job.submission_id)
    for submission_id in ids:
        redis_client.lpush(REDIS_JOB_LIST, submission_id)


def queue_deletion(db, kind, object_key):
    db.add(StorageDeletion(kind=kind, object_key=object_key))


def cleanup_storage():
    with SessionLocal.begin() as db:
        for item in (
            db.query(StorageDeletion).with_for_update(skip_locked=True).limit(100).all()
        ):
            try:
                store = (
                    get_storage_testcases()
                    if item.kind == "testcase"
                    else get_storage_submission_code()
                )
                store.delete_file(item.object_key)
                db.delete(item)
            except Exception:
                log.warning("Object deletion will be retried")

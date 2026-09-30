import os
import threading
import time
import redis
from config import (
    REDIS_DB,
    REDIS_JOB_LIST,
    REDIS_HOST,
    REDIS_PORT,
    SHUTDOWN_KEY,
    WORKER_PREFIX,
)
from .database import Database
from .executor import JudgeExecutor
from .pipeline import JudgePipeline
from .redis_queue import RedisQueues
from .storage_adapter import StorageAdapter
from shared import jobs
from ..utils import setup_logger


class JudgeWorker:
    def __init__(self, identifier):
        self.identifier = identifier
        self.local_shutdown_key = f"{WORKER_PREFIX}:{identifier}:shutdown"
        self.local_heartbeat_key = f"{WORKER_PREFIX}:{identifier}:heartbeat"
        self.current_submission_key = f"{WORKER_PREFIX}:{identifier}:submission"
        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        self.pipeline = JudgePipeline(
            Database(), StorageAdapter(), RedisQueues(self.redis), JudgeExecutor()
        )
        self.log = setup_logger(f"worker-{identifier}", f"logs/worker_{identifier}.log")
        self.stop = threading.Event()
        self.active = None

    def _heartbeat(self):
        while not self.stop.is_set():
            try:
                self.redis.set(self.local_heartbeat_key, time.time(), ex=30)
                self.redis.set(
                    f"{WORKER_PREFIX}:{self.identifier}:pid", os.getpid(), ex=30
                )
            except redis.RedisError:
                self.log.warning("Heartbeat Redis unavailable")
            active = self.active
            if active:
                try:
                    if not jobs.renew(*active):
                        self.log.warning(
                            "Job lease lost; stale result will be rejected"
                        )
                except Exception:
                    self.log.warning("Lease renewal failed")
            self.stop.wait(3)

    def _consume_from_list(self):
        while not self.stop.is_set():
            submission_id = token = None
            try:
                if (
                    self.redis.get(SHUTDOWN_KEY) == "1"
                    or self.redis.get(self.local_shutdown_key) == "1"
                ):
                    return
                item = self.redis.brpop(REDIS_JOB_LIST, timeout=1)
                if not item:
                    continue
                submission_id = int(item[1])
                token = jobs.claim(submission_id)
                if not token:
                    continue
                self.active = (submission_id, token)
                self.redis.set(self.current_submission_key, submission_id)
                result = self.pipeline.process_submission(submission_id, token)
                jobs.finish(submission_id, token, result)
                self.log.info(
                    "Submission %s finished: %s", submission_id, result.verdict.value
                )
            except Exception:
                self.log.exception(
                    "Job or queue operation failed; durable job will retry"
                )
                self.stop.wait(1)
            finally:
                self.active = None
                if token:
                    try:
                        jobs.release(submission_id, token)
                    except Exception:
                        self.log.warning("Lease release failed; expiry will recover it")
                try:
                    self.redis.delete(self.current_submission_key)
                except redis.RedisError:
                    pass

    def run(self):
        heartbeat = threading.Thread(target=self._heartbeat, daemon=True)
        heartbeat.start()
        try:
            self._consume_from_list()
        finally:
            self.stop.set()
            heartbeat.join(timeout=5)
            try:
                self.redis.delete(self.local_heartbeat_key, self.local_shutdown_key)
            except redis.RedisError:
                pass

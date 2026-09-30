import time
import signal
import uuid
import multiprocessing as mp
import docker
from redis import Redis
from .sandbox_manager import SandboxManager
from .judge_worker import JudgeWorker
from shared import jobs
from shared.core import Base, engine
from config import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_JOB_LIST,
    MINIMUM_JUDGE_WORKER,
    MAXIMUM_JUDGE_WORKER,
    SHUTDOWN_KEY,
    WORKER_PREFIX,
    JUDGE_WORKER_TIMEOUT,
    validate_security_config,
)
from .utils import setup_logger


def run_worker(identifier):
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    engine.dispose(close=False)
    JudgeWorker(identifier).run()


def run_pool():
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    engine.dispose(close=False)
    SandboxManager().run()


class JudgeOrchestrator:
    def __init__(self):
        validate_security_config()
        Base.metadata.create_all(bind=engine)
        self.redis = Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        self.client = docker.from_env(timeout=10)
        self.min_workers = MINIMUM_JUDGE_WORKER
        self.max_workers = MAXIMUM_JUDGE_WORKER
        self.sandbox_manager_process = None
        self.workers = []
        self.log = setup_logger("orchestrator", "logs/orchestrator.log")
        self.redis.set(SHUTDOWN_KEY, "0")
        self.kill_now = False
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def start_sandbox_manager(self):
        p = mp.Process(target=run_pool)
        p.start()
        self.sandbox_manager_process = p

    def spawn_worker(self):
        identifier = uuid.uuid4().hex
        self.redis.set(f"{WORKER_PREFIX}:{identifier}:shutdown", "0")
        self.redis.set(f"{WORKER_PREFIX}:{identifier}:heartbeat", time.time(), ex=30)
        p = mp.Process(target=run_worker, args=(identifier,))
        p.start()
        self.workers.append((identifier, p))

    def _retire(self, identifier, p):
        self.redis.set(f"{WORKER_PREFIX}:{identifier}:shutdown", "1", ex=60)
        p.join(timeout=5)
        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
        if p.is_alive():
            p.kill()
            p.join(timeout=2)
        # The database lease/outbox survives even if Redis bookkeeping is absent.
        submission = self.redis.get(f"{WORKER_PREFIX}:{identifier}:submission")
        if submission:
            self.redis.lpush(REDIS_JOB_LIST, submission)
        self.redis.delete(
            f"{WORKER_PREFIX}:{identifier}:heartbeat",
            f"{WORKER_PREFIX}:{identifier}:submission",
            f"{WORKER_PREFIX}:{identifier}:pid",
        )

    def stop_worker(self):
        # Scale down only idle workers; shutdown/crash recovery handles busy ones.
        for item in list(reversed(self.workers)):
            identifier, p = item
            if not self.redis.get(f"{WORKER_PREFIX}:{identifier}:submission"):
                self._retire(identifier, p)
                self.workers.remove(item)
                return

    def check_heartbeat(self):
        for item in list(self.workers):
            identifier, p = item
            hb = self.redis.get(f"{WORKER_PREFIX}:{identifier}:heartbeat")
            if (
                not p.is_alive()
                or not hb
                or time.time() - float(hb) > JUDGE_WORKER_TIMEOUT
            ):
                self._retire(identifier, p)
                self.workers.remove(item)

    def scale(self):
        desired = min(
            self.max_workers,
            max(self.min_workers, self.redis.llen(REDIS_JOB_LIST) // 5 + 1),
        )
        if len(self.workers) < desired:
            for _ in range(desired - len(self.workers)):
                self.spawn_worker()
        elif len(self.workers) > desired:
            for _ in range(len(self.workers) - desired):
                self.stop_worker()

    def exit_gracefully(self, signum, frame):
        self.kill_now = True

    def shutdown(self):
        try:
            self.redis.set(SHUTDOWN_KEY, "1")
        except Exception:
            pass
        for identifier, p in self.workers:
            try:
                self._retire(identifier, p)
            except Exception:
                if p.is_alive():
                    p.terminate()
                p.join(timeout=5)
        p = self.sandbox_manager_process
        if p:
            p.join(timeout=10)
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)

    def run(self):
        try:
            self.start_sandbox_manager()
            while not self.kill_now:
                try:
                    if not self.sandbox_manager_process.is_alive():
                        self.sandbox_manager_process.join(timeout=1)
                        self.start_sandbox_manager()
                    jobs.dispatch(self.redis, self.client)
                    jobs.cleanup_storage()
                    self.check_heartbeat()
                    self.scale()
                except Exception:
                    self.log.exception("Service unavailable; retrying orchestration")
                time.sleep(2)
        finally:
            self.shutdown()


if __name__ == "__main__":
    JudgeOrchestrator().run()

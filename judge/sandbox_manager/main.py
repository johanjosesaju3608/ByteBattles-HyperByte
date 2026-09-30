import docker
import redis
import json
import threading
import uuid
import time
from datetime import datetime, timezone
from shared.core import SessionLocal
from shared.models import JudgeJob
from config import SANDBOX_POOL_ID, WORKSPACE_DIR
from queue import Queue, Empty as QueueEmpty

from shared.models import Language, IMAGE

from config import REDIS_HOST, REDIS_PORT, REDIS_DB
from config import (
    MAX_PIDS,
    MAX_MEMCAP_GB,
    REDIS_RESULT_CHANNEL,
    WARM_QUEUE_PREFIX,
    SHUTDOWN_KEY,
)
from config import CONTAINER_POOL_THRESHOLD, CONTAINER_WORKER_COUNT

from ..utils import setup_logger


class SandboxManager:

    def __init__(
        self,
        redis_host=REDIS_HOST,
        redis_port=REDIS_PORT,
        redis_db=REDIS_DB,
        pool_threshold=CONTAINER_POOL_THRESHOLD,
    ):

        self.client = docker.from_env(timeout=10)

        self.redis = redis.Redis(
            host=redis_host, port=redis_port, db=redis_db, decode_responses=True
        )

        self.pubsub = self.redis.pubsub()
        self.pubsub.subscribe(REDIS_RESULT_CHANNEL)

        self.task_queue = Queue()
        self.threads = []
        self.stop_event = threading.Event()
        self.pending_lock = threading.Lock()

        self.pool_threshold = pool_threshold
        self.log = setup_logger("sandbox", "logs/sandbox.log")

        self.pending = {}
        for lang in Language:
            self.pending[lang.value] = 0

    # =================================================
    # QUEUE HELPERS
    # =================================================

    def warm_queue(self, language: Language) -> str:
        return f"{WARM_QUEUE_PREFIX}:{language}"

    # =================================================
    # HEALTHCHECK
    # =================================================

    def healthcheck(self, container) -> bool:
        try:
            result = container.exec_run(["/bin/sh", "-lc", "true"])
            return result.exit_code == 0
        except Exception:
            return False

    # =================================================
    # COUNT WARM SANDBOXES
    # =================================================

    def count(self, language: Language) -> int:

        return self.redis.llen(self.warm_queue(language))

    # =================================================
    # CREATE SANDBOX
    # =================================================

    def create_sandbox(self, language: Language):

        image = IMAGE[language]

        container = self.client.containers.create(
            name=f"sandbox_{language}_{uuid.uuid4().hex}",
            image=image,
            tty=True,
            detach=True,
            auto_remove=False,
            labels={
                "bytebattles.pool": SANDBOX_POOL_ID,
                "bytebattles.sandbox-version": "3",
            },
            read_only=True,
            nano_cpus=1_000_000_000,
            tmpfs={
                WORKSPACE_DIR: "size=64m,uid=1000,gid=1000,mode=0700,nosuid,nodev,exec",
                "/tmp": "size=32m,uid=1000,gid=1000,mode=1777,nosuid,nodev,noexec",
            },
            cap_drop=["ALL"],
            network_mode="none",
            security_opt=["no-new-privileges"],
            mem_limit=str(MAX_MEMCAP_GB) + "g",
            memswap_limit=str(MAX_MEMCAP_GB) + "g",
            pids_limit=MAX_PIDS,
            user="run",
        )

        # START CONTAINER
        try:
            container.start()
        except Exception:
            container.remove(force=True)
            raise

        # HEALTHCHECK
        if not self.healthcheck(container):

            try:
                container.remove(force=True)
            except Exception:
                pass

            raise RuntimeError("Healtcheck failed")

        container_id = container.id

        # PUSH TO WARM QUEUE
        self.redis.lpush(self.warm_queue(language), container_id)

        return container_id

    # =================================================
    # CREATOR WORKER
    # =================================================

    def creator_worker(self):
        while not self.stop_event.is_set():

            try:
                language = self.task_queue.get(timeout=1)
            except QueueEmpty:
                continue

            try:
                self.create_sandbox(language)
                with self.pending_lock:
                    self.pending[language] -= 1
            except Exception as e:
                self.task_queue.put(language)
                self.log.error(e)
                self.stop_event.wait(2)
            finally:
                self.task_queue.task_done()

    def reconcile(self):
        queued = set()
        for lang in Language:
            key = self.warm_queue(lang.value)
            for cid in self.redis.lrange(key, 0, -1):
                try:
                    c = self.client.containers.get(cid)
                    valid = (
                        c.status == "running"
                        and c.labels.get("bytebattles.sandbox-version") == "3"
                    )
                except docker.errors.NotFound:
                    valid = False
                if valid:
                    queued.add(cid)
                else:
                    self.redis.lrem(key, 0, cid)
                    try:
                        self.client.containers.get(cid).remove(force=True)
                    except docker.errors.NotFound:
                        pass
            self.maintain_pool(lang.value)
        with SessionLocal() as db:
            active = {
                row[0]
                for row in db.query(JudgeJob.container_id)
                .filter(JudgeJob.lease_until > datetime.now(timezone.utc))
                .all()
            }
        for c in self.client.containers.list(
            all=True, filters={"label": "bytebattles.pool=" + SANDBOX_POOL_ID}
        ):
            created = datetime.fromisoformat(c.attrs["Created"].replace("Z", "+00:00"))
            if (
                c.id not in queued
                and c.id not in active
                and (datetime.now(timezone.utc) - created).total_seconds() > 60
            ):
                c.remove(force=True)

    # =================================================
    # MAINTAIN POOL
    # =================================================

    def maintain_pool(self, language: Language):

        with self.pending_lock:
            deficit = self.pool_threshold - (
                self.count(language) + self.pending[language]
            )
            if deficit <= 0:
                return

            self.pending[language] += deficit

        self.log.info(f"Maintaing pool - {language} - creating {deficit} containers")

        for _ in range(deficit):
            self.task_queue.put(language)

    # =================================================
    # CLEAN POOL
    # =================================================

    def clean_pool(self, language: Language):

        self.log.info(f"Cleaning pool - {language}")

        while self.count(language) > 0:

            try:
                container_id = self.redis.rpop(self.warm_queue(language))
                container = self.client.containers.get(container_id)
                container.remove(force=True)

            except Exception as e:
                self.log.error(e)

    # =================================================
    # MAIN
    # =================================================

    def run(self):
        try:
            # STARTING CREATOR WORKERS
            for _ in range(CONTAINER_WORKER_COUNT):
                t = threading.Thread(target=self.creator_worker)
                t.start()
                self.threads.append(t)

            # INITIAL POOL
            for language in Language:
                self.maintain_pool(language.value)

            self.log.info(f"Running...")

            last_reconcile = 0
            while self.redis.get(SHUTDOWN_KEY) != "1":
                if time.monotonic() - last_reconcile > 3:
                    self.reconcile()
                    last_reconcile = time.monotonic()
                message = self.pubsub.get_message(timeout=1)
                if not message:
                    continue

                if message["type"] != "message":
                    continue

                data = message["data"]
                data = json.loads(data)
                language = data["language"]
                self.maintain_pool(language)

        except KeyboardInterrupt:
            pass
        finally:
            self.log.info(f"Stopping...")
            self.stop_event.set()

            for t in self.threads:
                t.join()
            for language in Language:
                self.clean_pool(language.value)

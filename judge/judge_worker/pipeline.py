import docker
from contextlib import contextmanager
from shared.models import Submission, TestCase, Language, Verdict, Problem
from shared import jobs
from config import ACQUIRE_TIMEOUT_SECONDS, WORKSPACE_DIR
from .types import SubmissionResult


class JudgePipeline:
    def __init__(self, db, storage, queues, executor):
        self.db = db
        self.storage = storage
        self.queues = queues
        self.executor = executor
        self.client = docker.from_env(timeout=10)

    @contextmanager
    def sandbox(self, language, submission_id, lease_token):
        cid = self.queues.acquire_warm_sandbox(
            language.value, timeout=ACQUIRE_TIMEOUT_SECONDS
        )
        if cid is None:
            raise TimeoutError("No warm sandbox available")
        container = None
        try:
            container = self.client.containers.get(cid)
            if not jobs.attach_container(submission_id, lease_token, cid):
                raise RuntimeError("Job lease lost before execution")
            self.queues.publish_event(
                {"language": language.value, "submission_id": submission_id}
            )
            yield container
        finally:
            if container:
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass

    def process_submission(self, submission_id, lease_token):
        with self.db.session() as db:
            sub = db.get(Submission, submission_id)
            if not sub:
                raise ValueError("Submission no longer exists")
            problem = db.get(Problem, sub.problem_id)
            cases = (
                db.query(TestCase)
                .filter_by(problem_id=sub.problem_id)
                .order_by(TestCase.id)
                .all()
            )
            if not problem or not cases:
                raise ValueError("Problem has no valid testcases")
            language = sub.language
            time_limit = problem.time_limit_sec
            memory_limit = problem.memory_limit_mb * 1024
            source_key = sub.code_object_key
        source = self.storage.read_submission_code(source_key)
        result = SubmissionResult(
            submission_id=submission_id,
            verdict=Verdict.ACCEPTED,
            runtime_ms=0,
            memory_kb=0,
        )
        binary = None
        if language in (Language.C, Language.CPP):
            with self.sandbox(language, submission_id, lease_token) as container:
                self.executor.copy_code_to_container(container, language, source)
                compilation = (
                    self.executor.compile_c
                    if language == Language.C
                    else self.executor.compile_cpp
                )(container)
                if not compilation.ok:
                    result.verdict = Verdict.COMPILATION_ERROR
                    result.output = compilation.output
                    return result
                binary = self.executor.read_binary(container)
        elif language != Language.PYTHON:
            raise ValueError("Unsupported language")
        for idx, case in enumerate(cases, 1):
            # Each testcase gets fresh memory, processes, and a bounded workspace.
            with self.sandbox(language, submission_id, lease_token) as container:
                if binary is None:
                    self.executor.copy_code_to_container(container, language, source)
                    path = WORKSPACE_DIR + "/main.py"
                else:
                    self.executor.copy_binary(container, binary)
                    path = WORKSPACE_DIR + "/main.out"
                run = self.executor.run_program(
                    container,
                    language,
                    path,
                    self.storage.read_testcase_input(case.input_key).decode("utf-8"),
                    self.storage.read_testcase_output(case.output_key).decode("utf-8"),
                    time_limit,
                    memory_limit,
                )
                result.runtime_ms = max(result.runtime_ms, run.runtime_ms)
                result.memory_kb = max(result.memory_kb, run.memory_kb)
                if not run.ok:
                    result.verdict = run.verdict
                    result.output = run.output
                    result.incorrect_testcase_key = case.input_key
                    result.incorrect_testcase_idx = idx
                    break
        return result

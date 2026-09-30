"""Focused regression checks for the repaired execution and recovery paths."""

import io
import os
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from fastapi import HTTPException

for line in (
    (Path(__file__).resolve().parents[1] / ".env.example").read_text().splitlines()
):
    if line and not line.startswith("#"):
        key, value = line.split("=", 1)
        os.environ[key] = value
os.environ["SECRET_KEY"] = "test-only-" + "a" * 64
from judge.judge_worker.executor import JudgeExecutor
from judge.judge_worker.worker import JudgeWorker
from judge.run import JudgeOrchestrator
from shared.models import Language, Verdict
from config import REDIS_JOB_LIST, MAX_OUTPUT_BYTES
from api.app.routes.problems import read_testcases
from api.app.schemas.submissions import SubmissionCreate
from api.app.utils.oauth2 import (
    user_payload,
    valid_session,
    create_access_token,
    verify_token,
)


def executor_case(stats="__BB_TIME__ 0.35 1024\n", code=0, overflow=False, oom=False):
    executor = JudgeExecutor.__new__(JudgeExecutor)
    executor._copy = Mock()
    executor._execute = Mock(return_value=(code, "3\n", stats, False, overflow))
    executor._oom_count = Mock(side_effect=[0, 1 if oom else 0])
    result = executor.run_program(
        Mock(), Language.PYTHON, "/workspace/main.py", "1 2\n", "3\n", 2, 65536
    )
    return executor, result


def test_runtime_is_milliseconds():
    _, result = executor_case()
    assert result.runtime_ms == 350


def test_input_is_a_finite_file_not_open_stdin():
    executor, result = executor_case()
    assert executor._copy.call_args.args[1:] == (".input", b"1 2\n")
    assert "< /workspace/.input" in executor._execute.call_args.args[1]
    assert result.verdict == Verdict.ACCEPTED


def test_missing_timing_statistics_never_accepts():
    with pytest.raises(RuntimeError, match="statistics missing"):
        executor_case(stats="")


def test_output_limit_is_terminal_execution_error():
    _, result = executor_case(overflow=True)
    assert result.verdict == Verdict.RUNTIME_ERROR
    assert "Output limit" in result.output


def test_oom_is_not_misclassified_as_timeout():
    _, result = executor_case(code=137, oom=True)
    assert result.verdict == Verdict.MEMORY_LIMIT_EXCEEDED


def test_stream_collection_is_bounded():
    executor = JudgeExecutor.__new__(JudgeExecutor)
    executor.client = Mock()
    executor.client.api.exec_create.return_value = {"Id": "test"}
    executor.client.api.exec_inspect.return_value = {"ExitCode": 137}
    with patch(
        "judge.judge_worker.executor.frames_iter",
        return_value=iter([(1, b"x" * (MAX_OUTPUT_BYTES + 1))]),
    ):
        _, out, err, _, overflow = executor._execute(Mock(), "echo", 3)
    assert overflow and len(out) + len(err) <= MAX_OUTPUT_BYTES
    assert executor.client.api.exec_create.call_args.kwargs["stdin"] is False


def orchestrator(alive):
    obj = JudgeOrchestrator.__new__(JudgeOrchestrator)
    obj.redis = Mock()
    obj.redis.get.return_value = "123"
    obj.log = Mock()
    proc = Mock()
    proc.is_alive.return_value = alive
    obj.workers = [(1, proc)]
    return obj, proc


def test_dead_worker_requeues_and_keeps_durable_job():
    obj, _ = orchestrator(False)
    obj.check_heartbeat()
    obj.redis.lpush.assert_called_once_with(REDIS_JOB_LIST, "123")
    assert not obj.workers


def test_scale_down_does_not_kill_busy_worker():
    obj, proc = orchestrator(True)
    obj.stop_worker()
    proc.terminate.assert_not_called()
    assert len(obj.workers) == 1


def test_missing_heartbeat_never_joins_without_timeout():
    obj, proc = orchestrator(True)
    obj.redis.get.return_value = None
    obj.check_heartbeat()
    assert all("timeout" in call.kwargs for call in proc.join.call_args_list)


def test_queue_outage_before_job_is_received_does_not_crash():
    obj = JudgeWorker.__new__(JudgeWorker)
    obj.redis = Mock()
    obj.redis.get.side_effect = [ConnectionError("offline"), "1"]
    obj.local_shutdown_key = "test:shutdown"
    obj.current_submission_key = "test:submission"
    obj.log = Mock()
    obj.stop = threading.Event()
    obj.active = None
    with patch.object(obj.stop, "wait", return_value=False):
        obj._consume_from_list()
    obj.log.exception.assert_called_once()


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return out.getvalue()


def test_zip_root_folders_and_matching_names():
    assert read_testcases(archive([("inputs/a.txt", "1"), ("outputs/a.txt", "2")])) == [
        ("a.txt", b"1", b"2")
    ]


@pytest.mark.parametrize(
    "entries",
    [
        [("inputs/a", "1"), ("outputs/b", "2")],
        [("../inputs/a", "1"), ("../outputs/a", "2")],
        [("inputs/a", "1"), ("outputs/a", b"\xff")],
        [],
    ],
)
def test_bad_archives_are_rejected(entries):
    with pytest.raises(HTTPException):
        read_testcases(archive(entries))


def test_code_size_is_measured_in_bytes():
    with pytest.raises(ValueError):
        SubmissionCreate(problem_id="TEST", code="🙂" * 20000, language="PY")


def test_password_change_invalidates_existing_tokens():
    user = SimpleNamespace(id=1, password_hash="original")
    payload = user_payload(user)
    token = create_access_token(payload)
    assert valid_session(verify_token(token, "access"), user)
    user.password_hash = "changed"
    assert not valid_session(payload, user)

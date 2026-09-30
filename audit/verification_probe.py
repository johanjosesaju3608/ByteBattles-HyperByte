"""Run ONLY inside the disposable audit API container; never against real data.
Uses current application code, PostgreSQL, Redis, MinIO and a separate judge.
Produces observations, not a claim that observed buggy behavior is correct.
"""

import io
import os

if os.environ.get("BYTEBATTLES_AUDIT") != "1":
    raise RuntimeError("Refusing to seed data outside the disposable audit stack")

import json
import time
import urllib.request
import urllib.error
import zipfile
from unittest.mock import patch
from shared.core import SessionLocal, get_storage_testcases, get_storage_submission_code
from shared.models import User, UserType, Category, Problem, Submission, TestCase
from api.app.utils import oauth2
from api.app.schemas.user import TokenPayload
import jwt

observations = []


def record(name, **details):
    item = dict(name=name, **details)
    observations.append(item)
    print(
        json.dumps(
            item, default=lambda v: v.decode() if isinstance(v, bytes) else str(v)
        ),
        flush=True,
    )


def request(method, path, data=None, token=None, raw=None, content_type=None):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        raw = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path, data=raw, headers=headers, method=method
    )
    try:
        response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        response = e
    body = response.read().decode(errors="replace")
    try:
        body = json.loads(body)
    except ValueError:
        pass
    return response.status, body


def login(username):
    status, body = request(
        "POST",
        "/auth/login",
        raw=f"username={username}&password=Testing123".encode(),
        content_type="application/x-www-form-urlencoded",
    )
    assert status == 200, (status, body)
    return body


def problem(pid, inputs="1 2\n", output="3\n", limit=2, memory=64):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("cases/inputs/1.txt", inputs)
        z.writestr("cases/outputs/1.txt", output)
    fields = dict(
        id=pid,
        title="Audit " + pid,
        description="Add the two integers",
        difficulty="EASY",
        constraints='["small integers"]',
        tags='["audit"]',
        sample_io='{"1 2":"3"}',
        input_desc="two integers",
        output_desc="sum",
        memory_limit_mb=str(memory),
        time_limit_sec=str(limit),
        visibility="true",
    )
    boundary = "audit-multipart-boundary"
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="tests_zip"; filename="cases.zip"\r\nContent-Type: application/zip\r\n\r\n'.encode()
        + archive.getvalue()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return request(
        "POST",
        "/problems/",
        token=admin,
        raw=b"".join(parts),
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def submit(name, code, language="PY", pid="SUM001", expected="AC"):
    start = time.monotonic()
    status, result = request(
        "POST",
        "/submissions/",
        dict(problem_id=pid, code=code, language=language),
        token=student,
    )
    if status != 201:
        record(name, status=status, result=result)
        return None
    sid = result["id"]
    while time.monotonic() - start < 15:
        status, result = request("GET", f"/submissions/{sid}", token=student)
        if status != 200 or result["verdict"] != "PD":
            break
        time.sleep(0.2)
    record(
        name,
        status=status,
        submission_id=sid,
        expected=expected,
        verdict=result.get("verdict") if isinstance(result, dict) else result,
        runtime_ms=result.get("walltime_ms") if isinstance(result, dict) else None,
        elapsed_seconds=round(time.monotonic() - start, 2),
        output=result.get("output") if isinstance(result, dict) else None,
    )
    return sid


# Seed controlled test fixtures; exercise the real bootstrap endpoint below.
for storage in (get_storage_testcases(), get_storage_submission_code()):
    storage.client.head_bucket(Bucket=storage.bucket_name)
for name in ("auditadmin", "auditstudent", "auditother"):
    status, body = request(
        "POST",
        "/auth/register",
        dict(
            username=name,
            email=name + "@example.com",
            password="Testing123",
            conf_password="Testing123",
        ),
    )
    assert status == 201, (status, body)
with SessionLocal() as db:
    # Administrator is bootstrapped through the real endpoint below.
    db.query(User).filter_by(username="auditstudent").one().is_verified = True
    db.add(Category(name="Audit", slug="audit"))
    db.commit()
admin = login("auditadmin")["access_token"]
student_tokens = login("auditstudent")
student = student_tokens["access_token"]
# Bootstrap uses the secret only within the disposable API container.
req = urllib.request.Request(
    "http://127.0.0.1:8000/users/bootstrap-admin",
    data=b"",
    method="POST",
    headers={
        "Authorization": "Bearer " + admin,
        "X-Bootstrap-Token": os.environ["ADMIN_BOOTSTRAP_TOKEN"],
    },
)
assert urllib.request.urlopen(req).status == 200
record("register_login_bootstrap", status="working")
access = jwt.decode(student, options={"verify_signature": False})
refresh = jwt.decode(
    student_tokens["refresh_token"], options={"verify_signature": False}
)
record("refresh_token_lifetime", difference_seconds=refresh["exp"] - access["exp"])
record(
    "restored_tag_endpoint",
    status=request("POST", "/problems/tag", dict(name="New", slug="new"), token=admin)[
        0
    ],
)
record("public_verified_profile", status=request("GET", "/users/auditstudent")[0])
record("create_problem", response=problem("SUM001"))
record(
    "problem_page_one",
    status=request("GET", "/problems/?limit=5")[0],
    ids=[p["id"] for p in request("GET", "/problems/?limit=5")[1]],
)
record(
    "nonadmin_create_problem", status=request("POST", "/problems/", token=student)[0]
)
# Print marker before judge starts in a separate command.
print("FIXTURES_READY", flush=True)
for _ in range(60):
    from api.app.utils.redis_utils import get_redis_client

    if get_redis_client().get("audit:judge-ready"):
        break
    time.sleep(1)
else:
    raise RuntimeError("Audit judge not started within 60 seconds")

sid = submit("python_line_input", "a,b=map(int,input().split()); print(a+b)")
submit(
    "python_read_until_eof", "import sys; print(sum(map(int,sys.stdin.read().split())))"
)
submit(
    "cpp_correct",
    "#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b;}",
    "CPP",
)
submit(
    "c_correct",
    '#include <stdio.h>\nint main(){int a,b;scanf("%d%d",&a,&b);printf("%d",a+b);}',
    "C",
)
submit("wrong_answer", "print(99)", expected="WA")
submit("compilation_error", "int main( {", "C", expected="CE")
submit("runtime_error", 'raise RuntimeError("audit")', expected="RE")
submit("time_limit", "while True: pass", expected="TLE")
submit("runtime_units", "import time; time.sleep(.35); print(3)")
if sid:
    status, body = request("GET", f"/submissions/{sid}")
    record(
        "anonymous_source_access",
        status=status,
        source_visible=isinstance(body, dict) and "code" in body,
    )
with SessionLocal() as db:
    p = db.query(Problem).filter_by(id="SUM001").one()
    record(
        "submission_counters",
        accepted=p.accepted_submissions,
        total=p.total_submissions,
        actual_rows=db.query(Submission).filter_by(problem_id=p.id).count(),
    )
    failed = (
        db.query(Submission).filter_by(problem_id=p.id, verdict="WRONG_ANSWER").first()
    )
    if failed:
        record(
            "failed_testcase_lookup",
            has_stored_key=bool(failed.incorrect_testcase_key),
            returned_testcase=failed.incorrect_testcase,
        )
record("negative_problem_limits", response=problem("NEG001", limit=-1, memory=-1))
record("empty_test_fixture_creation", response=problem("EMPTY1"))
with SessionLocal() as db:
    db.query(TestCase).filter_by(problem_id="EMPTY1").delete()
    db.commit()
submit("no_testcases", 'print("definitely wrong")', pid="EMPTY1", expected="SKP")
# Fault injection proves DB commit precedes durable queue handoff.
from api.app.routes import submissions
from api.app.schemas.submissions import SubmissionCreate

with SessionLocal() as db:
    user = db.query(User).filter_by(username="auditstudent").one()
    before = db.query(Submission).count()
    try:
        with patch.object(
            submissions,
            "enqueue_job",
            side_effect=ConnectionError("simulated queue outage"),
        ):
            submissions.create_submission(
                SubmissionCreate(problem_id="SUM001", code="print(3)", language="PY"),
                current_user=user,
                db=db,
            )
    except ConnectionError:
        pass
    record(
        "queue_outage_persistence",
        rows_before=before,
        rows_after=db.query(Submission).count(),
        last_verdict=db.query(Submission)
        .order_by(Submission.id.desc())
        .first()
        .verdict.value,
    )
# Deleted accounts retain refresh-token capability.
other = login("auditother")
request("DELETE", "/users/me", token=other["access_token"])
record(
    "deleted_account_refresh",
    status=request("POST", "/auth/refresh", dict(refresh_token=other["refresh_token"]))[
        0
    ],
)
checks = {r["name"]: r for r in observations}
assert checks["restored_tag_endpoint"]["status"] == 201
assert checks["public_verified_profile"]["status"] == 200
for name in (
    "python_line_input",
    "python_read_until_eof",
    "cpp_correct",
    "c_correct",
    "wrong_answer",
    "compilation_error",
    "runtime_error",
    "time_limit",
    "runtime_units",
    "no_testcases",
):
    assert checks[name]["verdict"] == checks[name]["expected"], checks[name]
assert checks["runtime_units"]["runtime_ms"] >= 300
assert checks["anonymous_source_access"]["status"] == 401
assert checks["submission_counters"]["total"] == 9
assert checks["submission_counters"]["accepted"] == 5
assert checks["failed_testcase_lookup"]["returned_testcase"] is not None
assert checks["negative_problem_limits"]["response"][0] == 422
assert checks["deleted_account_refresh"]["status"] == 401
print("VERIFICATION_COMPLETE", flush=True)

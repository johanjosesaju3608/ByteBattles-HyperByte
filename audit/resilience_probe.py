"""Host-side tests against ONLY the named disposable audit stack."""

import io, json, time, zipfile, os
import requests, docker

BASE = os.getenv("AUDIT_API_URL", "http://127.0.0.1:18080")
client = docker.from_env()
judge = client.containers.get("bytebattles-audit-judge-1")
api_container = client.containers.get("bytebattles-audit-api-1")
assert "BYTEBATTLES_AUDIT=1" in api_container.attrs["Config"]["Env"]


def log(name, **kw):
    print(json.dumps({"name": name, **kw}), flush=True)


def login(user):
    r = requests.post(
        BASE + "/auth/login",
        data={"username": user, "password": "Testing123"},
        timeout=10,
    )
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


student = login("auditstudent")
admin = login("auditadmin")


def submit(code, pid="SUM001", language="PY"):
    r = requests.post(
        BASE + "/submissions/",
        json={"problem_id": pid, "language": language, "code": code},
        headers=student,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["id"]


def wait(sid, timeout=65):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        r = requests.get(BASE + f"/submissions/{sid}", headers=student, timeout=10)
        r.raise_for_status()
        s = r.json()
        if s["verdict"] != "PD":
            return s
        time.sleep(0.3)
    raise AssertionError(f"Submission {sid} remained pending")


# Let the earlier injected Redis-outage job finish before measuring deltas.
for prior in requests.get(BASE + "/submissions/?limit=100", headers=student).json():
    if prior["verdict"] == "PD":
        wait(prior["id"])
log("pending_outbox_recovery", status="passed")

for name, code, expected in [
    ("memory_limit", "x=bytearray(80*1024*1024);print(3)", "MLE"),
    ("output_limit", 'print("x"*1100000)', "RE"),
    ("worker_survives_resource_failures", "print(3)", "AC"),
]:
    s = wait(submit(code))
    log(name, verdict=s["verdict"], output=s["output"], runtime_ms=s["walltime_ms"])
    assert s["verdict"] == expected

# Duplicate notifications must produce one counter increment.
p = requests.get(BASE + "/problems/SUM001").json()
before = p["accepted_submissions"]
sid = submit("import time;time.sleep(.5);print(3)")
result = client.containers.get("bytebattles-audit-redis-1").exec_run(
    ["redis-cli", "LPUSH", "judge:queue"] + [str(sid)] * 8
)
assert result.exit_code == 0
assert wait(sid)["verdict"] == "AC"
time.sleep(2)
after = requests.get(BASE + "/problems/SUM001").json()["accepted_submissions"]
log("duplicate_queue_idempotency", before=before, after=after)
assert after == before + 1

# Kill one busy audit worker. Its durable lease must expire and be retried.
z = io.BytesIO()
with zipfile.ZipFile(z, "w") as a:
    a.writestr("inputs/1.txt", "1 2\n")
    a.writestr("outputs/1.txt", "3\n")
    a.writestr("inputs/2.txt", "1 2\n")
    a.writestr("outputs/2.txt", "3\n")
data = dict(
    id="CRASH1",
    title="Crash recovery",
    description="Sum",
    difficulty="EASY",
    constraints="[]",
    tags="[]",
    sample_io="{}",
    input_desc="two integers",
    output_desc="sum",
    memory_limit_mb="64",
    time_limit_sec="5",
    visibility="true",
)
r = requests.post(
    BASE + "/problems/",
    headers=admin,
    data=data,
    files={"tests_zip": ("tests.zip", z.getvalue(), "application/zip")},
    timeout=10,
)
r.raise_for_status()
sid = submit(
    'import time,os; assert not os.path.exists("/workspace/marker"); open("/workspace/marker","w").close(); time.sleep(3);print(3)',
    "CRASH1",
)
script = """import os,time,signal
from redis import Redis
from config import REDIS_HOST,REDIS_PORT,REDIS_DB,WORKER_PREFIX
r=Redis(host=REDIS_HOST,port=REDIS_PORT,db=REDIS_DB,decode_responses=True)
for _ in range(100):
 for key in r.scan_iter(WORKER_PREFIX+':*:submission'):
  if r.get(key)==%r:
   pid=r.get(key.rsplit(':',1)[0]+':pid')
   if pid:
    os.kill(int(pid),signal.SIGKILL)
    print('Killed one busy audit worker')
    raise SystemExit(0)
 time.sleep(.1)
raise SystemExit('No busy worker found')
""" % str(
    sid
)
result = judge.exec_run([".venv/bin/python", "-c", script])
assert result.exit_code == 0, result.output.decode()
start = time.monotonic()
s = wait(sid)
log(
    "worker_crash_recovery",
    verdict=s["verdict"],
    recovery_seconds=round(time.monotonic() - start, 2),
)
assert s["verdict"] == "AC"
p = requests.get(BASE + "/problems/CRASH1").json()
assert p["accepted_submissions"] == p["total_submissions"] == 1

s = wait(
    submit(
        "#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b;}",
        "CRASH1",
        "CPP",
    )
)
assert s["verdict"] == "AC"
log("multiple_testcases_and_isolated_workspaces", status="passed")

# Permission and validation controls.
r = requests.get(BASE + f"/submissions/{sid}")
assert r.status_code == 401
r = requests.post(
    BASE + "/problems/tag",
    headers=student,
    json={"name": "forbidden", "slug": "forbidden"},
)
assert r.status_code == 403
r = requests.post(
    BASE + "/submissions/",
    headers=student,
    json={"problem_id": "SUM001", "language": "PY", "code": "x" * 65537},
)
assert r.status_code == 422
r = requests.get(
    BASE + "/problems/", params={"metadata": "true", "title": "Crash", "limit": 1}
)
r.raise_for_status()
assert r.json()["total"] == 1 and not r.json()["has_more"]
log("permissions_size_limits_search", status="passed")

# Fencing rejects stale workers; finish is idempotent under duplicate completion.
script = """from datetime import timedelta
from shared import jobs
from shared.core import SessionLocal,get_storage_submission_code
from shared.models import Submission,JudgeJob,Problem,Verdict,User
from sqlalchemy import update
from types import SimpleNamespace
with SessionLocal.begin() as db:
 user=db.query(User).filter_by(username='auditstudent').one()
 key=get_storage_submission_code().upload_bytes(extension='py',data=b'print(3)')
 s=Submission(problem_id='SUM001',user_id=user.id,language='PY',code_object_key=key,verdict=Verdict.PENDING)
 db.add(s);db.flush();sid=s.id
 db.add(JudgeJob(submission_id=sid,lease_token='current',lease_until=jobs.now()+timedelta(seconds=60)))
 db.execute(update(Problem).where(Problem.id=='SUM001').values(total_submissions=Problem.total_submissions+1))
 before=db.get(Problem,'SUM001').accepted_submissions
result=SimpleNamespace(verdict=Verdict.ACCEPTED,output=None,incorrect_testcase_key=None,runtime_ms=10,memory_kb=1000)
assert jobs.claim(sid) is None
assert not jobs.finish(sid,'stale',result)
assert jobs.finish(sid,'current',result)
assert not jobs.finish(sid,'current',result)
with SessionLocal() as db: assert db.get(Problem,'SUM001').accepted_submissions==before+1
print('Lease fencing and duplicate completion passed')
"""
result = api_container.exec_run([".venv/bin/python", "-c", script])
assert result.exit_code == 0, result.output.decode()
log("lease_fencing_and_completion", status="passed")

# Force a rate-limit threshold on disposable account without flooding the API.
script = """from api.app.utils.redis_utils import get_redis_client
from shared.core import SessionLocal
from shared.models import User
from config import SUBMISSION_RATE_LIMIT
with SessionLocal() as db: uid=db.query(User).filter_by(username='auditstudent').one().id
get_redis_client().set(f'rate:submit:{uid}',SUBMISSION_RATE_LIMIT,ex=3)
"""
assert api_container.exec_run([".venv/bin/python", "-c", script]).exit_code == 0
r = requests.post(
    BASE + "/submissions/",
    headers=student,
    json={"problem_id": "SUM001", "language": "PY", "code": "print(3)"},
    timeout=10,
)
assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
log("rate_limit", status=r.status_code, retry_after=r.headers["Retry-After"])
print("RESILIENCE_COMPLETE", flush=True)

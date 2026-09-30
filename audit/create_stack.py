import json, pathlib, secrets

root = pathlib.Path(__file__).resolve().parents[1]
env = dict(
    line.split("=", 1)
    for line in (root / ".env.example").read_text().splitlines()
    if line and not line.startswith("#")
)
env.update(
    BYTEBATTLES_AUDIT="1",
    SANDBOX_POOL_ID="bytebattles-audit",
    SUBMISSION_RATE_LIMIT="1000",
    ADMIN_BOOTSTRAP_TOKEN=secrets.token_hex(32),
    SECRET_KEY=secrets.token_hex(32),
    CONTAINER_POOL_THRESHOLD="1",
    CONTAINER_WORKER_COUNT="1",
    MINIMUM_JUDGE_WORKER="1",
    MAXIMUM_JUDGE_WORKER="1",
    MAX_MEMCAP_GB="1",
    JUDGE_WORKER_TIMEOUT="20",
)
mounts = [
    f"{root / name}:/src/{name}:ro" for name in ["api", "judge", "shared", "config.py"]
]
services = {
    "postgres": {
        "image": "postgres:16",
        "environment": {
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "postgres",
            "POSTGRES_DB": "postgres",
        },
        "tmpfs": ["/var/lib/postgresql/data"],
    },
    "redis": {"image": "redis:latest"},
    "minio": {
        "image": "cgr.dev/chainguard/minio:latest",
        "user": "root",
        "command": ["server", "/data"],
        "environment": {
            "MINIO_ROOT_USER": "minioadmin",
            "MINIO_ROOT_PASSWORD": "minioadmin",
        },
        "tmpfs": ["/data"],
    },
    "api": {
        "image": "bytebattles-api:latest",
        "environment": env,
        "volumes": mounts,
        "ports": ["127.0.0.1:18080:8000"],
    },
    "judge": {
        "image": "bytebattles-judge:latest",
        "environment": env,
        "volumes": mounts + ["/var/run/docker.sock:/var/run/docker.sock"],
        "command": [
            "/bin/sh",
            "-c",
            "mkdir -p logs && exec .venv/bin/python -m judge.run",
        ],
        "stop_grace_period": "20s",
    },
}
p = pathlib.Path("/private/tmp/bytebattles-audit-compose.json")
p.write_text(json.dumps({"services": services}, indent=2))
p.chmod(0o600)
print("Isolated audit configuration created; test storage is ephemeral.")

"""Back up and upgrade the existing LOCAL Compose installation without deleting data.
Run from the repository root after building the updated API/judge images.
No credential values are printed or included in shell command strings.
"""

from pathlib import Path
from datetime import datetime
import os, secrets, subprocess, time

root = Path(__file__).resolve().parents[1]
os.chdir(root)


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


envpath = root / ".env"
lines = envpath.read_text().splitlines()
config = dict(
    line.split("=", 1)
    for line in lines
    if line and not line.startswith("#") and "=" in line
)
backup = root / ".backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
backup.mkdir(parents=True, mode=0o700)
(backup / "env.before").write_text(envpath.read_text())
(backup / "env.before").chmod(0o600)
# Stop writers before taking the backup and reconciling legacy counters.
command(["docker", "compose", "stop", "api", "judge"])
with (backup / "database.dump").open("wb") as out:
    command(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "pg_dump",
            "-U",
            config["DB_USER"],
            "-d",
            config["DB_DATABASE"],
            "-Fc",
        ],
        stdout=out,
    )
(backup / "database.dump").chmod(0o600)
changes = {"DB_PASSWD": secrets.token_hex(32), "S3_SECRET_KEY": secrets.token_hex(32)}
for key in ("SECRET_KEY", "ADMIN_BOOTSTRAP_TOKEN"):
    if len(config.get(key, "")) < 32 or config.get(key, "").startswith("CHANGE_ME"):
        changes[key] = secrets.token_hex(32)
newlines = []
for line in lines:
    key = line.split("=", 1)[0]
    newlines.append(key + "=" + changes.pop(key) if key in changes else line)
newlines.extend(key + "=" + value for key, value in changes.items())
newtext = "\n".join(newlines) + "\n"
newconfig = dict(
    line.split("=", 1)
    for line in newlines
    if line and not line.startswith("#") and "=" in line
)
newpath = root / ".env.upgrade"
newpath.write_text(newtext)
newpath.chmod(0o600)
role = config["DB_USER"].replace('"', '""')
statement = 'ALTER ROLE "' + role + "\" PASSWORD '" + newconfig["DB_PASSWD"] + "';\n"
command(
    [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        config["DB_USER"],
        "-d",
        config["DB_DATABASE"],
        "-v",
        "ON_ERROR_STOP=1",
    ],
    input=statement.encode(),
    stdout=subprocess.DEVNULL,
)
os.replace(newpath, envpath)
command(["docker", "compose", "up", "-d", "postgres", "redis", "minio"])
for attempt in range(60):
    ready=subprocess.run(['docker','compose','exec','-T','postgres','pg_isready','-U',newconfig['DB_USER'],'-d',newconfig['DB_DATABASE']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if ready.returncode==0: break
    time.sleep(1)
else: raise RuntimeError('PostgreSQL did not become ready; backup and configuration were preserved')

command(
    [
        "docker",
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "api",
        ".venv/bin/python",
        "-m",
        "scripts.reconcile_database",
    ]
)
command(["docker", "compose", "up", "-d", "api", "judge"])
print("Local upgrade complete. Private backup directory:", backup)

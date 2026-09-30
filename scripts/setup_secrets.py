"""Generate local signing/bootstrap secrets without printing their values.
Database credentials must also be changed inside an existing database; never
silently rotate only the client setting of an initialized PostgreSQL volume.
"""

from pathlib import Path
import secrets
import sys

root = Path(__file__).resolve().parents[1]
p = root / ".env"
fresh = "--fresh" in sys.argv or not p.exists()
text = p.read_text() if p.exists() else (root / ".env.example").read_text()
lines = text.splitlines()
values = dict(
    line.split("=", 1)
    for line in lines
    if line and not line.startswith("#") and "=" in line
)
keys = ["SECRET_KEY", "ADMIN_BOOTSTRAP_TOKEN"]
if fresh:
    keys += ["DB_PASSWD", "S3_SECRET_KEY"]
for key in keys:
    if (
        key not in values
        or len(values[key]) < 32
        or values[key].startswith("CHANGE_ME")
        or (fresh and key in ("DB_PASSWD", "S3_SECRET_KEY"))
    ):
        replacement = key + "=" + secrets.token_hex(32)
        indices = [i for i, line in enumerate(lines) if line.startswith(key + "=")]
        if indices:
            lines[indices[0]] = replacement
        else:
            lines.append(replacement)
p.write_text("\n".join(lines) + "\n")
p.chmod(0o600)
print("Local signing and bootstrap secrets are configured. Values were not displayed.")

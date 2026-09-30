from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from config import validate_security_config
from .body_limit import BodyLimitMiddleware
from sqlalchemy import text
from shared.core import get_storage_testcases, get_storage_submission_code
from botocore.exceptions import ClientError
from fastapi.staticfiles import StaticFiles

from shared.core import engine, Base
from shared import models
from .routes import auth, users, problems, submissions

validate_security_config()
Base.metadata.create_all(bind=engine)
for storage in (get_storage_testcases(), get_storage_submission_code()):
    try:
        storage.client.head_bucket(Bucket=storage.bucket_name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket", "NotFound"):
            raise
        storage.client.create_bucket(Bucket=storage.bucket_name)

app = FastAPI()
app.add_middleware(BodyLimitMiddleware)


@app.get("/healthz", include_in_schema=False)
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/app")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith(("/auth", "/users", "/submissions")):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(problems.router)
app.include_router(submissions.router)

# Minimal built-in frontend (problem list, login, submissions, dark-mode toggle)
static_dir = Path(__file__).resolve().parent / "static"


@app.get("/app", include_in_schema=False)
def frontend():
    return FileResponse(
        static_dir / "index.html", headers={"Cache-Control": "no-store"}
    )


app.mount("/static", StaticFiles(directory=static_dir), name="static")

from dotenv import load_dotenv
import os
from urllib.parse import quote_plus

load_dotenv()

S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_REGION = os.getenv("S3_REGION")
S3_SIGNATURE_VERSION = os.getenv("S3_SIGNATURE_VERSION")

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))
REDIS_DB = int(os.getenv("REDIS_DB"))

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_USER = os.getenv("DB_USER")
DB_PASSWD = os.getenv("DB_PASSWD")
DB_DATABASE = os.getenv("DB_DATABASE")

DB_URL = f"postgresql+psycopg2://{quote_plus(DB_USER or "")}:{quote_plus(DB_PASSWD or "")}@{DB_HOST}:{DB_PORT}/{DB_DATABASE}"

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS"))
DUMMY_PASS = os.getenv("DUMMY_PASS")

REDIS_JOB_LIST = os.getenv("REDIS_JOB_LIST")
REDIS_RESULT_CHANNEL = os.getenv("REDIS_RESULT_CHANNEL")
SHUTDOWN_KEY = os.getenv("SHUTDOWN_KEY")
WORKER_PREFIX = os.getenv("WORKER_PREFIX")

WARM_QUEUE_PREFIX = os.getenv("WARM_QUEUE_PREFIX")

CONTAINER_POOL_THRESHOLD = int(os.getenv("CONTAINER_POOL_THRESHOLD"))

CONTAINER_WORKER_COUNT = int(os.getenv("CONTAINER_WORKER_COUNT"))
MINIMUM_JUDGE_WORKER = int(os.getenv("MINIMUM_JUDGE_WORKER"))
MAXIMUM_JUDGE_WORKER = int(os.getenv("MAXIMUM_JUDGE_WORKER"))

JUDGE_WORKER_TIMEOUT = int(os.getenv("JUDGE_WORKER_TIMEOUT"))
ACQUIRE_TIMEOUT_SECONDS = int(os.getenv("ACQUIRE_TIMEOUT_SECONDS"))

MAX_MEMCAP_GB = int(os.getenv("MAX_MEMCAP_GB"))
MAX_PIDS = int(os.getenv("MAX_PIDS"))

WORKSPACE_DIR = os.getenv("WORKSPACE_DIR")

TESTCASE_BUCKET = os.getenv("TESTCASE_BUCKET")
SUBMISSION_BUCKET = os.getenv("SUBMISSION_BUCKET")
# Limits are deliberately small enough for a single-machine competition demo.
MAX_CODE_BYTES = int(os.getenv("MAX_CODE_BYTES", "65536"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "8388608"))
MAX_TESTCASE_BYTES = int(os.getenv("MAX_TESTCASE_BYTES", "1048576"))
MAX_TESTCASE_TOTAL_BYTES = int(os.getenv("MAX_TESTCASE_TOTAL_BYTES", "16777216"))
MAX_TESTCASES = int(os.getenv("MAX_TESTCASES", "100"))
MAX_TIME_LIMIT_SEC = int(os.getenv("MAX_TIME_LIMIT_SEC", "10"))
MAX_MEMORY_LIMIT_MB = min(
    int(os.getenv("MAX_MEMORY_LIMIT_MB", "512")), MAX_MEMCAP_GB * 1024
)
MAX_OUTPUT_BYTES = int(os.getenv("MAX_OUTPUT_BYTES", "1048576"))
COMPILE_TIMEOUT_SEC = int(os.getenv("COMPILE_TIMEOUT_SEC", "15"))
SUBMISSION_RATE_LIMIT = int(os.getenv("SUBMISSION_RATE_LIMIT", "10"))
SUBMISSION_RATE_WINDOW = int(os.getenv("SUBMISSION_RATE_WINDOW", "60"))
JOB_LEASE_SECONDS = int(os.getenv("JOB_LEASE_SECONDS", "30"))
MAX_JOB_ATTEMPTS = int(os.getenv("MAX_JOB_ATTEMPTS", "3"))
SANDBOX_POOL_ID = os.getenv("SANDBOX_POOL_ID", "bytebattles")
ADMIN_BOOTSTRAP_TOKEN = os.getenv("ADMIN_BOOTSTRAP_TOKEN", "")


def validate_security_config():
    if (
        not SECRET_KEY
        or len(SECRET_KEY) < 32
        or SECRET_KEY == "jwt_secret_key"
        or SECRET_KEY.startswith("CHANGE_ME")
    ):
        raise RuntimeError(
            "Set a random SECRET_KEY of at least 32 characters; run scripts/setup_secrets.py"
        )
    if ALGORITHM != "HS256":
        raise RuntimeError("This deployment supports HS256 signing only")

    if os.getenv("BYTEBATTLES_AUDIT") != "1" and (
        DB_PASSWD in ("postgres", "", None) or S3_SECRET_KEY in ("minioadmin", "", None)
    ):
        raise RuntimeError(
            "Replace example database/storage credentials before starting the application"
        )

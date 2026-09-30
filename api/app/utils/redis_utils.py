from functools import cache
from fastapi import HTTPException
from redis import Redis, RedisError
from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_JOB_LIST


@cache
def get_redis_client():
    return Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def enqueue_job(submission_id):
    get_redis_client().lpush(REDIS_JOB_LIST, submission_id)


def rate_limit(key, limit, window):
    script = """
    local n=redis.call('INCR',KEYS[1])
    if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end
    return {n,redis.call('TTL',KEYS[1])}
    """
    try:
        count, ttl = get_redis_client().eval(script, 1, "rate:" + key, window)
    except RedisError:
        raise HTTPException(
            503,
            "Submission/authentication service temporarily unavailable",
            headers={"Retry-After": "5"},
        )
    if count > limit:
        raise HTTPException(
            429,
            "Too many requests. Please try again later.",
            headers={"Retry-After": str(max(ttl, 1))},
        )

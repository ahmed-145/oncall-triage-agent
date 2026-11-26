import json
import os
import time
from contextlib import asynccontextmanager
from urllib.request import urlopen

import psycopg
import redis
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from psycopg_pool import ConnectionPool, PoolTimeout
from redis.backoff import NoBackoff
from redis.retry import Retry

MODE = os.getenv("SHOP_FAULT", "")
if MODE == "crash-loop":
    print(json.dumps({"event": "bad_configuration"}), flush=True)
    raise SystemExit(78)

POOL = ConnectionPool(os.getenv("DATABASE_URL", "postgresql://shop:shop@postgres/shop"),
                      min_size=0, max_size=3, timeout=0.4, open=False)
CACHE = redis.Redis(host="redis", socket_timeout=0.4, socket_connect_timeout=0.4,
                    retry=Retry(NoBackoff(), 0))
REQUESTS = Counter("shop_requests_total", "Shop requests", ["status"])
DURATION = Histogram("shop_request_duration_seconds", "Shop request latency")
EVENTS = Counter("shop_fault_events_total", "Shop diagnostic events", ["signal"])
for signal in ("release_errors", "slow_queries", "pool_full", "redis_errors", "upstream_timeouts"):
    EVENTS.labels(signal)


@asynccontextmanager
async def lifespan(_: FastAPI):
    POOL.open()
    held = []
    try:
        if MODE == "db-leak":
            held = [POOL.getconn(timeout=3) for _ in range(3)]
        yield
    finally:
        for conn in held:
            POOL.putconn(conn)
        POOL.close()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def telemetry(request: Request, call_next):
    started = time.monotonic()
    response = await call_next(request)
    if request.url.path == "/orders":
        DURATION.observe(time.monotonic() - started)
        REQUESTS.labels(str(response.status_code)).inc()
        print(json.dumps({"event": "request", "route": "/orders",
                          "status": response.status_code,
                          "duration_ms": round((time.monotonic() - started) * 1000)}), flush=True)
    return response


def fail(signal: str, status: int) -> None:
    EVENTS.labels(signal).inc()
    print(json.dumps({"event": signal}), flush=True)
    raise HTTPException(status, signal)


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/orders")
def order() -> dict:
    if MODE == "bad-deploy":
        fail("release_errors", 500)
    if MODE == "oom":
        # Allocate and touch memory in the demo container until its cgroup limit is reached.
        blocks = []
        while True:
            blocks.append(bytearray(b"x" * (8 * 1024 * 1024)))
    if MODE == "cpu-throttle":
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            sum(range(20000))
    if MODE == "dependency-timeout":
        try:
            with urlopen("http://worker:8000/demo-delay", timeout=0.5):
                pass
        except OSError:
            fail("upstream_timeouts", 504)
    try:
        with POOL.connection() as conn:
            if MODE == "slow-query":
                conn.execute("SELECT pg_sleep(0.6)")
                EVENTS.labels("slow_queries").inc()
            conn.execute("SELECT 1")
    except PoolTimeout:
        fail("pool_full", 503)
    except psycopg.Error:
        raise HTTPException(503, "database unavailable") from None
    try:
        CACHE.rpush("orders", "demo-order")
    except redis.RedisError:
        fail("redis_errors", 503)
    return {"status": "queued"}

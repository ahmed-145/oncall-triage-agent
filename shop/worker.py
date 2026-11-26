import json
import time
from threading import Thread
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, make_server

from prometheus_client import Counter, make_wsgi_app
from redis import Redis, RedisError

PROCESSED = Counter("worker_orders_processed_total", "Orders processed")
FAILURES = Counter("worker_queue_failures_total", "Redis read failures")
METRICS = make_wsgi_app()


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


def http_app(env: dict, start_response: Any) -> Any:
    if env["PATH_INFO"] == "/healthz":
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"status":"ok"}']
    if env["PATH_INFO"] == "/demo-delay":
        time.sleep(1)
        start_response("204 No Content", [])
        return []
    return METRICS(env, start_response)


def main() -> None:
    cache = Redis(host="redis", socket_connect_timeout=1, socket_timeout=3)
    server = make_server("0.0.0.0", 8000, http_app, handler_class=QuietHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    while True:
        try:
            event = cache.blpop(["orders"], timeout=2)
            if event:
                PROCESSED.inc()
                print(json.dumps({"event": "order_processed"}), flush=True)
        except RedisError:
            FAILURES.inc()
            print(json.dumps({"event": "redis_unavailable"}), flush=True)
            time.sleep(2)


if __name__ == "__main__":
    main()

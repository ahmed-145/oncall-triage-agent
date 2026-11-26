import json
import time

from redis import Redis, RedisError

cache = Redis(host="redis", socket_connect_timeout=1, socket_timeout=3)
while True:
    try:
        event = cache.blpop("orders", timeout=2)
        if event:
            print(json.dumps({"event": "order_processed"}), flush=True)
    except RedisError:
        print(json.dumps({"event": "redis_unavailable"}), flush=True)
        time.sleep(2)

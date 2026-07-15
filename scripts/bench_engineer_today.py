"""Benchmark /api/engineer/today cold vs cached (in-process)."""
from __future__ import annotations

import time

from bot import api, espn_api


def main() -> None:
    api._load_state()
    espn_api.clear_cache()
    api._engineer_today_cache.clear()
    api.app.testing = True
    client = api.app.test_client()

    t0 = time.time()
    resp = client.get("/api/engineer/today?limit=15")
    cold = time.time() - t0

    espn_api.clear_cache()
    api._engineer_today_cache.clear()
    t0 = time.time()
    resp_cold2 = client.get("/api/engineer/today?limit=15")
    cold_espn = time.time() - t0

    t0 = time.time()
    resp2 = client.get("/api/engineer/today?limit=15")
    cached = time.time() - t0

    data = resp.get_json() or {}
    print(f"cold_espn_warm={cold:.2f}s status={resp.status_code} count={data.get('count')}")
    print(f"true_cold_espn={cold_espn:.2f}s status={resp_cold2.status_code}")
    print(f"cached={cached:.2f}s")


if __name__ == "__main__":
    main()

"""Quick timing script for slow Phase 12 endpoints."""
from __future__ import annotations

import time

from bot import api, espn_api, match_intelligence


def main() -> None:
    t0 = time.time()
    api._load_state()
    print(f"load_state: {time.time() - t0:.2f}s, players={len(api._MEM.get('players', {}))}")

    t0 = time.time()
    fixtures = espn_api.fetch_upcoming(days_ahead=1)
    print(f"espn fetch_upcoming: {time.time() - t0:.2f}s, fixtures={len(fixtures)}")

    singles = [
        f for f in fixtures
        if not f.get("is_doubles") and f.get("player1") and f.get("player2")
    ]
    print(f"singles: {len(singles)}")

    if singles:
        f = singles[0]
        n1 = api._resolve(f.get("player1", "")) or f.get("player1", "")
        n2 = api._resolve(f.get("player2", "")) or f.get("player2", "")
        t0 = time.time()
        match_intelligence.compute_tis(n1, n2, surface=f.get("surface"), mem=api._MEM)
        print(f"single compute_tis: {time.time() - t0:.2f}s ({n1} vs {n2})")

    t0 = time.time()
    count = 0
    for f in singles:
        n1 = api._resolve(f.get("player1", "")) or f.get("player1", "")
        n2 = api._resolve(f.get("player2", "")) or f.get("player2", "")
        try:
            match_intelligence.compute_tis(n1, n2, surface=f.get("surface"), mem=api._MEM)
            count += 1
        except Exception as exc:
            print(f"  err: {exc}")
    print(f"all {count} compute_tis: {time.time() - t0:.2f}s")

    api.app.testing = True
    client = api.app.test_client()

    # Warm caches
    client.get("/api/match/intelligence?p1=Jannik+Sinner&p2=Carlos+Alcaraz&surface=hard")
    client.get("/api/engineer/today?limit=15")

    t0 = time.time()
    resp = client.get("/api/match/intelligence?p1=Jannik+Sinner&p2=Carlos+Alcaraz&surface=hard")
    intel_ms = time.time() - t0
    print(f"/api/match/intelligence (cached): {intel_ms:.2f}s status={resp.status_code}")

    t0 = time.time()
    resp = client.get("/api/engineer/today?limit=15")
    eng_ms = time.time() - t0
    print(f"/api/engineer/today (cached): {eng_ms:.2f}s status={resp.status_code}")

    # Clear caches for cold timing
    api._tis_response_cache.clear()
    api._engineer_today_cache.clear()

    t0 = time.time()
    resp = client.get("/api/match/intelligence?p1=Jannik+Sinner&p2=Carlos+Alcaraz&surface=hard")
    print(f"/api/match/intelligence (cold): {time.time() - t0:.2f}s status={resp.status_code}")

    t0 = time.time()
    resp = client.get("/api/engineer/today?limit=15")
    print(f"/api/engineer/today (cold): {time.time() - t0:.2f}s status={resp.status_code}")


if __name__ == "__main__":
    main()

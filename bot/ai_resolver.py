"""AI Resolver — intelligent player resolution with hybrid sources.

Resolution pipeline (ordered by cost/reliability):
  1. Local DB exact match
  2. namematch fuzzy (last name + initial)
  3. ATP/WTA rankings page scrape
  4. Wikipedia infobox parse
  5. Peer inference (same league/surface/ranking zone)
  6. Store result + confidence in resolver_cache table

Every resolved entry is cached in SQLite with a TTL (default 7 days).
Unknown players get a synthetic profile from peer inference so the
predictor never returns None.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .config import DB_FILE
from .log import log
from . import namematch

# ---------------------------------------------------------------------------
# Cache table DDL (added to existing DB on first use)
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS resolver_cache (
    raw_name    TEXT PRIMARY KEY,
    resolved    TEXT,
    confidence  REAL,
    source      TEXT,
    profile     TEXT,      -- JSON: {elo, serve, return1, return2, recent, n, tour}
    expires_at  REAL
);
"""

CACHE_TTL   = 7 * 86400   # 7 days
MIN_CONF    = 0.30         # below this → treated as unknown
PEER_N_MIN  = 5            # min peers to build inference profile

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    c.execute(_DDL)
    c.commit()
    return c


def _cache_get(raw: str) -> Optional[sqlite3.Row]:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM resolver_cache WHERE raw_name=? AND expires_at>?",
            (raw, time.time())
        ).fetchone()
    return row


def _cache_set(raw: str, resolved: Optional[str], confidence: float,
               source: str, profile: Optional[Dict]) -> None:
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO resolver_cache
               (raw_name, resolved, confidence, source, profile, expires_at)
               VALUES (?,?,?,?,?,?)""",
            (raw, resolved, confidence, source,
             json.dumps(profile) if profile else None,
             time.time() + CACHE_TTL)
        )
        c.commit()


# ---------------------------------------------------------------------------
# Source 1 — local DB + namematch
# ---------------------------------------------------------------------------

def _resolve_local(raw: str, mem: Dict) -> Tuple[Optional[str], float]:
    players = mem.get("players") or {}
    if raw in players:
        return raw, 1.0
    counts = {n: int(p.get("n", 0)) for n, p in players.items()}
    idx    = namematch.build_index(list(players.keys()), counts)
    hit    = namematch.resolve(raw, idx)
    if hit:
        conf = 0.90 if namematch.split_name(raw)[0] else 0.75
        return hit, conf
    return None, 0.0


# ---------------------------------------------------------------------------
# Source 2 — ATP/WTA rankings scrape
# ---------------------------------------------------------------------------

_ATP_URL = "https://www.atptour.com/en/rankings/singles"
_WTA_URL = "https://www.wtatennis.com/rankings/singles"

def _scrape_ranking_page(url: str, last_name: str) -> Optional[str]:
    """Very light scrape — looks for 'Last Name' pattern in ranking HTML."""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        # Simple regex: find full names containing the last name
        pattern = re.compile(
            rf'\b([A-Z][a-zéèêëàâùûîïôç\-]+ (?:[A-Z][a-z\-]+ )*{re.escape(last_name)})\b'
        )
        matches = pattern.findall(r.text)
        if matches:
            return matches[0].strip()
    except Exception:
        pass
    return None


def _resolve_ranking(raw: str) -> Tuple[Optional[str], float]:
    first, last = namematch.split_name(raw)
    if not last or len(last) < 3:
        return None, 0.0
    # Try ATP first, then WTA
    for url in (_ATP_URL, _WTA_URL):
        found = _scrape_ranking_page(url, last)
        if not found:
            continue
        # Guard faux positifs : le regex prend le 1er nom contenant le nom de
        # famille n'importe où dans le HTML. Si on connaît l'initiale du prénom,
        # elle doit matcher ; sinon conf 0.55 (< 0.60 = seuil "reliable" pour
        # le calcul d'EV réel).
        if first:
            if found.split()[0][:1].lower() != first[:1].lower():
                continue
            return found, 0.72
        return found, 0.55
    return None, 0.0


# ---------------------------------------------------------------------------
# Source 3 — Wikipedia infobox
# ---------------------------------------------------------------------------

_WIKI_API = "https://en.wikipedia.org/w/api.php"

def _resolve_wikipedia(raw: str) -> Tuple[Optional[str], float, Optional[Dict]]:
    """Search Wikipedia for the player, parse infobox for basic stats."""
    try:
        # Search
        r = requests.get(_WIKI_API, params={
            "action": "query", "list": "search",
            "srsearch": f"{raw} tennis player",
            "srlimit": 3, "format": "json"
        }, headers=_HEADERS, timeout=10)
        hits = r.json().get("query", {}).get("search", [])
        if not hits:
            return None, 0.0, None

        title = hits[0]["title"]

        # Fetch infobox via parse
        r2 = requests.get(_WIKI_API, params={
            "action": "parse", "page": title,
            "prop": "wikitext", "format": "json"
        }, headers=_HEADERS, timeout=10)
        wikitext = r2.json().get("parse", {}).get("wikitext", {}).get("*", "")

        if "tennis" not in wikitext.lower() and "atp" not in wikitext.lower() \
                and "wta" not in wikitext.lower():
            return None, 0.0, None

        # Extract nationality + birth year for confidence boost
        profile: Dict[str, Any] = {"source": "wikipedia", "wiki_title": title}
        nat_m = re.search(r'\|\s*country\s*=\s*([A-Z]{2,3})', wikitext)
        if nat_m:
            profile["nationality"] = nat_m.group(1)
        tour_m = re.search(r'\|\s*tour\s*=\s*(ATP|WTA)', wikitext, re.I)
        if tour_m:
            profile["tour"] = tour_m.group(1).lower()

        # Clean up full name from title
        full = re.sub(r'\(.*?\)', '', title).strip()
        conf = 0.80 if tour_m else 0.60
        return full, conf, profile

    except Exception:
        return None, 0.0, None


# ---------------------------------------------------------------------------
# Source 4 — Peer inference
# ---------------------------------------------------------------------------

def _peer_profile(mem: Dict, league: str, surface: Optional[str] = None,
                  tour: Optional[str] = None) -> Optional[Dict]:
    """Build a synthetic profile from players in the same league/surface zone."""
    players = mem.get("players") or {}
    if not players:
        return None

    # Determine tour from league name
    inferred_tour = tour
    if not inferred_tour:
        league_lower = (league or "").lower()
        if "women" in league_lower or "wta" in league_lower:
            inferred_tour = "wta"
        elif "men" in league_lower or "atp" in league_lower or "itf men" in league_lower:
            inferred_tour = "atp"

    # Filter by tour + min matches
    peers = [
        p for p in players.values()
        if p.get("n", 0) >= PEER_N_MIN
        and (not inferred_tour or p.get("tour", inferred_tour) == inferred_tour)
    ]

    if len(peers) < PEER_N_MIN:
        peers = [p for p in players.values() if p.get("n", 0) >= PEER_N_MIN]

    if not peers:
        return None

    # Use lower-quartile profile (ITF players are below average ATP)
    vals: Dict[str, List[float]] = {k: [] for k in ("serve", "return1", "return2", "recent")}
    for p in peers:
        for k in vals:
            v = p.get(k)
            if v is not None:
                vals[k].append(float(v))

    profile = {}
    for k, lst in vals.items():
        if lst:
            lst.sort()
            q25 = lst[len(lst) // 4]
            profile[k] = round(q25, 4)

    profile["n"] = PEER_N_MIN
    profile["tour"] = inferred_tour or "atp"
    profile["source"] = "peer_inference"
    profile["confidence"] = 0.35
    return profile


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

class ResolvedPlayer:
    __slots__ = ("raw", "resolved", "confidence", "source", "profile", "is_known")

    def __init__(self, raw: str, resolved: Optional[str], confidence: float,
                 source: str, profile: Optional[Dict]):
        self.raw        = raw
        self.resolved   = resolved or raw
        self.confidence = confidence
        self.source     = source
        self.profile    = profile or {}
        self.is_known   = confidence >= MIN_CONF


def resolve(raw: str, mem: Dict,
            league: str = "",
            surface: Optional[str] = None,
            tour: Optional[str] = None,
            use_web: bool = True) -> ResolvedPlayer:
    """
    Resolve a raw player name to a known entity.

    Args:
        raw:       Name as returned by odds-api.io
        mem:       TennisBoss _MEM dict (players, elo, etc.)
        league:    Match league string (used for peer inference)
        surface:   Court surface if known
        tour:      'atp' or 'wta' if known
        use_web:   Allow HTTP lookups (disable in tests)

    Returns:
        ResolvedPlayer with .resolved, .confidence, .source, .profile
    """
    raw = (raw or "").strip()
    if not raw:
        return ResolvedPlayer(raw, None, 0.0, "empty", None)

    # ── Cache hit ────────────────────────────────────────────────────────
    cached = _cache_get(raw)
    if cached:
        profile = json.loads(cached["profile"]) if cached["profile"] else None
        return ResolvedPlayer(raw, cached["resolved"], cached["confidence"],
                              cached["source"] + " (cached)", profile)

    # ── Pipeline ─────────────────────────────────────────────────────────
    resolved: Optional[str] = None
    confidence = 0.0
    source = "unknown"
    profile: Optional[Dict] = None

    # 1. Local
    r, c = _resolve_local(raw, mem)
    if r and c > confidence:
        resolved, confidence, source = r, c, "local_db"

    # 2. ATP/WTA rankings (web) — SKIP if confidence high enough (timeout guard)
    if confidence < 0.80 and use_web:
        try:
            r, c = _resolve_ranking(raw)
            if r and c > confidence:
                resolved, confidence, source = r, c, "atp_wta_ranking"
        except Exception:
            pass

    # 3. Wikipedia (web) — SKIP if confidence high enough (timeout guard)
    if confidence < 0.80 and use_web:
        try:
            r, c, p = _resolve_wikipedia(raw)
            if r and c > confidence:
                resolved, confidence, source, profile = r, c, "wikipedia", p
        except Exception:
            pass

    # 4. Peer inference (always available — provides synthetic profile)
    if confidence < MIN_CONF:
        peer = _peer_profile(mem, league, surface, tour)
        if peer:
            # Can't resolve the name, but provide a usable profile
            profile   = peer
            source    = "peer_inference"
            confidence = peer["confidence"]
            resolved  = raw  # keep raw name, flag as inferred

    log(f"AI Resolver: '{raw}' → '{resolved}' conf={confidence:.2f} src={source}", "INFO")

    # ── Cache & return ────────────────────────────────────────────────────
    _cache_set(raw, resolved, confidence, source, profile)
    return ResolvedPlayer(raw, resolved, confidence, source, profile)


def resolve_match(home: str, away: str, mem: Dict,
                  league: str = "", surface: Optional[str] = None) -> Tuple[ResolvedPlayer, ResolvedPlayer]:
    """Resolve both players of a match, inferring tour from league."""
    league_lower = (league or "").lower()
    tour = None
    if "women" in league_lower or "wta" in league_lower:
        tour = "wta"
    elif "men" in league_lower or "atp" in league_lower or "itf men" in league_lower:
        tour = "atp"

    p1 = resolve(home, mem, league=league, surface=surface, tour=tour)
    p2 = resolve(away, mem, league=league, surface=surface, tour=tour)
    return p1, p2


def cache_stats() -> Dict[str, Any]:
    """Return cache hit/miss stats for monitoring."""
    with _conn() as c:
        total   = c.execute("SELECT COUNT(*) FROM resolver_cache").fetchone()[0]
        fresh   = c.execute(
            "SELECT COUNT(*) FROM resolver_cache WHERE expires_at>?", (time.time(),)
        ).fetchone()[0]
        sources = c.execute(
            "SELECT source, COUNT(*) as n FROM resolver_cache GROUP BY source"
        ).fetchall()
    return {
        "total": total,
        "fresh": fresh,
        "expired": total - fresh,
        "by_source": {row["source"]: row["n"] for row in sources},
    }


def purge_expired() -> int:
    """Remove expired cache entries. Returns count deleted."""
    with _conn() as c:
        n = c.execute(
            "DELETE FROM resolver_cache WHERE expires_at<=?", (time.time(),)
        ).rowcount
        c.commit()
    return n

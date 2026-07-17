# Track Record

Professional performance history for every settled TennisBoss pick. Read-only aggregation over existing tables (`bet_history`, `clv_log`) — no changes to prediction or betting logic.

## Data sources

| Field | Primary source | Fallback |
|-------|----------------|----------|
| Pick ID, match, odds, result, P/L | `bet_history` | — |
| Tournament, closing odds, EV, versions | `clv_log` (join on `event_key` or player pair + date) | defaults from `bot/versions.py` |
| Surface | `bet_history.surface` | `clv_log.surface`, value_pick archive |

Settlement flow already populates `bet_history` via `db.sync_bet_history_on_settle()` after CLV or value-pick settlement.

## Configuration

Flat analytical stake (does **not** affect live betting):

```bash
TENNISBOSS_TRACK_RECORD_STAKE=1.0   # default: 1 unit per pick
```

Defined in `bot/config.py` as `TRACK_RECORD_STAKE`.

## API endpoints

All JSON, same auth as other `/api/*` routes (`X-API-Token` when `TENNISBOSS_API_TOKEN` is set).

### `GET /api/track-record`

Paginated settled picks.

| Query | Default | Description |
|-------|---------|-------------|
| `days` | 365 | Lookback window |
| `surface` | — | Filter: `hard`, `clay`, `grass` |
| `result` | — | Filter: `win`, `loss`, `void` |
| `page` | 1 | Page number |
| `limit` | 50 | Page size (max 500) |

### `GET /api/track-record/summary`

Aggregate stats: win rate, units, ROI, yield, avg odds/EV/CLV, streaks, confidence buckets.

### `GET /api/track-record/monthly`

Monthly breakdown (label = `YYYY-MM`).

### `GET /api/track-record/surfaces`

Performance grouped by surface.

## Sample response — pick list

```json
{
  "stake_unit": 1.0,
  "days": 365,
  "page": 1,
  "limit": 50,
  "total": 42,
  "pages": 1,
  "closing_odds_coverage_pct": 78.6,
  "picks": [
    {
      "id": 17,
      "pick_id": "abc123",
      "timestamp": "2026-07-10T14:22:00",
      "date": "2026-07-10",
      "match": "Player A vs Player B",
      "player1": "Player A",
      "player2": "Player B",
      "tournament": "Wimbledon",
      "tournament_level": "grand_slam",
      "surface": "grass",
      "market": "match_winner",
      "selection": "Player A",
      "odds_at_pick": 2.05,
      "closing_odds": 1.92,
      "closing_odds_available": true,
      "result": "win",
      "stake": 1.0,
      "profit_loss": 1.05,
      "clv_pct": 6.77,
      "ev_pct": 11.2,
      "confidence": 0.74,
      "predictor_version": "1.0",
      "calibration_version": "1.0"
    }
  ]
}
```

## Sample response — summary

```json
{
  "stake_unit": 1.0,
  "settled_picks": 42,
  "void_picks": 1,
  "wins": 24,
  "losses": 18,
  "win_rate": 0.571,
  "net_units": 3.85,
  "roi": 0.0917,
  "yield_pct": 9.2,
  "avg_odds": 1.94,
  "avg_ev_pct": 9.8,
  "avg_clv_pct": 2.1,
  "closing_odds_coverage_pct": 78.6,
  "longest_win_streak": 5,
  "longest_loss_streak": 3,
  "by_confidence": [ "... buckets ..." ]
}
```

## Module

Implementation: `bot/track_record.py`

- `list_picks()` — paginated enriched records
- `summary()` — aggregate statistics
- `monthly_breakdown()` / `surface_breakdown()` / `tournament_breakdown()`

## Tests

```bash
python -m pytest tests/test_track_record.py -v
```

## Known gaps

- **Closing odds coverage** depends on pre-match snapshots; older picks or value-only settlements may lack `closing_odds` (reported via `closing_odds_coverage_pct`).
- **Tournament** only present when pick was logged through CLV with repro fields; value-pick-only rows show `tournament: null`.
- **Market** is always `match_winner` today (in-play picks live in a separate table).
- **Predictor/calibration versions** on legacy rows fall back to current `bot/versions.py` constants when not stored in `clv_log`.

---

## Implementation report (2026-07-16)

| Item | Status |
|------|--------|
| Read layer `bot/track_record.py` | Done |
| Config `TRACK_RECORD_STAKE` | Done |
| API: `/api/track-record`, `/summary`, `/monthly`, `/surfaces` | Done |
| OpenAPI spec updated | Done |
| Tests `tests/test_track_record.py` | Done |
| No schema changes | Confirmed — additive read-only |

Files created: `bot/track_record.py`, `tests/test_track_record.py`, `docs/TRACK_RECORD.md`

Files modified: `bot/api.py`, `bot/openapi_spec.py`, `bot/config.py`, `MASTER_TODO.md`

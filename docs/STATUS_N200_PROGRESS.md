# STATUS — progress toward n=200 (ADR-013)

**Snapshot date:** 2026-07-18 (post CTO lane)  
**Data source:** live state/tennisboss.db on prod host (shared /mnt/c/Users/donpa/TennisBoss)  
**Prediction core:** frozen per ADR-005 — no predictor/calibration/threshold changes.

## Headline metrics

| Metric | Value | ADR-013 gate |
|--------|------:|--------------|
| Scanner-era settled picks (clv.stats() scanner) | **n=63** | **n≥200** |
| Distance to verdict sample | **137 picks** (31.5% of target) | — |
| Mean CLV (scanner, all settled) | **+17.83%** | GO needs mean CLV > 0 + significance |
| Mean CLV (7d window, scanner) | **+22.66%** (n=50) | informational |
| et_history settled (7d) | 51 (avg CLV **22.02%**) | confirmatory ROI |
| Logging completeness (24h) | **0.0%** (0/3 picks) | **≥90%** required |
| Logging completeness (all clv_log) | **1.8%** (2/110) | **≥90%** required |
| Prod /health | status=ok, players_loaded=4524 | — |

**Current CLV verdict (automated):** prometteur — positive CLV but sample too short (n=63).

## Calendar / volume

Mid-July often sits in a **natural ATP/WTA lull** (between Masters blocks, post–Grand Slam). The past 7d audit showed low pick seeding; **do not widen selection filters** — wait for tour flux (see weekly-audit calendar note).

## ADR-013 checkpoint countdown

- **Protocol:** [ADR-013](adr/ADR-013-verdict-protocol.md) — pre-committed GO / ITÉRER / NO-GO at **n≥200** scanner-era settled picks with complete logging.
- **Remaining:** 137 settled picks before the mandatory verdict run.
- **Blockers today:** logging completeness far below 90% (repro fields missing on most historical rows; recent 24h also 0%). Even strong CLV would likely land **ITÉRER** until observability catches up.
- **Operational checkpoint:** Sunday weekly-audit digest (scheduler) + manual python run.py weekly-audit.

## Production services (verified 2026-07-18)

| Check | Result |
|-------|--------|
| systemctl is-active tennisboss-bot | **active** |
| systemctl is-active tennisboss-scheduler | **active** |
| .env TENNISBOSS_AI_TOOLS | **1** |
| GET https://api.tennisboss.online/health | **200 OK** |

## Data quality (spot check)

python run.py data-quality: WTA serve non-neutral **94.34%**; rankings active **49.76%**; et_history rows **110**.

## WSL git hygiene

WSL git status may show **6 modified paths** (android UI + oddspapi_feeder). Windows Git reports a **clean** tree; git diff --ignore-cr-at-eol on WSL is **empty** → line-ending (CRLF) noise only, not uncommitted logic. **No stash required.**

## This week

**Passive:** let open picks settle; no pick-selection or model changes.

**Active:** read Sunday **weekly-audit** digest; run python run.py weekly-audit on demand; ops-only work on logging completeness (not predictor/thresholds).

## Commands reference

`ash
curl -sS https://api.tennisboss.online/health
python run.py weekly-audit
python run.py data-quality
wsl systemctl is-active tennisboss-bot tennisboss-scheduler
`

# TennisBoss — Architecture Blueprint

**Status:** Permanent architecture reference — supersedes ad-hoc structural guidance in older audit docs.
**Date:** 2026-07-16
**Author:** CTO / Chief Software Architect session (design only — no production code changed)
**Scope:** Everything *around* the frozen prediction core. `bot/predictor.py`, `bot/calibrate.py`, the market blend, `/api/value` thresholds and betting/pick-selection logic are **out of scope by decree** (see ADR-005) and are treated here as a stable, sealed component.
**Change process:** This document evolves only through new ADRs (§15). Do not edit past ADRs; supersede them.

---

## Table of contents

- [0. Executive Summary](#0-executive-summary)
- [1. Vision — TennisBoss in 3 years](#1-vision)
- [2. Core Engineering Principles](#2-core-principles)
- [3. Domain-Driven Design — Bounded Contexts](#3-bounded-contexts)
- [4. Target Folder Structure](#4-folder-structure)
- [5. Component Architecture](#5-component-architecture)
- [6. AI Architecture](#6-ai-architecture)
- [7. Data Architecture](#7-data-architecture)
- [8. API Architecture](#8-api-architecture)
- [9. Deployment Architecture](#9-deployment-architecture)
- [10. Observability](#10-observability)
- [11. Security](#11-security)
- [12. Plugin Architecture](#12-plugin-architecture)
- [13. AI Governance](#13-ai-governance)
- [14. Architecture Diagrams (ASCII)](#14-diagrams)
- [15. ADRs — Architecture Decision Records](#15-adrs)
- [16. Technical Debt Register](#16-technical-debt)
- [17. Risk Assessment](#17-risk-assessment)
- [18. 12-Month Priority Roadmap](#18-roadmap)
- [19. Work Ownership Matrix (AI agents)](#19-ownership-matrix)

---

<a name="0-executive-summary"></a>
## 0. Executive Summary

TennisBoss today is a **healthy, release-ready single-operator product**: a Python
backend (flat `bot/` package, Flask, SQLite), an Android client (Kotlin/Compose,
MVVM), an autonomous scheduler (11 jobs), a nascent AI analyst layer (`ai/chat/`),
and a single-node production deployment behind a Cloudflare tunnel. Test coverage
is strong (~585 backend, ~64 Android tests), the prediction core is deliberately
frozen pending statistical evidence (n≥200 settled picks; currently n≈97), and the
team — one human plus AI engineering agents — ships at high velocity.

The architecture problem is not that anything is broken. It is that **the current
shape will not survive three more years of this velocity**:

1. **`bot/api.py` is a 4,200-line god-module** that is simultaneously the HTTP
   layer, four background daemons (value scanner, followed-matches refresher,
   Telegram poller, settlement/CLV threads), a caching layer, and business logic.
2. **The flat `bot/` package has no enforced boundaries** — 69 modules where any
   file may import any other; the only boundary that exists (the frozen core) is
   enforced by one test file and social convention.
3. **Data responsibilities are conflated** — one SQLite file mixes operational
   state, analytics history, and experiment archives; `state/` mixes databases,
   secrets (`firebase-adminsdk.json`), and hundreds of corrupt temp files.
4. **Knowledge lives in ~25 overlapping Markdown audits** with no supersession
   rules, so every new AI-agent session re-derives (or worse, trusts stale) facts.
5. **Everything runs on one machine** with no staging environment and an
   unverified restore path.

The blueprint answers with a **modular monolith evolved by strangler-fig
migration**: bounded contexts as top-level packages, re-export shims preserving
every existing import and API route, an in-process event bus with a SQLite outbox
for decoupling, a read-only AI tool plane with a real knowledge base, and a
promotion path from one WSL box to a reproducible VPS deployment. No rewrite, no
framework change, no microservices — evolution in slices that each keep the
~585-test suite green.

**The three moves that matter most in the next 12 months:**

1. **Decompose `bot/api.py`** into Flask blueprints + extracted worker loops
   (routes unchanged, byte-identical responses) — everything else gets easier after this.
2. **Stand up the knowledge base** (`project_knowledge.db`, FTS5) and make it the
   single source of truth for decisions, superseding the audit-file sprawl —
   this is what makes AI agents compound instead of churn.
3. **Make production reproducible** — staging via docker-compose, tested restore,
   secrets hygiene — before the user base or the data volume grows.

---

<a name="1-vision"></a>
## 1. Vision — TennisBoss in 3 years

**TennisBoss in 2029 is a personal quantitative tennis-analytics platform with a
provable track record, operated mostly by AI agents under human governance.**

Concretely:

- **Evidence-first prediction platform.** The frozen predictor either earned its
  unfreeze (n≥500 settled picks, CLV-positive, calibration within tolerance) or
  was superseded through the formal experiment pipeline — never through vibes.
  Every pick ever made is reproducible from logged inputs (`clv_log` repro
  fields), and every model change is an auditable, versioned event.
- **An AI analyst you can trust.** The chat assistant is the primary interface
  for "why" questions — why this pick, why this calibration, what changed last
  month — grounded in the knowledge base and the operational DB, always citing
  sources, always labeling sparse data. It proposes; humans dispose. It never
  gained write access to the model.
- **A platform, not a script collection.** New data feeders, new betting-market
  analyzers, new notification channels, and new AI tools are added by dropping a
  module into a registry — without touching core files. The bounded contexts of
  §3 are real packages with enforced import rules, not aspirations.
- **Multi-surface delivery.** Android remains the flagship client; a lightweight
  web dashboard (read-only at first) exists for desktop analysis; Telegram
  remains the ops channel. All of them consume the same versioned API contract.
- **Boringly reliable operations.** Staging and production are the same
  docker-compose artifact on different hosts. Restore from backup is rehearsed,
  not hoped. Health, metrics, and alerts arrive before the user notices problems.
- **Small by design.** Still one human operator. Still SQLite unless measured
  contention says otherwise (ADR-002). Still a monolith unless a bounded context
  demonstrably needs independent scaling (ADR-001). Three years of growth in
  capability, not in accidental complexity.

What TennisBoss deliberately is **not** becoming: a multi-tenant SaaS, an
automated bet-execution engine (it reads odds; it never places bets), or a
research playground that mutates the production model without evidence.

---

<a name="2-core-principles"></a>
## 2. Core Engineering Principles

These principles are binding for all agents (human and AI). When a PR/change
conflicts with one, the change needs an ADR, not an exception.

| # | Principle | Meaning in practice |
|---|-----------|---------------------|
| P1 | **Evidence before optimization** | No model, threshold, or blend change without a walk-forward validation doc and sufficient n. The surface-features and clutch-blend rejections (docs/) are the template. |
| P2 | **Frozen core, evolving shell** | `predictor.py`, `calibrate.py`, market blend, value thresholds are sealed (ADR-005). All innovation happens in the layers around them. |
| P3 | **Backward compatible, additive-only** | API responses gain fields, never lose or repurpose them. DB schema changes are additive migrations. Package moves keep re-export shims until a documented removal window. |
| P4 | **Incremental evolution (strangler fig)** | No big-bang rewrites. Every structural change is a slice that ships with the full test suite green and production behavior byte-identical. The `app/` FastAPI failure (ADR-003) is the cautionary tale. |
| P5 | **Modular first** | Bounded contexts (§3) own their data access and expose narrow interfaces. Cross-context calls go through those interfaces, eventually enforced by import-linting in CI. |
| P6 | **AI-first, human-governed** | Every capability is designed to be operable and explainable by AI agents (structured outputs, machine-readable state, tool interfaces) — with write authority gated by human approval (§13). |
| P7 | **Observable by default** | Every background job, feeder, and scanner emits structured status (last run, last success, error count) queryable via API. Silent `except: pass` is banned; failures log with context. |
| P8 | **Testable seams everywhere** | Every external dependency (odds API, ESPN, LLM providers, clock) sits behind an interface that tests can fake. The Android `FakeApi.kt` + injectable dispatcher pattern is the reference standard. |
| P9 | **Event-driven where it decouples, not everywhere** | Domain events (PickSettled, OddsMoved, ModelDriftDetected) flow through an in-process bus with a durable outbox (ADR-006). Synchronous request/response stays synchronous. |
| P10 | **One source of truth per fact** | Odds come from the Odds context; predictions from the Prediction context; decisions from the knowledge base. Duplicated derivations (e.g., two surface-detection paths) are debt to be retired. |
| P11 | **Docs are data** | Decisions live in the knowledge base with supersession links; Markdown audits are generated views or ingestion sources, not competing truths. |
| P12 | **Secure by default** | Prod serves nothing unauthenticated except `/health` and `/privacy`. Secrets never live inside data directories. Admin surface is separated from client surface. |

---

<a name="3-bounded-contexts"></a>
## 3. Domain-Driven Design — Bounded Contexts

Eleven bounded contexts. Each lists its responsibility, what it owns (data +
modules today), and its published interface (what other contexts may use).

### 3.1 Context map (ASCII)

```
                        ┌──────────────────────────────┐
                        │         CLIENTS               │
                        │  Android ── Web (future)      │
                        │  Telegram ── CLI (run.py)     │
                        └──────────────┬───────────────┘
                                       │ HTTPS (versioned contract)
                        ┌──────────────▼───────────────┐
                        │        API GATEWAY            │◄──── Security
                        │  public / admin / internal    │      (authn, rate-limit,
                        └───┬──────┬───────┬───────┬───┘       audit)
                            │      │       │       │
              ┌─────────────▼┐ ┌───▼────┐ ┌▼──────────┐ ┌▼─────────────┐
              │  PREDICTION  │ │BETTING │ │ AI         │ │ ANALYTICS    │
              │  (FROZEN 🔒) │ │& VALUE │ │ ASSISTANT  │ │ & REPORTS    │
              └─────┬────────┘ └──┬─────┘ └──┬─────────┘ └──┬───────────┘
                    │  reads      │ emits    │ reads        │ reads
              ┌─────▼─────────────▼──────────▼──────────────▼───────────┐
              │                    DATA PLATFORM                         │
              │   ingestion (feeders) · storage · identity · quality     │
              └─────┬────────────────────────────────────────┬──────────┘
                    │ events (outbox)                        │
              ┌─────▼─────────┐                    ┌─────────▼──────────┐
              │ OPERATIONS    │                    │ KNOWLEDGE           │
              │ scheduler ·   │                    │ decisions · docs ·  │
              │ monitor ·     │                    │ experiment archive  │
              │ self-healing  │                    └────────────────────┘
              └───────────────┘
```

### 3.2 Prediction (FROZEN CORE) 🔒

- **Responsibility:** Compute first-set/match probabilities from player profiles;
  apply calibration; produce confidence labels and fair odds.
- **Owns today:** `bot/predictor.py`, `bot/features.py`, `bot/elo.py`,
  `bot/calibrate.py`, `bot/versions.py`, training weights in `state/memory.json`.
- **Published interface:** `predict(profiles) → probability`, calibration apply,
  version constants. Nothing else. Other contexts *read* predictions; none may
  alter parameters.
- **Change policy:** ADR-005. Human-only, evidence-gated, version-bumped.

### 3.3 Data Platform

- **Responsibility:** Ingest, normalize, deduplicate, and store all external
  tennis data; own player identity resolution; own data-quality reporting.
- **Owns today:** `bot/db.py`, `bot/datasource.py`, all `*_feeder.py` modules
  (Sackmann, tennis-data, ManTennisData, MCP, rankings), `bot/espn_api.py`,
  `bot/live_api.py`, `bot/namematch.py`, `bot/dedupe_players.py`,
  `bot/data_quality.py`, tables `players`, `matches`, `player_rankings`.
- **Published interface:** repositories (player, match, ranking lookups), the
  feeder plugin contract (§12.2), quality reports.
- **Key rule:** feeders are *plugins*; the platform never hard-codes a source.
  Source outages (the Sackmann repo disappearance, 2026-07-12) must degrade to
  warnings + fallback, never crash ingestion.

### 3.4 Odds & Market

- **Responsibility:** Fetch and cache market odds, compute no-vig probabilities,
  track line movement and closing lines, guard the provider quota.
- **Owns today:** `bot/odds_api.py`, `bot/odds_ws.py`, `bot/oddspapi_feeder.py`,
  tables `market_snapshots`, `historical_odds`.
- **Published interface:** `get_match_odds(event, ttl)`, `get_closing_line(event)`,
  no-vig conversion, quota status. TTL policy (10 min pre-match / 60 s live) is
  this context's decision, not the caller's guesswork.

### 3.5 Betting & Value (decision logic FROZEN 🔒 at thresholds)

- **Responsibility:** Detect value picks (EV vs no-vig market), log them with
  full reproducibility fields, settle results, compute CLV, maintain
  `bet_history` and the track record.
- **Owns today:** value scanner loop + `/api/value` logic (inside `bot/api.py` —
  to be extracted), `bot/clv.py`, `bot/settlement.py`, `bot/track_record.py`,
  `bot/recommendations.py`, bet-builder combinatorics, tables `value_picks`,
  `clv_log`, `bet_history`, `bet_log`, `inplay_picks`.
- **Published interface:** open picks, pick history, settlement events
  (`PickSettled` on the bus), track-record stats.
- **Frozen inside it:** EV/odds/confidence thresholds and pick-selection gates.
  The surrounding machinery (logging, settlement, reporting) evolves freely.

### 3.6 Intelligence & Signals

- **Responsibility:** Non-core enrichment signals — TIS score, weather edge,
  sentiment, clutch/surface experiments — clearly labeled as advisory.
- **Owns today:** `bot/match_intelligence.py`, `bot/intelligence_layer.py`,
  `bot/intelligence.py`, `bot/weather.py`, `bot/weather_profile.py`,
  `bot/sentiment.py`, `bot/surface_features.py` (rejected-but-kept experiments).
- **Published interface:** signal registry (§12.4) — each signal declares name,
  inputs, output range, and validation status (validated / experimental /
  rejected). UI may only render signals through this registry, which is how we
  prevent another "HONEYPOT" mislabeling incident.

### 3.7 AI Assistant

- **Responsibility:** Conversational and analytical interface — chat, read-only
  tools, retrieval from the knowledge base, suggestion reports. Detailed in §6.
- **Owns today:** `ai/chat/` (orchestrator, tool registry), `bot/chat.py` (LLM
  providers), `bot/agent_router.py` (prompts), `bot/search.py`,
  `bot/file_parser.py`.
- **Published interface:** `POST /api/chat` (modes: chat/analyst), tool registry.
- **Hard rule:** read-only against every other context (§13, ADR-007).

### 3.8 Knowledge (new context)

- **Responsibility:** Project memory — decisions, experiment outcomes, deployment
  history, model-version snapshots — stored structured and searchable
  (`project_knowledge.db`, FTS5), with supersession semantics. The antidote to
  audit-file sprawl. Detailed in §6.4 and §7.
- **Owns (future):** `ai/memory/` (or `knowledge/`), `state/project_knowledge.db`,
  ingestion pipeline over `docs/`, `reports/`, git history.
- **Published interface:** `search_knowledge`, `get_decision(topic)`,
  `get_model_snapshot(date)` — consumed by the AI Assistant and by humans.

### 3.9 Learning (suggestion-only)

- **Responsibility:** Post-settlement analysis, drift detection, pattern reports.
  Emits suggestions and reports; **never** writes model parameters (Phase 3 of
  the AI plan). The pre-freeze `auto_learner`/`job_learn` loop is grandfathered
  but must become explicitly governed (see debt item D-11).
- **Owns today:** `bot/mistake_learner.py`, `bot/calibration_report.py`,
  `bot/signal_backtest.py`, `bot/market_efficiency_audit.py`,
  `bot/decision_policy_backtest.py`, `bot/compare_engines.py`, `bot/backtest*.py`.
- **Published interface:** report artifacts (`reports/`), weekly analysis events,
  suggestion entries in the knowledge base.

### 3.10 Operations (Scheduler · Monitor · Self-healing)

- **Responsibility:** Run and supervise all background work; system health; backup.
- **Owns today:** `bot/scheduler.py` (11 jobs), `bot/monitor.py`,
  `bot/supervisor.py`, `bot/healer.py`, `bot/heartbeat.py`, `bot/backup.py`,
  `watchdog.py`, systemd units, plus — **wrongly** — the daemon threads embedded
  in `bot/api.py` (scanner, followed-matches refresh, Telegram poll), which
  belong here (§5.3, roadmap Q3).
- **Published interface:** job registry with per-job status, `/api/monitor/status`,
  backup/restore commands.

### 3.11 Notifications

- **Responsibility:** Deliver alerts and digests over any channel (push/FCM,
  Telegram, future email) from domain events — channel-agnostic.
- **Owns today:** `bot/push_notifications.py`, `bot/realtime_alerts.py`,
  `bot/digest.py`, table `device_tokens`.
- **Published interface:** `notify(event, audience, channel?)` + channel plugin
  contract (§12.5).

### 3.12 Clients (Android · Web · Telegram · CLI)

- **Responsibility:** Presentation only. All logic server-side; clients render
  the API contract.
- **Owns today:** `android/` (14 screens, MVVM), Telegram poll UX, `run.py` CLI.
- **Architecture rule for Android:** before any offline/caching feature, insert
  the Repository layer + DI seam identified in `ARCHITECTURE_REVIEW.md`
  (ADR-010). Until then, network-only is a *decision*, not neglect.

### 3.13 Infrastructure & Security (cross-cutting)

- **Responsibility:** Config, secrets, authn/authz, rate limiting, audit logging,
  deployment artifacts (Docker, systemd, Cloudflare), CI/CD.
- **Owns today:** `bot/config.py`, `.env`, `cloudflare/`, `systemd/`,
  `docker-compose.yml`, `.github/workflows/ci.yml`.
- Detailed in §9 and §11.

---

<a name="4-folder-structure"></a>
## 4. Target Folder Structure

### 4.1 Principles

- Top-level packages **are** the bounded contexts — the directory tree teaches
  the architecture.
- Migration is strangler-fig (ADR-004): a module moves only when touched for
  another reason or in a dedicated migration slice; a re-export shim stays at the
  old path (`bot/xyz.py` → `from <new>.xyz import *`) until a two-release
  deprecation window closes. `from bot import predictor` must keep working the
  entire time.
- `bot/` is **never deleted**, it just thins into a compatibility façade — and
  the frozen core may stay physically in `bot/` indefinitely (moving frozen files
  is risk without reward; the *logical* package `prediction/` can begin life as
  pure re-exports the other direction).

### 4.2 Target tree (3-year horizon)

```
TennisBoss/
├── prediction/            # 🔒 FROZEN CORE (predictor, features, elo, calibrate, versions)
├── data/                  # Data Platform
│   ├── db/                #   schema, migrations/, repositories
│   ├── feeders/           #   sackmann, tennisdata, mantennisdata, mcp, rankings, espn, live
│   ├── identity/          #   namematch, dedupe_players
│   └── quality/           #   data_quality, audits
├── odds/                  # Odds & Market (odds_api, odds_ws, novig, line movement, quota)
├── betting/               # Betting & Value (scanner, clv, settlement, track_record,
│                          #   bet_builder, recommendations) — thresholds frozen
├── intelligence/          # Signals (TIS, weather, sentiment) + signal registry
├── ai/                    # AI Assistant
│   ├── chat/              #   orchestrator, tools/, prompts/
│   ├── providers/         #   groq / gemini / ollama adapters (from bot/chat.py)
│   └── learning/          #   analyzers, weekly reports (suggestion-only)
├── knowledge/             # Knowledge context (index, ingestion, project_knowledge.db access)
├── ops/                   # Operations (scheduler, jobs/, monitor, supervisor, healer,
│                          #   heartbeat, backup) + extracted daemon loops from api.py
├── notifications/         # push, telegram, digest, channel registry
├── api/                   # API Gateway
│   ├── app.py             #   Flask app factory (slim)
│   ├── blueprints/        #   core, matches, value, performance, intelligence,
│   │                      #   chat, admin, devices
│   ├── auth.py, ratelimit.py, audit.py
│   └── openapi_spec.py    #   contract source of truth
├── platform/              # shared kernel: config, log, events (bus + outbox), clock, http
├── bot/                   # compatibility façade (re-export shims) → thins over time
├── android/               # Android client (unchanged location)
├── dashboard/             # future read-only web UI (only when roadmap reaches it)
├── run.py                 # CLI entry (thin dispatcher over contexts)
├── tests/                 # mirrors package structure over time (tests/data/, tests/api/, …)
├── scripts/               # ops one-offs (audited, dated)
├── docs/
│   ├── adr/               #   ADR-NNN-*.md (one decision per file, this doc indexes them)
│   ├── audits/            #   dated, immutable audit snapshots (moved from docs/ root)
│   └── ARCHITECTURE_BLUEPRINT.md   # ← this file
├── reports/               # generated artifacts (never hand-edited)
├── state/                 # runtime data ONLY (no secrets — see §11.3)
│   ├── tennisboss.db, project_knowledge.db, memory.json, config.json, backups/
├── secrets/               # gitignored; firebase key etc. (moved out of state/)
└── logs/
```

### 4.3 Why this shape

- **Contexts become import-lintable.** A CI rule ("`ai/` may not import
  `prediction/` internals", "`api/` may not import feeders directly") is only
  expressible once packages exist. Today's flat `bot/` makes every boundary
  invisible to tooling.
- **The frozen core gets a physical fence.** `prediction/` + an import-lint gate
  turns ADR-005 from a convention into a build failure.
- **`docs/adr/` + `docs/audits/`** ends the "which of these 25 files is true?"
  problem: audits are immutable snapshots; ADRs are the living decisions; this
  blueprint is the index.
- **`platform/`** gives the shared kernel (config/log/events/clock) a home so
  contexts don't reach into each other for cross-cutting needs.
- **What we are *not* doing:** renaming routes, moving `android/`, or moving
  frozen files in any early phase. The tree above is the destination; §18
  sequences the journey.

---

<a name="5-component-architecture"></a>
## 5. Component Architecture

For each major component: inputs, outputs, dependencies, responsibilities,
extension points.

### 5.1 API Gateway (`api/`, today `bot/api.py`)

| Aspect | Design |
|---|---|
| **Inputs** | HTTPS requests (Android, Telegram bridge, web, curl); auth headers |
| **Outputs** | JSON responses matching `openapi_spec.py`; audit log entries; request metrics |
| **Dependencies** | All context interfaces (never their internals); Security cross-cut |
| **Responsibilities** | Routing, auth, rate limiting, request validation, response shaping, caching policy per route. **Nothing else** — no daemons, no business logic |
| **Extension points** | New blueprint per context; per-route cache TTL config; middleware chain (auth → ratelimit → audit) |

**Decomposition contract (Q3 roadmap):** split into blueprints matching today's
OpenAPI tags (core, matches, value, performance, intelligence, chat, admin,
devices). Every route keeps its exact path, method, params, and response shape;
`tests/test_api_endpoints*.py` are the regression harness. The four daemon loops
move to `ops/` (§5.3). `bot/api.py` remains as a shim importing the app factory.

### 5.2 Frozen Prediction Core (`prediction/`)

| Aspect | Design |
|---|---|
| **Inputs** | Player feature vectors (from Data Platform), memory weights |
| **Outputs** | Probabilities, confidence labels, fair odds, version tags |
| **Dependencies** | `platform/config` only |
| **Responsibilities** | Deterministic prediction math; calibration application |
| **Extension points** | **None until unfrozen.** A future v2 engine arrives as a *parallel* engine behind the engine-comparison harness (`compare_engines.py`), selected by explicit version pin — never by editing v1 |

### 5.3 Background Workers (`ops/jobs/`, today `bot/scheduler.py` + threads in `api.py`)

| Aspect | Design |
|---|---|
| **Inputs** | Schedule triggers; domain events (outbox); config |
| **Outputs** | DB writes via context interfaces; job-status records; events; alerts |
| **Dependencies** | Context interfaces; event bus; monitor |
| **Responsibilities** | All periodic and continuous work: 11 scheduled jobs **plus** the value-scanner loop, followed-matches refresher, Telegram poller, settlement/CLV threads (extracted from the API process) |
| **Extension points** | Job registry (§12.3): a job = module with `name`, `schedule`, `run()`, `health()`. Adding a job touches zero core files |

**Why extraction matters:** today a Flask worker crash can take the value scanner
down with it (and vice versa); API restarts silently reset scanner state; and the
API process cannot be scaled or moved independently of the daemons. One process
per role (api / worker) — docker-compose already models this split correctly.

### 5.4 Data Feeders (`data/feeders/`)

| Aspect | Design |
|---|---|
| **Inputs** | External HTTP sources (Sackmann mirrors, tennis-data.co.uk, ManTennisData, MCP, ESPN, API-Tennis, odds-api.io) |
| **Outputs** | Normalized rows via repositories; ingest reports; `DataIngested` events; quality warnings |
| **Dependencies** | `platform/http` (retries, UA, timeouts), repositories, identity resolution |
| **Responsibilities** | Fetch → normalize → dedupe (via `namematch`) → upsert → report. Tolerate source death (Sackmann incident) via env-overridable URLs and mirror fallbacks |
| **Extension points** | Feeder plugin contract (§12.2). New source = new module + registry entry |

### 5.5 Value Scanner & Settlement (`betting/`)

| Aspect | Design |
|---|---|
| **Inputs** | Upcoming fixtures, model probabilities (Prediction), market odds (Odds), frozen thresholds |
| **Outputs** | `value_picks`, `clv_log` rows (17 repro columns per `LOGGING_SCHEMA.md`), `PickOpened`/`PickSettled` events, track-record updates |
| **Dependencies** | Prediction (read), Odds (read), Data Platform (read/write own tables) |
| **Responsibilities** | Pick detection (frozen gates), full-fidelity logging, settlement, CLV computation, bet-history sync |
| **Extension points** | New *markets* (bet-builder style) compose existing probabilities — allowed. New *decision gates* — frozen, ADR-005 |

### 5.6 Android App (`android/`)

| Aspect | Design |
|---|---|
| **Inputs** | API contract; push notifications (FCM) |
| **Outputs** | UI; device registration |
| **Dependencies** | Retrofit/OkHttp/Gson; `TokenManager` |
| **Responsibilities** | Presentation, error/loading states (sealed UiState), light client-side sorting |
| **Extension points** | The **Repository + DI seam** is the designated pre-requisite for offline/Room, chat persistence, or any cross-screen state (ADR-010). NavHost adoption is backlog, justified only when deep links are needed |

### 5.7 CLI (`run.py`)

Thin dispatcher over context interfaces; every command a context offers must be
reachable here (the missing `compare-engines` registration is debt item D-9).
Long-term: subcommands auto-registered from a per-context `cli.py` so `run.py`
stops growing.

### 5.8 Event Bus (`platform/events`) — new

| Aspect | Design |
|---|---|
| **Inputs** | `publish(event_type, payload)` from any context |
| **Outputs** | Synchronous in-process dispatch to subscribers + durable row in `events_outbox` (SQLite) |
| **Responsibilities** | Decouple producers (settlement, odds moves, monitor) from consumers (notifications, learning, knowledge ingestion); give workers a replayable log |
| **Extension points** | Subscribers register per event type; outbox consumers mark processed. Starts as ~100 lines of stdlib; the *contract* (event names + schemas, versioned) is the investment, the transport can be swapped later (ADR-006) |

Initial event catalog: `PickOpened`, `PickSettled`, `OddsMoved`, `DataIngested`,
`ModelDriftDetected`, `JobFailed`, `BackupCompleted`, `DecisionRecorded`.

---

<a name="6-ai-architecture"></a>
## 6. AI Architecture

Builds directly on `docs/AI_ASSISTANT_ARCHITECTURE.md` (the 5-phase plan, Phase 1
delivered 2026-07-16) — this section is the *permanent* architecture those phases
converge to.

### 6.1 Module map & communication

```
            ┌────────────────────────── clients ──────────────────────────┐
            │ Android ChatScreen · Telegram · CLI (run.py ai) · Web (fut.) │
            └───────────────────────────────┬──────────────────────────────┘
                                            │ POST /api/chat {message, mode, history}
                                    ┌───────▼────────┐
                                    │  Chat Gateway   │ (api/blueprints/chat)
                                    └───────┬────────┘
                                            │
                                    ┌───────▼────────┐
                                    │  Orchestrator   │ ai/chat/orchestrator.py
                                    │  intent → plan  │
                                    └─┬─────┬─────┬──┘
                          ┌───────────┘     │     └──────────────┐
                  ┌───────▼──────┐  ┌───────▼───────┐  ┌─────────▼────────┐
                  │ ContextBuilder│  │ Tool Registry │  │  Prompt Bank      │
                  │ (players, H2H)│  │ (read-only)   │  │ (versioned files) │
                  └───────┬──────┘  └───────┬───────┘  └─────────┬────────┘
                          │                 │                     │
                          │        ┌────────▼─────────┐           │
                          │        │ Data sources      │           │
                          │        │ tennisboss.db ·   │           │
                          │        │ knowledge db ·    │           │
                          │        │ docs/ · reports/ ·│           │
                          │        │ openapi spec      │           │
                          │        └────────┬─────────┘           │
                          └─────────────────┼─────────────────────┘
                                            │ assembled context
                                    ┌───────▼────────┐
                                    │ Provider Chain  │ ai/providers/
                                    │ Groq→Gemini→    │ (fallback, budgets,
                                    │ Ollama          │  per-mode params)
                                    └───────┬────────┘
                                            │
                              {reply, tools_called[], sources[],
                               context_used, mode, agent}
```

### 6.2 AI Chat & orchestration

- **Orchestrator** owns the loop: classify intent → select tools → execute →
  assemble context → call provider → shape response. Today's regex
  classification is the v1; v2 upgrades to **LLM function-calling** behind the
  same `ToolRegistry` interface so tools don't change when the dispatcher does.
- **Modes** are first-class: `chat` (brief, mobile) and `analyst` (512 tokens,
  T=0.3, cite sources). Future modes (e.g. `ops` for incident Q&A) are config
  entries, not code forks.
- **Provider chain** (Groq → Gemini → Ollama) moves from `bot/chat.py` into
  `ai/providers/` with a uniform interface (`complete(messages, params) → text`),
  per-provider timeout/budget, and health status surfaced in `/api/monitor/status`.

### 6.3 Memory — three kinds, never conflated

| Memory | Store | Owner | Writers |
|---|---|---|---|
| **Training memory** (weights, player EMA, ELO) | `state/memory.json` | Prediction 🔒 | learner pipeline only — assistant blocked |
| **Project memory** (decisions, experiments, deploys, versions) | `state/project_knowledge.db` | Knowledge | ingestion pipeline + explicit human/agent `knowledge-add` |
| **Conversation memory** (chat history) | client-side today; optional server `chat_sessions` table later | AI Assistant | chat gateway |

This three-way split is the load-bearing wall of the AI design: the audits'
recurring confusion ("memory.json = project memory?") is resolved by naming and
by physically separate stores.

### 6.4 RAG & Knowledge base

- **Store:** `project_knowledge.db` — `knowledge_entries` (typed: architecture /
  decision / experiment / deployment / audit), FTS5 index, `superseded_by`
  chains, `source_hash` for staleness detection; plus `deployment_history` and
  `model_snapshots` tables (schema already specified in
  `AI_ASSISTANT_ARCHITECTURE.md` §4.3 — adopted as-is).
- **Ingestion:** bootstrap walk of `docs/`, `reports/`, root `*.md`; nightly
  model-version snapshot; git-hook re-index of changed Markdown; manual
  `run.py knowledge-add` for decisions made in conversation.
- **Retrieval ladder (ADR-008):** FTS5 keyword search first — sufficient for
  <100 docs. Embeddings are added *only* when a measured recall eval (<80% on a
  golden-question set) demands it, as a second index, not a replacement.
- **Supersession is the killer feature:** `get_decision("surface features")`
  returns the latest non-superseded entry — ending stale-audit archaeology.

### 6.5 Self-learning (suggestion-only)

**MVP shipped 2026-07-23** (`ai/learning/analyzer.py`) — a thin orchestrator
over already-existing, already-tested analysis modules (`bot/calibration_report.py`,
`bot/track_record.py::surface_breakdown/tournament_breakdown`,
`bot/market_efficiency_audit.py::market_disagreement_analysis`), not a
reimplementation. Consumes settled `bet_history`/`clv_log` rows → findings by
calibration bin, surface, tournament, market disagreement, each tagged `ok` /
`insuffisant` (n below `MIN_N_SUGGESTION=15` — observation noted, no
conclusion drawn) / `à investiguer` (suggestion, never a directive) → writes
`reports/learning/YYYY-MM-DD.md` + JSON. Wired to `run.py learning-report`,
a weekly scheduler job (Sun 22:30, idempotent per ISO week), and a new
read-only chat tool (`get_learning_report`) so the question "quelles
suggestions cette semaine ?" works from the app, `/api/chat`, or Telegram.
**Not yet done:** knowledge-base ingestion (blocked on Phase 2, not built).
- **Never writes:** model params, thresholds, `memory.json` — verified by a
  guard test (source-text scan for `predictor`/`calibrate`/`learner` imports,
  same convention as `tests/test_ai_tools.py`). Suggestions carry `n` and a
  fixed footer citing ADR-005 ("no change applied, human approval required").
- The pre-freeze `auto_learner` hourly job is an anomaly under this architecture:
  it must be either (a) formally exempted by ADR with its write-surface
  documented, or (b) demoted to suggestion-only. Tracked as debt D-11 —
  decision belongs to the human owner.

### 6.6 Prompt management

- Prompts live as **versioned files** (`ai/chat/prompts/*.md`), not string
  literals: base system prompt, honesty/no-fabrication addendum, analyst
  addendum, per-agent addenda (`@stats_agent` etc.).
- Every response logs `prompt_version` alongside `tools_called` — prompt changes
  become diffable, revertable, and attributable, like model versions.

### 6.7 Tool calling

- Single **ToolRegistry** (exists: `ai/chat/tools/registry.py`) — each tool:
  `name`, `description`, `params schema`, `read_only=True`, `run() → ToolResult
  {data, summary, source}`.
- Roadmap tools beyond the shipped six: `search_knowledge`, `get_decision`,
  `query_clv_log`, `get_project_status`, `run_report_read`, `get_model_snapshot`.
- **Blocked forever** (ADR-007): `train_model`, `settle_match`, `place_bet`,
  `modify_memory`, `bump_version`, `run_learn`. Enforced three ways: not in the
  registry; write endpoints excluded; CI guard test asserting `ai/` never imports
  `predictor`/`calibrate`/`learner` (exists — `tests/test_ai_tools.py`).

### 6.8 Conversation history

- Phase now: client-held history array passed per request (stateless server) —
  correct for privacy and simplicity.
- When persistence is wanted: server-side `chat_sessions`/`chat_messages` tables
  keyed by device, retention-capped (e.g. 90 days), exposed via
  `GET /api/chat/history` — *after* the Android Repository seam exists, so the
  client caches through one layer, not 14 call sites.

---

<a name="7-data-architecture"></a>
## 7. Data Architecture

### 7.1 Stores and their single responsibilities

| Store | Content | Owner context | Lifecycle |
|---|---|---|---|
| `state/tennisboss.db` (SQLite WAL) | Operational: players, matches, picks, clv_log, bet_history, rankings, snapshots, device tokens (20 tables) | Data Platform (schema), each context its tables | Continuous; backed up 6h |
| `state/project_knowledge.db` (new) | Decisions, experiments, deployments, model snapshots, FTS index | Knowledge | Append-mostly; supersession not deletion |
| `state/memory.json` | 🔒 Training weights + player profiles | Prediction | Written by learner only; hash-fingerprinted into `model_snapshots` |
| `state/config.json` | Runtime tuning | Operations | Bootstrap-created; env overrides win |
| `reports/` | Generated analysis artifacts | Learning/Analytics | Regenerable; never hand-edited |
| `logs/tennisboss.log` | Application log | Operations | Rotated (see §10) |
| `state/backups/` | DB snapshots | Operations | 6h cadence + boot; restore rehearsed quarterly |

### 7.2 Rules

- **One writer role per table.** E.g. only settlement writes `clv_log.result`;
  only feeders write `matches`. Documented in a table-ownership map inside
  `data/db/` when migrations land.
- **Migrations become explicit.** Today: `CREATE TABLE IF NOT EXISTS` + scattered
  `ALTER`. Target: numbered migration files under `data/db/migrations/` applied
  by a tiny runner recording `schema_migrations` — additive-only (P3), each
  reversible or explicitly marked irreversible.
- **Versioning of model artifacts.** `PREDICTOR_VERSION` / `FEATURE_SET_VERSION`
  / `CALIBRATION_VERSION` stamped on every pick (already done via repro columns)
  + nightly `model_snapshots` row = point-in-time reconstruction of "what was
  live when this pick was made."
- **Experiment storage.** Every experiment produces: a `reports/` artifact, a
  knowledge-base entry (accepted/rejected + why), and — if it touched picks — a
  tagged subset in `clv_log`. Rejected experiments (surface, clutch) stay in the
  repo as inert modules with their rejection recorded; they are documentation.
- **Retention & archive.** `matches` (~94k rows) and settled `clv_log` grow
  forever by design (they are the moat). At SQLite pain thresholds (>2 GB file or
  >100 ms p95 on hot queries — measure, don't guess), archive cold partitions to
  attached yearly DB files before considering Postgres (ADR-002 revisit trigger).
- **State hygiene.** `state/` gains a janitor job: corrupt `tmp*.json.corrupt`
  files (hundreds today — atomic-write leftovers) are pruned after 7 days with a
  count in monitor status; secrets move out (§11.3).

### 7.3 Data lifecycle (ASCII)

```
 External sources          INGEST                 OPERATE                    LEARN/REPORT
┌───────────────┐   ┌──────────────────┐   ┌────────────────────┐   ┌──────────────────────┐
│ Sackmann mirr.│──▶│ feeders normalize │──▶│ players/matches     │──▶│ nightly/weekly:       │
│ tennis-data   │   │ + namematch/dedupe│   │   (profiles, ELO)   │   │  calibration report   │
│ ManTennisData │   │ + quality report  │   │        │            │   │  learning analyzer    │
│ MCP · ESPN    │   └──────────────────┘   │        ▼            │   │  CLV weekly           │
│ API-Tennis    │                          │ predict → pick gate  │   └─────────┬────────────┘
│ odds-api.io   │──── odds (TTL cache) ───▶│  → clv_log (17 repro│             │
└───────────────┘                          │     cols) + value_  │             ▼
                                           │     picks           │   ┌──────────────────────┐
                                           │        │ settle      │   │ reports/*.md + KB     │
                                           │        ▼            │──▶│ entries (decisions,   │
                                           │ bet_history, CLV,   │   │ suggestions, snapshots)│
                                           │ track record        │   └──────────────────────┘
                                           └────────────────────┘
        backups: state/backups (6h) ── restore drill quarterly ── janitor prunes tmp files
```

---

<a name="8-api-architecture"></a>
## 8. API Architecture

### 8.1 Four planes, one process (initially)

| Plane | Routes (today) | Consumers | Auth |
|---|---|---|---|
| **Public/client API** | `/api/status`, `/api/players*`, `/api/predict`, `/api/upcoming`, `/api/live`, `/api/value*`, `/api/bet-history*`, `/api/track-record*`, `/api/chat`, `/api/upload`, `/api/bet-builder/combo`, follows, `/api/app/version` | Android, web (future) | `X-API-Token` (client token) |
| **Admin API** | `/api/settlement/run`, `/api/learn/run`, `/api/ingest/*`, `/api/backfill`, `/api/intelligence/cycle`, inplay pick CRUD | Operator, ops agents | **Separate admin token** (new — §11.2); audit-logged |
| **Internal/observability** | `/api/monitor/status`, `/api/logging/health`, `/api/scanner/status`, `/api/learner/stats` | Scheduler monitor, dashboards, AI tools | client token; read-only |
| **Unauthenticated** | `/health`, `/privacy`, `/api/openapi.json`, `/api/docs` | Load balancers, stores | none (keep minimal) |

Background workers (§5.3) are **not** an API plane — they talk to the DB and the
event bus directly; the monitor observes them; the API only *reports* on them.

### 8.2 Contract rules

- **`openapi_spec.py` is the contract source of truth** (hand-written is fine at
  this scale — ADR-012), with a CI drift check: every registered Flask route must
  appear in the spec and vice versa. That check is what keeps "hand-written"
  honest.
- **Additive-only evolution (P3).** New fields optional; nothing removed or
  re-typed. If a breaking change ever becomes unavoidable: new route, old route
  deprecated with a sunset header and an Android version gate
  (`/api/app/version` already exists for forced-update messaging).
- **Blueprint decomposition** (Q3): one blueprint per OpenAPI tag; shared
  middleware (auth → rate limit → audit → cache) applied in the app factory.
  Route behavior byte-identical; `test_api_endpoints*.py` guards it.
- **Rate limiting** stays deliberately scoped (odds-quota routes) + a coarse
  global ceiling on `/api/chat` (LLM cost) and auth-failure throttling (§11).

---

<a name="9-deployment-architecture"></a>
## 9. Deployment Architecture

### 9.1 Environments

| Env | Host | Artifact | Data | Purpose |
|---|---|---|---|---|
| **Development** | Windows / WSL, developer machine | source checkout | dev copy of DBs (never prod `state/`) | daily work |
| **Staging** (new) | same box, different port/compose project — later the VPS | `docker-compose.yml` (exists, correct 3-service split) | restored **from latest prod backup** — doubles as the restore drill | pre-deploy validation, restore rehearsal |
| **Production** | WSL + systemd today → VPS via the same compose file when ready | systemd units / compose | live `state/` | serving `api.tennisboss.online` |

The key insight: **the compose file is already the portable production
definition** — staging = running it against a backup copy; VPS migration = running
it on a rented box. No new tooling required, only discipline.

### 9.2 Topology (production)

```
 Android app ── HTTPS ──▶ Cloudflare Worker (holds client token, edge auth)
                              │
                              ▼
                        Cloudflare Tunnel (cloudflared)
                              │
                 ┌────────────▼────────────┐   single host (WSL → VPS)
                 │  api process (Flask)     │◄─── systemd: tennisboss-bot
                 │  worker process          │◄─── systemd: tennisboss-scheduler
                 │  (scheduler + extracted  │
                 │   daemon loops)          │
                 │  cloudflared             │◄─── systemd: tennisboss-tunnel
                 │  shared: state/ (SQLite  │
                 │   WAL), logs/, secrets/  │
                 └─────────────────────────┘
                              │ 6h
                              ▼
                     state/backups/  ──(roadmap)──▶ off-host copy (encrypted)
```

### 9.3 CI/CD

- **CI (exists):** GitHub Actions — backend pytest + Android unit tests on
  push/PR to main. **Add:** OpenAPI drift check, import-boundary lint (once
  packages exist), `ruff` lint, and an `assembleRelease` smoke on tags.
- **CD (target):** deploy = `git pull && docker compose up -d --build` on the
  host, wrapped in a `scripts/deploy.sh` that: records the git hash into
  `deployment_history` (knowledge base), runs migrations, health-checks, and
  rolls back to the previous image on failed health. Manual trigger is fine —
  the value is *recorded, repeatable* deploys, not automation for its own sake.
  This also closes today's "deployed code vs repo HEAD drift" risk (R-6).

### 9.4 Secrets, backup, recovery

- Secrets: `.env` on host (never committed — verified), Firebase key in
  `secrets/` (moved out of `state/`, §11.3), Cloudflare Worker holds the edge
  token. Rotation runbook documented per key (providers: odds-api, API-Tennis,
  Groq, Gemini, Telegram, Firebase).
- Backup: 6h DB snapshot (exists) + `memory.json` + `.env` inventory (not
  values) → **off-host encrypted copy** (roadmap Q4) — today a disk failure
  loses everything including backups.
- Recovery: quarterly restore drill = spin up staging from the latest backup and
  run the smoke suite. A backup that has never been restored is a hope, not a
  backup.

---

<a name="10-observability"></a>
## 10. Observability

Philosophy: single-node scale ⇒ no Prometheus/Grafana stack (the compose file's
reasoning stands). Instead, **first-party observability**: structured data in
SQLite + API endpoints + Telegram alerts — all of it consumable by the AI
assistant's read-only tools, which makes the assistant the de-facto ops console.

| Pillar | Today | Target |
|---|---|---|
| **Logging** | `bot/log.py` → single file, thread-safe; `except: pass` mostly eradicated (26→WARN) | Size-based rotation; optional JSON lines mode (`TENNISBOSS_LOG_JSON=1`) so logs become queryable; every log line carries context (job name, event key) |
| **Metrics** | implicit (scanner status, jobs_run counter) | lightweight `metrics` table (name, value, ts) written by jobs and API middleware: request counts/latency p95 per route, feeder rows ingested, odds quota used, LLM tokens/day, scanner cycle time. Exposed at `/api/metrics` (internal plane) |
| **Tracing** | none | not needed at this scale; **correlation id** per request/job (logged + returned as header) gives 90% of the value for 1% of the cost |
| **Health** | `/health` (liveness), `/api/monitor/status` (5-min system check: DB, endpoints, quota, drift) | keep; add per-job `last_success_at` from the job registry so a silently-dead job is visible within one schedule period |
| **Alerts** | Telegram digest + steam alerts; monitor logs | alert rules on events: `JobFailed` ×3 consecutive, backup age > 12h, odds quota > 80%, logging completeness < threshold, disk > 85% — routed through Notifications (channel-agnostic) |
| **Audits** | rich but ad-hoc Markdown audits | admin-endpoint audit log (§11.4) + `deployment_history` + immutable dated audits under `docs/audits/` |

**North-star check (memory of the freeze decree):** `/api/logging/health` —
pick-reproducibility completeness — is the observability metric that gates the
entire modeling roadmap. It belongs on every digest.

---

<a name="11-security"></a>
## 11. Security

### 11.1 Authentication

- Keep token-based auth (`X-API-Token`, centralized `before_request`) — right-sized
  for a single-operator product; full user accounts arrive only if multi-user does.
- **Close the LAN loophole as default-deny:** serving unauthenticated when
  `TENNISBOSS_API_TOKEN` is unset flips from warn-and-serve to
  **refuse-to-start in production** (`TENNISBOSS_ENV=prod`), warn-and-serve only in dev.
- Edge auth (Cloudflare Worker injecting the token) stays; the origin still
  validates (defense in depth — the tunnel URL must not be a bypass).

### 11.2 Authorization

- Introduce a **second token for the admin plane** (`TENNISBOSS_ADMIN_TOKEN`):
  settlement/learn/ingest/backfill/inplay-CRUD require it. Client token can no
  longer trigger state-changing ops. Two scopes is enough; RBAC is over-design here.
- AI assistant tools authenticate as a third, read-only identity — blocked from
  the admin plane by construction (registry) *and* by token scope.

### 11.3 Secrets

- Move `firebase-adminsdk.json` out of `state/` (which is volume-mounted,
  backed up, and browsed by tools) into gitignored `secrets/` with explicit path
  config. Backups must not embed live credentials.
- Per-key rotation runbook (provider dashboard link, env var name, restart
  needed?) in ops docs. Any key that ever transited in clear text gets rotated
  (the README already mandates this — make it a checklist, not a sentence).

### 11.4 Rate limiting & audit

- Keep scoped odds-route limits; add auth-failure throttling (per-IP backoff on
  401s) and a chat-route ceiling (LLM cost protection).
- **Audit log** (new table): every admin-plane call → who (token scope), what
  (route, params), when, result. Every deploy → `deployment_history`. Every
  model-version bump → knowledge base. This is what makes an AI-operated system
  reviewable after the fact.

---

<a name="12-plugin-architecture"></a>
## 12. Plugin Architecture

### 12.1 Pattern

One pattern, five registries. A plugin is a Python module implementing a small
Protocol and registering itself (explicit registry list — no import-time magic,
no entry-points machinery; discoverability beats cleverness at this scale).
The core defines contracts and lifecycles; plugins never modify core files.

```
        ┌────────────────────── core contracts (platform/) ─────────────────────┐
        │  FeederPlugin      JobPlugin        SignalPlugin                      │
        │  ToolPlugin        ChannelPlugin    (each: name, meta, run, health)   │
        └───────┬───────────────┬────────────────┬───────────────┬─────────────┘
                │               │                │               │
        data/feeders/*     ops/jobs/*    intelligence/signals/*  ai/chat/tools/*
                                                                 notifications/channels/*
```

### 12.2 Feeder plugins (`data/feeders/`)
`name`, `source_url(s)`, `schedule_hint`, `fetch()`, `normalize()`, `ingest() →
IngestReport`, `health()`. The registry drives scheduler wiring and the
`/api/ingest/*` admin routes. Sackmann/tennis-data/MTD/MCP/rankings retrofit into
this contract as-is.

### 12.3 Job plugins (`ops/jobs/`)
`name`, `schedule` (cron-ish), `run()`, `health() → {last_run, last_success,
error_count}`. The scheduler becomes a loop over the registry; monitor gets
per-job status for free; adding job #12 touches zero existing files.

### 12.4 Signal plugins (`intelligence/signals/`)
`name`, `compute(match_ctx) → SignalResult {value, direction, confidence}`,
`validation_status: validated|experimental|rejected`, `ui_label` (both locales).
API exposes signals *only* through the registry with status attached — the UI can
then render experimental signals visually distinct, preventing mislabeling
regressions (the HONEYPOT lesson) structurally.

### 12.5 Notification channel plugins (`notifications/channels/`)
`name`, `send(audience, message) → DeliveryResult`, `health()`. Telegram, FCM
push, and the digest formatter become three plugins behind `notify()`; email or
Discord later are drop-ins.

### 12.6 AI tool plugins (`ai/chat/tools/`)
Already exists — the registry ships with `read_only=True` enforced. Extension =
new tool module + registry entry + a guard test. The blocked-tool list (§6.7) is
a permanent denylist in the contract itself.

---

<a name="13-ai-governance"></a>
## 13. AI Governance

Who (which agent) may do what, and how overlap is prevented.

### 13.1 Ground rules for all agents

1. **The frozen boundary is absolute** (ADR-005). No agent modifies
   `predictor.py`, `calibrate.py`, market blend, value thresholds, or
   `versions.py`. Guard test + (future) import-lint enforce it mechanically.
2. **MASTER_TODO.md is the coordination ledger.** Every work item an agent picks
   up is claimed there (status → in-progress with agent name) before code is
   touched, and closed with verification evidence. Two agents never work the
   same item.
3. **Decisions go to the knowledge base** (until it exists: a dated entry in
   MASTER_TODO + doc). "We decided X because Y" must outlive the chat session
   that decided it.
4. **Destructive actions require human sign-off** — deletion, schema changes,
   production restarts, force-push. (Existing convention, now codified.)
5. **Every slice ships green:** full backend suite + relevant Android tests, and
   byte-identical API behavior unless the change is an approved additive one.
6. **Audits are read-only and dated.** An auditing agent never "fixes while
   auditing"; it files findings.

### 13.2 Ownership matrix

| Area | Owner | Consulted | Notes |
|---|---|---|---|
| Architecture, ADRs, this blueprint | **Human owner** (decides) + Claude (drafts) | Cursor | Only the human ratifies an ADR |
| Frozen prediction core | **Human owner only** | — | Unfreeze requires evidence per ADR-005 |
| Backend refactors (blueprint slices, package moves, event bus) | **Claude** | Human sign-off per slice | Strangler-fig slices; suite green each time |
| Backend features (new endpoints, feeders, jobs) | **Claude** | — | Follows plugin contracts |
| AI assistant (`ai/`, prompts, tools, knowledge base) | **Claude** | Human approves new tools | Read-only plane enforced by tests |
| Android UI & UX (screens, components, copy) | **Cursor Composer** | Claude for API contract questions | Repository/DI seam design is joint (contract from Claude, implementation Cursor) |
| Android architecture seams (Repository, DI, Nav) | **Claude designs, Cursor implements** | — | Prevents 14 divergent call-site patterns |
| Tests (backend) | **Claude** (with owning feature) | — | Tests ship with the slice, never after |
| Tests (Android) | **Cursor Composer** | — | FakeApi + dispatcher-seam pattern is the standard |
| Ops/deploy (systemd, compose, deploy script, backups) | **Claude** | Human executes prod restarts | Deploys recorded in deployment_history |
| Docs hygiene (audits→`docs/audits/`, stale-doc pruning) | **Claude** | Human sign-off on deletions | Supersession, not silent edits |
| Release management (versioning, Play Store) | **Human owner** | Cursor (build), Claude (checklists) | |
| Future agents (specialized) | Onboard via this doc §13 + AGENTS.md | — | Must claim ledger items like everyone else |

### 13.3 Conflict prevention protocol

- **File-level ownership follows the context map:** Cursor works under
  `android/`; Claude works under backend packages; neither edits the other's
  domain without a ledger handoff note.
- **Contract-first collaboration:** cross-boundary work (new endpoint + new
  screen) starts by writing the OpenAPI spec entry; both agents implement
  against it independently.
- **Session hygiene:** agents commit or explicitly hand off uncommitted work at
  session end — a dirty work tree spanning agents is how production/repo drift
  happens (risk R-6, observed 2026-07-16).

---

<a name="14-diagrams"></a>
## 14. Architecture Diagrams (ASCII)

### 14.1 System context (C4 level 1)

```
                    ┌─────────────┐
                    │   Operator   │ (single human, + AI agents in dev)
                    └──────┬──────┘
             Android app   │   Telegram · curl · CLI
                    ┌──────▼───────────────────────────────┐
                    │              TENNISBOSS               │
                    │  prediction 🔒 · data · odds · betting │
                    │  intelligence · ai · knowledge ·       │
                    │  learning · ops · notifications · api  │
                    └──┬──────┬──────┬──────┬──────┬────────┘
                       │      │      │      │      │
                 Sackmann  tennis- ESPN/  odds-  LLMs (Groq,
                 mirrors   data/MTD API-   api.io  Gemini,
                           /MCP    Tennis  (quota) Ollama)
                       + Firebase FCM · Telegram Bot API · Cloudflare
```

### 14.2 Runtime topology — target (two processes, one host)

```
┌─────────────────────────── host (WSL → VPS) ───────────────────────────┐
│                                                                         │
│  ┌────────────── api process ─────────────┐  ┌──────── worker ────────┐ │
│  │ Flask app factory                       │  │ job registry:          │ │
│  │  blueprints: core/matches/value/perf/   │  │  11 scheduled jobs     │ │
│  │  intel/chat/admin/devices               │  │  + value scanner loop  │ │
│  │ middleware: auth→ratelimit→audit→cache  │  │  + followed refresher  │ │
│  │ NO daemon threads                       │  │  + telegram poller     │ │
│  └──────────────┬─────────────────────────┘  │  + settlement/CLV      │ │
│                 │                             └───────────┬───────────┘ │
│                 │        shared via SQLite WAL + events_outbox          │
│         ┌───────▼─────────────────────────────────────────▼──────────┐ │
│         │ state/: tennisboss.db · project_knowledge.db · memory.json │ │
│         └────────────────────────────────────────────────────────────┘ │
│  secrets/ (gitignored)   logs/ (rotated)   state/backups/ (6h→off-host)│
└─────────────────────────────────────────────────────────────────────────┘
```

### 14.3 Event flow (outbox pattern)

```
 settlement job                     events_outbox (SQLite)
──────────────────                 ┌──────────────────────┐
 settle(pick)                      │ id | type | payload | │
   ├─ UPDATE clv_log  ──same txn──▶│ processed_at         │
   └─ publish(PickSettled) ───────▶└──────────┬───────────┘
                                              │ poll / in-process dispatch
                     ┌────────────────────────┼──────────────────────┐
                     ▼                        ▼                      ▼
             notifications:            learning analyzer:      knowledge:
             push/telegram if          accumulate for          update track-
             followed match            weekly report           record stats
```

### 14.4 Strangler-fig migration (per slice)

```
 before:  callers ──▶ bot/xyz.py (implementation)

 during:  callers ──▶ bot/xyz.py (shim: from data.feeders.xyz import *)
                         └────────▶ data/feeders/xyz.py (implementation)
          [full test suite green; API byte-identical]

 after (2 releases + grep gate): callers ──▶ data/feeders/xyz.py
                                  bot/xyz.py deleted
```

---

<a name="15-adrs"></a>
## 15. ADRs — Architecture Decision Records

Format: Status · Context · Decision · Consequences · Revisit trigger.
Future ADRs go to `docs/adr/ADR-NNN-title.md`; this section seeds the log.

---

**ADR-001 — Modular monolith; no microservices.**
*Accepted 2026-07-16.* One codebase, two processes (api, worker), one host.
Bounded contexts are packages with enforced imports, not network services.
**Why:** single operator, single node, SQLite concurrency model, AI agents
navigate one repo far better than N. **Consequences:** discipline must come from
import rules and CI, not process boundaries. **Revisit:** a context needs
independent scaling or a second host becomes necessary.

**ADR-002 — SQLite (WAL) remains the system of record.**
*Accepted 2026-07-16.* No Postgres migration. **Why:** zero-ops, proven here at
~94k matches / 4.8k picks; the mcp_feeder incident was a connection-usage bug,
not an engine limit. **Consequences:** single-writer discipline per table;
archive strategy at growth thresholds (§7.2). **Revisit:** DB file > 2 GB,
hot-query p95 > 100 ms, or true multi-host writes needed.

**ADR-003 — Flask (sync) stays; FastAPI rejected.**
*Accepted 2026-07-13 (app/ removal), codified 2026-07-16.* The parallel FastAPI
`app/` package was removed after proving inert. **Why:** two competing
architectures in one repo cost more than async buys at this traffic.
**Consequences:** long-running work never runs in-request (workers own it).
**Revisit:** sustained request concurrency the sync worker pool can't serve.

**ADR-004 — Strangler-fig package migration with re-export shims.**
*Accepted 2026-07-16.* Flat `bot/` evolves into context packages (§4) via shims;
every slice ships with the suite green; shims removed after two release cycles
via grep gate. **Why:** ~585 tests and production continuity beat big-bang
purity. **Consequences:** temporary dual paths; a visible shim inventory.

**ADR-005 — Prediction core frozen; evidence-gated unfreeze.**
*Accepted 2026-07 (user decree), codified 2026-07-16.* `predictor.py`,
`calibrate.py`, market blend, value thresholds sealed until 200–500 settled
picks with complete logging (`/api/logging/health` is the gate metric). Changes:
human-only, ADR + walk-forward validation + version bump. New engines run in
parallel via `compare_engines` harness; they never edit v1.

**ADR-006 — In-process event bus with SQLite outbox; no broker.**
*Accepted 2026-07-16.* Domain events via a ~100-line dispatcher + durable
`events_outbox` table. **Why:** decoupling and replay without Kafka/Redis ops
burden. **Consequences:** the event *schema catalog* is the real contract;
transport swappable later. **Revisit:** multi-host consumers.

**ADR-007 — AI assistant is read-only; write tools permanently blocked.**
*Accepted 2026-07-16.* Tool registry enforces `read_only=True`; denylist
(`train_model`, `place_bet`, `modify_memory`, …) is contractual; CI guard test
asserts `ai/` never imports frozen modules. Suggestions require human approval.
**Revisit:** never for bet placement; other write scopes only via new ADR with
human-in-the-loop design.

**ADR-008 — FTS5 keyword retrieval before embeddings.**
*Accepted 2026-07-16.* Knowledge base ships with SQLite FTS5 only. Embeddings
added only on measured recall failure (<80% on a golden-question eval).
**Why:** <100 docs; zero new dependencies; deterministic and debuggable.

**ADR-009 — Additive-only API evolution; no /v2 URL scheme.**
*Accepted 2026-07-16.* Contract grows by optional fields; breaking changes get a
new route + deprecation window + Android version gate. Hand-written
`openapi_spec.py` stays authoritative with a CI drift check (ADR-012).

**ADR-010 — Android stays a thin client; Repository + DI seam precedes any
offline/caching/persistence feature.** *Accepted 2026-07-16.* Network-only is
the current *decision* (staleness is actively harmful for betting data). Room,
chat persistence, or cross-screen state may only be built behind a Repository
layer with constructor-injected dependencies (Hilt or manual — implementer's
choice), added screen-by-screen.

**ADR-011 — Single-host deployment with a rehearsed promotion path.**
*Accepted 2026-07-16.* WSL+systemd today; `docker-compose.yml` is the portable
production definition; staging = compose against a restored backup; VPS
migration = same compose on a rented box. Off-host encrypted backups and
quarterly restore drills are part of this ADR, not optional extras.

**ADR-012 — Hand-written OpenAPI spec, CI-checked against routes.**
*Accepted 2026-07-16.* Generation from code is rejected (loses curation);
honesty is enforced by a CI check that route table ⊆ spec ⊆ route table.

---

<a name="16-technical-debt"></a>
## 16. Technical Debt Register

Severity: 🔴 structural (blocks the target architecture) · 🟡 real but contained · 🟢 hygiene.

| ID | Debt | Sev | Where | Blueprint answer |
|----|------|-----|-------|------------------|
| D-1 | `bot/api.py` god-module — **progress confirmed 2026-07-23**: down to 2,891 lines (was ~4.2k), 38 routes still inline (was 52 — 19 already moved to `bot/blueprints/{core,matches,performance,personalization}.py`), the 4 daemon loops are now thin compat shims (2-5 lines each) delegating to `bot/workers/*.py` — see D-3. Still 🔴: far from the Q4 #7 exit criterion (`bot/api.py` < 500 lines, shim + factory only) | 🔴 | `bot/api.py` | §5.1/§5.3 blueprint split (Q4 #7) — remaining route batches |
| D-2 | No enforced module boundaries in flat `bot/` (69 files) | 🔴 | `bot/` | Context packages + import lint (ADR-004, §4) |
| D-3 | Daemon threads live inside the API process — **partially resolved 2026-07-23**: loop *logic* fully extracted to `bot/workers/{clv,settlement,inplay_settlement,match_refresh,data_refresh,value_scanner,telegram}_worker.py` (verified: `bot/api.py`'s `_clv_closing_loop`/`_settlement_loop`/etc. are now pure delegating shims, docstring-labeled "Compatibility shim"). Downgraded 🔴→🟡: the harder untangling is done. Still open: the threads are *started from and run inside* the single `bot/api.py` process, not a separate OS process — Q3 #4's exit criterion ("scanner survives API restarts") not yet met | 🟡 | `bot/api.py` | Actual process split still open (§5.3, Q3 #4) |
| D-4 | No schema migration mechanism (CREATE IF NOT EXISTS + ad-hoc ALTERs) | 🔴 | `bot/db.py` | `data/db/migrations/` + `schema_migrations` (§7.2) |
| D-5 | Knowledge sprawl: ~25 overlapping audit MDs, stale ones misleading (AI_CHAT_AUDIT, REALTIME-ROI, PROJECT_STATUS lag) — **PROJECT_STATUS refreshed 2026-07-22**; **`AI_CHAT_AUDIT.md`/`RELEASE_AUDIT.md` archived to `docs/audits/` 2026-07-23** (`git mv` + live cross-refs in `QUICK_START_CHAT.md`/`docs/AI_ASSISTANT_ARCHITECTURE.md` fixed; dated historical docs — `RELEASE_NOTES_CHAT.md`, `docs/DEVELOPMENT_AUDIT_2026-07-16.md` — left untouched by design, they're frozen snapshots not living docs). Still 🔴: ~23 other overlapping MDs, `REALTIME-ROI.md` still needs its rewrite (not a mechanical move), no KB (§6.4) yet | 🔴 | root + `docs/` | Knowledge base with supersession (§6.4, Q4 #8); remaining doc sprawl |
| D-6 | Secrets inside data dir (`state/firebase-adminsdk.json` — volume-mounted & backed up) | 🟡 | `state/` | `secrets/` move + backup exclusion (§11.3) |
| D-7 | ~~Hundreds of `tmp*.json.corrupt` files polluting `state/`~~ **closed — verified 2026-07-23**: `bot/scheduler.py` janitor job (`backup.prune_state_tmp`) confirmed live in prod (2026-07-23 startup log: "16 fichier(s) temporaire(s) orphelin(s) purgé(s)") | 🟢 | `state/` | Done |
| D-8 | ~~LAN unauthenticated-serve fallback when token unset~~ **closed — verified 2026-07-23**: `_enforce_prod_token()` (`bot/api.py`) refuses to start under `TENNISBOSS_ENV=prod` without a token (default-deny); prod `.env` confirmed running with `TENNISBOSS_ENV=prod` active | 🟢 | `bot/api.py` | Done |
| D-9 | ~~`compare-engines` CLI documented but not registered in `run.py`~~ **closed — verified 2026-07-23**: `run.py` has `cmd_compare_engines` wired as the `compare-engines` subcommand | 🟢 | `run.py` | Done |
| D-10 | ~~Two surface-detection paths~~ **corrected 2026-07-23: false — investigated, `config.surface_from_league()` has no duplicate; `_tourn_rank()` in `bot/api.py`/`bot/workers/value_scanner.py` is tournament-*tier* ranking (scan priority), unrelated to surface, and already documented as deliberately separate (`config.py:273`). That pair IS a real, minor duplication (P10) but the two copies have diverged tier boundaries — consolidating requires a scan-order product decision, not a mechanical fix; left alone, low value/low urgency.** Android `StatCard` duplication (`ui/components/StatCard.kt` vs inline copies in `EdgeScreen.kt`/`PerformanceScreen.kt`) **confirmed still real** — Android UI lane (§13/§19), not picked up here. | 🟢 | `EdgeScreen.kt`/`PerformanceScreen.kt` | Extract shared composable (Cursor); `_tourn_rank` merge only if scan-order behavior is explicitly revisited |
| D-11 | `auto_learner` hourly job writes model-adjacent state despite the freeze (grandfathered, ungoverned) | 🟡 | `bot/auto_learner.py`, `job_learn` | Human decision: exempt-by-ADR (documenting exact write surface) or demote to suggestion-only (§6.5) |
| D-12 | Android: no Repository/DI seam (13+ direct ApiClient call sites); zero instrumented UI tests despite testTags | 🟡 | `android/` | ADR-010 seam before any persistence feature; instrumented smoke later |
| D-13 | `security-crypto` alpha dependency for token storage; R8 disabled in release | 🟡 | `android/` | Swap to stable / EncryptedSharedPreferences alternative; enable R8 with keep rules when touched |
| D-14 | Uncommitted multi-day work-tree drift (AI Phase 1 files modified/untracked at audit time) | 🟡 | repo | Governance rule 13.3 (commit/hand-off per session); deploy script records hashes |
| D-15 | Backups never restore-tested; no off-host copy | 🔴 | ops | ADR-011 drills (Roadmap Q3/Q4) |
| D-16 | ~~openclaw-era artifacts~~ **partially closed 2026-07-23**: liveness audit done — `SOUL.md`/`IDENTITY.md`/`MEMORY.md`/`TOOLS.md`/`HEARTBEAT.md` were unreferenced vision/scaffolding docs describing a multi-agent "Gateway" architecture never actually built (`HEARTBEAT.md` was actively misleading — implied live agent orchestration that doesn't exist). Confirmed superseded by the real, current architecture (this blueprint, `AGENTS.md`, `docs/AI_ASSISTANT_ARCHITECTURE.md`, the shipped `bot/workers/telegram_worker.py`) — **deleted with explicit user sign-off**. `ksearch.py`/`watchdog.py` confirmed as real, functional standalone tools (ELO grid search, external crash-recovery monitor) — not dead, just misplaced at root instead of `scripts/`; left as-is (cosmetic, low priority). `.openclaw/`, `.openclaw-cli-images/` — untouched, out of scope of this pass. | 🟢 | root, `scripts/` | `ksearch.py`/`watchdog.py` → `scripts/` move still open, low priority |
| D-17 | Rate limiting absent on `/api/chat` (LLM cost) and on auth failures | 🟡 | `bot/api.py` | §11.4 |
| D-18 | ~~Log file grows unbounded (no rotation found)~~ **closed — verified 2026-07-23**: `bot/log.py` implements size-based rotation (`_MAX_BYTES`/`_KEEP`, `tennisboss.log` → `.1`/`.2`/`.3`), code comment explicitly cites this debt item | 🟢 | `bot/log.py` | Done |

---

<a name="17-risk-assessment"></a>
## 17. Risk Assessment

| ID | Risk | Likelihood | Impact | Mitigation (blueprint section) |
|----|------|-----------|--------|-------------------------------|
| R-1 | **Upstream data death** — Sackmann repos already vanished once (2026-07-12); tennis-data/MTD/MCP could follow | High (proven) | High — ingestion starves, profiles stale | Feeder plugin contract with env-overridable mirrors (§12.2); multi-source redundancy per data type; `DataIngested` monitoring with staleness alerts |
| R-2 | **Single-host total loss** (disk/machine failure) — backups live on the same disk | Medium | Critical — product + track record gone | Off-host encrypted backups + quarterly restore drill (ADR-011, Q3–Q4) |
| R-3 | **Odds provider quota/plan fragility** (2 bookmakers, scoped quota) | Medium | High — value pipeline blind | Quota metrics + 80% alert (§10); TTL discipline owned by Odds context; second-provider adapter behind the same interface when justified |
| R-4 | **No statistical edge after n≥200** — the product's core hypothesis fails | Medium | High (product, not code) | Honest framing already in copy; freeze discipline ensures the verdict is *valid*; learning reports make the verdict legible early (§6.5) |
| R-5 | **God-module regression risk** — every api.py edit risks unrelated routes/daemons | High until D-1 done | Medium per incident | Blueprint decomposition with byte-identical contract tests (Q3) |
| R-6 | **Prod/repo drift** — uncommitted changes + manual restarts = unreproducible prod | Medium (observed) | Medium | Deploy script recording git hash → `deployment_history` (§9.3); session hand-off rule (§13.3) |
| R-7 | **AI-agent governance failure** — an agent modifies frozen logic or two agents collide | Low (guards exist) | High | Guard tests, ledger claiming, import-lint on packages, ownership matrix (§13) |
| R-8 | **SQLite contention** as workers multiply | Low | Medium | WAL + single-writer-per-table rule (§7.2); measured revisit trigger (ADR-002) |
| R-9 | **LLM provider churn/cost** (Groq model deprecations, quota) | Medium | Low–Medium — chat degrades | Provider chain already 3-deep; provider health in monitor; per-day token budget metric (§10) |
| R-10 | **Security exposure on wider deployment** — LAN fallback, alpha crypto lib, single token scope | Medium | High if user base grows | Default-deny prod, admin token split, audit log (§11) before any public scale-up |
| R-11 | **Knowledge decay** — future agents trust stale audits and act on them | High today | Medium, compounding | Knowledge base with supersession as the *only* citable source (§6.4); audits made immutable snapshots |

---

<a name="18-roadmap"></a>
## 18. 12-Month Priority Roadmap

Sequencing logic: (1) never block pick-volume accumulation — it gates everything
statistical; (2) structural work first where it de-risks all later work;
(3) each item is strangler-slice sized, suite-green, individually shippable.

### Q3 2026 (Jul–Sep) — Foundations & safety

| # | Item | Context | Exit criterion |
|---|------|---------|----------------|
| 1 | **Ship what's built:** commit/deploy AI Phase 1 (`TENNISBOSS_AI_TOOLS=1`), Android `mode=analyst` + Sources chip | AI / Android | Analyst mode live end-to-end in prod |
| 2 | **Secrets & state hygiene:** firebase key → `secrets/`; janitor for corrupt tmp files; log rotation | Security / Ops | `state/` contains data only; monitor reports janitor counts |
| 3 | **Default-deny auth in prod** + admin-token plane split | Security | Unset token ⇒ refuse to start (prod); admin routes reject client token |
| 4 | **api.py decomposition, phase 1:** extract the 4 daemon loops into the worker (scheduler registry); api process serves HTTP only | Ops / API | Two clean process roles; scanner survives API restarts |
| 5 | **Deploy script + deployment_history** (git hash, migrations, health check, rollback) | Ops | Every prod change recorded; drift risk R-6 closed |
| 6 | Wire `compare-engines` into `run.py`; refresh `PROJECT_STATUS.md`; archive stale docs into `docs/audits/` | Learning / Docs | Documented workflows all executable |
| — | *(Continuous)* accumulate settled picks; watch `/api/logging/health` | Betting | n grows toward 200 with complete logging |

### Q4 2026 (Oct–Dec) — Structure & knowledge

| # | Item | Context | Exit criterion |
|---|------|---------|----------------|
| 7 | **api.py decomposition, phase 2:** Flask blueprints per OpenAPI tag + middleware chain; OpenAPI drift check in CI | API | `bot/api.py` < 500 lines (shim + factory); routes byte-identical |
| 8 | **Knowledge base MVP (Phase 2):** `project_knowledge.db`, FTS5, ingestion of docs/reports/versions; `search_knowledge` + `get_decision` tools | Knowledge / AI | Assistant answers "why did we reject surface features?" with citation from the KB, not a raw file walk |
| 9 | **Migration runner** (`schema_migrations`) + table-ownership map | Data | Next schema change ships as migration file |
| 10 | **Event bus + outbox** with initial catalog (PickSettled, OddsMoved, JobFailed…); notifications consume events | Platform | Settlement → push flows through the bus |
| 11 | **Off-host encrypted backups + first restore drill** (staging = compose from backup) | Ops | Documented, timed restore; staging exists |
| 12 | First package moves under ADR-004: `data/feeders/`, `ops/jobs/` (with shims) | All | Suite green; shim inventory documented |

### Q1 2027 (Jan–Mar) — Intelligence & learning loop

| # | Item | Context | Exit criterion |
|---|------|---------|----------------|
| 13 | **Learning reports (Phase 3, suggestion-only):** weekly analyzer → report + KB entry + digest | Learning | First weekly report cites real calibration bins; zero writes to model state |
| 14 | **auto_learner governance decision** (D-11): exempt-by-ADR or demote | Human + Learning | ADR filed either way |
| 15 | **Signal registry** with validation status; Android renders status-aware badges | Intelligence / Android | No signal reaches UI outside the registry |
| 16 | **Android Repository + DI seam** (design Claude, build Cursor), then chat persistence as its first consumer | Android | One data layer; ViewModels no longer construct clients |
| 17 | Metrics table + `/api/metrics`; alert rules (job failures, quota, backup age) | Observability | Silent-death window for any job ≤ its schedule period |
| 18 | **Edge checkpoint (n≥200 expected):** run the frozen-core evidence review — unfreeze case, or extend freeze with documented reasoning | Human + Learning | ADR-005 review minuted in the KB |

### Q2 2027 (Apr–Jun) — Platform maturity

| # | Item | Context | Exit criterion |
|---|------|---------|----------------|
| 19 | Package migration wave 2: `betting/`, `odds/`, `intelligence/`, `ai/providers/`; import-boundary lint in CI | All | Frozen core physically fenced; boundary violations fail CI |
| 20 | **LLM function-calling orchestrator v2** behind the same ToolRegistry | AI | Regex classifier retired; tool behavior unchanged |
| 21 | Embeddings *if and only if* FTS recall eval fails (ADR-008) | Knowledge | Eval results recorded either way |
| 22 | **VPS migration** using the compose file (staging promoted) — retires the WSL single-point | Ops | Prod on rented box; WSL becomes dev only |
| 23 | Read-only web dashboard (optional, if operator wants desktop analysis) consuming the public API | Clients | No new backend surface needed — proof the API plane is complete |
| 24 | Android: security-crypto swap, R8 enablement, instrumented smoke tests on the now-testTagged UI | Android | Release pipeline fully healthy |

**Explicitly deferred beyond 12 months:** multi-user auth, Postgres, message
broker, engine v2 modeling (gated on the Q1 evidence checkpoint), bet execution
(never).

---

<a name="19-ownership-matrix"></a>
## 19. Work Ownership Matrix (AI agents) — quick reference

*(Full governance in §13; this is the at-a-glance version to paste into agent
session prompts.)*

| Layer | Cursor Composer | Claude | Human owner |
|---|---|---|---|
| Frozen core (`predictor`, `calibrate`, thresholds) | ❌ | ❌ | ✅ (evidence-gated) |
| Backend refactors & platform (`api/`, `ops/`, `data/`, events) | ❌ | ✅ (slice sign-off) | approves |
| Backend features (endpoints, feeders, jobs) | ❌ | ✅ | approves scope |
| AI assistant & knowledge base | ❌ | ✅ (new tools need approval) | approves tools |
| Android UI/UX & Android tests | ✅ | contract consult | approves UX |
| Android architecture seams (Repo/DI/Nav) | implements | designs | approves |
| Ops/deploy/backups | ❌ | ✅ (prepares) | executes prod actions |
| Docs & audits | own area | ✅ (hygiene, supersession) | approves deletions |
| ADRs & this blueprint | proposes | drafts | **ratifies** |
| Releases (versioning, Play Store) | builds | checklists | ✅ ships |

**Coordination:** claim items in `MASTER_TODO.md` before touching code; record
decisions in the knowledge base (interim: dated MASTER_TODO entries); commit or
hand off at session end; audits never fix, fixes never audit.

---

*End of blueprint. Amend via `docs/adr/` — never by silently editing history.*

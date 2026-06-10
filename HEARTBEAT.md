# HEARTBEAT.md

## System Status Monitor

This file tracks the real-time health and operational state of the TennisBoss AI system.

---

## Core Status

- System: ACTIVE
- Mode: Multi-Agent Tennis Prediction Engine
- Leader Agent: main
- Gateway: required for full operation
- LLM Backend: Ollama (DeepSeek-R1 8B)

---

## Agent Health

- main: OK (decision engine active)
- stats_agent: OK (performance analysis)
- odds_agent: OK (market analysis)
- analyzer_agent: OK (synthesis layer)
- coder_agent: OK (maintenance layer)

---

## Data Flow Status

- Odds API: UNKNOWN / CHECK REQUIRED
- Historical Data: ACTIVE
- Live Match Feed: OPTIONAL / DEPENDS ON CONFIG
- Local Cache: ACTIVE

---

## Risk Flags

- Model drift: LOW
- Data inconsistency: LOW
- Market delay risk: MEDIUM
- Gateway connectivity: CHECK REQUIRED

---

## Gateway Dependency

- Status: CRITICAL
- If Gateway is DOWN:
  - No agent coordination
  - No orchestration
  - Only local reasoning available

---

## Performance Mode

Current Mode:
- Balanced analysis (accuracy > speed)

Optional Modes:
- SAFE MODE → conservative bets only
- AGGRESSIVE MODE → high EV + higher risk
- LIVE MODE → fast odds reaction

---

## Health Rules

System is considered healthy if:
- Gateway reachable
- All agents return structured output
- Ollama model responds within timeout
- No repeated analysis failures

---

## Objective Tracking

- Primary Goal: Maximize long-term ROI in tennis betting markets
- Secondary Goal: Improve prediction confidence calibration
- Tertiary Goal: Reduce false positives in value detection
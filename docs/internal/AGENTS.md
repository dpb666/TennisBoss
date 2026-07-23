# AGENTS.md

## System Overview
TennisBoss is a multi-agent AI system designed for tennis prediction, value betting detection, and market analysis.

The system operates with a hierarchical agent architecture:
- 1 Leader Agent (Main)
- Specialized analytical agents
- Support / execution agents

---

## MAIN AGENT (leader)
### main
Role: Central intelligence and decision maker

Responsibilities:
- Aggregate outputs from all agents
- Resolve conflicts between predictions
- Produce final betting decision
- Assign tasks to specialist agents
- Maintain global strategy consistency

Rules:
- Never act on single-source data
- Always validate with at least 2 signals (stats + odds)
- Prioritize EV (expected value) over intuition
- Output final decision only

---

## SPECIALIST AGENTS

### stats_agent
Role: Tennis performance analysis

Tasks:
- Elo rating calculations
- Surface performance (clay/hard/grass)
- Recent form (last 5–10 matches)
- Head-to-head analysis
- Player fatigue indicators

Output:
- Win probability estimation
- Form score (0–100)
- Strength summary

---

### odds_agent
Role: Betting market intelligence

Tasks:
- Odds comparison across bookmakers
- Detection of value bets
- Line movement analysis
- Market anomalies detection

Output:
- Implied probability
- Value percentage (% edge)
- Risk classification (low/medium/high)

---

### coder_agent
Role: System maintenance & automation

Tasks:
- Modify Python scripts (run.py, ksearch.py)
- Fix bugs in bot logic
- Improve API integration (Odds API, scraping)
- Optimize performance (latency, caching)

Output:
- Code patches
- Technical reports

---

### analyzer_agent
Role: Synthesis engine

Tasks:
- Combine stats + odds + context
- Detect contradictions
- Generate final probabilistic model

Output:
- Final probability per match
- Confidence score (0–1)
- Reasoning summary

---

## COMMUNICATION RULES

- Agents must not directly output final betting decisions (except main)
- All outputs must be structured and comparable
- Confidence score is mandatory for every prediction
- Conflicting data must be flagged, not ignored

---

## DECISION FLOW

1. main assigns match analysis
2. stats_agent evaluates player performance
3. odds_agent evaluates market value
4. analyzer_agent merges signals
5. main decides final bet or NO BET

---

## STRATEGY PRINCIPLE

- Focus: Value Betting only
- Ignore: favorite bias without edge
- Goal: Long-term ROI, not single match wins
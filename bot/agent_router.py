"""Agent routing for TennisBoss AI Chat.

Currently a stub — will integrate with OpenClaw sessions_spawn when available.
Routes messages to specialized agents:
  - stats_agent: player performance analysis
  - odds_agent: market value detection
  - analyzer_agent: signal synthesis
  - coder_agent: system diagnostics
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .log import log

# Agent prompts (injected as system context)
AGENT_PROMPTS = {
    "stats_agent": (
        "You are the TennisBoss Stats Agent. "
        "Analyze player performance using Elo ratings, surface expertise, "
        "recent form, and head-to-head records. "
        "Provide win probability estimates and confidence scores. "
        "Be concise and data-driven."
    ),
    "odds_agent": (
        "You are the TennisBoss Odds Agent. "
        "Analyze market values, detect arbitrage opportunities, "
        "compare implied probabilities across bookmakers. "
        "Calculate EV (expected value) and risk classifications. "
        "Flag anomalies and sharp money signals."
    ),
    "analyzer_agent": (
        "You are the TennisBoss Analyzer Agent. "
        "Synthesize signals from stats, odds, and market data. "
        "Reconcile conflicts between data sources. "
        "Produce final probability estimates with confidence scores. "
        "Focus on value betting, not prediction."
    ),
    "coder_agent": (
        "You are the TennisBoss Coder Agent. "
        "Diagnose system issues, suggest code improvements, "
        "explain architecture, and report performance metrics. "
        "Be technical and direct."
    ),
}


def route_to_agent(
    agent_name: str,
    message: str,
    context: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    """Route message to agent.

    Returns:
      (system_prompt, enriched_context)

    When OpenClaw is available, this will spawn an actual sub-agent.
    For now, returns system prompt for LLM context injection.
    """
    if agent_name not in AGENT_PROMPTS:
        log(f"Unknown agent: {agent_name}", "WARN")
        return ("", context)

    system = AGENT_PROMPTS[agent_name]
    enriched = context.copy()
    enriched["agent"] = agent_name
    enriched["system_prompt"] = system

    log(f"Routing to {agent_name}", "INFO")
    return (system, enriched)


async def spawn_agent_session(
    agent_name: str,
    message: str,
    context: Dict[str, Any],
) -> Optional[str]:
    """Spawn OpenClaw sub-agent session (TODO).

    When available, will use:
      sessions_spawn(
          sessionName=agent_name,
          prompt=message,
          context="fork"
      )
      sessions_yield()

    For now, returns None to fall back to local LLM.
    """
    # TODO: import sessions_spawn from openclaw when available
    # try:
    #     agent_session = sessions_spawn(...)
    #     sessions_yield()
    #     return agent_session.output
    # except Exception as e:
    #     log(f"Agent spawn failed: {e}", "WARN")
    #     return None

    return None

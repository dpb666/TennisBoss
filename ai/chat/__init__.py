"""AI chat orchestration layer — see docs/AI_ASSISTANT_ARCHITECTURE.md §3.

Read-only: supplements bot/chat.py's existing grounding (build_match_context)
with structured tool output. Never replaces it, never writes to production
state, never imports bot.predictor / bot.calibrate / bot.learner.
"""

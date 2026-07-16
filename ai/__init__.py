"""TennisBoss AI Assistant ecosystem (chat tools, project memory, self-learning).

See docs/AI_ASSISTANT_ARCHITECTURE.md. Everything under `ai/` is analytical
and read-only with respect to the frozen prediction engine: it must never
import `bot.predictor`, `bot.calibrate`, or `bot.learner`, and it must never
place bets, change predictions, or modify production logic automatically.
"""

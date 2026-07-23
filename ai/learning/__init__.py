"""Phase 3 self-learning — suggestion-only post-settlement analysis.

See docs/ARCHITECTURE_BLUEPRINT.md §6.5 and docs/AI_ASSISTANT_ARCHITECTURE.md
§5. Never writes model parameters, thresholds, or memory.json — read-only
synthesis of existing analysis modules (bot/calibration_report.py,
bot/track_record.py, bot/market_efficiency_audit.py) into a weekly report.
"""

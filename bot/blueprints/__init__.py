"""Flask blueprints — strangler-fig extraction from bot/api.py.

Phase 2 (read-only routes first): core + performance + personalization;
phase 2c adds /api/status, /privacy, /api/bet-history/*;
phase 2d adds /api/upcoming, /api/live;
phase 2e adds /api/intelligence/*, /api/learner/stats, /api/scanner/status,
/api/monitor/status (diagnostics — D-1); phase 2f adds /api/calibration,
/api/history, /api/clv, /api/clv/weekly, /api/line-movement (reporting).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Flask

if TYPE_CHECKING:
    from flask_limiter import Limiter


def register_blueprints(app: Flask) -> None:
    from .core import bp as core_bp
    from .diagnostics import bp as diagnostics_bp
    from .matches import bp as matches_bp
    from .performance import bp as performance_bp
    from .personalization import bp as personalization_bp
    from .reporting import bp as reporting_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(diagnostics_bp)
    app.register_blueprint(performance_bp)
    app.register_blueprint(personalization_bp)
    app.register_blueprint(matches_bp)
    app.register_blueprint(reporting_bp)


def apply_blueprint_rate_limits(limiter: "Limiter") -> None:
    """Rate limits that lived on api.py routes before blueprint extraction."""
    from . import matches

    limiter.limit("20 per minute")(matches.api_upcoming)
    limiter.limit("20 per minute")(matches.api_live)

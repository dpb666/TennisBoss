"""Flask blueprints — strangler-fig extraction from bot/api.py.

Phase 2 (read-only routes first): core + performance + personalization;
phase 2c adds /api/status, /privacy, /api/bet-history/*.
"""
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    from .core import bp as core_bp
    from .performance import bp as performance_bp
    from .personalization import bp as personalization_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(performance_bp)
    app.register_blueprint(personalization_bp)

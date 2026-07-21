"""Core blueprint — public health/status endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from .. import __version__

bp = Blueprint("core", __name__)


@bp.get("/health")
def health():
    from .. import api

    return jsonify({
        "status": "ok",
        "service": "TennisBoss",
        "version": __version__,
        "players_loaded": len(api._MEM.get("players", {})),
    })

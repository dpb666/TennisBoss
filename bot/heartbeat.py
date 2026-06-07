"""Battement de cœur : preuve de vie périodique du bot."""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict

from .log import log


def tick(mem: Dict[str, Any]) -> None:
    hb = mem["heartbeat"]
    hb["count"] = int(hb.get("count", 0)) + 1
    hb["last_iso"] = _dt.datetime.now().isoformat(timespec="seconds")
    acc = mem["metrics"].get("accuracy", 0.0)
    log(
        f"♥ heartbeat #{hb['count']} | joueurs={len(mem['players'])} | "
        f"précision={acc}",
        "BEAT",
    )

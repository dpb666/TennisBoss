"""Core blueprint — public health/status endpoints."""
from __future__ import annotations

import os
import re

from flask import Blueprint, jsonify

from .. import __version__, db, odds_api

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


@bp.get("/privacy")
def privacy_policy():
    """Politique de confidentialité — URL publique requise par Google Play Console.

    Sert PRIVACY_POLICY.md (racine du repo) en HTML simple, sans dépendance
    de rendu markdown (juste un mapping ligne à ligne suffisant pour ce doc).
    """
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "PRIVACY_POLICY.md")
    path = os.path.normpath(path)
    try:
        with open(path, encoding="utf-8") as f:
            md = f.read()
    except OSError:
        return "Politique de confidentialité indisponible.", 404

    def _inline(text: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    lines_html = []
    in_table = False
    in_list = False
    para_buf: list = []

    def _flush_para():
        if para_buf:
            lines_html.append(f"<p>{_inline(' '.join(para_buf))}</p>")
            para_buf.clear()

    def _close_list():
        nonlocal in_list
        if in_list:
            lines_html.append("</ul>")
            in_list = False

    for line in md.splitlines():
        s = line.strip()
        is_sep_row = bool(re.fullmatch(r"\|?[\s:|-]+\|?", s)) if s.startswith("|") else False
        if is_sep_row:
            continue
        if s.startswith("|"):
            _flush_para()
            _close_list()
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not in_table:
                lines_html.append("<table>")
                in_table = True
            tag = "th" if lines_html[-1] == "<table>" else "td"
            lines_html.append("<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            lines_html.append("</table>")
            in_table = False
        if s.startswith("# "):
            _flush_para()
            _close_list()
            lines_html.append(f"<h1>{_inline(s[2:])}</h1>")
        elif s.startswith("## "):
            _flush_para()
            _close_list()
            lines_html.append(f"<h2>{_inline(s[3:])}</h2>")
        elif s.startswith("- "):
            _flush_para()
            if not in_list:
                lines_html.append("<ul>")
                in_list = True
            lines_html.append(f"<li>{_inline(s[2:])}</li>")
        elif s:
            _close_list()
            para_buf.append(s)
        else:
            _flush_para()
            _close_list()
    _flush_para()
    _close_list()
    if in_table:
        lines_html.append("</table>")

    html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Politique de confidentialité — TennisBoss AI</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 720px;
       margin: 0 auto; padding: 24px 20px 60px; line-height: 1.55; color: #1a1a1a; }}
h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.15rem; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 0.9rem; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
th {{ background: #f5f5f5; }}
</style></head><body>{"".join(lines_html)}</body></html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@bp.get("/api/status")
def api_status():
    from .. import api

    m = api._MEM["metrics"]
    return jsonify({
        "metrics": m,
        "weights": api._MEM["weights"],
        "bias": api._MEM["bias"],
        "datasets_loaded": api._MEM["datasets_loaded"],
        "db": db.counts(),
        "rate_limit": odds_api.rate_limit_status(),
        "odds_rate_limit": odds_api.rate_limit_status(),
    })

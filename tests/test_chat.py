"""Tests unitaires pour bot/chat.py (sans LM Studio réel)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from bot.chat import _detect_players, _player_snapshot, build_context, _surface_elo_line


def _fake_mem():
    return {
        "players": {
            "Jannik Sinner": {"serve": 0.72, "return1": 0.55, "return2": 0.58, "recent": 1.0, "n": 321},
            "Carlos Alcaraz": {"serve": 0.70, "return1": 0.53, "return2": 0.56, "recent": 0.95, "n": 280},
            "Novak Djokovic": {"serve": 0.68, "return1": 0.60, "return2": 0.62, "recent": 0.80, "n": 500},
        },
        "elo": {
            "Jannik Sinner": 2112.0,
            "Carlos Alcaraz": 2085.0,
            "Novak Djokovic": 2050.0,
        },
        "elo_surface": {
            "clay": {"Carlos Alcaraz": 2120.0, "Jannik Sinner": 2060.0},
            "hard": {"Jannik Sinner": 2130.0, "Carlos Alcaraz": 2070.0},
        },
        "metrics": {"accuracy": 0.644},
    }


def test_build_context_has_top_elo():
    ctx = build_context(_fake_mem())
    assert "Jannik Sinner" in ctx
    assert "2112" in ctx


def test_build_context_has_surface():
    ctx = build_context(_fake_mem())
    assert "clay" in ctx
    assert "Carlos Alcaraz" in ctx


def test_detect_players_basic():
    mem = _fake_mem()
    players_lower = {n.lower(): n for n in mem["players"]}
    found = _detect_players("Comment se compare sinner contre alcaraz ?", players_lower)
    assert "Jannik Sinner" in found
    assert "Carlos Alcaraz" in found


def test_detect_players_none():
    mem = _fake_mem()
    players_lower = {n.lower(): n for n in mem["players"]}
    found = _detect_players("Quel est le meilleur tournoi sur terre ?", players_lower)
    assert found == []


def test_player_snapshot_known():
    snap = _player_snapshot(_fake_mem(), "Jannik Sinner")
    assert snap is not None
    assert "ELO=2112" in snap
    assert "n=321" in snap


def test_player_snapshot_unknown():
    snap = _player_snapshot(_fake_mem(), "Inconnu Dupont")
    assert snap is None


def test_chat_calls_lm_studio():
    """chat() appelle bien POST sur l'URL LM Studio et retourne le contenu."""
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "Sinner est n°1 avec ELO 2112."}}]
    }
    with patch("bot.chat.requests.post", return_value=fake_response) as mock_post:
        from bot.chat import chat
        reply = chat("Qui est le meilleur ?", [], _fake_mem(), "http://fake:1234/v1/chat/completions")
    assert reply == "Sinner est n°1 avec ELO 2112."
    assert mock_post.called
    body = mock_post.call_args[1]["json"]
    assert body["messages"][-1]["role"] == "user"
    assert "Qui est le meilleur" in body["messages"][-1]["content"]


def test_surface_elo_line_two_players():
    """L'ELO par surface (déjà calculé dans mem['elo_surface']) doit être
    formaté pour les 2 joueurs, sur les surfaces où ils ont une valeur."""
    line = _surface_elo_line(_fake_mem(), ["Jannik Sinner", "Carlos Alcaraz"])
    assert "hard:" in line
    assert "clay:" in line
    assert "Jannik Sinner=2130" in line
    assert "Carlos Alcaraz=2120" in line


def test_surface_elo_line_missing_player():
    """Un joueur sans ELO de surface connu ne casse pas le formatage."""
    line = _surface_elo_line(_fake_mem(), ["Novak Djokovic"])
    assert line == ""


def test_chat_system_prompt_has_honesty_clause():
    """Le system prompt doit toujours porter la clause anti-promesse-de-gain,
    même sur une question du type 'je vais gagner ?' — positionnement
    décision utilisateur : outil d'aide à la décision, pas prédicteur miracle."""
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "Réponse test."}}]
    }
    with patch("bot.chat.requests.post", return_value=fake_response) as mock_post:
        from bot.chat import chat
        chat("Je vais gagner mon pari sur Sinner ?", [], _fake_mem(), "http://fake:1234/v1/chat/completions")
    system_msg = mock_post.call_args[1]["json"]["messages"][0]["content"]
    assert "not a betting system with a proven edge" in system_msg
    assert "never promise a win" in system_msg


def test_chat_injects_player_context():
    """Le joueur mentionné (nom de famille seul) est injecté dans le system prompt."""
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "Réponse test."}}]
    }
    with patch("bot.chat.requests.post", return_value=fake_response) as mock_post:
        from bot.chat import chat
        chat("Analyse sinner en détail", [], _fake_mem(), "http://fake:1234/v1/chat/completions")
    system_msg = mock_post.call_args[1]["json"]["messages"][0]["content"]
    # Le joueur détecté par nom de famille doit apparaître dans le prompt
    assert "Jannik Sinner" in system_msg
    assert "ELO=2112" in system_msg

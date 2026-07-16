"""Tests unitaires pour bot/chat.py (sans LM Studio réel)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from bot.chat import (
    _detect_players, _player_snapshot, build_context, _surface_elo_line, _calibrated,
    _detect_value_query, _format_value_picks, build_match_context, strip_agent_prefix,
)


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


def test_chat_default_uses_module_constants():
    """Sans override, chat() envoie MAX_TOKENS/TEMPERATURE d'origine (mode=chat)."""
    from bot import chat as chat_mod
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    with patch("bot.chat.requests.post", return_value=fake_response) as mock_post:
        chat_mod.chat("Question", [], _fake_mem(), "http://fake:1234/v1/chat/completions")
    body = mock_post.call_args[1]["json"]
    assert body["max_tokens"] == chat_mod.MAX_TOKENS
    assert body["temperature"] == chat_mod.TEMPERATURE


def test_chat_analyst_mode_overrides_max_tokens_and_temperature():
    """max_tokens/temperature explicites (mode=analyst côté api.py) doivent
    remplacer les constantes par défaut, sans toucher au comportement mode=chat."""
    from bot import chat as chat_mod
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "réponse détaillée"}}]}
    with patch("bot.chat.requests.post", return_value=fake_response) as mock_post:
        chat_mod.chat(
            "Quel est notre ROI ?", [], _fake_mem(), "http://fake:1234/v1/chat/completions",
            max_tokens=chat_mod.ANALYST_MAX_TOKENS, temperature=chat_mod.ANALYST_TEMPERATURE,
        )
    body = mock_post.call_args[1]["json"]
    assert body["max_tokens"] == chat_mod.ANALYST_MAX_TOKENS
    assert body["temperature"] == chat_mod.ANALYST_TEMPERATURE
    # Le prompt système doit refléter le mode détaillé, pas "3 phrases max".
    system_msg = body["messages"][0]["content"]
    assert "3 phrases max" not in system_msg


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


def test_calibrated_prefers_platt_when_fitted():
    """Avant ce fix, le chat n'utilisait QUE la température k, jamais Platt —
    incohérent avec /api/value et /api/live qui préfèrent Platt dès qu'il est
    fitté. _calibrated doit désormais donner le même résultat que Platt seul
    quand (a,b) != (1.0, 0.0), peu importe k."""
    from bot import calibrate
    p = 0.8
    platt_ab = (0.5, 0.1)
    expected = calibrate.calibrated_prob_platt(p, *platt_ab)
    result = _calibrated(p, k=2.5, platt_ab=platt_ab)  # k très différent, doit être ignoré
    assert abs(result - expected) < 1e-9


def test_calibrated_falls_back_to_temperature_when_platt_not_fitted():
    from bot import calibrate
    p = 0.8
    expected = calibrate.calibrated_prob(p, 0.6)
    result = _calibrated(p, k=0.6, platt_ab=(1.0, 0.0))
    assert abs(result - expected) < 1e-9


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


def test_detect_value_query_true_on_keyword():
    assert _detect_value_query("Quels sont les meilleurs value bets du moment ?")
    assert _detect_value_query("any good bets tonight?")


def test_detect_value_query_false_without_keyword():
    assert not _detect_value_query("Quel est le meilleur tournoi sur terre battue ?")


def test_format_value_picks_empty_says_so_explicitly():
    """Vide != absence de contexte : le LLM doit savoir qu'il n'y a rien
    plutôt que recevoir un extra_context vide qui le laisserait halluciner."""
    msg = _format_value_picks([])
    assert "aucun" in msg.lower() or "Aucun" in msg


def test_format_value_picks_lists_real_rows_sorted_by_ev():
    rows = [
        {"date": "2026-07-17", "player1": "A", "player2": "B", "side": "B", "odds": 2.1, "ev": 5.0},
        {"date": "2026-07-17", "player1": "C", "player2": "D", "side": "C", "odds": 1.8, "ev": 9.5},
    ]
    msg = _format_value_picks(rows)
    # Le meilleur EV (9.5) doit apparaître avant l'autre (5.0)
    assert msg.index("C vs D") < msg.index("A vs B")
    assert "+9.5%" in msg


def test_build_match_context_grounds_generic_value_query_on_real_picks(monkeypatch):
    """Reproduit le bug constaté sur émulateur : « meilleurs value bets du
    moment » (aucun nom de joueur cité) ne doit PAS renvoyer un contexte vide
    (qui laisserait le LLM inventer Sinner/Alcaraz) — doit injecter les vrais
    picks ouverts du scanner."""
    from bot import db
    fake_rows = [
        {"date": "2026-07-17", "player1": "Mateus Alves", "player2": "Fons Van Sambeek",
         "side": "Fons Van Sambeek", "odds": 4.5, "ev": 16.2},
    ]
    monkeypatch.setattr(db, "list_value_picks_open", lambda: fake_rows)
    ctx = build_match_context("Quels sont les meilleurs value bets du moment ?", _fake_mem())
    assert "Mateus Alves" in ctx
    assert "Fons Van Sambeek" in ctx
    assert "Sinner" not in ctx


def test_build_match_context_forces_value_picks_for_odds_agent(monkeypatch):
    """@odds_agent doit forcer le grounding réel même sans mot-clé value/edge/etc."""
    from bot import db
    monkeypatch.setattr(db, "list_value_picks_open", lambda: [])
    ctx = build_match_context("des idées pour ce soir ?", _fake_mem(), agent="odds_agent")
    assert "aucun" in ctx.lower()


def test_build_match_context_empty_for_unrelated_question_without_players():
    """Une question sans joueur ET sans lien value bets reste sans contexte
    (comportement historique préservé — pas de régression)."""
    ctx = build_match_context("Quel est le meilleur tournoi sur terre ?", _fake_mem())
    assert ctx == ""


def test_strip_agent_prefix_known_agent():
    agent, msg = strip_agent_prefix("@odds_agent meilleurs value bets du moment")
    assert agent == "odds_agent"
    assert msg == "meilleurs value bets du moment"


def test_strip_agent_prefix_unknown_agent_ignored():
    agent, msg = strip_agent_prefix("@random_thing hello")
    assert agent is None
    assert msg == "@random_thing hello"


def test_strip_agent_prefix_no_prefix():
    agent, msg = strip_agent_prefix("juste une question normale")
    assert agent is None
    assert msg == "juste une question normale"


def test_chat_system_prompt_has_no_fabrication_clause():
    """Clause anti-hallucination toujours présente (constaté sur émulateur :
    le LLM inventait des matchs/cotes plausibles mais faux sans elle)."""
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "Réponse test."}}]}
    with patch("bot.chat.requests.post", return_value=fake_response) as mock_post:
        from bot.chat import chat
        chat("Meilleurs value bets ?", [], _fake_mem(), "http://fake:1234/v1/chat/completions")
    system_msg = mock_post.call_args[1]["json"]["messages"][0]["content"]
    assert "Never invent specific matches" in system_msg


def test_chat_injects_agent_prompt():
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "Réponse test."}}]}
    with patch("bot.chat.requests.post", return_value=fake_response) as mock_post:
        from bot.chat import chat
        chat("meilleurs value bets", [], _fake_mem(), "http://fake:1234/v1/chat/completions",
             agent_prompt="You are the TennisBoss Odds Agent.")
    system_msg = mock_post.call_args[1]["json"]["messages"][0]["content"]
    assert system_msg.startswith("You are the TennisBoss Odds Agent.")


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

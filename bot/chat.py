"""Chat IA local via LM Studio (API OpenAI-compatible).

LM Studio doit tourner sur Windows avec un modèle chargé (ex: Llama 3.2 3B,
Mistral 7B Q4) et le serveur local activé (port 1234 par défaut).

Depuis WSL2 en mode réseau miroir, `localhost:1234` pointe sur Windows.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import requests

from .log import log

DEFAULT_LM_URL = "http://localhost:11434/v1/chat/completions"
DEFAULT_MODEL = "qwen3:4b"     # Ollama sur port 11434 (2.5GB, think:false)
HISTORY_WINDOW = 8              # nb de messages conservés dans le contexte glissant
MAX_TOKENS = 600
TEMPERATURE = 0.7

# Endpoint génération native Ollama (contourne le bug de timeout du chat template qwen3)
_OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"


# ---------------------------------------------------------------------------
# Construction du contexte TennisBoss
# ---------------------------------------------------------------------------

def _top_elo(elo: Dict[str, float], n: int = 10) -> List[tuple]:
    return sorted(elo.items(), key=lambda x: x[1], reverse=True)[:n]


def _player_snapshot(mem: Dict[str, Any], name: str) -> Optional[str]:
    """Retourne une ligne de stats pour un joueur (si connu)."""
    prof = (mem.get("players") or {}).get(name)
    if not prof:
        return None
    elo_val = (mem.get("elo") or {}).get(name, 1500)
    return (
        f"{name}: serve={prof.get('serve', 0):.2f} "
        f"ret={prof.get('return1', 0):.2f}/{prof.get('return2', 0):.2f} "
        f"forme={prof.get('recent', 0):.2f} ELO={elo_val:.0f} "
        f"(n={prof.get('n', 0)} matchs)"
    )


def _detect_players(message: str, players_lower: Dict[str, str]) -> List[str]:
    """Détecte les noms de joueurs mentionnés (nom complet ou nom de famille seul)."""
    found = []
    msg_lower = message.lower()
    # Index lastname → original pour le matching partiel
    lastname_map: Dict[str, str] = {}
    for key, original in players_lower.items():
        parts = key.split()
        if parts:
            lastname_map.setdefault(parts[-1], original)

    for key, original in players_lower.items():
        if original in found:
            continue
        if key in msg_lower:          # nom complet
            found.append(original)
        else:                          # nom de famille seul (ex: "sinner" → "Jannik Sinner")
            parts = key.split()
            if parts and parts[-1] in msg_lower and original not in found:
                found.append(original)
        if len(found) >= 4:
            break
    return found


def build_context(mem: Dict[str, Any]) -> str:
    """Contexte statique TennisBoss pour le system prompt."""
    lines = []
    n_players = len(mem.get("players") or {})
    metrics = mem.get("metrics") or {}
    lines.append(f"Base : {n_players} joueurs (ATP + WTA), 2022-2026")
    acc = metrics.get("accuracy")
    if acc:
        lines.append(f"Précision modèle (1er set) : {acc:.1%} OOS")

    elo = mem.get("elo") or {}
    if elo:
        top = _top_elo(elo, 12)
        lines.append("\nTop ELO global :")
        for name, rating in top:
            lines.append(f"  {name}: {rating:.0f}")

    surf = mem.get("elo_surface") or {}
    for surface in ("clay", "hard", "grass"):
        if surface in surf and surf[surface]:
            top_s = _top_elo(surf[surface], 5)
            lines.append(f"\nTop ELO {surface} :")
            for name, rating in top_s:
                lines.append(f"  {name}: {rating:.0f}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def chat(
    message: str,
    history: List[Dict[str, str]],
    mem: Dict[str, Any],
    lm_url: str = DEFAULT_LM_URL,
    model: str = DEFAULT_MODEL,
) -> str:
    """Envoie un message au LLM local avec contexte TennisBoss enrichi dynamiquement.

    Détecte les joueurs cités dans le message et injecte leurs stats en temps réel.
    """
    context = build_context(mem)

    # Détection dynamique des joueurs mentionnés
    players_lower = {n.lower(): n for n in (mem.get("players") or {})}
    mentioned = _detect_players(message, players_lower)
    player_context = ""
    if mentioned:
        snapshots = [s for n in mentioned if (s := _player_snapshot(mem, n))]
        if snapshots:
            player_context = "\nJoueurs mentionnés dans la question :\n" + "\n".join(snapshots)

    system = f"""Tu es TennisBoss AI, expert en analyse tennis et prédictions de matchs.
Tu analyses les données réelles du modèle TennisBoss (régression logistique + ELO avec dominance surface).

DONNÉES EN TEMPS RÉEL :
{context}{player_context}

RÔLE :
- Analyser forces/faiblesses (serve, retour, forme récente, ELO surface)
- Comparer des joueurs, expliquer qui est favori et pourquoi
- Décrypter la logique ELO (une grosse victoire 6-1 6-2 = plus de points qu'un 7-6 7-6)
- Signaler les valeurs quand notre proba dépasse le marché
- Identifier les spécialistes de surface

Réponds en français, directement et sans intro superflue. Max 3 paragraphes courts."""

    messages = [{"role": "system", "content": system}]
    for h in (history or [])[-HISTORY_WINDOW:]:
        messages.append(h)
    messages.append({"role": "user", "content": message})

    # Détecte si on est sur Ollama natif (qwen3 et autres thinking models
    # ont un bug de timeout sur /v1/chat/completions — on utilise /api/generate).
    is_ollama = "11434" in lm_url or "ollama" in lm_url.lower()
    if is_ollama:
        return _chat_via_generate(model, messages)
    return _chat_via_openai(lm_url, model, messages)


def _chat_via_openai(lm_url: str, model: str, messages: list) -> str:
    """Endpoint OpenAI-compatible (/v1/chat/completions) — LM Studio / OpenAI."""
    try:
        resp = requests.post(
            lm_url,
            json={
                "model": model,
                "messages": messages,
                "temperature": TEMPERATURE,
                "max_tokens": MAX_TOKENS,
                "stream": False,
            },
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.RequestException as exc:
        log(f"LM Studio inaccessible ({lm_url}): {exc}", "WARN")
        raise
    except (KeyError, IndexError) as exc:
        log(f"Réponse LM Studio inattendue : {exc}", "WARN")
        raise RuntimeError(f"Réponse invalide du LLM : {exc}") from exc


def _build_prompt(messages: list) -> str:
    """Convertit l'historique en prompt texte pour /api/generate."""
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            parts.append(f"[Système]\n{content}")
        elif role == "assistant":
            parts.append(f"[Assistant]\n{content}")
        else:
            parts.append(f"[Utilisateur]\n{content}")
    parts.append("[Assistant]")
    return "\n\n".join(parts)


def _chat_via_generate(model: str, messages: list) -> str:
    """Endpoint natif Ollama (/api/generate) avec think:false.

    Contourne le bug de timeout du chat template pour les modèles de réflexion
    (qwen3, deepseek-r1, etc.).  think:false désactive le raisonnement interne
    pour des réponses rapides (~5-10s vs 60s+).
    """
    prompt = _build_prompt(messages)
    try:
        resp = requests.post(
            _OLLAMA_GENERATE_URL,
            json={
                "model":      model,
                "prompt":     prompt,
                "stream":     False,
                "think":      False,      # désactive <think> pour qwen3
                "keep_alive": "60m",      # garde le modèle en VRAM 60 min
                "options": {
                    "temperature": TEMPERATURE,
                    "num_predict": MAX_TOKENS,
                },
            },
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        # qwen3 sépare thinking et response — on prend uniquement response
        return (data.get("response") or "").strip()
    except requests.RequestException as exc:
        log(f"Ollama /api/generate inaccessible : {exc}", "WARN")
        raise
    except (KeyError, ValueError) as exc:
        log(f"Réponse Ollama inattendue : {exc}", "WARN")
        raise RuntimeError(f"Réponse invalide du LLM : {exc}") from exc

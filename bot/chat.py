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
DEFAULT_MODEL = "qwen2.5:7b"   # qwen3 nécessite mise à jour du service Ollama Windows
HISTORY_WINDOW = 8
MAX_TOKENS = 200
TEMPERATURE = 0.7

# Endpoint chat natif Ollama — plus rapide que /api/generate pour les modèles thinking
_OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"


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


def _tokens(text: str) -> set:
    """Mots du texte (\\w, sépare sur espaces ET traits d'union/ponctuation)."""
    return set(re.findall(r"\w+", text.lower()))


def _detect_players(message: str, players_lower: Dict[str, str]) -> List[str]:
    """Détecte les joueurs mentionnés par MOTS ENTIERS (nom complet ou famille).

    Match par tokens, pas par sous-chaîne : sinon "fiche" matchait le nom de
    famille "He", "sur"/"est" matchaient des noms courts, etc. Les noms de
    famille seuls doivent faire ≥3 lettres par token (évite les faux positifs).
    """
    found: List[str] = []
    msg_tokens = _tokens(message)
    if not msg_tokens:
        return found

    for key, original in players_lower.items():
        if original in found:
            continue
        parts = key.split()
        if not parts:
            continue
        name_tokens = _tokens(key)
        last_tokens = _tokens(parts[-1])
        if name_tokens and name_tokens <= msg_tokens:            # nom complet
            found.append(original)
        elif (last_tokens and last_tokens <= msg_tokens          # nom de famille seul
              and all(len(t) >= 3 for t in last_tokens)):
            found.append(original)
        if len(found) >= 4:
            break
    return found


_FR_WORDS = frozenset(
    "qui va le la les est sont sur avec pour dans au aux du des mais ou donc "
    "ne pas très bien aussi même plus moins quel quelle quels quelles".split()
)
_EN_WORDS = frozenset(
    "who will the is are on with for in at of and but or not very well also "
    "more less what which how when where why should would could can".split()
)

def _detect_lang(text: str) -> str:
    """Retourne 'fr' ou 'en' selon la langue détectée (heuristique rapide)."""
    words = set(text.lower().split())
    score = sum(1 for w in words if w in _EN_WORDS) - sum(1 for w in words if w in _FR_WORDS)
    return "en" if score > 0 else "fr"


def build_context(mem: Dict[str, Any]) -> str:
    """Contexte minimal TennisBoss — optimisé pour LLM local (peu de tokens)."""
    lines = []
    elo = mem.get("elo") or {}
    if elo:
        top = _top_elo(elo, 5)
        lines.append("Top ELO: " + ", ".join(f"{n}={r:.0f}" for n, r in top))
    surf = mem.get("elo_surface") or {}
    for surface in ("clay", "hard", "grass"):
        if surface in surf and surf[surface]:
            top_s = _top_elo(surf[surface], 2)
            lines.append(f"{surface}: " + ", ".join(f"{n}={r:.0f}" for n, r in top_s))
    return " | ".join(lines)


def _calib_k(mem: Dict[str, Any]) -> float:
    """Facteur de calibration appris (mémoire d'abord, sinon DB). Bornes [0.1,3]."""
    try:
        k = mem.get("match_calib_k")
        if k is None:
            from . import db
            k = float(db.get_meta("match_calib_k") or 1.0)
        k = float(k)
        return k if 0.1 <= k <= 3.0 else 1.0
    except Exception:
        return 1.0


def build_match_context(message: str, mem: Dict[str, Any]) -> str:
    """Contexte prédiction/joueur CALIBRÉ pour le chat (sans appel réseau).

    Détecte les joueurs cités et injecte la prédiction match best-of-3 calibrée
    + H2H (2 joueurs) ou la fiche ELO/forme (1 joueur). Sans ça, le LLM du
    téléphone n'a que des stats brutes et invente des probabilités.
    Pas de cotes live ici (1 appel API/message épuiserait le quota).
    """
    try:
        from . import predictor, features, db
        players_lower = {n.lower(): n for n in (mem.get("players") or {})}
        names = _detect_players(message, players_lower)[:2]
    except Exception:
        return ""

    if not names:
        return ""

    k = _calib_k(mem)
    try:
        if len(names) >= 2:
            n1, n2 = names[0], names[1]
            f1 = features.feature_vector(features.get_profile(mem, n1))
            f2 = features.feature_vector(features.get_profile(mem, n2))
            r = predictor.predict(mem, n1, f1, n2, f2)
            pm1 = _calibrated(predictor.set_to_match_prob(r["prob1"] / 100.0), k)
            h2h = db.head_to_head(n1, n2)
            w1 = sum(1 for row in h2h if row["winner"] == n1)
            w2 = sum(1 for row in h2h if row["winner"] == n2)
            elo = mem.get("elo") or {}
            return (
                f"Match {n1} vs {n2}\n"
                f"Proba match (calibrée) : {n1} {pm1*100:.0f}% | {n2} {(1-pm1)*100:.0f}%\n"
                f"Favori : {r['favorite'] or 'très serré'}\n"
                f"H2H : {n1} {w1}-{w2} {n2} ({w1+w2} matchs)\n"
                f"ELO : {n1}={elo.get(n1,1500):.0f} {n2}={elo.get(n2,1500):.0f}"
            )
        n = names[0]
        prof = features.get_profile(mem, n)
        feat = features.feature_vector(prof)
        rec = db.player_record(n)
        elo = (mem.get("elo") or {}).get(n, 1500)
        total = rec["wins"] + rec["losses"]
        wr = rec["wins"] / total * 100 if total else 0.0
        return (
            f"Joueur {n}\n"
            f"ELO : {elo:.0f} | Record : {rec['wins']}V-{rec['losses']}D ({wr:.0f}%)\n"
            f"Serve {feat['serve']:.2f} Retour {feat['return1']:.2f}/{feat['return2']:.2f} "
            f"Forme {feat['recent']:.2f}"
        )
    except Exception as exc:
        log(f"build_match_context: {exc}", "WARN")
        return ""


def _calibrated(p: float, k: float) -> float:
    from . import calibrate
    return calibrate.calibrated_prob(p, k)


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def chat(
    message: str,
    history: List[Dict[str, str]],
    mem: Dict[str, Any],
    lm_url: str = DEFAULT_LM_URL,
    model: str = DEFAULT_MODEL,
    extra_context: str = "",
) -> str:
    """Envoie un message au LLM local avec contexte TennisBoss enrichi dynamiquement.

    extra_context : bloc pré-construit (prédiction, H2H, stats joueur) injecté directement,
    court-circuite la détection automatique de joueurs.
    """
    context = build_context(mem)

    # Détection automatique des joueurs seulement si pas de contexte externe fourni
    player_context = ""
    if not extra_context:
        players_lower = {n.lower(): n for n in (mem.get("players") or {})}
        mentioned = _detect_players(message, players_lower)
        if mentioned:
            snapshots = [s for n in mentioned if (s := _player_snapshot(mem, n))]
            if snapshots:
                player_context = "\nJoueurs mentionnés :\n" + "\n".join(snapshots)

    # Recherche web si la question porte sur des données fraîches (cap 10s)
    from .search import needs_search, web_search
    import threading
    web_context = ""
    if needs_search(message):
        _result: list = []
        def _do_search():
            _result.append(web_search(message))
        t = threading.Thread(target=_do_search, daemon=True)
        t.start()
        t.join(timeout=10)
        snippets = _result[0] if _result else None
        if snippets:
            web_context = f"\nWeb (récent):\n{snippets}"
            log(f"Web search injecté ({len(snippets)} chars)", "INFO")
        elif not _result:
            log("Web search timeout (>10s) — ignoré", "WARN")

    lang = _detect_lang(message)
    reply_instr = "Reply in English, max 3 sentences." if lang == "en" else "Réponds en français, 3 phrases max."
    web_instr = " Use the web results above to answer — do not say you lack real-time data." if web_context else ""
    extra_instr = " Base your answer strictly on the TennisBoss data provided." if extra_context else ""
    extra_block = f"\n\nTennisBoss data:\n{extra_context}" if extra_context else ""
    system = (
        f"TennisBoss AI. Global ELO: {context}{player_context}"
        f"{extra_block}{web_context} {reply_instr}{web_instr}{extra_instr}"
    )

    messages = [{"role": "system", "content": system}]
    for h in (history or [])[-HISTORY_WINDOW:]:
        messages.append(h)
    messages.append({"role": "user", "content": message})

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


_THINKING_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _chat_via_generate(model: str, messages: list) -> str:
    """Endpoint natif Ollama (/api/chat) — applique le chat template du modèle.

    think:false désactive le raisonnement pour qwen3 (Ollama ≥ 0.7).
    Le champ message.thinking est séparé ; message.content est la réponse nette.
    """
    try:
        resp = requests.post(
            _OLLAMA_CHAT_URL,
            json={
                "model":      model,
                "messages":   messages,
                "stream":     False,
                "think":      False,
                "keep_alive": "60m",
                "options": {
                    "temperature": TEMPERATURE,
                    "num_predict": MAX_TOKENS,
                },
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        content = (data.get("message") or {}).get("content") or ""
        # Supprime les balises <think>…</think> résiduelles si le modèle en génère
        content = _THINKING_RE.sub("", content).strip()
        return content
    except requests.RequestException as exc:
        log(f"Ollama /api/chat inaccessible : {exc}", "WARN")
        raise
    except (KeyError, ValueError) as exc:
        log(f"Réponse Ollama inattendue : {exc}", "WARN")
        raise RuntimeError(f"Réponse invalide du LLM : {exc}") from exc

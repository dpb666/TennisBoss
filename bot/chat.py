"""Chat IA — Groq primaire, Gemini/Gemma fallback, Ollama local en dernier.

Groq : llama-3.1-8b-instant, ~0.5s/réponse, 14 400 req/jour (gratuit).
Gemini API : Gemma 4 cloud si Groq est inaccessible.
Fallback final : Ollama local (gemma3:4b).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import requests

from .log import log
from .agent_router import AGENT_PROMPTS

DEFAULT_LM_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.1-8b-instant"
HISTORY_WINDOW = 8
MAX_TOKENS = 120
TEMPERATURE = 0.7

# mode=analyst (docs/AI_ASSISTANT_ARCHITECTURE.md §3.5) : réponses factuelles
# plus longues et moins créatives pour les questions techniques/analytiques
# (ROI, calibration, architecture...) — mode=chat (défaut) garde la brièveté
# mobile-friendly actuelle, comportement strictement inchangé.
ANALYST_MAX_TOKENS = 512
ANALYST_TEMPERATURE = 0.3

_OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
_OLLAMA_FALLBACK_MODEL = "gemma3:4b"
_GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_FALLBACK_MODEL = "gemma-4-31b-it"


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


_AGENT_PREFIX_RE = re.compile(r"^@(\w+)\s*(.*)$", re.DOTALL)


def strip_agent_prefix(message: str) -> tuple:
    """Détecte un préfixe « @agent_name » en tête de message (ex. « @odds_agent
    meilleurs value bets du moment »). Retourne (agent_name_ou_None, message_sans_prefixe).

    Avant ce fix, @odds_agent/@stats_agent/etc. n'étaient JAMAIS parsés nulle
    part (agent_router.py était du code mort, jamais importé) : le préfixe
    partait tel quel dans le message utilisateur et le LLM l'ignorait
    silencieusement — aucune spécialisation, aucun grounding forcé."""
    m = _AGENT_PREFIX_RE.match(message.strip())
    if not m:
        return None, message
    name, rest = m.group(1), m.group(2)
    if name not in AGENT_PROMPTS:
        return None, message
    return name, (rest or message)


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


def _platt_ab(mem: Dict[str, Any]) -> tuple:
    """(a, b) Platt appris (mémoire d'abord, sinon DB). (1.0, 0.0) = non fitté."""
    try:
        from . import db
        a = float(mem.get("platt_a") if mem.get("platt_a") is not None else (db.get_meta("platt_a") or 1.0))
        b = float(mem.get("platt_b") if mem.get("platt_b") is not None else (db.get_meta("platt_b") or 0.0))
        return a, b
    except Exception:
        return 1.0, 0.0


def _surface_elo_line(mem: Dict[str, Any], names: List[str]) -> str:
    """Ligne 'ELO par surface' pour 1-2 joueurs, depuis mem['elo_surface']
    (déjà calculé/maintenu par predictor.elo_logit — juste pas encore
    exposé au chat)."""
    surf_map = mem.get("elo_surface") or {}
    parts = []
    for surface in ("hard", "clay", "grass"):
        ratings = surf_map.get(surface) or {}
        vals = [f"{n}={ratings[n]:.0f}" for n in names if n in ratings]
        if vals:
            parts.append(f"{surface}: " + " ".join(vals))
    return " | ".join(parts)


_VALUE_QUERY_WORDS = frozenset(
    "value edge pari pronostic pronostics cote cotes opportunite "
    "opportunites bet bets betting odds pick picks".split()
    # "paris" (pluriel de pari) volontairement absent : collision avec la
    # ville de Paris trop probable dans une question générale sur le tennis.
)


def _detect_value_query(message: str) -> bool:
    """Heuristique : la question porte sur les value bets en général (pas un
    joueur précis) — ex. « meilleurs value bets du moment », « des paris
    intéressants ce soir ? ». Mots FR/EN sans accent (comparés après normalisation
    basique : accents retirés côté appelant via _tokens qui utilise \\w)."""
    tokens = _tokens(message)
    normalized = {t.replace("é", "e").replace("è", "e") for t in tokens}
    return bool(normalized & _VALUE_QUERY_WORDS)


def _format_value_picks(rows: List[Any], limit: int = 5) -> str:
    """Formate les value picks OUVERTS (déjà identifiés par le scanner/API,
    donc réels — aucun appel réseau ici) pour grounder le LLM. Si la liste est
    vide, le dit explicitement : mieux vaut « aucun pick ouvert actuellement »
    qu'un silence que le LLM comblerait en inventant un match."""
    if not rows:
        return "Aucun value bet ouvert actuellement dans le scanner TennisBoss."
    top = sorted(rows, key=lambda r: r["ev"], reverse=True)[:limit]
    lines = ["Value bets ouverts (réels, détectés par le scanner TennisBoss) :"]
    for r in top:
        lines.append(
            f"- {r['player1']} vs {r['player2']} : pari {r['side']} "
            f"@ {r['odds']} (EV {r['ev']:+.1f}%), {r['date']}"
        )
    return "\n".join(lines)


def build_match_context(message: str, mem: Dict[str, Any], agent: Optional[str] = None) -> str:
    """Contexte prédiction/joueur CALIBRÉ pour le chat (sans appel réseau).

    Détecte les joueurs cités et injecte la prédiction match best-of-3 calibrée
    + H2H (2 joueurs) ou la fiche ELO/forme (1 joueur). Sans ça, le LLM du
    téléphone n'a que des stats brutes et invente des probabilités.
    Pas de cotes live ici (1 appel API/message épuiserait le quota).

    agent="odds_agent" ou question sans nom de joueur mais évoquant les value
    bets ("meilleurs value bets du moment ?") : injecte les VRAIS picks ouverts
    du scanner (db.list_value_picks_open, déjà en mémoire, pas d'appel réseau)
    au lieu de laisser le LLM inventer des matchs/cotes plausibles mais faux —
    constaté sur émulateur avec de vraies données (ex. Sinner/Alcaraz inventés
    alors que les vrais picks du jour étaient des Challenger qualifs)."""
    try:
        from . import predictor, features, db
        players_lower = {n.lower(): n for n in (mem.get("players") or {})}
        names = _detect_players(message, players_lower)[:2]
    except Exception:
        return ""

    if not names:
        if agent == "odds_agent" or _detect_value_query(message):
            try:
                return _format_value_picks(db.list_value_picks_open())
            except Exception as exc:
                log(f"build_match_context (value picks): {exc}", "WARN")
                return ""
        return ""

    k = _calib_k(mem)
    platt_ab = _platt_ab(mem)
    try:
        if len(names) >= 2:
            n1, n2 = names[0], names[1]
            f1 = features.feature_vector(features.get_profile(mem, n1))
            f2 = features.feature_vector(features.get_profile(mem, n2))
            r = predictor.predict(mem, n1, f1, n2, f2)
            pm1 = _calibrated(predictor.set_to_match_prob(r["prob1"] / 100.0), k, platt_ab)
            h2h = db.head_to_head(n1, n2)
            w1 = sum(1 for row in h2h if row["winner"] == n1)
            w2 = sum(1 for row in h2h if row["winner"] == n2)
            elo = mem.get("elo") or {}
            surf = r.get("surface") or "?"
            surf_elo = _surface_elo_line(mem, [n1, n2])
            lines = [
                f"Match {n1} vs {n2}",
                f"Surface : {surf}",
                f"Proba match (calibrée) : {n1} {pm1*100:.0f}% | {n2} {(1-pm1)*100:.0f}%",
                f"Favori : {r['favorite'] or 'très serré'}",
                f"Confiance : {r.get('confidence_label','?')} ({r.get('confidence',0):.0%})",
                f"H2H : {n1} {w1}-{w2} {n2} ({w1+w2} matchs)",
                f"ELO : {n1}={elo.get(n1,1500):.0f} {n2}={elo.get(n2,1500):.0f}",
            ]
            if surf_elo:
                lines.append(f"ELO par surface : {surf_elo}")
            return "\n".join(lines)
        n = names[0]
        prof = features.get_profile(mem, n)
        feat = features.feature_vector(prof)
        rec = db.player_record(n)
        elo = (mem.get("elo") or {}).get(n, 1500)
        total = rec["wins"] + rec["losses"]
        wr = rec["wins"] / total * 100 if total else 0.0
        lines = [
            f"Joueur {n}",
            f"ELO : {elo:.0f} | Record : {rec['wins']}V-{rec['losses']}D ({wr:.0f}%)",
            f"Serve {feat['serve']:.2f} Retour {feat['return1']:.2f}/{feat['return2']:.2f} "
            f"Forme {feat['recent']:.2f}",
        ]
        surf_elo = _surface_elo_line(mem, [n])
        if surf_elo:
            lines.append(f"ELO par surface : {surf_elo}")
        return "\n".join(lines)
    except Exception as exc:
        log(f"build_match_context: {exc}", "WARN")
        return ""


def _calibrated(p: float, k: float, platt_ab: tuple = (1.0, 0.0)) -> float:
    """Platt scaling en priorité (le reste de l'app — /api/value, /api/live —
    l'utilise dès qu'il est fitté), sinon repli sur la température k. Avant ce
    fix, le chat n'utilisait QUE k et ignorait Platt même quand celui-ci est
    actif partout ailleurs : réponses du chat moins bien calibrées que le
    reste de l'app pour la même prédiction."""
    from . import calibrate
    a, b = platt_ab
    if a != 1.0 or b != 0.0:
        return calibrate.calibrated_prob_platt(p, a, b)
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
    agent_prompt: str = "",
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> str:
    """Envoie un message au LLM local avec contexte TennisBoss enrichi dynamiquement.

    extra_context : bloc pré-construit (prédiction, H2H, stats joueur, ou value
    picks réels via build_match_context) injecté directement, court-circuite
    la détection automatique de joueurs.
    agent_prompt : instruction spécialisée d'un agent (voir agent_router.py),
    ex. « You are the TennisBoss Odds Agent... » — préfixée au system prompt.
    max_tokens/temperature : None -> valeurs par défaut (MAX_TOKENS/TEMPERATURE,
    comportement inchangé) ; voir ANALYST_MAX_TOKENS/ANALYST_TEMPERATURE pour
    mode=analyst (branché dans bot/api.py::api_chat()).
    """
    max_tokens = max_tokens if max_tokens is not None else MAX_TOKENS
    temperature = temperature if temperature is not None else TEMPERATURE
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
    is_analyst = max_tokens > MAX_TOKENS
    if is_analyst:
        reply_instr = (
            "Reply in English, in detail, citing the data/sources given above."
            if lang == "en" else
            "Réponds en français, de façon détaillée, en citant les données/sources fournies ci-dessus."
        )
    else:
        reply_instr = "Reply in English, max 3 sentences." if lang == "en" else "Réponds en français, 3 phrases max."
    web_instr = " Use the web results above to answer — do not say you lack real-time data." if web_context else ""
    extra_instr = " Base your answer strictly on the TennisBoss data provided." if extra_context else ""
    extra_block = f"\n\nTennisBoss data:\n{extra_context}" if extra_context else ""
    # Positionnement honnête (décision utilisateur) : jamais de promesse de gain,
    # même si on demande explicitement "je vais gagner ?" / "combien parier ?".
    honesty_instr = (
        " You are a decision-support tool, not a betting system with a proven edge "
        "— never promise a win or guarantee profit, even if asked directly; state "
        "probabilities as estimates, not certainties."
    )
    # Constaté sur émulateur avec de vraies données : sans contrainte explicite,
    # une question générale ("meilleurs value bets du moment ?") sans nom de
    # joueur cité faisait halluciner des matchs connus (Sinner/Alcaraz) avec des
    # cotes inventées, alors que les vrais picks du jour étaient tout autres.
    # Cette clause s'applique TOUJOURS (pas juste quand extra_context est fourni)
    # pour couvrir les cas que la détection de contexte aurait manqués.
    no_fabrication_instr = (
        " Never invent specific matches, player pairings, or odds numbers that "
        "are not explicitly given in the context above — if you lack real "
        "TennisBoss data to answer a specific question, say so plainly instead "
        "of guessing plausible-sounding examples."
    )
    agent_block = f"{agent_prompt} " if agent_prompt else ""
    system = (
        f"{agent_block}TennisBoss AI. Global ELO: {context}{player_context}"
        f"{extra_block}{web_context} {reply_instr}{web_instr}{extra_instr}"
        f"{honesty_instr}{no_fabrication_instr}"
    )

    messages = [{"role": "system", "content": system}]
    for h in (history or [])[-HISTORY_WINDOW:]:
        messages.append(h)
    messages.append({"role": "user", "content": message})

    lm_url_l = lm_url.lower()
    is_groq = "groq.com" in lm_url_l
    is_gemini = "generativelanguage.googleapis.com" in lm_url_l or model.startswith(("gemini-", "gemma-"))
    is_ollama = ("11434" in lm_url_l or "ollama" in lm_url_l) and not is_groq
    if is_ollama:
        return _chat_via_generate(model, messages, max_tokens, temperature)
    if is_gemini:
        return _chat_via_gemini(os.environ.get("GEMINI_MODEL", model), messages, max_tokens, temperature)
    try:
        return _chat_via_openai(lm_url, model, messages, max_tokens, temperature)
    except Exception as exc:
        log(f"LLM primaire KO ({exc}) — fallback Gemini/Gemma", "WARN")
        try:
            gemini_model = os.environ.get("GEMINI_MODEL", _GEMINI_FALLBACK_MODEL)
            return _chat_via_gemini(gemini_model, messages, max_tokens, temperature)
        except Exception as gemini_exc:
            ollama_model = os.environ.get("OLLAMA_FALLBACK_MODEL", _OLLAMA_FALLBACK_MODEL)
            log(
                f"Gemini/Gemma KO ({gemini_exc}) — fallback Ollama local "
                f"({ollama_model})",
                "WARN",
            )
            return _chat_via_generate(ollama_model, messages, max_tokens, temperature)


def answer(
    message: str,
    history: List[Dict[str, str]],
    mem: Dict[str, Any],
    *,
    mode: str = "chat",
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """Point d'entrée unique pour un tour de chat complet : préfixe d'agent,
    contexte joueur (build_match_context), outils IA Phase 1 (si
    TENNISBOSS_AI_TOOLS=1 et aucun contexte joueur détecté), puis appel LLM.

    Utilisé par bot/api.py::api_chat() (HTTP) et
    bot/workers/telegram_worker.py (chat texte libre Telegram) — évite deux
    implémentations divergentes du même tour de conversation (P10, "one
    source of truth per fact"). Ne capture pas les exceptions : à l'appelant
    de décider de la présentation de l'échec (503 JSON côté HTTP, message
    Telegram côté bot).
    """
    from . import config

    agent, clean_message = strip_agent_prefix(message)
    agent_prompt = AGENT_PROMPTS.get(agent, "") if agent else ""
    extra = build_match_context(clean_message, mem, agent=agent)

    # AI Assistant Phase 1 (read-only tools, docs/AI_ASSISTANT_ARCHITECTURE.md
    # §3) : ne s'exécute QUE si aucun joueur n'a été détecté (build_match_context
    # vide) et seulement derrière un flag désactivé par défaut — comportement
    # strictement identique à avant quand TENNISBOSS_AI_TOOLS n'est pas activé.
    tools_called: List[str] = []
    sources: List[str] = []
    if config.AI_TOOLS_ENABLED and not extra:
        try:
            from ai.chat import orchestrator as ai_orchestrator
            tool_context, tools_called, sources = ai_orchestrator.run_tools_for_message(clean_message)
            if tool_context:
                extra = tool_context
        except Exception as exc:  # noqa: BLE001
            log(f"AI tools orchestrator échoué ({exc}) — chat inchangé.", "WARN")

    if mode == "analyst":
        chat_max_tokens = max_tokens if max_tokens is not None else ANALYST_MAX_TOKENS
        chat_temperature = ANALYST_TEMPERATURE
    else:
        chat_max_tokens = max_tokens
        chat_temperature = None

    primary_url = os.environ.get("GROQ_API_URL", config.GROQ_API_URL)
    primary_model = os.environ.get("GROQ_MODEL", config.GROQ_MODEL)
    reply = chat(clean_message, history, mem, primary_url, model=primary_model,
                extra_context=extra, agent_prompt=agent_prompt,
                max_tokens=chat_max_tokens, temperature=chat_temperature)
    return {
        "reply": reply,
        "context_used": bool(extra),
        "agent": agent,
        "mode": mode,
        "tools_called": tools_called,
        "sources": sources,
    }


def _chat_via_openai(lm_url: str, model: str, messages: list,
                     max_tokens: int = MAX_TOKENS, temperature: float = TEMPERATURE) -> str:
    """Endpoint OpenAI-compatible (/v1/chat/completions) — LLM / Groq / OpenAI."""
    api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        resp = requests.post(
            lm_url,
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.RequestException as exc:
        log(f"LLM inaccessible ({lm_url}): {exc}", "WARN")
        raise
    except (KeyError, IndexError) as exc:
        log(f"Réponse LLM inattendue : {exc}", "WARN")
        raise RuntimeError(f"Réponse invalide du LLM : {exc}") from exc


def _chat_via_gemini(model: str, messages: list,
                     max_tokens: int = MAX_TOKENS, temperature: float = TEMPERATURE) -> str:
    """Endpoint Gemini API REST — modèles Gemini et Gemma hébergés par Google."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY absente")

    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        text = str(msg.get("content", ""))
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
            continue
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": text}],
        })

    if system_parts:
        system_text = "\n".join(system_parts)
        if contents and contents[0]["role"] == "user":
            contents[0]["parts"].insert(0, {"text": system_text + "\n\n"})
        else:
            contents.insert(0, {"role": "user", "parts": [{"text": system_text}]})

    generation_config: Dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
    }
    thinking_level = os.environ.get("GEMINI_THINKING_LEVEL", "").strip()
    if thinking_level:
        generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}

    try:
        resp = requests.post(
            _GEMINI_API_URL.format(model=model),
            params={"key": api_key},
            json={
                "contents": contents,
                "generationConfig": generation_config,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts).strip()
    except requests.RequestException as exc:
        log(f"Gemini API inaccessible ({model}): {exc}", "WARN")
        raise
    except (KeyError, IndexError, ValueError) as exc:
        log(f"Réponse Gemini inattendue : {exc}", "WARN")
        raise RuntimeError(f"Réponse invalide de Gemini : {exc}") from exc


def _ollama_chat_url() -> str:
    base = os.environ.get("OLLAMA_FALLBACK_URL", _OLLAMA_CHAT_URL).rstrip("/")
    return base if base.endswith("/api/chat") else f"{base}/api/chat"


_THINKING_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _chat_via_generate(model: str, messages: list,
                       max_tokens: int = MAX_TOKENS, temperature: float = TEMPERATURE) -> str:
    """Endpoint natif Ollama (/api/chat) — applique le chat template du modèle.

    think:false désactive le raisonnement pour qwen3 (Ollama ≥ 0.7).
    Le champ message.thinking est séparé ; message.content est la réponse nette.
    """
    try:
        resp = requests.post(
            _ollama_chat_url(),
            json={
                "model":      model,
                "messages":   messages,
                "stream":     False,
                "think":      False,
                "keep_alive": "60m",
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
            timeout=300,
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

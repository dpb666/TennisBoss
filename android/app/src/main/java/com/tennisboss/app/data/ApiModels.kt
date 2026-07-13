package com.tennisboss.app.data

/** Modèles JSON renvoyés par l'API REST TennisBoss (run.py serve). */

data class Health(
    val status: String,
    val service: String,
    val version: String,
    val players_loaded: Int,
)

data class Player(
    val name: String,
    val tour: String = "",
    val matches: Int = 0,
    val serve: Double = 0.0,
    val return1: Double = 0.0,
    val return2: Double = 0.0,
    val recent: Double = 0.0,
    val win_prob_vs_avg: Double = 0.0,
    val confident: Boolean = false,
    val followed: Boolean = false,
)

data class PlayersResponse(
    val count: Int,
    val players: List<Player>,
)

/** Bilan victoires / défaites d'un joueur. */
data class Record(
    val wins: Int = 0,
    val losses: Int = 0,
    val total: Int = 0,
    val win_rate: Double = 0.0,
)

/** Un match récent dans la forme du joueur. */
data class FormMatch(
    val date: String = "",
    val tour: String = "",
    val opponent: String = "",
    val result: String = "",   // "W" ou "L"
)

/** Score ELO d'un joueur (signal le plus fort du modèle) + rang dans son tour. */
data class PlayerElo(
    val rating: Double = 0.0,
    val rank: Int? = null,
    val n_ranked: Int? = null,
    val by_surface: Map<String, Double> = emptyMap(),
)

/** Fiche détaillée renvoyée par /api/player (force + bilan + forme). */
data class PlayerDetail(
    val name: String,
    val tour: String = "",
    val matches: Int = 0,
    val serve: Double = 0.0,
    val return1: Double = 0.0,
    val return2: Double = 0.0,
    val recent: Double = 0.0,
    val win_prob_vs_avg: Double = 0.0,
    val confident: Boolean = false,
    val rating: Double = 0.0,
    val win_prob: Double = 0.0,
    val record: Record? = null,
    val form: List<FormMatch> = emptyList(),
    val elo: PlayerElo? = null,
    val followed: Boolean = false,
)

/** Requête pour /api/player/follow et /api/player/unfollow. */
data class FollowPlayerRequest(val name: String)

data class FollowPlayerResponse(
    val name: String = "",
    val followed: Boolean = false,
)

data class FollowedPlayersResponse(
    val count: Int = 0,
    val players: List<Player> = emptyList(),
)

/** Message dans l'historique du chat. */
data class ChatMessage(
    val role: String,    // "user" ou "assistant"
    val content: String,
    val context_used: Boolean = false,   // réponse ancrée dans nos données (pas juste le LLM seul)
)

data class ChatRequest(
    val message: String,
    val history: List<ChatMessage> = emptyList(),
)

data class ChatResponse(
    val reply: String? = null,
    val error: String? = null,
    val context_used: Boolean = false,
)

data class FirstSet(
    val prob1: Double,
    val prob2: Double,
    val favorite: String?,
    val verdict: String,
    val surface: String? = null,
    val confidence: Double = 0.0,
    val confidence_label: String = "",
)

/** Un facteur du modèle et sa contribution exacte à la prédiction. */
data class ExplainFactor(
    val key: String,
    val label: String,
    val value1: Double,
    val value2: Double,
    val weight: Double,
    val contribution: Double,
    val favors: String?,
)

/** Décomposition « pourquoi cette prédiction » renvoyée par l'API. */
data class Explain(
    val bias: Double,
    val logit: Double,
    val factors: List<ExplainFactor>,
    val decisive: String,
    val model_accuracy: Double,
)

/**
 * Un facteur de /api/insight. weight/contribution restent à 0.0 pour le
 * facteur H2H (pas de décomposition de logit pour lui, juste value1/value2) —
 * contrairement à [ExplainFactor] où ils sont toujours renseignés.
 */
data class InsightFactor(
    val key: String = "",
    val label: String = "",
    val value1: Double = 0.0,
    val value2: Double = 0.0,
    val weight: Double = 0.0,
    val contribution: Double = 0.0,
    val favors: String? = null,
)

/** Mouvement de cote capté par le scanner (ouverture -> dernière cote). Null si <2 snapshots. */
data class MarketMovement(
    val event_key: String = "",
    val n_snapshots: Int = 0,
    val opening_odds_home: Double = 0.0,
    val closing_odds_home: Double = 0.0,
    val opening_odds_away: Double = 0.0,
    val closing_odds_away: Double = 0.0,
    val move_home_pct: Double = 0.0,
    val move_away_pct: Double = 0.0,
)

/** Auto-diagnostic du modèle (voir bot/intelligence.py) appliqué aux 2 joueurs du match. */
data class ModelHealth(
    val player1_blacklisted: Boolean = false,
    val player2_blacklisted: Boolean = false,
    val surface_danger: Boolean = false,
    val accuracy_drift_pts: Double = 0.0,
)

/**
 * Bascule de forme (Sport Intelligence Layer Phase 2) : écart entre la forme
 * récente (EMA) d'un joueur et son bilan carrière. Informatif uniquement —
 * n'influence pas la prédiction (voir bot/intelligence_layer.py).
 */
data class FormSignal(
    val player: String = "",
    val direction: String = "",   // "surperformance" | "méforme"
    val recent_form_pct: Double = 0.0,
    val career_baseline_pct: Double = 0.0,
    val diff_pts: Double = 0.0,
)

/** Mouvement de cote anormal (Sport Intelligence Layer Phase 2), informatif. */
data class SteamMove(
    val side: String = "",   // "home" | "away"
    val move_pct: Double = 0.0,
    val n_snapshots: Int = 0,
)

/** Enregistrement du token FCM d'un appareil pour les notifications push. */
data class DeviceRegisterRequest(
    val token: String,
    val platform: String = "android",
)

data class DeviceRegisterResponse(
    val status: String = "",
)

/** Fatigue (Sport Intelligence Layer), informatif. */
data class FatigueSignal(
    val player: String = "",
    val matches_recent: Int = 0,
    val window_days: Int = 14,
)

/** Jours de repos avant le match (Sport Intelligence Layer), informatif. */
data class RestDaySignal(
    val player: String = "",
    val rest_days: Int = 0,
    val flag: String = "",
)

/** Qualité des adversaires (Sport Intelligence Layer), informatif. */
data class OpponentQualitySignal(
    val player: String = "",
    val n_matches: Int = 0,
    val avg_opponent_elo: Double = 0.0,
    val own_elo: Double = 0.0,
    val diff_elo: Double = 0.0,
    val direction: String = "",
)

/** Facteur "clutch" (Sport Intelligence Layer), informatif. */
data class ClutchSignal(
    val player: String = "",
    val n_matches: Int = 0,
    val bp_save_rate: Double? = null,
    val tb_win_rate: Double? = null,
    val direction: String = "",
)

/** Sentiment (Sport Intelligence Layer), informatif. */
data class SentimentSignal(
    val player: String = "",
    val sentiment_score: Double = 0.0,
    val label: String = "",
)

/** Réponse de /api/insight — Sport Intelligence Layer Phase 1+2 : "pourquoi ce pick ?". */
data class InsightResponse(
    val player1: String = "",
    val player2: String = "",
    val confidence: Double = 0.0,
    val confidence_label: String = "",
    val decisive_factor: String? = null,
    val factors: List<InsightFactor> = emptyList(),
    val form_signals: List<FormSignal> = emptyList(),
    val fatigue_signals: List<FatigueSignal> = emptyList(),
    val rest_days_signals: List<RestDaySignal> = emptyList(),
    val opponent_quality_signals: List<OpponentQualitySignal> = emptyList(),
    val clutch_signals: List<ClutchSignal> = emptyList(),
    val sentiment_signals: List<SentimentSignal> = emptyList(),
    val market: MarketMovement? = null,
    val model_health: ModelHealth = ModelHealth(),
)

/** Une confrontation directe passée. */
data class H2HMeeting(
    val date: String = "",
    val tour: String = "",
    val winner: String = "",
)

/** Bilan face-à-face entre deux joueurs. */
data class H2H(
    val player1: String = "",
    val player2: String = "",
    val wins1: Int = 0,
    val wins2: Int = 0,
    val total: Int = 0,
    val leader: String? = null,
    val meetings: List<H2HMeeting> = emptyList(),
)

/** Un marché à deux issues (proba J1 / proba J2), en %. */
data class BetMarket(
    val prob1: Double = 0.0,
    val prob2: Double = 0.0,
)

/** Bet Builder : marchés dérivés de la proba 1er set (best-of-3). */
data class BetBuilder(
    val match: BetMarket = BetMarket(),
    val set2: BetMarket = BetMarket(),
    val third_set_prob: Double = 0.0,
    val correct_score: Map<String, Double> = emptyMap(),
)

data class PredictResponse(
    val player1: Player,
    val player2: Player,
    val first_set: FirstSet,
    val explain: Explain? = null,
    val h2h: H2H? = null,
    val bet_builder: BetBuilder? = null,
    val weather_analysis: WeatherAnalysis? = null,
)

data class Prediction(
    val player1: String,
    val player2: String,
    val prob1: Double,
    val prob2: Double,
    val favorite: String?,
    val surface: String? = null,
    val confidence: Double = 0.0,
    val confidence_label: String = "",
    // Cible 1er set (cote juste = 1/proba ; jouable si >= 1.60)
    val first_set_prob: Double? = null,
    val fair_odds: Double? = null,
    val target_160: Boolean = false,
    // Bet Builder data
    val ml_prob1: Double? = null,
    val ml_prob2: Double? = null,
    val set2_prob1: Double? = null,
    val set2_prob2: Double? = null,
    val total_points_over: Double? = null,
    val total_sets_over: Double? = null,
    val correct_score_probs: Map<String, Double>? = null,
    val total_aces_avg: Double? = null
)

data class Odds(
    val market_match_prob_home: Double,
    val home_odds: Double,
    val away_odds: Double,
    val books: List<String> = emptyList(),
)

data class MatchResult(
    val score: String,
    val winner: String,
    val status: String // "Finished", "Retired", "Live"
)

data class WeatherInfo(
    val temp_c: Double? = null,
    val wind_mph: Double? = null,
    val rain_mm: Double? = null,
    val humidity_pct: Double? = null,
    val conditions: String = "",
)

data class WeatherImpact(
    val beneficiary: String = "neutre",
    val label: String = "",
    val impact_level: String = "faible",
    val net_edge: Double = 0.0,
    val factors: List<WeatherFactor> = emptyList(),
)

data class CrowdInfo(
    val beneficiary: String = "neutre",
    val label: String = "",
    val magnitude: Double = 0.0,
)

data class SurfaceAdvantage(
    val beneficiary: String = "neutre",
    val player: String = "",
    val delta_pct: Double = 0.0,
    val label: String = "",
)

data class HoneypotSignal(
    val flag: Boolean = false,
    val beneficiary: String = "neutre",
    val player: String = "",
    val edge_pct: Double = 0.0,
    val note: String = "",
)

data class PlayerConditionProfile(
    val name: String = "",
    val style_label: String = "",
    val serve_score: Double = 0.5,
    val return_score: Double = 0.5,
    val serve_edge: Double = 0.0,
    val n_matches: Int = 0,
)

data class WeatherFactor(
    val side: String = "",
    val magnitude: Double = 0.0,
    val reason: String = "",
)

data class WeatherAnalysis(
    val player1: PlayerConditionProfile? = null,
    val player2: PlayerConditionProfile? = null,
    val weather_impact: WeatherImpact? = null,
    val crowd: CrowdInfo? = null,
    val surface_advantage: SurfaceAdvantage? = null,
    val honeypot: HoneypotSignal? = null,
    val total_condition_edge: Double = 0.0,
    val summary: String = "",
    val is_indoor: Boolean = false,
)

data class H2HSummary(
    val wins1: Int = 0,
    val wins2: Int = 0,
    val total: Int = 0,
    val last_winner: String? = null,
)

data class BetContext(
    val model_fav: String? = null,
    val model_fav_prob: Double = 0.0,
    val market_fav: String? = null,
    val market_fav_prob: Double = 0.0,
    val agree: Boolean = false,
    val edge_pct: Double = 0.0,
    val tag: String = "",     // "good_bet" | "bad_bet" | "neutral" | "value_underdog"
    val label: String = "",
)

data class UpcomingMatch(
    val player1_raw: String,
    val player2_raw: String,
    val tournament: String,
    val round: String,
    val date: String,
    val time: String,
    val live: Boolean,
    val tour: String,
    val predictable: Boolean,
    val prediction_skip: String? = null,
    val prediction: Prediction? = null,
    val odds: Odds? = null,
    val result: MatchResult? = null,
    val weather: WeatherInfo? = null,
    val source: String = "",
    val bet_context: BetContext? = null,
    val weather_analysis: WeatherAnalysis? = null,
    val h2h: H2HSummary? = null,
    val rank1: Int? = null,
    val rank2: Int? = null,
)

data class UpcomingResponse(
    val count: Int,
    val matches: List<UpcomingMatch>,
)

/** Profil de risque déduit des cotes des picks réellement pris (pas suggérés). */
data class RiskProfile(
    val n_picks: Int = 0,
    val profile: String = "",       // "prudent" | "équilibré" | "agressif" | "insuffisant"
    val avg_odds: Double? = null,
)

/** Match "à venir" scoré par /api/recommendations — sous-ensemble d'UpcomingMatch
 * + le score/les raisons de personnalisation (voir bot/recommendations.py). */
data class RecommendedMatch(
    val date: String = "",
    val time: String = "",
    val tournament: String = "",
    val tour: String = "",
    val prediction: Prediction? = null,
    val recommendation_score: Double = 0.0,
    val recommendation_reasons: List<String> = emptyList(),
)

/** Réponse de /api/recommendations — personnalisation basée sur l'usage du compte actuel. */
data class RecommendationsResponse(
    val favorite_players: List<String> = emptyList(),
    val risk_profile: RiskProfile = RiskProfile(),
    val preferred_surfaces: List<String> = emptyList(),
    val matches: List<RecommendedMatch> = emptyList(),
)

/** Cotes marché (décimales) pour un match. */
data class ValueOdds(
    val home: Double = 0.0,
    val away: Double = 0.0,
    val books: List<String> = emptyList(),
)

/** Comparaison modèle vs marché + EV (espérance de gain) pour un match. */
data class ValueComparison(
    val player1: String = "",
    val player2: String = "",
    val league: String = "",
    val confidence: Double = 0.0,
    val confidence_label: String = "",
    val model_first_set_prob1: Double = 0.0,
    val model_match_prob1: Double = 0.0,
    val model_match_prob2: Double = 0.0,
    val blend_match_prob1: Double = 0.0,
    val blend_match_prob2: Double = 0.0,
    val market_match_prob1: Double = 0.0,
    val market_match_prob2: Double = 0.0,
    val odds: ValueOdds = ValueOdds(),
    val ev1: Double = 0.0,
    val ev2: Double = 0.0,
    val best_side: String? = null,
    val best_ev: Double = 0.0,
    val best_book: String? = null,
    val value: Boolean = false,
    val kelly_u: Double = 0.0,
    val terrain_favorable: Boolean = false,
    val date: String = "",
    val source: String = "",
    val surface: String? = null,
    val filter_reason: String? = null,
    // Sport Intelligence Layer Phase 2 : purement informatif, n'influence pas
    // ev1/ev2/value côté backend (voir bot/intelligence_layer.py).
    val steam_move: SteamMove? = null,
    val honeypot: HoneypotSignal? = null,
)

data class ValueResponse(
    val count: Int = 0,
    val comparisons: List<ValueComparison> = emptyList(),
    val rate_limited: Boolean = false,
    val retry_in_s: Int? = null,
    val message: String = "",
    val note: String = "",
)

data class ValuePickHistory(
    val date: String = "",
    val player1: String = "",
    val player2: String = "",
    val side: String = "",
    val odds: Double = 0.0,
    val ev: Double = 0.0,
    val result: Int? = null,
    val pnl: Double? = null,
    val winner: String? = null,
    val league: String? = null,
    val surface: String? = null,
    val kelly_u: Double? = null,
)

data class ValuePickStats(
    val n: Int = 0,
    val wins: Int = 0,
    val win_rate: Double? = null,
    val roi: Double? = null,
)

data class ValueHistoryResponse(
    val picks: List<ValuePickHistory> = emptyList(),
    val stats: ValuePickStats = ValuePickStats(),
)

// ─── Live matches ────────────────────────────────────────────────────────────

data class LiveSetScore(val h: Int = 0, val a: Int = 0)

data class LiveOdds(
    val home: Double? = null,
    val away: Double? = null,
    val books: List<String> = emptyList(),
)

data class LiveProbPoint(
    val ts: String = "",
    val prob1: Double = 0.0,
    val minute: Int = 0,
    val sets: String = "",
)

data class LivePrediction(
    val player1: String = "",
    val player2: String = "",
    val prob1: Double = 0.0,
    val prob2: Double = 0.0,
    val favorite: String? = null,
    val confidence: Double = 0.0,
    val confidence_label: String = "",
    val prob_history: List<LiveProbPoint> = emptyList(),
)

data class LiveMatch(
    val event_id: Long = 0,
    val player1: String = "",
    val player2: String = "",
    val player1_resolved: String? = null,
    val player2_resolved: String? = null,
    val league: String = "",
    val surface: String? = null,
    val sets_home: Int = 0,
    val sets_away: Int = 0,
    val set_scores: List<LiveSetScore> = emptyList(),
    val game_home: String = "",
    val game_away: String = "",
    val serve: String = "",       // "home" | "away"
    val status_detail: String = "",
    val minute: Int = 0,
    val prediction: LivePrediction? = null,
    val live_odds: LiveOdds? = null,
)

data class LiveResponse(
    val count: Int = 0,
    val matches: List<LiveMatch> = emptyList(),
)

// ─── Inplay best pick ─────────────────────────────────────────────────────────

data class InplayBestPick(
    val event_id: Long = 0,
    val player1: String = "",
    val player2: String = "",
    val player1_resolved: String? = null,
    val player2_resolved: String? = null,
    val league: String = "",
    val sets_home: Int = 0,
    val sets_away: Int = 0,
    val set_scores: List<LiveSetScore> = emptyList(),
    val minute: Int = 0,
    val status_detail: String = "",
    val prediction: LivePrediction? = null,
    val live_odds: LiveOdds? = null,
    val edge_pct: Double? = null,
    val fav_odds: Double? = null,
    val score: Double = 0.0,
)

data class InplayBestResponse(
    val count: Int = 0,
    val best: List<InplayBestPick> = emptyList(),
    val note: String = "",
)

// ─── Inplay markets ───────────────────────────────────────────────────────────

data class InplayMarket(
    val type: String = "",
    val label: String = "",
    val pick: String = "",
    val prob: Double = 0.0,
    val confidence: String = "",
    val rationale: String = "",
    val odds: Double? = null,
    val has_real_odds: Boolean = false,
)

data class InplayMatchMarkets(
    val event_id: Long = 0,
    val player1: String = "",
    val player2: String = "",
    val player1_resolved: String? = null,
    val player2_resolved: String? = null,
    val league: String = "",
    val sets_home: Int = 0,
    val sets_away: Int = 0,
    val score_display: String = "",
    val minute: Int = 0,
    val markets: List<InplayMarket> = emptyList(),
)

data class InplayMarketsResponse(
    val count: Int = 0,
    val matches: List<InplayMatchMarkets> = emptyList(),
)

// ─── Inplay picks & ROI ───────────────────────────────────────────────────────

data class InplayPickRequest(
    val player1: String,
    val player2: String,
    val league: String,
    val market_type: String,
    val market_label: String,
    val pick: String,
    val odds: Double?,
    val odds_home: Double? = null,
    val odds_away: Double? = null,
    val odds_book: String? = null,
    val prob: Double,
    val score: String? = null,
    val sets_home: Int? = null,
    val sets_away: Int? = null,
    val minute: Int? = null,
    val event_id: Long? = null,
    val stake: Double = 10.0,
)

data class InplayPickItem(
    val id: Int = 0,
    val ts: String = "",
    val player1: String = "",
    val player2: String = "",
    val league: String = "",
    val market_type: String = "",
    val market_label: String = "",
    val pick: String = "",
    val odds: Double? = null,
    val odds_home: Double? = null,
    val odds_away: Double? = null,
    val odds_book: String? = null,
    val prob: Double = 0.0,
    val score: String? = null,
    val minute: Int? = null,
    val stake: Double = 10.0,
    val result: String? = null,
    val pnl: Double? = null,
)

data class InplayROIStats(
    val total: Int = 0,
    val settled: Int = 0,
    val wins: Int = 0,
    val losses: Int = 0,
    val pending: Int = 0,
    val staked: Double = 0.0,
    val pnl: Double = 0.0,
    val roi_pct: Double = 0.0,
    val avg_odds: Double = 0.0,
)

data class InplayPicksResponse(
    val stats: InplayROIStats = InplayROIStats(),
    val picks: List<InplayPickItem> = emptyList(),
)

data class InplayPickLogResponse(
    val id: Int = 0,
    val status: String = "",
)

// ─── Historique par date ──────────────────────────────────────────────────────

data class HistoryMatch(
    val date: String = "",
    val tour: String = "",
    val tournament: String = "",
    val player1: String = "",
    val player2: String = "",
    val winner: String = "",
    val score: String = "",
    val pred_favorite: String? = null,
    val correct: Int? = null,          // 1=correct 0=faux null=pas prédit
    val is_doubles: Boolean = false,
)

data class HistoryResponse(
    val date: String = "",
    val count: Int = 0,
    val n_predicted: Int = 0,
    val accuracy_day: Double? = null,
    val matches: List<HistoryMatch> = emptyList(),
)

data class HistoryDatesResponse(
    val dates: List<String> = emptyList(),
)

/** Métriques de performance du modèle sur les matchs réglés. */
data class CalibMetrics(
    val n: Int = 0,
    val accuracy: Double? = null,
    val roi: Double? = null,
    val roi_n: Int = 0,
    val roi_value: Double? = null,
    val roi_value_n: Int = 0,
    val brier: Double? = null,
    val atp_acc: Double? = null,
    val wta_acc: Double? = null,
    val fav_acc: Double? = null,
    val dog_acc: Double? = null,
    val note: String = "",
)

/** Un match réglé récent (prédiction vs résultat). */
data class SettledRecent(
    val date: String = "",
    val tour: String = "",
    val player1: String = "",
    val player2: String = "",
    val winner: String = "",
    val score: String = "",
    val pred_favorite: String? = null,
    val correct: Int? = null,
)

data class CalibrationResponse(
    val metrics: CalibMetrics = CalibMetrics(),
    val calibration_k: Double = 1.0,
    // Platt (a,b) prime sur la température k dès qu'il est fitté (bot/api.py::_calib) —
    // (1.0, 0.0) = non fitté, encore sur k. Jamais modélisé avant ce fix : l'écran
    // Perf montrait "Calibration k" même quand ce n'était plus vraiment k qui
    // calibrait les probas en production.
    val platt_a: Double = 1.0,
    val platt_b: Double = 0.0,
    val elo_blend: Double? = null,
    val market_blend_w: Double? = null,
    val recent: List<SettledRecent> = emptyList(),
)

// --- CLV (Closing Line Value) — preuve d'edge -----------------------------

/** Agrégat CLV (global ou par palier de confiance). `n` non nul = palier vide. */
data class ClvAgg(
    val n: Int? = null,
    val n_picks: Int = 0,
    val n_settled: Int = 0,
    val n_clv: Int = 0,
    val avg_clv_pct: Double? = null,
    val beat_closing_pct: Double? = null,
    val beat_closing_ci95: Double? = null,
    val roi_flat_pct: Double? = null,
    val pnl_kelly_units: Double? = null,
    val win_rate_pct: Double? = null,
)

data class ClvByConfidence(
    val high: ClvAgg = ClvAgg(),
    val medium: ClvAgg = ClvAgg(),
    val low: ClvAgg = ClvAgg(),
)

/** Un pick CLV récent (cote pick vs cote de clôture). */
data class ClvRecent(
    val date: String = "",
    val player1: String = "",
    val player2: String = "",
    val side: String = "",
    val pick_odds: Double? = null,
    val closing_odds: Double? = null,
    val closing_src: String? = null,
    val clv_pct: Double? = null,
    val beat_closing: Int? = null,
    val result: Int? = null,
    val pnl_flat: Double? = null,
    val honeypot: HoneypotSignal? = null,
)

data class ClvResponse(
    val global: ClvAgg = ClvAgg(),
    val scanner: ClvAgg = ClvAgg(),   // stats post-filtre uniquement (signal propre)
    val by_confidence: ClvByConfidence = ClvByConfidence(),
    val verdict: String = "insuffisant",
    val verdict_label: String = "",
    val note: String = "",
    val recent: List<ClvRecent> = emptyList(),
)

/** Zones dangereuses apprises (EV bucket × cotes × surface). */
data class DangerZone(
    val type: String = "",
    val ev_bucket: String = "",
    val odds_bucket: String? = null,
    val surface: String? = null,
    val n: Int = 0,
    val roi: Double = 0.0,
)

/** Thresholds du mistake_learner. */
data class LearnerThresholds(
    val min_n: Int = 7,
    val roi_threshold_pct: Double = -12.0,
)

/** Réponse /api/learner/stats. */
data class LearnerStats(
    val n_zones: Int = 0,
    val zones: List<DangerZone> = emptyList(),
    val thresholds: LearnerThresholds = LearnerThresholds(),
)

/** Réponse /api/intelligence/stats — cerveau autonome. */
data class IntelligenceStats(
    val blacklist: List<String> = emptyList(),
    val surface_danger: List<String> = emptyList(),
    val accuracy_drift_pts: Double = 0.0,
    val last_cycle_ts: Double = 0.0,
    val thresholds: Map<String, Double> = emptyMap(),
)

/** Un near-miss : event EV 2-8%, pas encore un pick mais surveillé. */
data class NearMiss(
    val player1: String = "",
    val player2: String = "",
    val side: String = "",
    val ev: Double = 0.0,
    val odds: Double = 0.0,
    val hours: Double? = null,
    val league: String = "",
)

/** Détail du dernier pick trouvé par le scanner. */
data class LastPick(
    val side: String = "",
    val ev: Double = 0.0,
    val odds: Double = 0.0,
    val hours: Double? = null,
    val league: String = "",
)

/** Réponse /api/scanner/status — état temps réel du scanner. */
data class ScannerStatus(
    val running: Boolean = false,
    val last_cycle_ts: String? = null,
    val next_cycle_ts: String? = null,
    val interval: Int = 90,
    val total_events: Int = 0,
    val checked: Int = 0,
    val cap: Int = 25,
    val active_picks: Int = 0,
    val last_pick_ts: String? = null,
    val last_pick: LastPick? = null,
    val rejections: Map<String, Int> = emptyMap(),
    val near_misses: List<NearMiss> = emptyList(),
)

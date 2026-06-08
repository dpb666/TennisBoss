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
)

data class PlayersResponse(
    val count: Int,
    val players: List<Player>,
)

data class FirstSet(
    val prob1: Double,
    val prob2: Double,
    val favorite: String?,
    val verdict: String,
)

data class PredictResponse(
    val player1: Player,
    val player2: Player,
    val first_set: FirstSet,
)

data class Prediction(
    val player1: String,
    val player2: String,
    val prob1: Double,
    val prob2: Double,
    val favorite: String?,
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
    val prediction: Prediction? = null,
)

data class UpcomingResponse(
    val count: Int,
    val matches: List<UpcomingMatch>,
)

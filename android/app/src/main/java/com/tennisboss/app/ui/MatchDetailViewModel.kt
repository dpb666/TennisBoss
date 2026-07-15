package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.H2H
import com.tennisboss.app.data.InsightResponse
import com.tennisboss.app.data.MatchIntelligence
import com.tennisboss.app.data.PlayerDetail
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

sealed interface MatchDetailUiState {
    object Idle : MatchDetailUiState
    object Loading : MatchDetailUiState
    data class Success(
        val player1: PlayerDetail,
        val player2: PlayerDetail,
        val insight: InsightResponse,
        val intelligence: MatchIntelligence,
        val h2h: H2H?,
    ) : MatchDetailUiState
    data class Error(val message: String) : MatchDetailUiState
}

class MatchDetailViewModel : ViewModel() {
    var uiState by mutableStateOf<MatchDetailUiState>(MatchDetailUiState.Idle)
        private set

    fun loadMatchDetail(p1: String, p2: String, surface: String? = null, eventId: String? = null) {
        uiState = MatchDetailUiState.Loading
        viewModelScope.launch {
            // coroutineScope{} : voir DashboardViewModel.load() pour pourquoi ce
            // n'est pas juste des async{} sur le scope du launch englobant.
            uiState = try {
                coroutineScope {
                    val api = ApiClient.create()
                    val p1Deferred = async { api.player(p1) }
                    val p2Deferred = async { api.player(p2) }
                    val insightDeferred = async { api.insight(p1, p2, surface, eventId) }
                    val intelDeferred = async {
                        try {
                            api.matchIntelligence(p1, p2, surface, eventId, eventId)
                        } catch (_: Exception) {
                            null
                        }
                    }
                    val h2hDeferred = async { try { api.h2h(p1, p2) } catch (e: Exception) { null } }

                    val insight = insightDeferred.await()
                    val intelligence = intelDeferred.await()
                        ?: insight.match_intelligence
                        ?: fallbackIntelligence(insight)

                    MatchDetailUiState.Success(
                        player1 = p1Deferred.await(),
                        player2 = p2Deferred.await(),
                        insight = insight,
                        intelligence = intelligence,
                        h2h = h2hDeferred.await(),
                    )
                }
            } catch (e: Exception) {
                MatchDetailUiState.Error(e.message ?: "Erreur inconnue")
            }
        }
    }

    /** Repli si /api/match/intelligence et match_intelligence imbriqué sont absents. */
    private fun lastName(name: String): String = name.split(" ").last()

    private fun fallbackIntelligence(insight: InsightResponse): MatchIntelligence {
        val recommendation = when {
            insight.confidence >= 0.80 -> "WATCH"
            else -> "NO_BET"
        }
        val why = buildList {
            insight.factors.take(3).forEach { f ->
                f.favors?.let { add("${f.label} en faveur de ${lastName(it)}") }
            }
            if (isEmpty() && insight.confidence_label.isNotBlank()) {
                add("Confiance modèle : ${insight.confidence_label}")
            }
        }
        val risks = buildList {
            if (insight.model_health.player1_blacklisted) {
                add("${lastName(insight.player1)} sur-listé par l'intelligence autonome")
            }
            if (insight.model_health.player2_blacklisted) {
                add("${lastName(insight.player2)} sur-listé par l'intelligence autonome")
            }
            if (insight.model_health.surface_danger) {
                add("Surface historiquement défavorable au modèle")
            }
        }
        val favorite = insight.factors
            .filter { it.favors != null }
            .maxByOrNull { kotlin.math.abs(it.contribution) }
            ?.favors
            ?: insight.player1
        return MatchIntelligence(
            tis = insight.confidence * 100.0,
            recommendation = recommendation,
            favorite = favorite,
            confidence = insight.confidence,
            confidence_label = insight.confidence_label,
            why = why,
            risks = risks,
            player1 = insight.player1,
            player2 = insight.player2,
        )
    }
}

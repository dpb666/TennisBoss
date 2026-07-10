package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.InplayBestPick
import com.tennisboss.app.data.InplayMarketsResponse
import com.tennisboss.app.data.InplayPickItem
import com.tennisboss.app.data.InplayPickRequest
import com.tennisboss.app.data.InplayPicksResponse
import com.tennisboss.app.data.InplayROIStats
import com.tennisboss.app.data.LiveResponse
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

sealed interface LiveUiState {
    data object Idle : LiveUiState
    data object Loading : LiveUiState
    data class Success(
        val data: LiveResponse,
        val bestPick: InplayBestPick?,
        val markets: InplayMarketsResponse? = null,
        val picksResp: InplayPicksResponse? = null,
        val refreshIn: Int = 30,
        val swungEventIds: Set<Long> = emptySet(),
    ) : LiveUiState
    data class Error(val message: String) : LiveUiState
}

class LiveViewModel : ViewModel() {

    var state by mutableStateOf<LiveUiState>(LiveUiState.Idle)
        private set

    // Dialog state pour "Prendre ce pick"
    var pickDialog by mutableStateOf<PickDialogState?>(null)
        private set

    var pickToastMessage by mutableStateOf<String?>(null)
        private set

    private var autoRefreshJob: kotlinx.coroutines.Job? = null

    fun startAutoRefresh() {
        if (autoRefreshJob?.isActive == true) return
        autoRefreshJob = viewModelScope.launch {
            while (isActive) {
                load()
                var countdown = 30
                while (isActive && countdown > 0) {
                    delay(1000)
                    countdown--
                    val current = state
                    if (current is LiveUiState.Success) {
                        state = current.copy(refreshIn = countdown)
                    }
                }
            }
        }
    }

    fun stopAutoRefresh() {
        autoRefreshJob?.cancel()
        autoRefreshJob = null
    }

    fun loadOnce() {
        viewModelScope.launch { load() }
    }

    private suspend fun load() {
        if (state !is LiveUiState.Success) state = LiveUiState.Loading
        try {
            val api = ApiClient.create()
            val liveDeferred = viewModelScope.async { api.live() }
            val bestDeferred = viewModelScope.async {
                try { api.inplayBest() } catch (e: Exception) { null }
            }
            val marketsDeferred = viewModelScope.async {
                try { api.inplayMarkets() } catch (e: Exception) { null }
            }
            val picksDeferred = viewModelScope.async {
                try { api.inplayPicks() } catch (e: Exception) { null }
            }
            val liveResp = liveDeferred.await()
            val bestResp = bestDeferred.await()
            val marketsResp = marketsDeferred.await()
            val picksResp = picksDeferred.await()
            val bestPick = bestResp?.best?.firstOrNull()

            // Bascule de favori détectée sur le refresh in-app (30s, plus fin
            // que le worker en tâche de fond limité à 15min par WorkManager).
            val prevFavorites = (state as? LiveUiState.Success)?.data?.matches
                ?.associate { it.event_id to it.prediction?.favorite }
                ?: emptyMap()
            val swung = liveResp.matches
                .filter { m ->
                    val prevFav = prevFavorites[m.event_id]
                    val newFav = m.prediction?.favorite
                    prevFav != null && newFav != null && prevFav != newFav
                }
                .map { it.event_id }
                .toSet()

            state = LiveUiState.Success(liveResp, bestPick, marketsResp, picksResp, refreshIn = 30, swungEventIds = swung)
        } catch (e: Exception) {
            if (state !is LiveUiState.Success) {
                state = LiveUiState.Error(e.message ?: "Erreur réseau")
            }
        }
    }

    // ── Pick dialog ──────────────────────────────────────────────────────────

    fun openPickDialog(
        player1: String, player2: String, league: String,
        marketType: String, marketLabel: String,
        pick: String, odds: Double?, prob: Double,
        oddsHome: Double? = null, oddsAway: Double? = null, oddsBook: String? = null,
        score: String? = null, setsHome: Int? = null, setsAway: Int? = null,
        minute: Int? = null, eventId: Long? = null,
        player1Resolved: String? = null, player2Resolved: String? = null,
    ) {
        pickDialog = PickDialogState(
            player1 = player1, player2 = player2, league = league,
            marketType = marketType, marketLabel = marketLabel,
            pick = pick, odds = odds, prob = prob, stake = 10.0,
            oddsHome = oddsHome, oddsAway = oddsAway, oddsBook = oddsBook,
            score = score, setsHome = setsHome, setsAway = setsAway,
            minute = minute, eventId = eventId,
            player1Resolved = player1Resolved, player2Resolved = player2Resolved,
        )
    }

    fun dismissPickDialog() {
        pickDialog = null
    }

    fun confirmPick(stake: Double) {
        val d = pickDialog ?: return
        pickDialog = null
        viewModelScope.launch {
            try {
                val api = ApiClient.create()
                val resp = api.logInplayPick(InplayPickRequest(
                    player1 = d.player1, player2 = d.player2, league = d.league,
                    market_type = d.marketType, market_label = d.marketLabel,
                    pick = d.pick, odds = d.odds, prob = d.prob, stake = stake,
                    odds_home = d.oddsHome, odds_away = d.oddsAway, odds_book = d.oddsBook,
                    score = d.score, sets_home = d.setsHome, sets_away = d.setsAway,
                    minute = d.minute, event_id = d.eventId,
                ))
                pickToastMessage = "✅ Pick #${resp.id} enregistré"
                val fresh = try { api.inplayPicks() } catch (e: Exception) { null }
                val current = state
                if (current is LiveUiState.Success && fresh != null) {
                    state = current.copy(picksResp = fresh)
                }
            } catch (e: Exception) {
                pickToastMessage = "❌ Erreur : ${e.message}"
            }
        }
    }

    fun settlePick(pickId: Int, result: String) {
        viewModelScope.launch {
            try {
                val api = ApiClient.create()
                api.settleInplayPick(pickId, mapOf("result" to result))
                pickToastMessage = "Pick #$pickId → $result"
                val fresh = try { api.inplayPicks() } catch (e: Exception) { null }
                val current = state
                if (current is LiveUiState.Success && fresh != null) {
                    state = current.copy(picksResp = fresh)
                }
            } catch (e: Exception) {
                pickToastMessage = "❌ Erreur : ${e.message}"
            }
        }
    }

    fun deletePick(pickId: Int) {
        viewModelScope.launch {
            try {
                val api = ApiClient.create()
                api.deleteInplayPick(pickId)
                pickToastMessage = "🗑 Pick #$pickId supprimé"
                val fresh = try { api.inplayPicks() } catch (e: Exception) { null }
                val current = state
                if (current is LiveUiState.Success && fresh != null) {
                    state = current.copy(picksResp = fresh)
                }
            } catch (e: Exception) {
                pickToastMessage = "❌ Erreur : ${e.message}"
            }
        }
    }

    fun clearToast() {
        pickToastMessage = null
    }
}

data class PickDialogState(
    val player1: String,
    val player2: String,
    val league: String,
    val marketType: String,
    val marketLabel: String,
    val pick: String,
    val odds: Double?,
    val prob: Double,
    val stake: Double,
    val oddsHome: Double? = null,
    val oddsAway: Double? = null,
    val oddsBook: String? = null,
    val score: String? = null,
    val setsHome: Int? = null,
    val setsAway: Int? = null,
    val minute: Int? = null,
    val eventId: Long? = null,
    val player1Resolved: String? = null,
    val player2Resolved: String? = null,
)

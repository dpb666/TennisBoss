package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.H2H
import com.tennisboss.app.data.InsightResponse
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
        val h2h: H2H?
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
                    val h2hDeferred = async { try { api.h2h(p1, p2) } catch (e: Exception) { null } }

                    MatchDetailUiState.Success(
                        player1 = p1Deferred.await(),
                        player2 = p2Deferred.await(),
                        insight = insightDeferred.await(),
                        h2h = h2hDeferred.await()
                    )
                }
            } catch (e: Exception) {
                MatchDetailUiState.Error(e.message ?: "Erreur inconnue")
            }
        }
    }
}

package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ClvResponse
import com.tennisboss.app.data.IntelligenceStats
import com.tennisboss.app.data.LearnerStats
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

data class EdgeData(
    val clv: ClvResponse,
    val intelligence: IntelligenceStats,
    val learner: LearnerStats,
)

sealed interface EdgeUiState {
    data object Idle : EdgeUiState
    data object Loading : EdgeUiState
    data class Success(val data: EdgeData) : EdgeUiState
    data class Error(val message: String) : EdgeUiState
}

/** Charge le dashboard Edge : CLV + Intelligence autonome + Zones dangereuses. */
class EdgeViewModel : ViewModel() {

    // Overridable en test pour piloter le dispatcher IO avec le TestDispatcher,
    // comme UpcomingViewModel.io / ValueViewModel.io.
    internal var io: CoroutineDispatcher = Dispatchers.IO

    var state by mutableStateOf<EdgeUiState>(EdgeUiState.Idle)
        private set

    fun load() {
        state = EdgeUiState.Loading
        viewModelScope.launch {
            state = try {
                // coroutineScope{} (pas juste le launch englobant) : si clvD échoue,
                // il faut que l'exception soit levée DANS ce bloc pour être interceptée
                // par le catch ci-dessous. Avec des async{} lancés directement sous
                // viewModelScope, l'échec annule les autres enfants avant que ce catch
                // ne puisse s'exécuter (même bug que Dashboard/MatchDetailViewModel,
                // déjà corrigé ailleurs cette session — voir ARCHITECTURE_REVIEW.md).
                coroutineScope {
                    val api = ApiClient.create()
                    val clvD = async(io) { api.clv() }
                    val intelD = async(io) {
                        try { api.intelligenceStats() } catch (_: Exception) { IntelligenceStats() }
                    }
                    val learnerD = async(io) {
                        try { api.learnerStats() } catch (_: Exception) { LearnerStats() }
                    }
                    EdgeUiState.Success(EdgeData(clvD.await(), intelD.await(), learnerD.await()))
                }
            } catch (e: Exception) {
                EdgeUiState.Error("Connexion impossible : ${e.message}")
            }
        }
    }
}

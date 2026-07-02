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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

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

    var state by mutableStateOf<EdgeUiState>(EdgeUiState.Idle)
        private set

    fun load() {
        state = EdgeUiState.Loading
        viewModelScope.launch {
            state = try {
                val api = ApiClient.create()
                val clvD = async(Dispatchers.IO) { api.clv() }
                val intelD = async(Dispatchers.IO) {
                    try { api.intelligenceStats() } catch (_: Exception) { IntelligenceStats() }
                }
                val learnerD = async(Dispatchers.IO) {
                    try { api.learnerStats() } catch (_: Exception) { LearnerStats() }
                }
                EdgeUiState.Success(EdgeData(clvD.await(), intelD.await(), learnerD.await()))
            } catch (e: Exception) {
                EdgeUiState.Error("Connexion impossible : ${e.message}")
            }
        }
    }
}

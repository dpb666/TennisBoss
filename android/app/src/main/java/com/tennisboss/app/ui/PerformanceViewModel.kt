package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.CalibrationResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

sealed interface PerformanceUiState {
    data object Idle : PerformanceUiState
    data object Loading : PerformanceUiState
    data class Success(val data: CalibrationResponse) : PerformanceUiState
    data class Error(val message: String) : PerformanceUiState
}

/** Charge les métriques de performance/calibration du modèle (/api/calibration). */
class PerformanceViewModel : ViewModel() {

    var state by mutableStateOf<PerformanceUiState>(PerformanceUiState.Idle)
        private set

    fun load() {
        state = PerformanceUiState.Loading
        viewModelScope.launch {
            state = try {
                val resp = withContext(Dispatchers.IO) {
                    ApiClient.create().calibration()
                }
                PerformanceUiState.Success(resp)
            } catch (e: Exception) {
                PerformanceUiState.Error("Connexion impossible : ${e.message}")
            }
        }
    }
}

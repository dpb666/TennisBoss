package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.CalibrationResponse
import com.tennisboss.app.data.UpcomingResponse
import com.tennisboss.app.data.ValueResponse
import kotlinx.coroutines.async
import kotlinx.coroutines.launch

sealed interface DashboardUiState {
    object Loading : DashboardUiState
    data class Success(
        val upcoming: UpcomingResponse,
        val value: ValueResponse,
        val calibration: CalibrationResponse
    ) : DashboardUiState
    data class Error(val message: String) : DashboardUiState
}

class DashboardViewModel : ViewModel() {
    var state by mutableStateOf<DashboardUiState>(DashboardUiState.Loading)
        private set

    init {
        load()
    }

    fun load() {
        state = DashboardUiState.Loading
        viewModelScope.launch {
            try {
                val api = ApiClient.create()
                val upcomingDeferred = async { api.upcoming(days = 1, limit = 5) }
                val valueDeferred = async { api.value(limit = 5) }
                val calibrationDeferred = async { api.calibration() }

                state = DashboardUiState.Success(
                    upcoming = upcomingDeferred.await(),
                    value = valueDeferred.await(),
                    calibration = calibrationDeferred.await()
                )
            } catch (e: Exception) {
                state = DashboardUiState.Error(e.message ?: "Erreur de chargement")
            }
        }
    }
}

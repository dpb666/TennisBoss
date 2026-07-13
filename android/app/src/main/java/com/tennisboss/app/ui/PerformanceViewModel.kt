package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.CalibrationResponse
import com.tennisboss.app.data.HistoryResponse
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

sealed interface PerformanceUiState {
    data object Idle : PerformanceUiState
    data object Loading : PerformanceUiState
    data class Success(val data: CalibrationResponse) : PerformanceUiState
    data class Error(val message: String) : PerformanceUiState
}

sealed interface HistoryUiState {
    data object Idle : HistoryUiState
    data object Loading : HistoryUiState
    data class Dates(val dates: List<String>) : HistoryUiState
    data class DayLoading(val dates: List<String>, val selectedDate: String) : HistoryUiState
    data class DaySuccess(val dates: List<String>, val selectedDate: String,
                          val history: HistoryResponse) : HistoryUiState
    data class Error(val message: String) : HistoryUiState
}

class PerformanceViewModel : ViewModel() {

    // Overridable en test pour piloter le dispatcher IO avec le TestDispatcher,
    // comme UpcomingViewModel.io / ValueViewModel.io.
    internal var io: CoroutineDispatcher = Dispatchers.IO

    var state by mutableStateOf<PerformanceUiState>(PerformanceUiState.Idle)
        private set

    var historyState by mutableStateOf<HistoryUiState>(HistoryUiState.Idle)
        private set

    fun load() {
        state = PerformanceUiState.Loading
        viewModelScope.launch {
            state = try {
                val resp = withContext(io) { ApiClient.create().calibration() }
                PerformanceUiState.Success(resp)
            } catch (e: Exception) {
                PerformanceUiState.Error("Connexion impossible : ${e.message}")
            }
        }
    }

    fun loadHistoryDates() {
        if (historyState is HistoryUiState.Dates || historyState is HistoryUiState.DaySuccess) return
        historyState = HistoryUiState.Loading
        viewModelScope.launch {
            historyState = try {
                val resp = withContext(io) { ApiClient.create().historyDates() }
                HistoryUiState.Dates(resp.dates)
            } catch (e: Exception) {
                HistoryUiState.Error(e.message ?: "Erreur")
            }
        }
    }

    fun selectDate(date: String) {
        val currentDates = when (val s = historyState) {
            is HistoryUiState.Dates -> s.dates
            is HistoryUiState.DaySuccess -> s.dates
            is HistoryUiState.DayLoading -> s.dates
            else -> emptyList()
        }
        historyState = HistoryUiState.DayLoading(currentDates, date)
        viewModelScope.launch {
            historyState = try {
                val resp = withContext(io) { ApiClient.create().historyByDate(date) }
                HistoryUiState.DaySuccess(currentDates, date, resp)
            } catch (e: Exception) {
                HistoryUiState.Error(e.message ?: "Erreur")
            }
        }
    }
}

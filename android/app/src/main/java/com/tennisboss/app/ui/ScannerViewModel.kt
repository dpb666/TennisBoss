package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ScannerStatus
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

sealed interface ScannerUiState {
    data object Idle : ScannerUiState
    data object Loading : ScannerUiState
    data class Success(val data: ScannerStatus) : ScannerUiState
    data class Error(val message: String) : ScannerUiState
}

class ScannerViewModel : ViewModel() {

    // Overridable en test pour piloter le dispatcher IO avec le TestDispatcher,
    // comme UpcomingViewModel.io / ValueViewModel.io.
    internal var io: CoroutineDispatcher = Dispatchers.IO

    var state by mutableStateOf<ScannerUiState>(ScannerUiState.Idle)
        private set

    var secondsToNext by mutableStateOf<Int?>(null)
        private set

    fun load() {
        state = ScannerUiState.Loading
        viewModelScope.launch {
            state = try {
                val data = kotlinx.coroutines.withContext(io) {
                    ApiClient.create().scannerStatus()
                }
                startCountdown(data)
                ScannerUiState.Success(data)
            } catch (e: Exception) {
                ScannerUiState.Error("Connexion impossible : ${e.message}")
            }
        }
    }

    private fun startCountdown(data: ScannerStatus) {
        val next = data.next_cycle_ts ?: return
        viewModelScope.launch {
            try {
                val fmt = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", java.util.Locale.US)
                fmt.timeZone = java.util.TimeZone.getTimeZone("UTC")
                val nextMs = fmt.parse(next)?.time ?: return@launch
                while (true) {
                    val diff = ((nextMs - System.currentTimeMillis()) / 1000).toInt()
                    secondsToNext = diff.coerceAtLeast(0)
                    if (diff <= 0) break
                    delay(1000)
                }
            } catch (_: Exception) {}
        }
    }
}

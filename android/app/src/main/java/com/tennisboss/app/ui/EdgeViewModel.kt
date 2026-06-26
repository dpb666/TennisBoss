package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ClvResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

sealed interface EdgeUiState {
    data object Idle : EdgeUiState
    data object Loading : EdgeUiState
    data class Success(val data: ClvResponse) : EdgeUiState
    data class Error(val message: String) : EdgeUiState
}

/** Charge le dashboard CLV (preuve d'edge) depuis /api/clv. */
class EdgeViewModel : ViewModel() {

    var state by mutableStateOf<EdgeUiState>(EdgeUiState.Idle)
        private set

    fun load() {
        state = EdgeUiState.Loading
        viewModelScope.launch {
            state = try {
                val resp = withContext(Dispatchers.IO) { ApiClient.create().clv() }
                EdgeUiState.Success(resp)
            } catch (e: Exception) {
                EdgeUiState.Error("Connexion impossible : ${e.message}")
            }
        }
    }
}

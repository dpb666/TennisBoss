package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ChatMessage
import com.tennisboss.app.data.ChatRequest
import kotlinx.coroutines.launch

class ChatViewModel : ViewModel() {

    val messages = mutableStateListOf<ChatMessage>()
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    fun send(text: String) {
        val trimmed = text.trim()
        if (trimmed.isBlank() || loading) return

        messages.add(ChatMessage("user", trimmed))
        loading = true
        error = null

        viewModelScope.launch {
            try {
                // Historique glissant : tous les messages sauf le dernier ajouté
                val history = messages.dropLast(1)
                val response = ApiClient.create().chat(
                    ChatRequest(message = trimmed, history = history)
                )
                val reply = response.reply
                if (!reply.isNullOrBlank()) {
                    messages.add(ChatMessage("assistant", reply))
                } else {
                    val err = response.error ?: "Réponse vide"
                    messages.add(ChatMessage("assistant", "⚠️ $err"))
                }
            } catch (e: Exception) {
                error = e.message ?: "Erreur réseau"
                messages.add(ChatMessage("assistant",
                    "⚠️ LM Studio inaccessible — assure-toi qu'il tourne sur le PC avec un modèle chargé."))
            } finally {
                loading = false
            }
        }
    }

    fun clear() {
        messages.clear()
        error = null
    }
}

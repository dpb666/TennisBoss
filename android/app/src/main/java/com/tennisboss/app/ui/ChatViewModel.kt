package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import android.content.Context
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ChatMessage
import com.tennisboss.app.data.ChatRequest
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.io.FileOutputStream

class ChatViewModel : ViewModel() {

    val messages = mutableStateListOf<ChatMessage>()
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    /** Analyst mode for technical / ROI / calibration questions (API mode=analyst). */
    internal fun resolveChatMode(text: String): String {
        val t = text.trim()
        if (t.startsWith("@")) return "analyst"
        val lower = t.lowercase()
        val analystHints = listOf(
            "roi", "clv", "calibration", "bet_history", "logging",
            "architecture", "verdict", "edge", "completeness", "beat closing",
        )
        return if (analystHints.any { lower.contains(it) }) "analyst" else "chat"
    }

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
                val mode = resolveChatMode(trimmed)
                val response = ApiClient.create().chat(
                    ChatRequest(message = trimmed, history = history, mode = mode)
                )
                val reply = response.reply
                if (!reply.isNullOrBlank()) {
                    messages.add(
                        ChatMessage(
                            role = "assistant",
                            content = reply,
                            context_used = response.context_used,
                            tools_called = response.tools_called.orEmpty(),
                            sources = response.sources.orEmpty(),
                        )
                    )
                } else {
                    val err = response.error ?: "Réponse vide"
                    messages.add(ChatMessage("assistant", "⚠️ $err"))
                }
            } catch (e: Exception) {
                error = e.message ?: "Erreur réseau"
                messages.add(ChatMessage("assistant",
                    "⚠️ IA hors ligne — Ollama n'est pas accessible sur le serveur (port 11434). Lance-le avec `ollama serve`."))
            } finally {
                loading = false
            }
        }
    }

    fun uploadFile(context: Context, uri: Uri, question: String = "Analyse ce fichier") {
        if (loading) return
        loading = true
        error = null
        messages.add(ChatMessage("user", "📎 $question"))

        viewModelScope.launch {
            try {
                val contentResolver = context.contentResolver
                val mimeType = contentResolver.getType(uri) ?: "application/octet-stream"
                val fileName = uri.lastPathSegment?.substringAfterLast('/') ?: "fichier"
                val tmpFile = File(context.cacheDir, fileName)
                contentResolver.openInputStream(uri)?.use { input ->
                    FileOutputStream(tmpFile).use { output -> input.copyTo(output) }
                }
                val filePart = MultipartBody.Part.createFormData(
                    "file", fileName,
                    tmpFile.asRequestBody(mimeType.toMediaTypeOrNull())
                )
                val msgBody = question.toRequestBody("text/plain".toMediaTypeOrNull())
                val response = ApiClient.create().upload(filePart, msgBody)
                val reply = response.reply
                if (!reply.isNullOrBlank()) {
                    messages.add(ChatMessage("assistant", reply))
                } else {
                    messages.add(ChatMessage("assistant", "⚠️ ${response.error ?: "Réponse vide"}"))
                }
            } catch (e: Exception) {
                messages.add(ChatMessage("assistant", "⚠️ Erreur upload : ${e.message}"))
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

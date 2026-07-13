package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ChatResponse
import com.tennisboss.app.ui.ChatViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * ChatViewModel n'avait aucun test avant celui-ci (voir TEST_REPORT.md —
 * 7 des 13 ViewModels sans couverture, ChatViewModel étant la fonctionnalité
 * "IA booster" la plus mise en avant cette session). uploadFile() n'est PAS
 * testé ici : il dépend d'un android.content.Context réel (contentResolver,
 * cacheDir), qui demanderait Robolectric — hors scope pour l'instant.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
        ApiClient.apiOverride = null
    }

    @Test
    fun `send ajoute le message utilisateur puis la reponse de l'assistant`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            chatResponse = ChatResponse(reply = "Sinner est favori sur dur.", context_used = true),
        )
        val vm = ChatViewModel()

        vm.send("Sinner vs Alcaraz sur dur ?")
        advanceUntilIdle()

        assertEquals(2, vm.messages.size)
        assertEquals("user", vm.messages[0].role)
        assertEquals("Sinner vs Alcaraz sur dur ?", vm.messages[0].content)
        assertEquals("assistant", vm.messages[1].role)
        assertEquals("Sinner est favori sur dur.", vm.messages[1].content)
        assertTrue(vm.messages[1].context_used)
        assertFalse(vm.loading)
    }

    @Test
    fun `send ignore un message vide`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(chatResponse = ChatResponse(reply = "..."))
        val vm = ChatViewModel()

        vm.send("   ")
        advanceUntilIdle()

        assertTrue(vm.messages.isEmpty())
    }

    @Test
    fun `send ignore les appels concurrents pendant le chargement`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(chatResponse = ChatResponse(reply = "ok"))
        val vm = ChatViewModel()

        vm.send("Premiere question")
        // loading est deja true ici (avant advanceUntilIdle) -> un second send()
        // pendant ce laps de temps ne doit rien ajouter.
        vm.send("Deuxieme question")
        advanceUntilIdle()

        assertEquals(2, vm.messages.size)  // 1 user + 1 assistant, pas 4
        assertEquals("Premiere question", vm.messages[0].content)
    }

    @Test
    fun `send affiche un message hors-ligne en cas d'erreur reseau`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("connection refused"))
        val vm = ChatViewModel()

        vm.send("Question quelconque")
        advanceUntilIdle()

        assertEquals(2, vm.messages.size)
        assertEquals("assistant", vm.messages[1].role)
        assertTrue(vm.messages[1].content.contains("hors ligne"))
        assertEquals("connection refused", vm.error)
        assertFalse(vm.loading)
    }

    @Test
    fun `send affiche l'erreur backend quand reply est vide`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            chatResponse = ChatResponse(reply = null, error = "modele indisponible"),
        )
        val vm = ChatViewModel()

        vm.send("Question")
        advanceUntilIdle()

        assertEquals("assistant", vm.messages[1].role)
        assertTrue(vm.messages[1].content.contains("modele indisponible"))
    }

    @Test
    fun `clear vide les messages et l'erreur`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("boom"))
        val vm = ChatViewModel()
        vm.send("Question")
        advanceUntilIdle()
        assertTrue(vm.messages.isNotEmpty())

        vm.clear()

        assertTrue(vm.messages.isEmpty())
        assertEquals(null, vm.error)
    }
}

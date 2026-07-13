package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.Player
import com.tennisboss.app.data.PlayersResponse
import com.tennisboss.app.ui.PlayersViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PlayersViewModelTest {

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
    fun `onQueryChange vide efface immediatement les resultats sans appel reseau`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("ne doit pas etre appele"))
        val vm = PlayersViewModel().apply { io = dispatcher }

        vm.onQueryChange("")
        advanceUntilIdle()

        assertTrue(vm.players.isEmpty())
        assertEquals(false, vm.loading)
    }

    @Test
    fun `onQueryChange peuple players apres le debounce`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            playersResponse = PlayersResponse(1, listOf(Player(name = "Jannik Sinner"))),
        )
        val vm = PlayersViewModel().apply { io = dispatcher }

        vm.onQueryChange("Sinner")
        advanceUntilIdle()

        assertEquals(1, vm.players.size)
        assertEquals("Jannik Sinner", vm.players[0].name)
        assertEquals(false, vm.loading)
    }

    @Test
    fun `un nouveau caractere annule la recherche precedente (debounce)`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            playersResponse = PlayersResponse(1, listOf(Player(name = "Carlos Alcaraz"))),
        )
        val vm = PlayersViewModel().apply { io = dispatcher }

        vm.onQueryChange("Alc")
        advanceTimeBy(100)   // avant les 300ms de debounce
        vm.onQueryChange("Alcaraz")
        advanceUntilIdle()

        assertEquals("Alcaraz", vm.query)
        assertEquals(1, vm.players.size)
    }

    @Test
    fun `erreur reseau vide players et affiche un message`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("timeout"))
        val vm = PlayersViewModel().apply { io = dispatcher }

        vm.onQueryChange("Sinner")
        advanceUntilIdle()

        assertTrue(vm.players.isEmpty())
        assertTrue(vm.error!!.contains("timeout"))
        assertEquals(false, vm.loading)
    }
}

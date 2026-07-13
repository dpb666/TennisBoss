package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.PlayerDetail
import com.tennisboss.app.ui.PlayerDetailState
import com.tennisboss.app.ui.PlayerDetailViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
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
class PlayerDetailViewModelTest {

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
    fun `state est Idle avant tout appel`() {
        val vm = PlayerDetailViewModel().apply { io = dispatcher }
        assertEquals(PlayerDetailState.Idle, vm.state)
    }

    @Test
    fun `load passe par Loading puis Success avec les donnees du joueur`() = runTest(dispatcher) {
        val detail = PlayerDetail(name = "Jannik Sinner", rating = 2450.0)
        ApiClient.apiOverride = FakeApi(playerResponses = mapOf("Jannik Sinner" to detail))
        val vm = PlayerDetailViewModel().apply { io = dispatcher }

        vm.load("Jannik Sinner")
        assertEquals(PlayerDetailState.Loading, vm.state)

        advanceUntilIdle()

        val state = vm.state
        assertTrue(state is PlayerDetailState.Success)
        assertEquals("Jannik Sinner", (state as PlayerDetailState.Success).data.name)
    }

    @Test
    fun `load passe en Error si l'appel echoue`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("introuvable"))
        val vm = PlayerDetailViewModel().apply { io = dispatcher }

        vm.load("Joueur Inconnu")
        advanceUntilIdle()

        val state = vm.state
        assertTrue(state is PlayerDetailState.Error)
        assertTrue((state as PlayerDetailState.Error).message.contains("introuvable"))
    }

    @Test
    fun `clear revient a Idle`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            playerResponses = mapOf("Jannik Sinner" to PlayerDetail(name = "Jannik Sinner")),
        )
        val vm = PlayerDetailViewModel().apply { io = dispatcher }
        vm.load("Jannik Sinner")
        advanceUntilIdle()
        assertTrue(vm.state is PlayerDetailState.Success)

        vm.clear()

        assertEquals(PlayerDetailState.Idle, vm.state)
    }
}

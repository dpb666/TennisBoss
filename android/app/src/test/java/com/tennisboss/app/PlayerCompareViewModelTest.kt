package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.H2H
import com.tennisboss.app.data.PlayerDetail
import com.tennisboss.app.ui.PlayerCompareViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PlayerCompareViewModelTest {

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
    fun `selectA seul charge p1 sans h2h`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            playerResponses = mapOf("Jannik Sinner" to PlayerDetail(name = "Jannik Sinner")),
        )
        val vm = PlayerCompareViewModel().apply { io = dispatcher }

        vm.selectA("Jannik Sinner")
        advanceUntilIdle()

        assertEquals("Jannik Sinner", vm.compare.p1?.name)
        assertNull(vm.compare.p2)
        assertEquals(false, vm.compare.loading)
    }

    @Test
    fun `selectA puis selectB charge p1, p2 et le h2h`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            playerResponses = mapOf(
                "Jannik Sinner" to PlayerDetail(name = "Jannik Sinner"),
                "Carlos Alcaraz" to PlayerDetail(name = "Carlos Alcaraz"),
            ),
            h2hResponse = H2H(player1 = "Jannik Sinner", player2 = "Carlos Alcaraz", wins1 = 3, wins2 = 5),
        )
        val vm = PlayerCompareViewModel().apply { io = dispatcher }

        vm.selectA("Jannik Sinner")
        advanceUntilIdle()
        vm.selectB("Carlos Alcaraz")
        advanceUntilIdle()

        assertEquals("Jannik Sinner", vm.compare.p1?.name)
        assertEquals("Carlos Alcaraz", vm.compare.p2?.name)
        assertEquals(5, vm.compare.h2h?.wins2)
    }

    @Test
    fun `un h2h en echec n'empeche pas d'afficher p1 et p2`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            playerResponses = mapOf(
                "Jannik Sinner" to PlayerDetail(name = "Jannik Sinner"),
                "Carlos Alcaraz" to PlayerDetail(name = "Carlos Alcaraz"),
            ),
            // h2hResponse non fourni -> FakeApi.h2h() leve RuntimeException("non utilisé")
        )
        val vm = PlayerCompareViewModel().apply { io = dispatcher }

        vm.selectA("Jannik Sinner")
        advanceUntilIdle()
        vm.selectB("Carlos Alcaraz")
        advanceUntilIdle()

        assertEquals("Carlos Alcaraz", vm.compare.p2?.name)
        assertNull(vm.compare.h2h)
    }

    @Test
    fun `clearB retire p2 et le h2h mais garde p1`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            playerResponses = mapOf(
                "Jannik Sinner" to PlayerDetail(name = "Jannik Sinner"),
                "Carlos Alcaraz" to PlayerDetail(name = "Carlos Alcaraz"),
            ),
            h2hResponse = H2H(player1 = "Jannik Sinner", player2 = "Carlos Alcaraz"),
        )
        val vm = PlayerCompareViewModel().apply { io = dispatcher }
        vm.selectA("Jannik Sinner")
        advanceUntilIdle()
        vm.selectB("Carlos Alcaraz")
        advanceUntilIdle()

        vm.clearB()

        assertEquals("Jannik Sinner", vm.compare.p1?.name)
        assertNull(vm.compare.p2)
        assertNull(vm.compare.h2h)
        assertEquals("", vm.queryB)
    }

    @Test
    fun `clearA reinitialise completement la comparaison`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            playerResponses = mapOf("Jannik Sinner" to PlayerDetail(name = "Jannik Sinner")),
        )
        val vm = PlayerCompareViewModel().apply { io = dispatcher }
        vm.selectA("Jannik Sinner")
        advanceUntilIdle()

        vm.clearA()

        assertNull(vm.compare.p1)
        assertNull(vm.selectedA)
        assertTrue(vm.queryA.isEmpty())
    }
}

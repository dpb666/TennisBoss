package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ComboLeg
import com.tennisboss.app.data.ComboResult
import com.tennisboss.app.ui.ComboBuilderViewModel
import com.tennisboss.app.ui.ComboLegInput
import com.tennisboss.app.ui.ComboUiState
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
import retrofit2.HttpException
import retrofit2.Response
import okhttp3.ResponseBody.Companion.toResponseBody

@OptIn(ExperimentalCoroutinesApi::class)
class ComboBuilderViewModelTest {

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
    fun `demarre avec 2 legs vides`() {
        val vm = ComboBuilderViewModel()
        assertEquals(2, vm.legs.size)
        assertFalse(vm.canCalculate())
    }

    @Test
    fun `addLeg ajoute jusqu'a 4 max`() {
        val vm = ComboBuilderViewModel()
        vm.addLeg()
        vm.addLeg()
        assertEquals(4, vm.legs.size)
        vm.addLeg()
        assertEquals(4, vm.legs.size)
    }

    @Test
    fun `removeLeg garde au moins 2 legs`() {
        val vm = ComboBuilderViewModel()
        vm.removeLeg(0)
        assertEquals(2, vm.legs.size)
    }

    @Test
    fun `canCalculate vrai seulement si tous les joueurs sont renseignes`() {
        val vm = ComboBuilderViewModel()
        assertFalse(vm.canCalculate())
        vm.updateLeg(0, ComboLegInput(player1 = "A", player2 = "B"))
        assertFalse(vm.canCalculate())
        vm.updateLeg(1, ComboLegInput(player1 = "C", player2 = "D"))
        assertTrue(vm.canCalculate())
    }

    @Test
    fun `calculate renvoie Success avec le resultat de l'API`() = runTest(dispatcher) {
        val result = ComboResult(
            legs = listOf(ComboLeg("A", "B", "player1", "match", 65.0, 1.54)),
            n_legs = 1, combined_probability_pct = 65.0, combined_fair_odds = 1.54,
            note = "note",
        )
        ApiClient.apiOverride = FakeApi(comboResultResponse = result)
        val vm = ComboBuilderViewModel()
        vm.updateLeg(0, ComboLegInput(player1 = "A", player2 = "B"))
        vm.updateLeg(1, ComboLegInput(player1 = "C", player2 = "D"))

        vm.calculate()
        advanceUntilIdle()

        val s = vm.state
        assertTrue(s is ComboUiState.Success)
        s as ComboUiState.Success
        assertEquals(1, s.result.n_legs)
    }

    @Test
    fun `calculate renvoie Error sur echec reseau`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            throwError = HttpException(Response.error<Any>(422, "".toResponseBody(null))),
        )
        val vm = ComboBuilderViewModel()
        vm.updateLeg(0, ComboLegInput(player1 = "A", player2 = "B"))
        vm.updateLeg(1, ComboLegInput(player1 = "C", player2 = "D"))

        vm.calculate()
        advanceUntilIdle()

        assertTrue(vm.state is ComboUiState.Error)
    }

    @Test
    fun `calculate sans joueurs renseignes renvoie Error sans appel reseau`() = runTest(dispatcher) {
        val vm = ComboBuilderViewModel()
        vm.calculate()
        advanceUntilIdle()
        assertTrue(vm.state is ComboUiState.Error)
    }
}

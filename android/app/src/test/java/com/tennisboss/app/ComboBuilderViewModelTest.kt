package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ComboLeg
import com.tennisboss.app.data.ComboResult
import com.tennisboss.app.ui.ComboBuilderViewModel
import com.tennisboss.app.ui.ComboLegInput
import com.tennisboss.app.ui.ComboUiState
import com.tennisboss.app.data.ValueComparison
import com.tennisboss.app.ui.computeComboEdge
import com.tennisboss.app.ui.computeComboEvPct
import com.tennisboss.app.ui.parseBookComboOdds
import com.tennisboss.app.ui.toComboLegInput
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

    @Test
    fun `toComboLegInput mappe best_side vers player1 ou player2`() {
        val pick = ValueComparison(
            player1 = "Sinner",
            player2 = "Alcaraz",
            best_side = "Alcaraz",
            ev1 = 2.0,
            ev2 = 8.0,
            value = true,
        )
        val leg = pick.toComboLegInput()
        assertEquals("Sinner", leg.player1)
        assertEquals("Alcaraz", leg.player2)
        assertEquals("player2", leg.side)
        assertEquals("match", leg.market)
    }

    @Test
    fun `addLegFromValuePick remplit la premiere leg vide`() {
        val vm = ComboBuilderViewModel()
        vm.updateLeg(1, ComboLegInput(player1 = "X", player2 = "Y"))
        vm.addLegFromValuePick(
            ValueComparison(
                player1 = "A",
                player2 = "B",
                best_side = "A",
                value = true,
            ),
        )
        assertEquals("A", vm.legs[0].player1)
        assertEquals("B", vm.legs[0].player2)
        assertEquals("player1", vm.legs[0].side)
        assertEquals("X", vm.legs[1].player1)
    }

    @Test
    fun `addLegFromValuePick ajoute une leg si toutes sont remplies et moins de 4`() {
        val vm = ComboBuilderViewModel()
        vm.updateLeg(0, ComboLegInput(player1 = "A", player2 = "B"))
        vm.updateLeg(1, ComboLegInput(player1 = "C", player2 = "D"))
        vm.addLegFromValuePick(
            ValueComparison(
                player1 = "E",
                player2 = "F",
                best_side = "F",
                value = true,
            ),
        )
        assertEquals(3, vm.legs.size)
        assertEquals("E", vm.legs[2].player1)
        assertEquals("player2", vm.legs[2].side)
    }

    @Test
    fun `dismissParlayBanner masque le bandeau`() {
        val vm = ComboBuilderViewModel()
        assertFalse(vm.parlayBannerDismissed)
        vm.dismissParlayBanner()
        assertTrue(vm.parlayBannerDismissed)
    }

    @Test
    fun `computeComboEvPct calcule EV analytique`() {
        assertEquals(25.0, computeComboEvPct(25.0, 5.0), 0.01)
        assertEquals(-10.0, computeComboEvPct(30.0, 3.0), 0.01)
    }

    @Test
    fun `computeComboEdge calcule edge vs marche`() {
        assertEquals(0.05, computeComboEdge(25.0, 5.0), 0.001)
        assertEquals(-0.0333, computeComboEdge(30.0, 3.0), 0.001)
    }

    @Test
    fun `parseBookComboOdds accepte decimales et virgule`() {
        assertEquals(4.5, parseBookComboOdds("4,50")!!, 0.001)
        assertEquals(null, parseBookComboOdds("1.0"))
        assertEquals(null, parseBookComboOdds("abc"))
    }

    @Test
    fun `displayedEvPct utilise saisie locale apres calcul`() {
        val vm = ComboBuilderViewModel()
        val result = ComboResult(
            legs = emptyList(),
            combined_probability_pct = 20.0,
            combined_fair_odds = 5.0,
            ev_pct = 999.0,
        )
        vm.updateBookComboOdds("6.0")
        assertEquals(20.0, vm.displayedEvPct(result)!!, 0.01)
    }
}

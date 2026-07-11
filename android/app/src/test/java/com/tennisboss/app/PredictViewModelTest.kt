package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.FirstSet
import com.tennisboss.app.data.Player
import com.tennisboss.app.data.PredictResponse
import com.tennisboss.app.ui.PredictUiState
import com.tennisboss.app.ui.PredictViewModel
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
import retrofit2.HttpException
import retrofit2.Response
import okhttp3.ResponseBody.Companion.toResponseBody

@OptIn(ExperimentalCoroutinesApi::class)
class PredictViewModelTest {

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

    private fun player(name: String) = Player(name = name)

    private fun response() = PredictResponse(
        player1 = player("Iga Swiatek"),
        player2 = player("Aryna Sabalenka"),
        first_set = FirstSet(prob1 = 47.7, prob2 = 52.3, favorite = "Aryna Sabalenka", verdict = "favori"),
    )

    @Test
    fun `predict renvoie Success avec les deux joueurs saisis`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(predictResponse = response())
        val vm = PredictViewModel().apply { io = dispatcher }
        vm.player1 = "Iga Swiatek"
        vm.player2 = "Aryna Sabalenka"

        vm.predict()
        advanceUntilIdle()

        val s = vm.state
        assertTrue(s is PredictUiState.Success)
        s as PredictUiState.Success
        assertEquals("Aryna Sabalenka", s.data.first_set.favorite)
    }

    @Test
    fun `predict refuse si un joueur est vide`() = runTest(dispatcher) {
        val vm = PredictViewModel().apply { io = dispatcher; player1 = ""; player2 = "Aryna Sabalenka" }

        vm.predict()
        advanceUntilIdle()

        assertTrue(vm.state is PredictUiState.Error)
    }

    @Test
    fun `predict traduit un 404 en message joueur inconnu`() = runTest(dispatcher) {
        val notFound = HttpException(Response.error<Any>(404, "".toResponseBody(null)))
        ApiClient.apiOverride = FakeApi(throwError = notFound)
        val vm = PredictViewModel().apply { io = dispatcher; player1 = "X"; player2 = "Y" }

        vm.predict()
        advanceUntilIdle()

        val s = vm.state
        assertTrue(s is PredictUiState.Error)
        s as PredictUiState.Error
        assertEquals("Joueur inconnu en base.", s.message)
    }
}

package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ValueComparison
import com.tennisboss.app.data.ValueResponse
import com.tennisboss.app.ui.ValueUiState
import com.tennisboss.app.ui.ValueViewModel
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
class ValueViewModelTest {

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
    fun `load renvoie Success avec les comparaisons`() = runTest(dispatcher) {
        val comparisons = listOf(
            ValueComparison(player1 = "A", player2 = "B", value = true, best_ev = 12.0),
        )
        ApiClient.apiOverride = FakeApi(valueResponse = ValueResponse(count = 1, comparisons = comparisons))
        val vm = ValueViewModel().apply { io = dispatcher }

        vm.load()
        advanceUntilIdle()

        val s = vm.state
        assertTrue(s is ValueUiState.Success)
        s as ValueUiState.Success
        assertEquals(1, s.comparisons.size)
        assertEquals("A", s.comparisons.first().player1)
    }

    @Test
    fun `load en 429 signale un rate-limit sans planter`() = runTest(dispatcher) {
        val rateLimited = HttpException(Response.error<Any>(429, "".toResponseBody(null)))
        ApiClient.apiOverride = FakeApi(throwError = rateLimited)
        val vm = ValueViewModel().apply { io = dispatcher }

        vm.load()
        advanceUntilIdle()

        assertTrue(vm.state is ValueUiState.Error)
    }
}

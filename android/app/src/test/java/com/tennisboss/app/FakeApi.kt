package com.tennisboss.app

import com.tennisboss.app.data.CalibrationResponse
import com.tennisboss.app.data.ChatRequest
import com.tennisboss.app.data.ChatResponse
import com.tennisboss.app.data.ClvResponse
import com.tennisboss.app.data.H2H
import com.tennisboss.app.data.Health
import com.tennisboss.app.data.HistoryDatesResponse
import com.tennisboss.app.data.HistoryResponse
import com.tennisboss.app.data.InplayBestResponse
import com.tennisboss.app.data.InplayMarketsResponse
import com.tennisboss.app.data.InplayPickLogResponse
import com.tennisboss.app.data.InplayPickRequest
import com.tennisboss.app.data.InplayPicksResponse
import com.tennisboss.app.data.IntelligenceStats
import com.tennisboss.app.data.LearnerStats
import com.tennisboss.app.data.LiveResponse
import com.tennisboss.app.data.PlayerDetail
import com.tennisboss.app.data.PlayersResponse
import com.tennisboss.app.data.PredictResponse
import com.tennisboss.app.data.ScannerStatus
import com.tennisboss.app.data.TennisBossApi
import com.tennisboss.app.data.UpcomingResponse
import com.tennisboss.app.data.ValueHistoryResponse
import com.tennisboss.app.data.ValueResponse
import okhttp3.MultipartBody
import okhttp3.RequestBody

/**
 * Implémentation de test de [TennisBossApi]. On fournit la réponse voulue
 * (ou on demande une exception) pour l'endpoint testé ; les autres ne sont
 * pas censés être appelés.
 */
class FakeApi(
    private val upcomingResponse: UpcomingResponse? = null,
    private val valueResponse: ValueResponse? = null,
    private val throwError: Throwable? = null,
) : TennisBossApi {

    override suspend fun health(): Health = Health("ok", "test", "1.0", 0)

    override suspend fun predict(p1: String, p2: String): PredictResponse =
        throw NotImplementedError("non utilisé")

    override suspend fun players(q: String, tour: String?, limit: Int): PlayersResponse =
        throw NotImplementedError("non utilisé")

    override suspend fun player(name: String): PlayerDetail =
        throw NotImplementedError("non utilisé")

    override suspend fun h2h(p1: String, p2: String): H2H =
        throw NotImplementedError("non utilisé")

    override suspend fun upcoming(days: Int, limit: Int, odds: Boolean): UpcomingResponse {
        throwError?.let { throw it }
        return upcomingResponse ?: UpcomingResponse(0, emptyList())
    }

    override suspend fun value(limit: Int): ValueResponse {
        throwError?.let { throw it }
        return valueResponse ?: ValueResponse()
    }

    override suspend fun calibration(): CalibrationResponse = throw NotImplementedError("non utilisé")
    override suspend fun live(): LiveResponse = throw NotImplementedError("non utilisé")
    override suspend fun inplayBest(): InplayBestResponse = throw NotImplementedError("non utilisé")
    override suspend fun inplayMarkets(): InplayMarketsResponse = throw NotImplementedError("non utilisé")
    override suspend fun inplayPicks(): InplayPicksResponse = throw NotImplementedError("non utilisé")
    override suspend fun logInplayPick(request: InplayPickRequest): InplayPickLogResponse =
        throw NotImplementedError("non utilisé")
    override suspend fun settleInplayPick(id: Int, body: Map<String, String>): InplayPickLogResponse =
        throw NotImplementedError("non utilisé")
    override suspend fun deleteInplayPick(id: Int): InplayPickLogResponse =
        throw NotImplementedError("non utilisé")
    override suspend fun historyDates(dates: Int): HistoryDatesResponse = throw NotImplementedError("non utilisé")
    override suspend fun historyByDate(date: String): HistoryResponse = throw NotImplementedError("non utilisé")
    override suspend fun clv(): ClvResponse = throw NotImplementedError("non utilisé")
    override suspend fun intelligenceStats(): IntelligenceStats = throw NotImplementedError("non utilisé")
    override suspend fun learnerStats(): LearnerStats = throw NotImplementedError("non utilisé")
    override suspend fun scannerStatus(): ScannerStatus = throw NotImplementedError("non utilisé")
    override suspend fun valueHistory(limit: Int): ValueHistoryResponse = throw NotImplementedError("non utilisé")
    override suspend fun chat(request: ChatRequest): ChatResponse = throw NotImplementedError("non utilisé")
    override suspend fun upload(file: MultipartBody.Part, message: RequestBody): ChatResponse =
        throw NotImplementedError("non utilisé")
}

package com.tennisboss.app

import com.tennisboss.app.data.CalibrationResponse
import com.tennisboss.app.data.ChatRequest
import com.tennisboss.app.data.ChatResponse
import com.tennisboss.app.data.ClvResponse
import com.tennisboss.app.data.DeviceRegisterRequest
import com.tennisboss.app.data.DeviceRegisterResponse
import com.tennisboss.app.data.FollowPlayerRequest
import com.tennisboss.app.data.FollowPlayerResponse
import com.tennisboss.app.data.FollowedPlayersResponse
import com.tennisboss.app.data.H2H
import com.tennisboss.app.data.Health
import com.tennisboss.app.data.HistoryDatesResponse
import com.tennisboss.app.data.HistoryResponse
import com.tennisboss.app.data.InplayBestResponse
import com.tennisboss.app.data.InplayMarketsResponse
import com.tennisboss.app.data.InplayPickLogResponse
import com.tennisboss.app.data.InplayPickRequest
import com.tennisboss.app.data.InplayPicksResponse
import com.tennisboss.app.data.InsightResponse
import com.tennisboss.app.data.IntelligenceStats
import com.tennisboss.app.data.LearnerStats
import com.tennisboss.app.data.LiveResponse
import com.tennisboss.app.data.PlayerDetail
import com.tennisboss.app.data.PlayersResponse
import com.tennisboss.app.data.PredictResponse
import com.tennisboss.app.data.RecommendationsResponse
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
    private val predictResponse: PredictResponse? = null,
    private val liveResponse: LiveResponse? = null,
    private val calibrationResponse: CalibrationResponse? = null,
    private val playerResponses: Map<String, PlayerDetail>? = null,
    private val insightResponse: InsightResponse? = null,
    private val h2hResponse: H2H? = null,
    private val throwError: Throwable? = null,
) : TennisBossApi {

    override suspend fun health(): Health = Health("ok", "test", "1.0", 0)

    override suspend fun predict(p1: String, p2: String): PredictResponse {
        throwError?.let { throw it }
        return predictResponse ?: throw NotImplementedError("predictResponse non fourni")
    }

    override suspend fun players(q: String, tour: String?, limit: Int): PlayersResponse =
        throw NotImplementedError("non utilisé")

    override suspend fun player(name: String): PlayerDetail {
        throwError?.let { throw it }
        return playerResponses?.get(name) ?: throw NotImplementedError("playerResponses[$name] non fourni")
    }

    override suspend fun followPlayer(request: FollowPlayerRequest): FollowPlayerResponse =
        throw NotImplementedError("non utilisé")

    override suspend fun unfollowPlayer(request: FollowPlayerRequest): FollowPlayerResponse =
        throw NotImplementedError("non utilisé")

    override suspend fun followedPlayers(): FollowedPlayersResponse =
        throw NotImplementedError("non utilisé")

    // RuntimeException (pas NotImplementedError) : MatchDetailViewModel rattrape
    // l'échec du H2H avec catch (e: Exception) { null }, best-effort.
    override suspend fun h2h(p1: String, p2: String): H2H =
        h2hResponse ?: throw RuntimeException("non utilisé")

    override suspend fun upcoming(days: Int, limit: Int, odds: Boolean): UpcomingResponse {
        throwError?.let { throw it }
        return upcomingResponse ?: UpcomingResponse(0, emptyList())
    }

    override suspend fun value(limit: Int): ValueResponse {
        throwError?.let { throw it }
        return valueResponse ?: ValueResponse()
    }

    override suspend fun calibration(): CalibrationResponse {
        throwError?.let { throw it }
        return calibrationResponse ?: CalibrationResponse()
    }

    override suspend fun registerDevice(request: DeviceRegisterRequest): DeviceRegisterResponse =
        throw NotImplementedError("non utilisé")

    override suspend fun recommendations(limit: Int): RecommendationsResponse =
        throw NotImplementedError("non utilisé")

    override suspend fun insight(p1: String, p2: String, surface: String?, eventId: String?): InsightResponse {
        throwError?.let { throw it }
        return insightResponse ?: throw NotImplementedError("insightResponse non fourni")
    }

    override suspend fun live(): LiveResponse {
        throwError?.let { throw it }
        return liveResponse ?: throw NotImplementedError("liveResponse non fourni")
    }
    // RuntimeException (pas NotImplementedError, qui hérite de Error) : ces 3
    // endpoints sont volontairement "best-effort" côté LiveViewModel (catch
    // (e: Exception) { null } — une Error ne serait pas rattrapée et ferait
    // planter la coroutine avant même d'atteindre l'état Success).
    override suspend fun inplayBest(): InplayBestResponse = throw RuntimeException("non utilisé")
    override suspend fun inplayMarkets(): InplayMarketsResponse = throw RuntimeException("non utilisé")
    override suspend fun inplayPicks(): InplayPicksResponse = throw RuntimeException("non utilisé")
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

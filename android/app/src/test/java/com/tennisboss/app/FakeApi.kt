package com.tennisboss.app

import com.tennisboss.app.data.H2H
import com.tennisboss.app.data.Health
import com.tennisboss.app.data.PlayerDetail
import com.tennisboss.app.data.PlayersResponse
import com.tennisboss.app.data.PredictResponse
import com.tennisboss.app.data.TennisBossApi
import com.tennisboss.app.data.UpcomingResponse
import com.tennisboss.app.data.ValueResponse

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
}

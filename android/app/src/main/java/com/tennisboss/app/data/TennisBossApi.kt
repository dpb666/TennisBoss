package com.tennisboss.app.data

import retrofit2.http.GET
import retrofit2.http.Query

/** Endpoints exposés par bot/api.py. */
interface TennisBossApi {

    @GET("health")
    suspend fun health(): Health

    @GET("api/predict")
    suspend fun predict(
        @Query("p1") p1: String,
        @Query("p2") p2: String,
    ): PredictResponse

    @GET("api/players")
    suspend fun players(
        @Query("q") q: String,
        @Query("tour") tour: String? = null,
        @Query("limit") limit: Int = 20,
    ): PlayersResponse

    @GET("api/player")
    suspend fun player(
        @Query("name") name: String,
    ): PlayerDetail

    @GET("api/h2h")
    suspend fun h2h(
        @Query("p1") p1: String,
        @Query("p2") p2: String,
    ): H2H

    @GET("api/upcoming")
    suspend fun upcoming(
        @Query("days") days: Int = 2,
        @Query("limit") limit: Int = 25,
        @Query("odds") odds: Boolean = false,
    ): UpcomingResponse

    @GET("api/value")
    suspend fun value(
        @Query("limit") limit: Int = 12,
    ): ValueResponse

    @GET("api/calibration")
    suspend fun calibration(): CalibrationResponse
}

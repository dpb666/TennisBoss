package com.tennisboss.app.data

import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Part
import retrofit2.http.Path
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

    @POST("api/device/register")
    suspend fun registerDevice(@Body request: DeviceRegisterRequest): DeviceRegisterResponse

    @GET("api/recommendations")
    suspend fun recommendations(@Query("limit") limit: Int = 10): RecommendationsResponse

    @GET("api/insight")
    suspend fun insight(
        @Query("p1") p1: String,
        @Query("p2") p2: String,
        @Query("surface") surface: String? = null,
        @Query("event_id") eventId: String? = null,
    ): InsightResponse

    @GET("api/live")
    suspend fun live(): LiveResponse

    @GET("api/inplay/best")
    suspend fun inplayBest(): InplayBestResponse

    @GET("api/inplay/markets")
    suspend fun inplayMarkets(): InplayMarketsResponse

    @GET("api/inplay/picks")
    suspend fun inplayPicks(): InplayPicksResponse

    @POST("api/inplay/picks")
    suspend fun logInplayPick(@Body request: InplayPickRequest): InplayPickLogResponse

    @PUT("api/inplay/picks/{id}")
    suspend fun settleInplayPick(
        @Path("id") id: Int,
        @Body body: Map<String, String>,
    ): InplayPickLogResponse

    @DELETE("api/inplay/picks/{id}")
    suspend fun deleteInplayPick(@Path("id") id: Int): InplayPickLogResponse

    @GET("api/history")
    suspend fun historyDates(@Query("dates") dates: Int = 1): HistoryDatesResponse

    @GET("api/history")
    suspend fun historyByDate(@Query("date") date: String): HistoryResponse

    @GET("api/clv")
    suspend fun clv(): ClvResponse

    @GET("api/intelligence/stats")
    suspend fun intelligenceStats(): IntelligenceStats

    @GET("api/learner/stats")
    suspend fun learnerStats(): LearnerStats

    @GET("api/scanner/status")
    suspend fun scannerStatus(): ScannerStatus

    @GET("api/value/history")
    suspend fun valueHistory(
        @Query("limit") limit: Int = 50,
    ): ValueHistoryResponse

    @POST("api/chat")
    suspend fun chat(@Body request: ChatRequest): ChatResponse

    @Multipart
    @POST("api/upload")
    suspend fun upload(
        @Part file: MultipartBody.Part,
        @Part("message") message: RequestBody,
    ): ChatResponse
}

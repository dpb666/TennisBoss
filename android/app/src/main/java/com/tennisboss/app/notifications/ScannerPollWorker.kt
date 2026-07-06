package com.tennisboss.app.notifications

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.tennisboss.app.data.ApiClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Worker qui poll /api/scanner/status toutes les 15min.
 * Si last_pick_ts a changé depuis la dernière vérification → notification.
 */
class ScannerPollWorker(
    private val appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    companion object {
        const val WORK_NAME = "scanner_poll"
        private const val PREFS = "tb_scanner_prefs"
        private const val KEY_LAST_PICK_TS = "last_pick_ts"
    }

    override suspend fun doWork(): Result {
        return try {
            val status = withContext(Dispatchers.IO) {
                ApiClient.create().scannerStatus()
            }
            val newPickTs = status.last_pick_ts ?: return Result.success()

            val prefs = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val lastSeen = prefs.getString(KEY_LAST_PICK_TS, null)

            if (lastSeen != newPickTs) {
                // Nouveau pick détecté — utilise last_pick si dispo
                val pick = status.last_pick
                PickNotificationHelper.showPickNotification(
                    appContext,
                    side = pick?.side ?: "Value Pick",
                    ev = pick?.ev ?: 0.0,
                    odds = pick?.odds ?: 0.0,
                    hoursAhead = pick?.hours,
                )
                prefs.edit().putString(KEY_LAST_PICK_TS, newPickTs).apply()
            }
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}

package com.tennisboss.app.notifications

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.tennisboss.app.data.ApiClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Worker qui poll /api/live toutes les 15min (plancher WorkManager pour du
 * périodique). Si le favori d'un match en cours change depuis le dernier poll
 * -> notification "bascule". Utile quand l'app n'est pas ouverte (le refresh
 * 30s de LiveScreen ne tourne que quand l'écran est visible).
 */
class LiveProbPollWorker(
    private val appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    companion object {
        const val WORK_NAME = "live_prob_poll"
        private const val PREFS = "tb_live_prob_prefs"
        private const val MIN_CONFIDENCE = 0.5
    }

    override suspend fun doWork(): Result {
        return try {
            val live = withContext(Dispatchers.IO) { ApiClient.create().live() }
            val prefs = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val editor = prefs.edit()

            val currentIds = mutableSetOf<String>()
            for (m in live.matches) {
                val pred = m.prediction ?: continue
                if (pred.confidence < MIN_CONFIDENCE) continue
                val fav = pred.favorite ?: continue
                val key = "fav_${m.event_id}"
                currentIds.add(key)
                val prevFav = prefs.getString(key, null)
                if (prevFav != null && prevFav != fav) {
                    val prob = if (fav == pred.player1) pred.prob1 else pred.prob2
                    PickNotificationHelper.showProbSwingNotification(
                        appContext, m.event_id, m.player1, m.player2, fav, prob,
                    )
                }
                editor.putString(key, fav)
            }

            // Nettoyage : retire les entrées des matchs qui ne sont plus live.
            prefs.all.keys.filter { it.startsWith("fav_") && it !in currentIds }
                .forEach { editor.remove(it) }
            editor.apply()

            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}

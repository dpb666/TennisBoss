package com.tennisboss.app.notifications

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.tennisboss.app.MainActivity
import com.tennisboss.app.R

object PickNotificationHelper {

    private const val CHANNEL_ID = "tb_picks"
    private const val CHANNEL_NAME = "Value Picks"
    private const val CHANNEL_DESC = "Alertes quand le scanner trouve un value pick"
    private const val NOTIFICATION_ID = 1001

    private const val SWING_CHANNEL_ID = "tb_live_swings"
    private const val SWING_CHANNEL_NAME = "Bascules live"
    private const val SWING_CHANNEL_DESC = "Alertes quand le favori change pendant un match en direct"
    private const val SWING_NOTIFICATION_ID_BASE = 2000

    private const val REMOTE_NOTIFICATION_ID_BASE = 3000

    fun createChannel(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                CHANNEL_NAME,
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                description = CHANNEL_DESC
                enableVibration(true)
            }
            val swingChannel = NotificationChannel(
                SWING_CHANNEL_ID,
                SWING_CHANNEL_NAME,
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description = SWING_CHANNEL_DESC
            }
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
            nm.createNotificationChannel(swingChannel)
        }
    }

    fun showProbSwingNotification(
        context: Context,
        eventId: Long,
        player1: String,
        player2: String,
        newFavorite: String,
        prob: Double,
    ) {
        val tapIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pendingIntent = PendingIntent.getActivity(
            context, eventId.toInt(), tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val title = "🔄 Bascule live : $player1 vs $player2"
        val body = "$newFavorite reprend l'avantage (${prob.toInt()}%)"

        val notification = NotificationCompat.Builder(context, SWING_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .build()

        try {
            NotificationManagerCompat.from(context).notify(SWING_NOTIFICATION_ID_BASE + (eventId % 1000).toInt(), notification)
        } catch (_: SecurityException) {
            // POST_NOTIFICATIONS non accordée — silencieux
        }
    }

    fun showPickNotification(
        context: Context,
        side: String,
        ev: Double,
        odds: Double,
        hoursAhead: Double?,
    ) {
        val tapIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pendingIntent = PendingIntent.getActivity(
            context, 0, tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val urgency = if (hoursAhead != null && hoursAhead < 1.0) "⚡" else "🎯"
        val timeStr = hoursAhead?.let { " · ${String.format("%.1f", it)}h" } ?: ""
        val title = "$urgency Value Pick détecté !"
        val body = "$side  EV+${String.format("%.1f", ev)}%  @${String.format("%.2f", odds)}$timeStr"

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .build()

        try {
            NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification)
        } catch (_: SecurityException) {
            // POST_NOTIFICATIONS non accordée — silencieux
        }
    }

    /**
     * Notification push serveur (FCM) reçue app au premier plan — quand l'app
     * est en arrière-plan/fermée, le système Android affiche directement le
     * payload "notification" du message sans passer par ce code. Réutilise le
     * canal CHANNEL_ID existant plutôt que d'en créer un 3e.
     */
    fun showRemoteNotification(context: Context, title: String, body: String) {
        val tapIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pendingIntent = PendingIntent.getActivity(
            context, 0, tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(context)
                .notify(REMOTE_NOTIFICATION_ID_BASE + (System.currentTimeMillis() % 1000).toInt(), notification)
        } catch (_: SecurityException) {
            // POST_NOTIFICATIONS non accordée — silencieux
        }
    }
}

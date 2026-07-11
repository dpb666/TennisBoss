package com.tennisboss.app.notifications

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.DeviceRegisterRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Reçoit les notifications push serveur (bot/push_notifications.py) et
 * enregistre/rafraîchit le token FCM auprès du backend.
 *
 * Quand l'app est en arrière-plan/fermée, Android affiche directement le
 * payload "notification" du message sans passer par [onMessageReceived] —
 * ce code ne s'exécute que si l'app est au premier plan, d'où l'appel
 * explicite à [PickNotificationHelper.showRemoteNotification] pour ce cas.
 */
class TennisBossMessagingService : FirebaseMessagingService() {

    private val scope = CoroutineScope(Dispatchers.IO)

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        registerToken(token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        val notif = message.notification ?: return
        PickNotificationHelper.showRemoteNotification(
            applicationContext,
            notif.title ?: "TennisBoss",
            notif.body ?: "",
        )
    }

    private fun registerToken(token: String) {
        scope.launch {
            try {
                ApiClient.create().registerDevice(DeviceRegisterRequest(token = token))
            } catch (_: Exception) {
                // Best-effort : réessayé au prochain démarrage de l'app (voir MainActivity).
            }
        }
    }
}

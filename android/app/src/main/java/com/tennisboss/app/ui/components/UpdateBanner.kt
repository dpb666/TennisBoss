package com.tennisboss.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tennisboss.app.data.AppVersionInfo

/** Bandeau informatif "nouvelle version disponible" — jamais d'installation
 * automatique, juste un rappel dismissible pour la durée de la session. */
@Composable
fun UpdateBanner(info: AppVersionInfo, onDismiss: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.tertiaryContainer)
            .padding(horizontal = 16.dp, vertical = 10.dp)
            .testTag("update_banner"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(
            Icons.Filled.SystemUpdate, contentDescription = null,
            tint = MaterialTheme.colorScheme.onTertiaryContainer,
        )
        Column(Modifier.weight(1f)) {
            Text(
                "Nouvelle version disponible" +
                    (info.version_name?.let { " ($it)" } ?: ""),
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onTertiaryContainer,
            )
            if (!info.notes.isNullOrBlank()) {
                Text(
                    info.notes,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onTertiaryContainer,
                )
            }
        }
        IconButton(onClick = onDismiss, modifier = Modifier.testTag("update_banner_dismiss")) {
            Icon(
                Icons.Filled.Close, contentDescription = "Ignorer",
                tint = MaterialTheme.colorScheme.onTertiaryContainer,
            )
        }
    }
}

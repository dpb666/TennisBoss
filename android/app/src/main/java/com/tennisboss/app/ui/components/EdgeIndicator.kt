package com.tennisboss.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp

private val GoodColor = Color(0xFF00E5A0)

/**
 * Badge d'edge % (espérance de gain modèle vs marché) — extrait de
 * ValueScreen.kt (anciennement `EvBadge`) pour être réutilisable ailleurs
 * (ex. DashboardScreen).
 */
@Composable
fun EdgeIndicator(edgePct: Double, isValue: Boolean, filterReason: String? = null) {
    val deadZone = filterReason == "dead_zone"
    val bg = when {
        deadZone -> Color(0xFF3E2723)
        isValue  -> GoodColor
        else     -> MaterialTheme.colorScheme.surfaceVariant
    }
    val fg = when {
        deadZone -> Color(0xFFFF8A65)
        isValue  -> Color(0xFF00251A)
        else     -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(bg)
            .padding(horizontal = 10.dp, vertical = 4.dp),
    ) {
        Text(
            when {
                deadZone -> "⛔ Zone EV 12-18%"
                isValue  -> "🟢 VALUE ${fmtSigned(edgePct)}"
                else     -> "Pas de value"
            },
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Bold,
            color = fg,
        )
    }
}

internal fun fmtSigned(v: Double): String = String.format("%+.1f%%", v)

@Preview(showBackground = true)
@Composable
private fun EdgeIndicatorValuePreview() {
    MaterialTheme { EdgeIndicator(edgePct = 8.4, isValue = true) }
}

@Preview(showBackground = true)
@Composable
private fun EdgeIndicatorNoValuePreview() {
    MaterialTheme { EdgeIndicator(edgePct = -2.1, isValue = false) }
}

@Preview(showBackground = true)
@Composable
private fun EdgeIndicatorDeadZonePreview() {
    MaterialTheme { EdgeIndicator(edgePct = 14.0, isValue = false, filterReason = "dead_zone") }
}

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
import androidx.compose.ui.unit.dp

@Composable
fun SurfaceBadge(surface: String?) {
    val (emoji, bg, fg) = when (surface?.lowercase()) {
        "grass"  -> Triple("🌿 Herbe",  Color(0xFF1B5E20), Color(0xFFA5D6A7))
        "clay"   -> Triple("🔴 Terre",  Color(0xFF4E1B00), Color(0xFFFF8A65))
        "hard"   -> Triple("🔵 Dur",    Color(0xFF0D2B5E), Color(0xFF90CAF9))
        "carpet" -> Triple("🟫 Indoor", Color(0xFF3E2723), Color(0xFFD7CCC8))
        else -> return
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(bg)
            .padding(horizontal = 8.dp, vertical = 2.dp),
    ) {
        Text(
            text = emoji,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            color = fg,
        )
    }
}

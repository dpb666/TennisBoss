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
fun ConfidenceBadge(label: String, confidence: Double = 0.0) {
    val (bg, fg) = when (label) {
        "élevée"  -> Color(0xFF00E5A0) to Color(0xFF00251A)
        "bonne"   -> Color(0xFF4F8CFF) to Color(0xFFFFFFFF)
        "modérée" -> Color(0xFFFFB800) to Color(0xFF2A1F00)
        "faible"  -> Color(0xFFFF5252) to Color(0xFF2A0000)
        else      -> Color(0xFF444444) to Color(0xFFCCCCCC)
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(bg)
            .padding(horizontal = 8.dp, vertical = 2.dp),
    ) {
        Text(
            // Préfixe "Confiance : " ajouté le 2026-07-13 : ce badge décrit la
            // confiance du MODÈLE dans sa prédiction (predictor.confidence_label,
            // 0.65-0.80 -> "bonne"), un axe indépendant de la valeur du pari
            // (EdgeIndicator "Pas de value" / HONEYPOT). Affiché seul, "bonne"
            // à côté de "Pas de value" + un avertissement HONEYPOT se lisait
            // comme un "bon pari" contradictoire avec les deux autres tags —
            // trouvé en test manuel sur émulateur (Dashboard et Matchs à venir).
            text = "Confiance : $label",
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            color = fg,
        )
    }
}

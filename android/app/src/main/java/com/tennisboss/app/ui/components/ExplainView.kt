package com.tennisboss.app.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tennisboss.app.data.Explain
import com.tennisboss.app.data.ExplainFactor
import java.util.Locale

// Couleurs des deux joueurs (cohérentes dans toute la vue d'explication).
private val P1Color = Color(0xFF4F8CFF) // bleu électrique
private val P2Color = Color(0xFF00C2A8) // turquoise
private val TrackColor = Color(0x22000000)

/**
 * Vue « Pourquoi cette prédiction ? » : décompose le résultat du modèle
 * facteur par facteur (service, retours, forme). Pour chaque facteur, une
 * barre divergente compare les deux joueurs ; le facteur décisif est mis
 * en avant. Données 100 % issues du calcul du modèle (pas d'invention).
 */
@Composable
fun ExplainView(
    name1: String,
    name2: String,
    explain: Explain,
) {
    val decisive = explain.factors.firstOrNull { it.key == explain.decisive }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(
            "Pourquoi cette prédiction ?",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )

        // Légende : qui est qui.
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            LegendDot(name1, P1Color)
            LegendDot(name2, P2Color)
        }

        // Callout du facteur décisif.
        if (decisive != null && decisive.favors != null) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(Color(0x1A4F8CFF))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(
                    "🎯 Facteur décisif : ${decisive.label} — avantage ${decisive.favors}",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }

        // Une ligne par facteur du modèle.
        explain.factors.forEach { f ->
            FactorRow(f, isDecisive = f.key == explain.decisive)
        }

        Spacer(Modifier.height(2.dp))
        Text(
            "Fiabilité du modèle : ${pct(explain.model_accuracy)} de bonnes " +
                "prédictions sur l'historique (backtest).",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.outline,
        )
    }
}

@Composable
private fun LegendDot(name: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .size(10.dp)
                .clip(RoundedCornerShape(50))
                .background(color),
        )
        Spacer(Modifier.width(6.dp))
        Text(name, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun FactorRow(f: ExplainFactor, isDecisive: Boolean) {
    val v1 = f.value1.toFloat().coerceIn(0f, 1f)
    val v2 = f.value2.toFloat().coerceIn(0f, 1f)
    val anim1 by animateFloatAsState(v1, tween(600), label = "v1")
    val anim2 by animateFloatAsState(v2, tween(600), label = "v2")

    val bg = if (isDecisive) Color(0x0D4F8CFF) else Color.Transparent

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(bg)
            .padding(vertical = 6.dp, horizontal = if (isDecisive) 8.dp else 0.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                f.label,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = if (isDecisive) FontWeight.Bold else FontWeight.Medium,
            )
            if (isDecisive) {
                Text("★ décisif", style = MaterialTheme.typography.labelSmall, color = P1Color)
            }
        }

        // Barre divergente : J1 pousse vers la gauche, J2 vers la droite.
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(18.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Moitié gauche (J1), barre ancrée au centre.
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(topStart = 9.dp, bottomStart = 9.dp))
                    .background(TrackColor),
                contentAlignment = Alignment.CenterEnd,
            ) {
                Box(
                    Modifier
                        .fillMaxWidth(anim1)
                        .fillMaxHeight()
                        .background(P1Color),
                )
                Text(
                    pctRaw(v1),
                    modifier = Modifier.padding(end = 6.dp),
                    color = Color.White,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            Spacer(Modifier.width(2.dp))
            // Moitié droite (J2), barre ancrée au centre.
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(topEnd = 9.dp, bottomEnd = 9.dp))
                    .background(TrackColor),
                contentAlignment = Alignment.CenterStart,
            ) {
                Box(
                    Modifier
                        .fillMaxWidth(anim2)
                        .fillMaxHeight()
                        .background(P2Color),
                )
                Text(
                    pctRaw(v2),
                    modifier = Modifier.padding(start = 6.dp),
                    color = Color.White,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}

private fun pct(v: Double): String = String.format("%.0f%%", v * 100)
private fun pctRaw(v: Float): String = String.format("%.0f", v * 100)

@Preview(showBackground = true)
@Composable
private fun ExplainPreview() {
    val demo = Explain(
        bias = 0.0,
        logit = 0.65,
        decisive = "recent",
        model_accuracy = 0.5992,
        factors = listOf(
            ExplainFactor("serve", "Service", 0.72, 0.71, 2.70, 0.03, "Jannik Sinner"),
            ExplainFactor("return1", "Retour (1er service adverse)", 0.33, 0.29, -0.33, -0.01, "Carlos Alcaraz"),
            ExplainFactor("return2", "Retour (2e service adverse)", 0.57, 0.49, 0.85, 0.07, "Jannik Sinner"),
            ExplainFactor("recent", "Forme récente", 0.99, 0.57, 1.34, 0.56, "Jannik Sinner"),
        ),
    )
    ExplainView("Jannik Sinner", "Carlos Alcaraz", demo)
}

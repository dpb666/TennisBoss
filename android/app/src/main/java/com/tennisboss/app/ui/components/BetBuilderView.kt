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
import com.tennisboss.app.data.BetBuilder
import com.tennisboss.app.data.BetMarket
import java.util.Locale

private val P1Color = Color(0xFF4F8CFF)
private val P2Color = Color(0xFF00C2A8)
private val AccentColor = Color(0xFF00E5A0)

/**
 * Bet Builder : marchés dérivés de la proba du 1er set (vainqueur match, 2e set,
 * match en 3 sets, score exact).
 */
@Composable
fun BetBuilderView(
    name1: String,
    name2: String,
    bb: BetBuilder? = null,
    // Support pour les données "à plat" du modèle Prediction si bb est null
    mlProb1: Double? = null,
    mlProb2: Double? = null,
    set2Prob1: Double? = null,
    set2Prob2: Double? = null,
    thirdSetProb: Double? = null,
    correctScore: Map<String, Double>? = null,
    totalPointsOver: Double? = null,
    totalSetsOver: Double? = null,
    totalAcesAvg: Double? = null,
) {
    val mProb1 = bb?.match?.prob1 ?: mlProb1
    val mProb2 = bb?.match?.prob2 ?: mlProb2
    val s2Prob1 = bb?.set2?.prob1 ?: set2Prob1
    val s2Prob2 = bb?.set2?.prob2 ?: set2Prob2
    val tSetProb = bb?.third_set_prob ?: thirdSetProb
    val scores = bb?.correct_score ?: correctScore

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(
            "🛠 BET BUILDER (AI)",
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.ExtraBold,
            color = MaterialTheme.colorScheme.secondary
        )

        if (mProb1 != null && mProb2 != null) {
            MarketBar("Vainqueur du match (ML)", name1, mProb1, name2, mProb2)
        }

        if (s2Prob1 != null && s2Prob2 != null) {
            MarketBar("Vainqueur du 2e set", name1, s2Prob1, name2, s2Prob2)
        }

        // Stats Additionnelles (Points, Sets, Aces) en ligne
        if (totalPointsOver != null || totalSetsOver != null || totalAcesAvg != null || tSetProb != null) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                if (tSetProb != null && tSetProb > 0) {
                    MiniStatCard("Match en 3 sets", fmt(tSetProb), Modifier.weight(1f))
                }
                if (totalPointsOver != null) {
                    MiniStatCard("Points Over", fmt(totalPointsOver), Modifier.weight(1f))
                }
                if (totalAcesAvg != null) {
                    MiniStatCard("Aces (avg)", String.format(Locale.US, "%.1f", totalAcesAvg), Modifier.weight(1f))
                }
            }
        }

        // Score exact, trié par probabilité décroissante.
        if (!scores.isNullOrEmpty()) {
            Text(
                "Top Scores Exacts",
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold,
            )
            scores.entries
                .sortedByDescending { it.value }
                .take(3) // On limite aux 3 meilleurs pour la lisibilité
                .forEach { (label, prob) -> ScoreRow(label, prob) }
        }
    }
}

@Composable
private fun MiniStatCard(label: String, value: String, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
            .padding(8.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(label, style = MaterialTheme.typography.labelSmall, fontSize = 9.sp, color = MaterialTheme.colorScheme.outline)
        Text(value, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Bold, color = AccentColor)
    }
}

@Composable
private fun MarketBar(title: String, n1: String, p1: Double, n2: String, p2: Double) {
    val total = if (p1 + p2 > 0) p1 + p2 else 100.0
    val frac1 = (p1 / total).toFloat().coerceIn(0f, 1f)
    val anim by animateFloatAsState(frac1, tween(600), label = "m")
    
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Medium)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(24.dp)
                .clip(RoundedCornerShape(6.dp)),
        ) {
            Box(
                modifier = Modifier
                    .weight(anim.coerceIn(0.01f, 0.99f))
                    .fillMaxHeight()
                    .background(P1Color),
                contentAlignment = Alignment.CenterStart,
            ) {
                if (anim > 0.15f) Text(
                    fmt(p1), color = Color.White, fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.labelSmall,
                    modifier = Modifier.padding(start = 6.dp),
                )
            }
            Box(
                modifier = Modifier
                    .weight((1f - anim).coerceIn(0.01f, 0.99f))
                    .fillMaxHeight()
                    .background(P2Color),
                contentAlignment = Alignment.CenterEnd,
            ) {
                if (anim < 0.85f) Text(
                    fmt(p2), color = Color.White, fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.labelSmall,
                    modifier = Modifier.padding(end = 6.dp),
                )
            }
        }
    }
}

@Composable
private fun ScoreRow(label: String, prob: Double) {
    val frac = (prob / 100.0).toFloat().coerceIn(0f, 1f)
    val anim by animateFloatAsState(frac, tween(600), label = "s")
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(label, style = MaterialTheme.typography.labelSmall, fontSize = 10.sp)
            Text(fmt(prob), style = MaterialTheme.typography.labelSmall, fontSize = 10.sp,
                fontWeight = FontWeight.SemiBold, color = AccentColor)
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(4.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f)),
        ) {
            Box(Modifier.fillMaxWidth(anim).fillMaxHeight().background(AccentColor))
        }
    }
}

private fun fmt(v: Double): String = String.format(Locale.US, "%.1f%%", v)

@Preview(showBackground = true)
@Composable
private fun BetBuilderPreview() {
    MaterialTheme {
        Box(Modifier.padding(16.dp)) {
            BetBuilderView(
                "Sinner", "Alcaraz",
                bb = BetBuilder(
                    match = BetMarket(72.8, 27.2),
                    set2 = BetMarket(65.7, 34.3),
                    third_set_prob = 45.1,
                    correct_score = mapOf(
                        "Sinner 2-0" to 43.2,
                        "Sinner 2-1" to 29.6,
                    ),
                ),
                totalAcesAvg = 8.5,
                totalPointsOver = 62.1
            )
        }
    }
}

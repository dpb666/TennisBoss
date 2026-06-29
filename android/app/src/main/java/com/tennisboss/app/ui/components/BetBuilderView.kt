package com.tennisboss.app.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
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
private val AmberColor = Color(0xFFFFB020)

@Composable
fun BetBuilderView(
    name1: String,
    name2: String,
    bb: BetBuilder? = null,
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

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {

        // ── Titre ─────────────────────────────────────────────────────────────
        Row(verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("🛠", fontSize = 14.sp)
            Text("BET BUILDER",
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.ExtraBold,
                color = MaterialTheme.colorScheme.secondary)
            Text("· IA",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.secondary.copy(alpha = 0.6f))
        }

        // ── Barres marché ──────────────────────────────────────────────────────
        if (mProb1 != null && mProb2 != null) {
            MarketBar("Vainqueur du match", name1, mProb1, name2, mProb2, P1Color, P2Color)
        }
        if (s2Prob1 != null && s2Prob2 != null) {
            MarketBar("Vainqueur 2e set", name1, s2Prob1, name2, s2Prob2, P1Color, P2Color)
        }

        // ── Mini-stats : 3 sets / Points / Aces ───────────────────────────────
        val hasStats = tSetProb != null || totalPointsOver != null || totalAcesAvg != null
        if (hasStats) {
            HorizontalDivider(thickness = 0.5.dp,
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f))
            Row(modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (tSetProb != null && tSetProb > 0) {
                    StatPill(
                        icon = "🎾",
                        label = "Match 3 sets",
                        value = pct(tSetProb),
                        valueColor = when {
                            tSetProb >= 50 -> AmberColor
                            tSetProb >= 35 -> AccentColor
                            else -> MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        modifier = Modifier.weight(1f),
                    )
                }
                if (totalPointsOver != null) {
                    StatPill(
                        icon = "📊",
                        label = "Points over",
                        value = pct(totalPointsOver),
                        valueColor = AccentColor,
                        modifier = Modifier.weight(1f),
                    )
                }
                if (totalAcesAvg != null) {
                    StatPill(
                        icon = "⚡",
                        label = "Aces (moy.)",
                        value = String.format(Locale.US, "%.1f", totalAcesAvg),
                        valueColor = P1Color,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }

        // ── Scores exacts ──────────────────────────────────────────────────────
        if (!scores.isNullOrEmpty()) {
            HorizontalDivider(thickness = 0.5.dp,
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f))
            Text("Scores exacts les + probables",
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            scores.entries
                .sortedByDescending { it.value }
                .take(3)
                .forEachIndexed { i, (label, prob) ->
                    ScoreRow(label, prob, highlight = i == 0)
                }
        }
    }
}

// ── StatPill : carte mini-stat lisible ────────────────────────────────────────
@Composable
private fun StatPill(
    icon: String,
    label: String,
    value: String,
    valueColor: Color,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(10.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        tonalElevation = 2.dp,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            Text(icon, fontSize = 16.sp)
            Text(value,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.ExtraBold,
                color = valueColor)
            Text(label,
                style = MaterialTheme.typography.labelSmall,
                fontSize = 10.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1)
        }
    }
}

// ── MarketBar ─────────────────────────────────────────────────────────────────
@Composable
private fun MarketBar(
    title: String,
    n1: String, p1: Double,
    n2: String, p2: Double,
    color1: Color, color2: Color,
) {
    val total = if (p1 + p2 > 0) p1 + p2 else 100.0
    val frac1 = (p1 / total).toFloat().coerceIn(0f, 1f)
    val anim by animateFloatAsState(frac1, tween(600), label = "m")

    Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
        // Titre + noms + probas
        Row(modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically) {
            Text(title,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface)
        }
        Row(modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween) {
            Text("${n1.substringAfterLast(" ").take(10)}  ${pct(p1)}",
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold, color = color1)
            Text("${pct(p2)}  ${n2.substringAfterLast(" ").take(10)}",
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold, color = color2)
        }
        // Barre bicolore
        Row(
            modifier = Modifier.fillMaxWidth().height(20.dp)
                .clip(RoundedCornerShape(6.dp)),
        ) {
            Box(
                modifier = Modifier
                    .weight(anim.coerceIn(0.05f, 0.95f))
                    .fillMaxHeight()
                    .background(color1),
                contentAlignment = Alignment.Center,
            ) {
                if (anim > 0.2f) Text(pct(p1),
                    color = Color.White, fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.labelSmall)
            }
            Box(
                modifier = Modifier
                    .weight((1f - anim).coerceIn(0.05f, 0.95f))
                    .fillMaxHeight()
                    .background(color2),
                contentAlignment = Alignment.Center,
            ) {
                if (anim < 0.8f) Text(pct(p2),
                    color = Color.White, fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

// ── ScoreRow ──────────────────────────────────────────────────────────────────
@Composable
private fun ScoreRow(label: String, prob: Double, highlight: Boolean) {
    val frac = (prob / 100.0).toFloat().coerceIn(0f, 1f)
    val anim by animateFloatAsState(frac, tween(600), label = "s")
    val barColor = if (highlight) AccentColor else AccentColor.copy(alpha = 0.5f)
    val textColor = if (highlight) MaterialTheme.colorScheme.onSurface
                    else MaterialTheme.colorScheme.onSurfaceVariant

    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Row(modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically) {
            Text(label,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = if (highlight) FontWeight.Bold else FontWeight.Normal,
                color = textColor)
            Text(pct(prob),
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold,
                color = barColor)
        }
        Row(
            modifier = Modifier.fillMaxWidth().height(4.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.25f)),
        ) {
            Box(Modifier.fillMaxWidth(anim).fillMaxHeight().background(barColor))
        }
    }
}

private fun pct(v: Double) = String.format(Locale.US, "%.1f%%", v)

@Preview(showBackground = true, backgroundColor = 0xFF0A0E14)
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
                        "Alcaraz 2-1" to 27.2,
                    ),
                ),
                totalAcesAvg = 8.5,
                totalPointsOver = 62.1,
            )
        }
    }
}

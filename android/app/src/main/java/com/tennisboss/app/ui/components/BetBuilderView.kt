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

        // ── Badge "meilleur pari" (heuristique de présentation uniquement) ──────
        if (bb?.best_market != null) {
            BestMarketBadge(bb.best_market, bb.best_market_confidence)
        }

        // ── Barres marché ──────────────────────────────────────────────────────
        if (mProb1 != null && mProb2 != null) {
            MarketBar(
                "Vainqueur du match", name1, mProb1, name2, mProb2, P1Color, P2Color,
                fairOdds1 = bb?.match?.fair_odds1, fairOdds2 = bb?.match?.fair_odds2,
                odds1 = bb?.match?.odds1, odds2 = bb?.match?.odds2,
                ev1 = bb?.match?.ev1, ev2 = bb?.match?.ev2,
            )
        }
        if (s2Prob1 != null && s2Prob2 != null) {
            MarketBar(
                "Vainqueur 2e set", name1, s2Prob1, name2, s2Prob2, P1Color, P2Color,
                fairOdds1 = bb?.set2?.fair_odds1, fairOdds2 = bb?.set2?.fair_odds2,
            )
        }
        bb?.total_sets?.let { ts ->
            if (ts.prob_over > 0 || ts.prob_under > 0) {
                MarketBar(
                    "Total sets (2.5)", "Plus", ts.prob_over, "Moins", ts.prob_under,
                    AmberColor, MaterialTheme.colorScheme.onSurfaceVariant,
                    fairOdds1 = ts.fair_odds_over, fairOdds2 = ts.fair_odds_under,
                )
            }
        }
        bb?.handicap?.let { h ->
            if (h.prob1 > 0 || h.prob2 > 0) {
                MarketBar(
                    "Handicap -1.5 sets (gagne 2-0)", name1, h.prob1, name2, h.prob2,
                    P1Color, P2Color,
                    fairOdds1 = h.fair_odds1, fairOdds2 = h.fair_odds2,
                )
            }
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

// ── BestMarketBadge : heuristique de présentation ("pari le plus sûr") ─────────
// N'affecte aucune décision de pari réelle — is_value/EV de production
// restent dans /api/value, ce badge ne fait que mettre en avant, parmi les
// marchés DÉJÀ calculés, celui où un côté domine le plus.
private fun marketLabel(key: String?): String = when (key) {
    "match" -> "Vainqueur du match"
    "set2" -> "Vainqueur 2e set"
    "total_sets" -> "Total sets"
    "handicap" -> "Handicap -1.5 sets"
    else -> ""
}

@Composable
private fun BestMarketBadge(bestMarket: String, confidence: Double?) {
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = AccentColor.copy(alpha = 0.15f),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            Text("⭐", fontSize = 12.sp)
            Text(
                "Pari le plus sûr : ${marketLabel(bestMarket)}" +
                    (confidence?.let { " (${pct(it)})" } ?: ""),
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold,
                color = AccentColor,
            )
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
    fairOdds1: Double? = null,
    fairOdds2: Double? = null,
    odds1: Double? = null,
    odds2: Double? = null,
    ev1: Double? = null,
    ev2: Double? = null,
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
        // Cote juste (théorique, 1/proba) + EV réelle si une cote bookmaker
        // est disponible (uniquement le marché "match", voir bot/api.py).
        if (fairOdds1 != null || fairOdds2 != null) {
            Row(modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                Text(oddsLine(fairOdds1, odds1, ev1),
                    style = MaterialTheme.typography.labelSmall,
                    fontSize = 10.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(oddsLine(fairOdds2, odds2, ev2),
                    style = MaterialTheme.typography.labelSmall,
                    fontSize = 10.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
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

/** "cote 1.85" seul (marchés sans bookmaker), ou "cote 2.10 · EV +3.2%" quand
 * une vraie cote (et donc une vraie EV) est disponible (marché "match"). */
private fun oddsLine(fair: Double?, real: Double?, ev: Double?): String {
    if (fair == null) return ""
    val odds = real ?: fair
    val base = "cote ${String.format(Locale.US, "%.2f", odds)}"
    return if (ev != null) "$base · EV ${String.format(Locale.US, "%+.1f", ev)}%" else base
}

@Preview(showBackground = true, backgroundColor = 0xFF0A0E14)
@Composable
private fun BetBuilderPreview() {
    MaterialTheme {
        Box(Modifier.padding(16.dp)) {
            BetBuilderView(
                "Sinner", "Alcaraz",
                bb = BetBuilder(
                    match = BetMarket(72.8, 27.2, fair_odds1 = 1.37, fair_odds2 = 3.68,
                        odds1 = 1.45, odds2 = 3.40, ev1 = 5.6, ev2 = -6.5),
                    set2 = BetMarket(65.7, 34.3, fair_odds1 = 1.52, fair_odds2 = 2.91),
                    total_sets = com.tennisboss.app.data.TotalSetsMarket(
                        prob_over = 45.1, prob_under = 54.9,
                        fair_odds_over = 2.22, fair_odds_under = 1.82),
                    handicap = BetMarket(43.2, 11.8, fair_odds1 = 2.31, fair_odds2 = 8.47),
                    third_set_prob = 45.1,
                    correct_score = mapOf(
                        "Sinner 2-0" to 43.2,
                        "Sinner 2-1" to 29.6,
                        "Alcaraz 2-1" to 27.2,
                    ),
                    best_market = "match",
                    best_market_confidence = 72.8,
                ),
                totalAcesAvg = 8.5,
                totalPointsOver = 62.1,
            )
        }
    }
}

package com.tennisboss.app.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import com.tennisboss.app.data.BetBuilder
import com.tennisboss.app.data.BetMarket

private val P1Color = Color(0xFF4F8CFF)
private val P2Color = Color(0xFF00C2A8)
private val AccentColor = Color(0xFF00E5A0)

/**
 * Bet Builder : marchés dérivés de la proba du 1er set (vainqueur match, 2e set,
 * match en 3 sets, score exact). 100 % issu du modèle, sans données inventées.
 */
@Composable
fun BetBuilderView(name1: String, name2: String, bb: BetBuilder) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(
            "🎰 Bet Builder",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )

        MarketBar("Vainqueur du match", name1, bb.match.prob1, name2, bb.match.prob2)
        MarketBar("Vainqueur du 2e set", name1, bb.set2.prob1, name2, bb.set2.prob2)

        // Match en 3 sets.
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("Match en 3 sets", style = MaterialTheme.typography.bodyMedium)
            Text(
                "${fmt(bb.third_set_prob)}",
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Bold,
                color = AccentColor,
            )
        }

        // Score exact, trié par probabilité décroissante.
        if (bb.correct_score.isNotEmpty()) {
            Text(
                "Score exact (en sets)",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
            )
            bb.correct_score.entries
                .sortedByDescending { it.value }
                .forEach { (label, prob) -> ScoreRow(label, prob) }
        }
    }
}

@Composable
private fun MarketBar(title: String, n1: String, p1: Double, n2: String, p2: Double) {
    val frac1 = (p1 / 100.0).toFloat().coerceIn(0f, 1f)
    val anim by animateFloatAsState(frac1, tween(600), label = "m")
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(26.dp)
                .clip(RoundedCornerShape(7.dp)),
        ) {
            Box(
                modifier = Modifier
                    .weight(anim.coerceIn(0.02f, 0.98f))
                    .fillMaxHeight()
                    .background(P1Color),
                contentAlignment = Alignment.CenterStart,
            ) {
                if (anim > 0.18f) Text(
                    fmt(p1), color = Color.White, fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.labelSmall,
                    modifier = Modifier.padding(start = 6.dp),
                )
            }
            Box(
                modifier = Modifier
                    .weight((1f - anim).coerceIn(0.02f, 0.98f))
                    .fillMaxHeight()
                    .background(P2Color),
                contentAlignment = Alignment.CenterEnd,
            ) {
                if (anim < 0.82f) Text(
                    fmt(p2), color = Color.White, fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.labelSmall,
                    modifier = Modifier.padding(end = 6.dp),
                )
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(n1, style = MaterialTheme.typography.labelSmall, color = P1Color)
            Text(n2, style = MaterialTheme.typography.labelSmall, color = P2Color)
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
            Text(label, style = MaterialTheme.typography.bodySmall)
            Text(fmt(prob), style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.SemiBold)
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(3.dp))
                .background(Color(0x22000000)),
        ) {
            Box(Modifier.fillMaxWidth(anim).fillMaxHeight().background(AccentColor))
        }
    }
}

private fun fmt(v: Double): String = String.format("%.1f%%", v)

@Preview(showBackground = true)
@Composable
private fun BetBuilderPreview() {
    BetBuilderView(
        "Jannik Sinner", "Carlos Alcaraz",
        BetBuilder(
            match = BetMarket(72.8, 27.2),
            set2 = BetMarket(65.7, 34.3),
            third_set_prob = 45.1,
            correct_score = mapOf(
                "Jannik Sinner 2-0" to 43.2,
                "Jannik Sinner 2-1" to 29.6,
                "Carlos Alcaraz 2-1" to 15.5,
                "Carlos Alcaraz 2-0" to 11.8,
            ),
        ),
    )
}

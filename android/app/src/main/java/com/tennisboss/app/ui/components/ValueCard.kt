package com.tennisboss.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.tennisboss.app.data.HoneypotSignal
import com.tennisboss.app.data.SteamMove
import com.tennisboss.app.data.ValueComparison
import com.tennisboss.app.data.ValueOdds
import com.tennisboss.app.ui.SignalChip
import com.tennisboss.app.ui.utcToLocalLabel

private val GoodColor = Color(0xFF00E5A0)
private val BadColor = Color(0xFFFF5C7A)
private val P1Color = Color(0xFF4F8CFF)
private val P2Color = Color(0xFF00C2A8)

/**
 * Card « value bet » — extraite de ValueScreen.kt pour être réutilisable
 * ailleurs (ex. DashboardScreen). Affiche : proba IA vs marché par joueur,
 * cotes + EV par côté, edge %, mouvement des odds (steam move), honeypot et
 * badge confiance.
 */
@Composable
fun ValueCard(c: ValueComparison, onClick: (() -> Unit)? = null) {
    Card(
        modifier = Modifier.fillMaxWidth().let { if (onClick != null) it.clickable { onClick() } else it },
        elevation = CardDefaults.cardElevation(2.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            // ── Header : ligue + date + badge ────────────────────────────────
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        c.league.ifBlank { "—" },
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    val dt = utcToLocalLabel(c.date)
                    if (dt.isNotBlank()) {
                        Text(dt,
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                SurfaceBadge(c.surface)
                if (c.surface != null) Spacer(Modifier.size(4.dp))
                if (c.confidence_label.isNotBlank()) {
                    ConfidenceBadge(c.confidence_label, c.confidence)
                    Spacer(Modifier.size(6.dp))
                }
                EdgeIndicator(c.best_ev, c.value, c.filter_reason)
            }

            Text("${c.player1}  vs  ${c.player2}", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)

            // Comparaison Proba IA vs Marché
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                ProbCompareRow(c.player1, c.blend_match_prob1, c.market_match_prob1, P1Color)
                ProbCompareRow(c.player2, c.blend_match_prob2, c.market_match_prob2, P2Color)
            }

            // Cotes + EV par côté.
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                SideBox(Modifier.weight(1f), c.player1, c.odds.home, c.ev1,
                    highlight = c.best_side == c.player1)
                SideBox(Modifier.weight(1f), c.player2, c.odds.away, c.ev2,
                    highlight = c.best_side == c.player2)
            }

            // Signaux Spéciaux (Honeypot, Steam Move)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                c.honeypot?.let { hp ->
                    if (hp.flag) {
                        SignalChip("⚠️ HONEYPOT +${String.format("%.1f", hp.edge_pct)}%", Color(0xFFFFD600))
                    }
                }
                c.steam_move?.let { sm ->
                    val side = if (sm.side == "home") "J1" else "J2"
                    SignalChip("📊 Steam Move $side ${String.format("%.0f", sm.move_pct)}%", Color(0xFF4FC3F7))
                }
            }

            if (c.value && c.best_side != null) {
                val odd = if (c.best_side == c.player1) c.odds.home else c.odds.away
                Text(
                    "Pari conseillé : ${c.best_side} @ $odd (EV ${fmtSigned(c.best_ev)})",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold,
                    color = GoodColor,
                )
            }
        }
    }
}

@Composable
private fun ProbCompareRow(name: String, model: Double, market: Double, color: Color) {
    val edge = model - market
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(name, style = MaterialTheme.typography.bodySmall, color = color,
            fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
        Text(
            "estimé ${fmt(model)} · marché ${fmt(market)}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            "  ${fmtSigned(edge)}",
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Bold,
            color = if (edge >= 0) GoodColor else BadColor,
        )
    }
}

@Composable
private fun SideBox(
    modifier: Modifier,
    name: String,
    odd: Double,
    ev: Double,
    highlight: Boolean,
) {
    val border = if (highlight) GoodColor.copy(alpha = 0.18f) else Color.Transparent
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(10.dp))
            .background(border)
            .padding(8.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(name, style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
        Text("cote $odd", style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold)
        Text(
            "EV ${fmtSigned(ev)}",
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Bold,
            color = if (ev >= 0) GoodColor else BadColor,
        )
    }
}

private fun fmt(v: Double): String = String.format("%.0f%%", v)

@Preview(showBackground = true)
@Composable
private fun ValueCardPreview() {
    MaterialTheme {
        ValueCard(
            ValueComparison(
                player1 = "Jannik Sinner",
                player2 = "Carlos Alcaraz",
                league = "ATP Wimbledon",
                confidence = 0.72,
                confidence_label = "élevée",
                blend_match_prob1 = 58.0,
                blend_match_prob2 = 42.0,
                market_match_prob1 = 50.0,
                market_match_prob2 = 50.0,
                odds = ValueOdds(home = 1.85, away = 2.05),
                ev1 = 8.4,
                ev2 = -3.1,
                best_side = "Jannik Sinner",
                best_ev = 8.4,
                value = true,
                surface = "grass",
                steam_move = SteamMove(side = "home", move_pct = 6.0, n_snapshots = 4),
                honeypot = HoneypotSignal(flag = false),
            )
        )
    }
}

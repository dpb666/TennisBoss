package com.tennisboss.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.tennisboss.app.data.H2H
import com.tennisboss.app.data.H2HMeeting

private val P1Color = Color(0xFF4F8CFF)
private val P2Color = Color(0xFF00C2A8)

/**
 * Vue « Face-à-face » : bilan des confrontations directes entre deux joueurs,
 * issu de l'historique des matchs (table `matches`).
 */
@Composable
fun H2HView(h2h: H2H) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            "Face-à-face",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )

        if (h2h.total == 0) {
            Text(
                "Aucune confrontation directe en base.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
            return@Column
        }

        // Score central : J1 X – Y J2.
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ScoreSide(h2h.player1, h2h.wins1, P1Color, h2h.leader == h2h.player1, Alignment.Start)
            Text(
                "–",
                modifier = Modifier.padding(horizontal = 8.dp),
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.outline,
            )
            ScoreSide(h2h.player2, h2h.wins2, P2Color, h2h.leader == h2h.player2, Alignment.End)
        }

        // Barre de répartition des victoires.
        val frac = if (h2h.total > 0) h2h.wins1.toFloat() / h2h.total else 0.5f
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(5.dp)),
        ) {
            Box(
                Modifier
                    .weight(frac.coerceIn(0.02f, 0.98f))
                    .background(P1Color)
                    .padding(vertical = 5.dp),
            )
            Box(
                Modifier
                    .weight((1f - frac).coerceIn(0.02f, 0.98f))
                    .background(P2Color)
                    .padding(vertical = 5.dp),
            )
        }

        // Dernières confrontations.
        h2h.meetings.take(5).forEach { MeetingRow(it) }
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.ScoreSide(
    name: String,
    wins: Int,
    color: Color,
    isLeader: Boolean,
    align: Alignment.Horizontal,
) {
    Column(
        modifier = Modifier.weight(1f),
        horizontalAlignment = align,
    ) {
        Text(
            "$wins",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
            color = color,
        )
        Text(
            name + if (isLeader) "  ⭐" else "",
            style = MaterialTheme.typography.bodySmall,
            fontWeight = if (isLeader) FontWeight.Bold else FontWeight.Normal,
            textAlign = if (align == Alignment.End) TextAlign.End else TextAlign.Start,
        )
    }
}

@Composable
private fun MeetingRow(m: H2HMeeting) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            "${m.date} · ${m.tour.uppercase()}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.outline,
        )
        Text(
            "🏆 ${m.winner}",
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun H2HPreview() {
    H2HView(
        H2H(
            player1 = "Jannik Sinner", player2 = "Carlos Alcaraz",
            wins1 = 4, wins2 = 5, total = 9, leader = "Carlos Alcaraz",
            meetings = listOf(
                H2HMeeting("12/05/2024", "atp", "Carlos Alcaraz"),
                H2HMeeting("10/11/2023", "atp", "Jannik Sinner"),
                H2HMeeting("02/06/2023", "atp", "Carlos Alcaraz"),
            ),
        ),
    )
}

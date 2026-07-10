package com.tennisboss.app.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tennisboss.app.data.FormMatch
import com.tennisboss.app.data.PlayerDetail
import com.tennisboss.app.ui.PlayerDetailState

private val WinColor = Color(0xFF2E9E5B)
private val LossColor = Color(0xFFE5484D)
private val BarColor = Color(0xFF4F8CFF)
private val TrackColor = Color(0x22000000)

/**
 * Fiche joueur en bottom sheet : force, bilan V/D et forme récente.
 * Exploite l'historique des 16k matchs servi par /api/player.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlayerDetailSheet(
    state: PlayerDetailState,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 20.dp, end = 20.dp, bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            when (state) {
                is PlayerDetailState.Loading, is PlayerDetailState.Idle ->
                    Box(Modifier.fillMaxWidth().padding(40.dp), Alignment.Center) {
                        CircularProgressIndicator()
                    }
                is PlayerDetailState.Error ->
                    Text(state.message, color = MaterialTheme.colorScheme.error)
                is PlayerDetailState.Success ->
                    DetailContent(state.data)
            }
        }
    }
}

@Composable
private fun DetailContent(d: PlayerDetail) {
    // En-tête : nom + tour + force.
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(d.name, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(
                buildString {
                    if (d.tour.isNotBlank()) append(d.tour.uppercase()).append(" · ")
                    append("${d.matches} matchs en base")
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
        Column(horizontalAlignment = Alignment.End) {
            Text(
                pct(d.win_prob_vs_avg),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
                color = BarColor,
            )
            Text("force", style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.outline)
        }
    }

    if (!d.confident) {
        Text(
            "⚠️ Peu de données — fiche à prendre avec prudence.",
            style = MaterialTheme.typography.bodySmall,
            color = Color(0xFFB26A00),
        )
    }

    // Bilan victoires / défaites.
    d.record?.let { r ->
        SectionTitle("Bilan")
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("${r.wins} V – ${r.losses} D", fontWeight = FontWeight.SemiBold)
            Text("${pct(r.win_rate)} de victoires", color = MaterialTheme.colorScheme.outline,
                style = MaterialTheme.typography.bodyMedium)
        }
        val rate by animateFloatAsState(
            r.win_rate.toFloat().coerceIn(0f, 1f), tween(600), label = "rate")
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(12.dp)
                .clip(RoundedCornerShape(6.dp))
                .background(LossColor),
        ) {
            Box(Modifier.fillMaxWidth(rate).fillMaxHeight().background(WinColor))
        }
    }

    // ELO : signal le plus fort du modèle, avec rang parmi les joueurs du même tour.
    d.elo?.let { elo ->
        SectionTitle("ELO")
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(elo.rating.toInt().toString(), style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold, color = BarColor)
            if (elo.rank != null && elo.n_ranked != null) {
                Text("#${elo.rank} sur ${elo.n_ranked} (${d.tour.uppercase()})",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.outline)
            }
        }
        if (elo.by_surface.isNotEmpty()) {
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                elo.by_surface.forEach { (surf, rating) ->
                    Text("$surf : ${rating.toInt()}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline)
                }
            }
        }
    }

    // Forces du modèle.
    SectionTitle("Forces")
    StatBar("Service", d.serve)
    StatBar("Retour (1er service adverse)", d.return1)
    StatBar("Retour (2e service adverse)", d.return2)
    StatBar("Forme récente", d.recent)

    // Forme récente : derniers résultats.
    if (d.form.isNotEmpty()) {
        SectionTitle("Forme récente (du plus récent)")
        Row(
            modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            d.form.forEach { FormChip(it) }
        }
        d.form.firstOrNull()?.let {
            val verb = if (it.result == "W") "✅ Victoire" else "❌ Défaite"
            Text(
                "Dernier : $verb vs ${it.opponent} — ${it.date}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}

@Composable
private fun SectionTitle(t: String) {
    Text(t, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
}

@Composable
private fun StatBar(label: String, value: Double) {
    val v by animateFloatAsState(value.toFloat().coerceIn(0f, 1f), tween(600), label = label)
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(label, style = MaterialTheme.typography.bodySmall)
            Text(pctRaw(value), style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.SemiBold)
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(8.dp)
                .clip(RoundedCornerShape(4.dp))
                .background(TrackColor),
        ) {
            Box(Modifier.fillMaxWidth(v).fillMaxHeight().background(BarColor))
        }
    }
}

@Composable
private fun FormChip(m: FormMatch) {
    val win = m.result == "W"
    Box(
        modifier = Modifier
            .size(28.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(if (win) WinColor else LossColor),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            if (win) "V" else "D",
            color = Color.White,
            fontWeight = FontWeight.Bold,
            fontSize = 13.sp,
        )
    }
}

private fun pct(v: Double): String = String.format("%.0f%%", v * 100)
private fun pctRaw(v: Double): String = String.format("%.0f", v * 100)

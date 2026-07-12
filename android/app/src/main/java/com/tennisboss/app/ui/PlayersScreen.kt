package com.tennisboss.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.FollowPlayerRequest
import com.tennisboss.app.data.FormMatch
import com.tennisboss.app.data.H2H
import com.tennisboss.app.data.Player
import com.tennisboss.app.data.PlayerDetail
import kotlinx.coroutines.launch
import java.util.Locale

private val P1Color = Color(0xFF4F8CFF)
private val P2Color = Color(0xFF00C2A8)
private val AccentColor = Color(0xFF00E5A0)
private val WinColor = Color(0xFF00C853)
private val LossColor = Color(0xFFFF5C7A)

@Composable
fun PlayersScreen(
    selectedP1: String,
    selectedP2: String,
    onPlayerClick: (String) -> Unit,
    vm: PlayerCompareViewModel = viewModel(),
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("Comparaison joueurs", style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold)

        // ── 2 champs de recherche côte à côte ─────────────────────────────────
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PlayerSearchField(
                label = "Joueur A",
                query = vm.queryA,
                selected = vm.selectedA,
                loading = vm.loadingA,
                results = vm.resultsA,
                color = P1Color,
                modifier = Modifier.weight(1f),
                onQueryChange = vm::onQueryA,
                onSelect = { vm.selectA(it); onPlayerClick(it) },
                onClear = vm::clearA,
            )
            PlayerSearchField(
                label = "Joueur B",
                query = vm.queryB,
                selected = vm.selectedB,
                loading = vm.loadingB,
                results = vm.resultsB,
                color = P2Color,
                modifier = Modifier.weight(1f),
                onQueryChange = vm::onQueryB,
                onSelect = { vm.selectB(it); onPlayerClick(it) },
                onClear = vm::clearB,
            )
        }

        val cs = vm.compare
        when {
            cs.loading -> Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = AccentColor, modifier = Modifier.padding(24.dp))
            }
            cs.error != null -> Text(cs.error!!, color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall)
            cs.p1 != null -> CompareView(cs.p1, cs.p2, cs.h2h)
            else -> EmptyHint()
        }
    }
}

// ── Champ de recherche avec dropdown ─────────────────────────────────────────
@Composable
private fun PlayerSearchField(
    label: String,
    query: String,
    selected: String?,
    loading: Boolean,
    results: List<Player>,
    color: Color,
    modifier: Modifier,
    onQueryChange: (String) -> Unit,
    onSelect: (String) -> Unit,
    onClear: () -> Unit,
) {
    Column(modifier = modifier) {
        OutlinedTextField(
            value = query,
            onValueChange = onQueryChange,
            label = { Text(label, style = MaterialTheme.typography.labelSmall) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            trailingIcon = {
                if (query.isNotBlank()) {
                    IconButton(onClick = onClear, modifier = Modifier.size(20.dp)) {
                        Icon(Icons.Default.Close, contentDescription = null,
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(16.dp))
                    }
                }
            },
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = color,
                focusedLabelColor = color,
            ),
        )
        if (loading) LinearProgressIndicator(modifier = Modifier.fillMaxWidth().height(2.dp), color = color)
        if (results.isNotEmpty() && selected == null) {
            Card(modifier = Modifier.fillMaxWidth()) {
                LazyColumn(modifier = Modifier.heightIn(max = 160.dp)) {
                    items(results) { p ->
                        Row(
                            modifier = Modifier.fillMaxWidth()
                                .clickable { onSelect(p.name) }
                                .padding(horizontal = 12.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(p.name, style = MaterialTheme.typography.bodySmall,
                                modifier = Modifier.weight(1f))
                            Text(p.tour.uppercase(), style = MaterialTheme.typography.labelSmall,
                                color = color, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }
    }
}

// ── Vue comparaison principale ────────────────────────────────────────────────
@Composable
private fun CompareView(p1: PlayerDetail, p2: PlayerDetail?, h2h: H2H?) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {

        // ── Noms + tour ───────────────────────────────────────────────────────
        item {
            Row(modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically) {
                PlayerNameBadge(p1, P1Color, Alignment.Start)
                if (p2 != null) {
                    Text("VS", style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.ExtraBold,
                        color = MaterialTheme.colorScheme.outline)
                    PlayerNameBadge(p2, P2Color, Alignment.End)
                } else {
                    // Suivre un seul joueur à la fois : pas de bouton en mode
                    // comparaison (ambiguïté sur lequel des deux suivre).
                    FollowButton(p1)
                }
            }
        }

        // ── Stats comparées ───────────────────────────────────────────────────
        if (p2 != null) {
            item { SectionTitle("📊 Statistiques") }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    StatBar("Service %", p1.serve * 100, p2.serve * 100, P1Color, P2Color,
                        suffix = "%", higherIsBetter = true)
                    StatBar("Retour 1re balle", p1.return1 * 100, p2.return1 * 100, P1Color, P2Color,
                        suffix = "%", higherIsBetter = true)
                    StatBar("Retour 2e balle", p1.return2 * 100, p2.return2 * 100, P1Color, P2Color,
                        suffix = "%", higherIsBetter = true)
                    StatBar("Forme récente", p1.recent * 100, p2.recent * 100, P1Color, P2Color,
                        suffix = "%", higherIsBetter = true)
                    StatBar("Rating ELO", p1.elo?.rating ?: 1500.0, p2.elo?.rating ?: 1500.0,
                        P1Color, P2Color, digits = 0, higherIsBetter = true)
                    StatBar("Win % vs moy.", p1.win_prob_vs_avg * 100, p2.win_prob_vs_avg * 100,
                        P1Color, P2Color, suffix = "%", higherIsBetter = true)
                }
            }

            // ── Record ─────────────────────────────────────────────────────────
            item { SectionTitle("🏆 Bilan") }
            item {
                Row(modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    RecordCard(p1, P1Color, Modifier.weight(1f))
                    RecordCard(p2, P2Color, Modifier.weight(1f))
                }
            }

            // ── H2H ────────────────────────────────────────────────────────────
            if (h2h != null && h2h.total > 0) {
                item { SectionTitle("🤜 Face-à-face (${h2h.total} matchs)") }
                item { H2HView(h2h, p1.name, p2.name) }
            }

            // ── Forme récente côte à côte ──────────────────────────────────────
            item { SectionTitle("📅 Forme récente") }
            item {
                Row(modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FormColumn(p1.form.take(8), p1.name, P1Color, Modifier.weight(1f))
                    FormColumn(p2.form.take(8), p2.name, P2Color, Modifier.weight(1f))
                }
            }

        } else {
            // ── Profil seul (aucun joueur B sélectionné) ──────────────────────
            item { SectionTitle("📊 Profil") }
            item { SingleProfile(p1, P1Color) }
            item { SectionTitle("📅 Derniers matchs") }
            item { FormColumn(p1.form.take(10), p1.name, P1Color, Modifier.fillMaxWidth()) }
        }
    }
}

// ── Composables utilitaires ───────────────────────────────────────────────────

@Composable
private fun PlayerNameBadge(p: PlayerDetail, color: Color, align: Alignment.Horizontal) {
    Column(horizontalAlignment = align) {
        Text(p.name.substringAfterLast(" "),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.ExtraBold, color = color)
        Text(p.name.substringBeforeLast(" ", ""),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Surface(color = color.copy(alpha = 0.15f), shape = RoundedCornerShape(4.dp)) {
            Text(p.tour.uppercase(),
                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold, color = color)
        }
    }
}

/**
 * Suivre/ne plus suivre un joueur — signal explicite de personnalisation
 * (bot/recommendations.py::favorite_players priorise les suivis explicites
 * sur l'inférence par fréquence de recherche). Mise à jour optimiste avec
 * retour arrière silencieux en cas d'échec réseau.
 */
@Composable
private fun FollowButton(player: PlayerDetail) {
    var followed by remember(player.name) { mutableStateOf(player.followed) }
    var loading by remember(player.name) { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    FilledTonalButton(
        onClick = {
            if (loading) return@FilledTonalButton
            val next = !followed
            followed = next
            loading = true
            scope.launch {
                try {
                    if (next) ApiClient.create().followPlayer(FollowPlayerRequest(player.name))
                    else ApiClient.create().unfollowPlayer(FollowPlayerRequest(player.name))
                } catch (_: Exception) {
                    followed = !next  // échec réseau : reviens à l'état précédent
                } finally {
                    loading = false
                }
            }
        },
        colors = ButtonDefaults.filledTonalButtonColors(
            containerColor = if (followed) AccentColor.copy(alpha = 0.2f)
                             else MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Text(
            if (followed) "✓ Suivi" else "+ Suivre",
            style = MaterialTheme.typography.labelMedium,
            color = if (followed) AccentColor else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(top = 4.dp))
}

@Composable
private fun StatBar(
    label: String,
    v1: Double, v2: Double,
    c1: Color, c2: Color,
    suffix: String = "",
    digits: Int = 0,
    higherIsBetter: Boolean = true,
) {
    val total = v1 + v2
    val frac1 = if (total > 0) (v1 / total).toFloat().coerceIn(0.05f, 0.95f) else 0.5f
    val win1 = (v1 > v2) == higherIsBetter

    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Row(modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically) {
            Text(fmt(v1, digits, suffix),
                style = MaterialTheme.typography.labelSmall,
                fontWeight = if (win1) FontWeight.ExtraBold else FontWeight.Normal,
                color = if (win1) c1 else MaterialTheme.colorScheme.onSurfaceVariant)
            Text(label, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            Text(fmt(v2, digits, suffix),
                style = MaterialTheme.typography.labelSmall,
                fontWeight = if (!win1) FontWeight.ExtraBold else FontWeight.Normal,
                color = if (!win1) c2 else MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Row(modifier = Modifier.fillMaxWidth().height(6.dp)
            .clip(CircleShape)) {
            Box(Modifier.weight(frac1).fillMaxHeight().background(c1))
            Box(Modifier.weight(1f - frac1).fillMaxHeight().background(c2))
        }
    }
}

@Composable
private fun RecordCard(p: PlayerDetail, color: Color, modifier: Modifier) {
    val rec = p.record
    Surface(modifier = modifier, shape = RoundedCornerShape(10.dp),
        color = MaterialTheme.colorScheme.surfaceVariant) {
        Column(modifier = Modifier.padding(10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(p.name.substringAfterLast(" ").take(10),
                style = MaterialTheme.typography.labelSmall, color = color,
                fontWeight = FontWeight.Bold)
            if (rec != null) {
                Text("${rec.wins}V – ${rec.losses}D",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.ExtraBold,
                    color = MaterialTheme.colorScheme.onSurface)
                Text("${String.format(Locale.US, "%.0f", rec.win_rate * 100)}% victoires",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("${rec.total} matchs",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline)
            }
        }
    }
}

@Composable
private fun SingleProfile(p: PlayerDetail, color: Color) {
    Surface(shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)) {
            StatRow("Service", p.serve * 100, color, "%")
            StatRow("Retour 1re balle", p.return1 * 100, color, "%")
            StatRow("Retour 2e balle", p.return2 * 100, color, "%")
            StatRow("Forme récente", p.recent * 100, color, "%")
            StatRow("Rating ELO", p.elo?.rating ?: 1500.0, color, "", digits = 0)
            p.elo?.let { elo ->
                if (elo.rank != null && elo.n_ranked != null) {
                    Text("#${elo.rank} sur ${elo.n_ranked} (${p.tour.uppercase()})",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline)
                }
            }
            StatRow("Win % vs moy.", p.win_prob_vs_avg * 100, color, "%")
            p.record?.let { rec ->
                HorizontalDivider(thickness = 0.5.dp,
                    color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f))
                Row(modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Bilan", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text("${rec.wins}V – ${rec.losses}D  (${
                        String.format(Locale.US, "%.0f", rec.win_rate * 100)}%)",
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface)
                }
            }
        }
    }
}

@Composable
private fun StatRow(label: String, value: Double, color: Color, suffix: String, digits: Int = 0) {
    Row(modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(fmt(value, digits, suffix), style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold, color = color)
    }
}

@Composable
private fun H2HView(h2h: H2H, name1: String, name2: String) {
    val s1 = name1.substringAfterLast(" ")
    val s2 = name2.substringAfterLast(" ")
    val total = h2h.total.toFloat().coerceAtLeast(1f)
    val frac1 = (h2h.wins1 / total).coerceIn(0.05f, 0.95f)

    Surface(shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                Text("$s1  ${h2h.wins1}",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.ExtraBold, color = P1Color)
                Text("–", style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("${h2h.wins2}  $s2",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.ExtraBold, color = P2Color)
            }
            Row(modifier = Modifier.fillMaxWidth().height(8.dp).clip(CircleShape)) {
                Box(Modifier.weight(frac1).fillMaxHeight().background(P1Color))
                Box(Modifier.weight(1f - frac1).fillMaxHeight().background(P2Color))
            }
            h2h.meetings.take(5).forEach { m ->
                val winColor = if (m.winner.contains(name1.substringAfterLast(" "), ignoreCase = true)
                    || m.winner == name1) P1Color else P2Color
                Row(modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(m.date, style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline)
                    Text("✓ ${m.winner.substringAfterLast(" ")}",
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.SemiBold, color = winColor)
                }
            }
        }
    }
}

@Composable
private fun FormColumn(form: List<FormMatch>, name: String, color: Color, modifier: Modifier) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(name.substringAfterLast(" ").take(10),
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold, color = color)
        form.forEach { m ->
            val isWin = m.result == "W"
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                Box(modifier = Modifier.size(18.dp).clip(CircleShape)
                    .background(if (isWin) WinColor else LossColor),
                    contentAlignment = Alignment.Center) {
                    Text(m.result, fontSize = 9.sp, fontWeight = FontWeight.ExtraBold,
                        color = Color.White)
                }
                Text(m.opponent.substringAfterLast(" ").take(10),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun EmptyHint() {
    Box(modifier = Modifier.fillMaxWidth().padding(top = 32.dp),
        contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("🎾", fontSize = 40.sp)
            Text("Cherche un joueur pour voir son profil",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Ajoute un 2e joueur pour comparer",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline)
        }
    }
}

private fun fmt(v: Double, digits: Int = 0, suffix: String = ""): String =
    "${String.format(Locale.US, "%.${digits}f", v)}$suffix"

package com.tennisboss.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Snackbar
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.InplayBestPick
import com.tennisboss.app.data.InplayMarket
import com.tennisboss.app.data.InplayMatchMarkets
import com.tennisboss.app.data.InplayMarketsResponse
import com.tennisboss.app.data.InplayPickItem
import com.tennisboss.app.data.InplayPicksResponse
import com.tennisboss.app.data.InplayROIStats
import com.tennisboss.app.data.LiveMatch
import com.tennisboss.app.data.LivePrediction
import com.tennisboss.app.ui.components.SkeletonList
import kotlinx.coroutines.delay

private val LiveRed    = Color(0xFFFF3B3B)
private val GreenEV    = Color(0xFF00E5A0)
private val ScoreGold  = Color(0xFFFFD600)
private val ServeClr   = Color(0xFF4FC3F7)
private val AmberMkt   = Color(0xFFFFB020)
private val TealMkt    = Color(0xFF00C2A8)
private val PurpleMkt  = Color(0xFF9C7EFF)

@Composable
fun LiveScreen(vm: LiveViewModel = viewModel()) {

    DisposableEffect(Unit) {
        vm.startAutoRefresh()
        onDispose { vm.stopAutoRefresh() }
    }

    // Toast auto-dismiss
    val toast = vm.pickToastMessage
    if (toast != null) {
        LaunchedEffect(toast) {
            delay(2500)
            vm.clearToast()
        }
    }

    Box(Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            // ── Header ───────────────────────────────────────────────────────
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    LiveDot()
                    Spacer(Modifier.width(8.dp))
                    Column {
                        Text("Live", style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold)
                        val sub = when (val s = vm.state) {
                            is LiveUiState.Success -> "${s.data.count} match${if (s.data.count > 1) "s" else ""} en cours"
                            else -> "Matchs tennis en cours"
                        }
                        Text(sub, style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                val s = vm.state
                if (s is LiveUiState.Success) {
                    Text(
                        "↺ ${s.refreshIn}s",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            // ── Content ──────────────────────────────────────────────────────
            when (val s = vm.state) {
                is LiveUiState.Loading -> SkeletonList(count = 3)
                is LiveUiState.Error   -> Text(s.message, color = MaterialTheme.colorScheme.error)
                is LiveUiState.Success -> {
                    if (s.data.matches.isEmpty()) {
                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally,
                                verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text("Aucun match en cours",
                                    style = MaterialTheme.typography.bodyLarge,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Text("Prochain refresh dans ${s.refreshIn}s",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    } else {
                        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            // ROI inplay banner (si picks enregistrés)
                            s.picksResp?.let { pr ->
                                if (pr.stats.total > 0) {
                                    item(key = "roi_banner") { InplayROIBanner(pr) }
                                }
                            }

                            s.bestPick?.takeIf { (it.prediction?.confidence ?: 0.0) >= 0.4 }?.let { pick ->
                                item(key = "best_pick") {
                                    BestPickBanner(pick, onTake = {
                                        val pred = pick.prediction ?: return@BestPickBanner
                                        val fav = pred.favorite ?: return@BestPickBanner
                                        val setScore = "${pick.sets_home}-${pick.sets_away}"
                                        vm.openPickDialog(
                                            player1 = pick.player1, player2 = pick.player2,
                                            league = pick.league, marketType = "set_winner",
                                            marketLabel = "Gagnant match", pick = fav,
                                            odds = pick.fav_odds, prob = pred.prob1,
                                            oddsHome = pick.live_odds?.home,
                                            oddsAway = pick.live_odds?.away,
                                            oddsBook = pick.live_odds?.books?.joinToString(", "),
                                            score = setScore, setsHome = pick.sets_home,
                                            setsAway = pick.sets_away, minute = pick.minute,
                                            eventId = pick.event_id,
                                        )
                                    })
                                }
                            }

                            s.markets?.let { mkts ->
                                if (mkts.matches.isNotEmpty()) {
                                    item(key = "markets_header") {
                                        InplayPicksSection(mkts, liveMatches = s.data.matches, onTakePick = { match, mkt ->
                                            val lm = s.data.matches.find { it.event_id == match.event_id }
                                            vm.openPickDialog(
                                                player1 = match.player1, player2 = match.player2,
                                                league = match.league, marketType = mkt.type,
                                                marketLabel = mkt.label, pick = mkt.pick,
                                                odds = mkt.odds, prob = mkt.prob,
                                                oddsHome = lm?.live_odds?.home,
                                                oddsAway = lm?.live_odds?.away,
                                                oddsBook = lm?.live_odds?.books?.joinToString(", "),
                                                score = match.score_display,
                                                setsHome = match.sets_home, setsAway = match.sets_away,
                                                minute = match.minute, eventId = match.event_id,
                                            )
                                        })
                                    }
                                }
                            }

                            // Picks récents en attente (résultat à saisir)
                            s.picksResp?.let { pr ->
                                val pending = pr.picks.filter { it.result == null }.take(5)
                                val recentSettled = pr.picks.filter { it.result != null }.take(2)
                                if (pending.isNotEmpty() || recentSettled.isNotEmpty()) {
                                    item(key = "pending_picks") {
                                        PendingPicksSection(
                                            pending = pending,
                                            recentSettled = recentSettled,
                                            onSettle = { id, res -> vm.settlePick(id, res) },
                                            onDelete = { id -> vm.deletePick(id) },
                                        )
                                    }
                                }
                            }

                            if (s.data.matches.isNotEmpty()) {
                                item(key = "matches_header") {
                                    Text(
                                        "📺 Matchs en direct",
                                        style = MaterialTheme.typography.titleSmall,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier.padding(top = 4.dp),
                                    )
                                }
                            }
                            items(s.data.matches, key = { it.event_id }) { match ->
                                LiveMatchCard(match, s.markets, onTakePick = { match2, mkt ->
                                    vm.openPickDialog(
                                        player1 = match2.player1, player2 = match2.player2,
                                        league = match2.league, marketType = mkt.type,
                                        marketLabel = mkt.label, pick = mkt.pick,
                                        odds = mkt.odds, prob = mkt.prob,
                                        oddsHome = match.live_odds?.home,
                                        oddsAway = match.live_odds?.away,
                                        oddsBook = match.live_odds?.books?.joinToString(", "),
                                        score = match2.score_display,
                                        setsHome = match2.sets_home, setsAway = match2.sets_away,
                                        minute = match2.minute, eventId = match2.event_id,
                                    )
                                })
                            }
                        }
                    }
                }
                else -> {}
            }
        }

        // Toast
        if (toast != null) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 16.dp, start = 16.dp, end = 16.dp),
            ) {
                Snackbar { Text(toast) }
            }
        }
    }

    // Pick dialog
    vm.pickDialog?.let { d ->
        PickConfirmDialog(
            dialog = d,
            onConfirm = { stake -> vm.confirmPick(stake) },
            onDismiss = { vm.dismissPickDialog() },
        )
    }
}

// ── ROI Inplay Banner ────────────────────────────────────────────────────────

@Composable
private fun InplayROIBanner(pr: InplayPicksResponse) {
    val stats = pr.stats
    val roiColor = if (stats.roi_pct >= 0) GreenEV else LiveRed
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color(0xFF1A1A2E)),
        shape = RoundedCornerShape(10.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text("ROI Inplay", style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(
                    "${if (stats.roi_pct >= 0) "+" else ""}${stats.roi_pct}%",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold, color = roiColor,
                )
            }
            // Stats rapides
            StatBlock("Picks", "${stats.total}")
            StatBlock("W/L", "${stats.wins}/${stats.losses}")
            StatBlock("P&L", "${if (stats.pnl >= 0) "+" else ""}${"%.1f".format(stats.pnl)}u")
            if (stats.avg_odds > 0.0) {
                StatBlock("Cote moy.", "%.2f".format(stats.avg_odds))
            }
            if (stats.pending > 0) {
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(50))
                        .background(AmberMkt.copy(alpha = 0.20f))
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                ) {
                    Text("${stats.pending} en attente",
                        style = MaterialTheme.typography.labelSmall, color = AmberMkt)
                }
            }
        }
    }
}

@Composable
private fun StatBlock(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurface)
        Text(label, style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// ── Pending picks (à résoudre) ───────────────────────────────────────────────

@Composable
private fun PendingPicksSection(
    pending: List<InplayPickItem>,
    recentSettled: List<InplayPickItem> = emptyList(),
    onSettle: (Int, String) -> Unit,
    onDelete: (Int) -> Unit = {},
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (pending.isNotEmpty()) {
            Text("⏳ Picks en attente", style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold)
            pending.forEach { p -> PendingPickRow(p, onSettle, onDelete) }
        }
        if (recentSettled.isNotEmpty()) {
            Text("✅ Récents réglés", style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 4.dp))
            recentSettled.forEach { p -> SettledPickRow(p, onDelete) }
        }
    }
}

@Composable
private fun PendingPickRow(
    p: InplayPickItem,
    onSettle: (Int, String) -> Unit,
    onDelete: (Int) -> Unit = {},
) {
    val color = mktColor(p.market_type)
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = color.copy(alpha = 0.08f)),
        shape = RoundedCornerShape(8.dp),
    ) {
        Column(modifier = Modifier.fillMaxWidth().padding(10.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        "${playerName(p.player1)} vs ${playerName(p.player2)}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1,
                    )
                    Text(p.pick, style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Bold, color = color)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        p.odds?.let {
                            Text("@${"%.2f".format(it)}", fontWeight = FontWeight.Bold,
                                color = color, style = MaterialTheme.typography.labelSmall)
                        }
                        Text("${p.stake.toInt()}u · ${p.prob.toInt()}%",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        p.score?.let {
                            Text("📊 $it", style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    // Cotes live snapshot
                    if (p.odds_home != null && p.odds_away != null) {
                        Text(
                            "ML: ${"%.2f".format(p.odds_home)} / ${"%.2f".format(p.odds_away)}" +
                            (p.odds_book?.let { " · $it" } ?: ""),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.outline,
                        )
                    }
                }
                Column(
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(6.dp))
                                .background(GreenEV.copy(alpha = 0.20f))
                                .clickable { onSettle(p.id, "W") }
                                .padding(horizontal = 10.dp, vertical = 6.dp),
                        ) { Text("W", fontWeight = FontWeight.Bold, color = GreenEV, fontSize = 13.sp) }
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(6.dp))
                                .background(LiveRed.copy(alpha = 0.20f))
                                .clickable { onSettle(p.id, "L") }
                                .padding(horizontal = 10.dp, vertical = 6.dp),
                        ) { Text("L", fontWeight = FontWeight.Bold, color = LiveRed, fontSize = 13.sp) }
                    }
                    Text("🗑 suppr", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline,
                        modifier = Modifier.clickable { onDelete(p.id) }.padding(4.dp))
                }
            }
        }
    }
}

@Composable
private fun SettledPickRow(p: InplayPickItem, onDelete: (Int) -> Unit = {}) {
    val isWin = p.result == "W"
    val resultColor = if (isWin) GreenEV else LiveRed
    val color = mktColor(p.market_type)
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = resultColor.copy(alpha = 0.06f)),
        shape = RoundedCornerShape(8.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text("${playerName(p.player1)} vs ${playerName(p.player2)}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                Text(p.pick, style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold, color = color)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    p.odds?.let {
                        Text("@${"%.2f".format(it)}", fontWeight = FontWeight.Bold,
                            color = color, style = MaterialTheme.typography.labelSmall)
                    }
                    Text("${p.stake.toInt()}u", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Column(horizontalAlignment = Alignment.End) {
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(6.dp))
                            .background(resultColor.copy(alpha = 0.20f))
                            .padding(horizontal = 12.dp, vertical = 6.dp),
                    ) {
                        Text(
                            if (isWin) "✓ W ${p.pnl?.let { "+${"%.1f".format(it)}u" } ?: ""}"
                            else "✗ L ${p.pnl?.let { "${"%.1f".format(it)}u" } ?: ""}",
                            fontWeight = FontWeight.Bold, color = resultColor, fontSize = 12.sp,
                        )
                    }
                    Text("🗑", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline,
                        modifier = Modifier.clickable { onDelete(p.id) }.padding(4.dp))
                }
            }
        }
    }
}

// ── Pick confirm dialog ───────────────────────────────────────────────────────

@Composable
private fun PickConfirmDialog(
    dialog: PickDialogState,
    onConfirm: (Double) -> Unit,
    onDismiss: () -> Unit,
) {
    var stakeText by remember { mutableStateOf("10") }
    val color = mktColor(dialog.marketType)

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text("📌 Prendre ce pick", fontWeight = FontWeight.Bold)
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                // Match + score
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        "${playerName(dialog.player1)} vs ${playerName(dialog.player2)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
                    if (dialog.score != null || dialog.minute != null) {
                        Text(
                            listOfNotNull(dialog.score, dialog.minute?.let { "${it}'" }).joinToString(" · "),
                            style = MaterialTheme.typography.labelSmall,
                            color = LiveRed,
                        )
                    }
                }
                // Marché + explication
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(6.dp))
                        .background(color.copy(alpha = 0.08f))
                        .padding(horizontal = 8.dp, vertical = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.Top,
                ) {
                    Text(mktIcon(dialog.marketType), fontSize = 16.sp)
                    Column {
                        Text(dialog.marketLabel,
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.SemiBold, color = color)
                        val explain = mktExplain(dialog.marketType, dialog.marketLabel)
                        if (explain.isNotBlank())
                            Text(explain,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.outline)
                    }
                }
                // Pick
                Text(dialog.pick, style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold, color = color)
                // Cote market + prob
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    dialog.odds?.let {
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(4.dp))
                                .background(color.copy(alpha = 0.15f))
                                .padding(horizontal = 8.dp, vertical = 3.dp),
                        ) {
                            Text("@ ${"%.2f".format(it)}", fontWeight = FontWeight.Bold,
                                color = color, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    Column {
                        Text("Probabilité IA : ${dialog.prob.toInt()}%",
                            style = MaterialTheme.typography.bodySmall,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        dialog.odds?.let { o ->
                            val impliedProb = (1.0 / o * 100).toInt()
                            val edge = dialog.prob.toInt() - impliedProb
                            Text(
                                "Cote implicite : $impliedProb% · Edge : ${if (edge > 0) "+$edge%" else "$edge%"}",
                                style = MaterialTheme.typography.labelSmall,
                                color = if (edge > 0) GreenEV else MaterialTheme.colorScheme.error,
                            )
                        }
                    }
                }
                // Cotes ML live snapshot
                if (dialog.oddsHome != null && dialog.oddsAway != null) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(6.dp))
                            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
                            .padding(8.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text("ML live", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(
                                "${playerName(dialog.player1)} ${"%.2f".format(dialog.oddsHome)}",
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                            Text(
                                "${playerName(dialog.player2)} ${"%.2f".format(dialog.oddsAway)}",
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                        }
                        dialog.oddsBook?.let {
                            Text(it.take(12), style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.outline)
                        }
                    }
                }
                OutlinedTextField(
                    value = stakeText,
                    onValueChange = { stakeText = it.filter { c -> c.isDigit() || c == '.' } },
                    label = { Text("Mise (unités)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val stake = stakeText.toDoubleOrNull() ?: 10.0
                onConfirm(stake)
            }) {
                Text("Enregistrer", fontWeight = FontWeight.Bold, color = GreenEV)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Annuler") }
        },
    )
}

// ── Live match card ──────────────────────────────────────────────────────────

@Composable
private fun LiveMatchCard(
    m: LiveMatch,
    allMarkets: InplayMarketsResponse? = null,
    onTakePick: (InplayMatchMarkets, InplayMarket) -> Unit,
) {
    val matchMarkets = allMarkets?.matches?.find { it.event_id == m.event_id }
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    m.league.ifBlank { "—" }.take(32),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.weight(1f),
                )
                if (m.status_detail.isNotBlank()) {
                    StatusChip(m.status_detail, m.minute)
                }
            }

            ScoreBoard(m)

            if (matchMarkets != null && matchMarkets.markets.isNotEmpty()) {
                val reliableMarkets = matchMarkets.markets.filter { (it.confidence.toDoubleOrNull() ?: 0.0) >= 0.4 }
                val hiddenMkts = matchMarkets.markets.size - reliableMarkets.size
                if (reliableMarkets.isNotEmpty()) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        reliableMarkets.forEach { mkt ->
                            MarketChip(mkt, onClick = { onTakePick(matchMarkets, mkt) })
                        }
                    }
                }
                if (hiddenMkts > 0) {
                    Text(
                        "$hiddenMkts marché${if (hiddenMkts > 1) "s" else ""} masqué${if (hiddenMkts > 1) "s" else ""} (confiance < 40%)",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            m.live_odds?.let { odds ->
                if (odds.home != null && odds.away != null) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        OddsChip(Modifier.weight(1f), playerName(m.player1), odds.home)
                        OddsChip(Modifier.weight(1f), playerName(m.player2), odds.away)
                    }
                    if (odds.books.isNotEmpty()) {
                        Text("via ${odds.books.joinToString(", ")}",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.outline)
                    }
                }
            }

            m.prediction?.let { pred -> PreMatchPredRow(m, pred) }
        }
    }
}

@Composable
private fun ScoreBoard(m: LiveMatch) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        val isHomeServing = m.serve == "home"
        val isAwayServing = m.serve == "away"

        PlayerScoreRow(
            name = playerName(m.player1),
            setsWon = m.sets_home,
            setScores = m.set_scores.map { it.h },
            gameScore = m.game_home,
            isServing = isHomeServing,
            isLeading = m.sets_home > m.sets_away,
        )
        PlayerScoreRow(
            name = playerName(m.player2),
            setsWon = m.sets_away,
            setScores = m.set_scores.map { it.a },
            gameScore = m.game_away,
            isServing = isAwayServing,
            isLeading = m.sets_away > m.sets_home,
        )
    }
}

@Composable
private fun PlayerScoreRow(
    name: String,
    setsWon: Int,
    setScores: List<Int>,
    gameScore: String,
    isServing: Boolean,
    isLeading: Boolean,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Row(
            modifier = Modifier.weight(1f),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            if (isServing) {
                Box(modifier = Modifier.size(8.dp).clip(CircleShape).background(ServeClr))
            } else {
                Spacer(Modifier.size(8.dp))
            }
            Text(
                name,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = if (isLeading) FontWeight.Bold else FontWeight.Normal,
                color = if (isLeading) MaterialTheme.colorScheme.onSurface
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
            )
        }

        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            setScores.dropLast(1).forEach { s ->
                SetScore(s.toString(), isCurrent = false)
            }
            setScores.lastOrNull()?.let { s ->
                SetScore(s.toString(), isCurrent = true)
            }
        }

        Spacer(Modifier.width(8.dp))
        val displayGame = if (gameScore.isBlank() || gameScore == "0") "—" else gameScore
        Text(
            displayGame,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Bold,
            color = if (isServing) ServeClr else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.width(36.dp),
            textAlign = TextAlign.End,
        )

        Spacer(Modifier.width(8.dp))
        Text(
            setsWon.toString(),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.ExtraBold,
            color = if (isLeading) ScoreGold else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(20.dp),
            textAlign = TextAlign.End,
        )
    }
}

@Composable
private fun SetScore(score: String, isCurrent: Boolean) {
    Text(
        score,
        style = MaterialTheme.typography.bodySmall,
        color = if (isCurrent) MaterialTheme.colorScheme.onSurface
                else MaterialTheme.colorScheme.onSurfaceVariant,
        fontWeight = if (isCurrent) FontWeight.SemiBold else FontWeight.Normal,
        modifier = Modifier.width(16.dp),
        textAlign = TextAlign.Center,
    )
}

@Composable
private fun StatusChip(status: String, minute: Int) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(LiveRed.copy(alpha = 0.15f))
            .padding(horizontal = 8.dp, vertical = 3.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        LiveDot(size = 6)
        Text(
            "${status.replaceFirstChar { it.uppercase() }} · ${minute}min",
            style = MaterialTheme.typography.labelSmall,
            color = LiveRed, fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun OddsChip(modifier: Modifier, name: String, odds: Double) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(name, style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
        Text("@ ${"%.2f".format(odds)}", style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurface)
    }
}

@Composable
private fun PreMatchPredRow(m: LiveMatch, pred: LivePrediction) {
    val fav = pred.favorite
    val p1prob = pred.prob1
    val p2prob = pred.prob2
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(6.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
            .padding(horizontal = 10.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("Pré-match", style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ProbLabel(playerName(m.player1), p1prob, fav == (pred.player1.ifBlank { m.player1 }))
            Text("vs", style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            ProbLabel(playerName(m.player2), p2prob, fav == (pred.player2.ifBlank { m.player2 }))
        }
        Text(
            pred.confidence_label.ifBlank { "conf ${(pred.confidence * 100).toInt()}%" },
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ProbLabel(name: String, prob: Double, isFav: Boolean) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(name, style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
        Text(
            "${"%.0f".format(prob)}%",
            style = MaterialTheme.typography.labelMedium,
            fontWeight = if (isFav) FontWeight.Bold else FontWeight.Normal,
            color = if (isFav) GreenEV else MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun LiveDot(size: Int = 10) {
    Box(
        modifier = Modifier
            .size(size.dp)
            .clip(CircleShape)
            .background(LiveRed),
    )
}

// ── InplayPicksSection (top picks + bouton Prendre) ──────────────────────────

@Composable
private fun InplayPicksSection(
    mkts: InplayMarketsResponse,
    liveMatches: List<LiveMatch> = emptyList(),
    onTakePick: (InplayMatchMarkets, InplayMarket) -> Unit,
) {
    val topPicks: List<Pair<InplayMatchMarkets, InplayMarket>> = mkts.matches
        .flatMap { match -> match.markets.map { mkt -> match to mkt } }
        .filter { (_, mkt) -> (mkt.confidence.toDoubleOrNull() ?: 0.0) >= 0.4 }
        .sortedByDescending { (_, mkt) -> mkt.prob }
        .take(5)

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("🎯 Meilleurs picks inplay", style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            topPicks.forEach { (match, mkt) ->
                PickCard(match, mkt, onTake = { onTakePick(match, mkt) })
            }
        }
    }
}

@Composable
private fun PickCard(
    match: InplayMatchMarkets,
    mkt: InplayMarket,
    onTake: () -> Unit,
) {
    val color = mktColor(mkt.type)
    val icon = mktIcon(mkt.type)
    Card(
        modifier = Modifier.width(160.dp),
        colors = CardDefaults.cardColors(containerColor = color.copy(alpha = 0.10f)),
        shape = RoundedCornerShape(10.dp),
    ) {
        Column(
            modifier = Modifier.padding(10.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(icon, fontSize = 14.sp)
                ConfChip(mkt.confidence, color)
            }
            Text(mkt.label, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            val explain = mktExplain(mkt.type, mkt.label)
            if (explain.isNotBlank()) {
                Text(explain,
                    style = MaterialTheme.typography.labelSmall.copy(fontSize = 9.sp),
                    color = MaterialTheme.colorScheme.outline, maxLines = 2,
                    lineHeight = 11.sp)
            }
            Text(
                mkt.pick,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Bold, color = color, maxLines = 1,
            )
            if (mkt.odds != null) {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(4.dp))
                            .background(color.copy(alpha = 0.18f))
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                    ) {
                        Text("@${"%.2f".format(mkt.odds)}", style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold, color = color)
                    }
                    Text("Betfair · ${mkt.prob.toInt()}%", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                Text(
                    "${mkt.prob.toInt()}% · ${playerName(match.player1)} vs ${playerName(match.player2)}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1,
                )
            }
            if (mkt.rationale.isNotBlank()) {
                Text(mkt.rationale, style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline, maxLines = 1)
            }
            // Bouton Prendre
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(6.dp))
                    .background(color.copy(alpha = 0.20f))
                    .clickable { onTake() }
                    .padding(vertical = 4.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text("📌 Prendre", style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold, color = color)
            }
        }
    }
}

@Composable
private fun MarketChip(mkt: InplayMarket, onClick: () -> Unit = {}) {
    val color = mktColor(mkt.type)
    val icon = mktIcon(mkt.type)
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(color.copy(alpha = if (mkt.has_real_odds) 0.18f else 0.12f))
            .border(
                width = if (mkt.has_real_odds) 1.dp else 0.dp,
                color = if (mkt.has_real_odds) color.copy(alpha = 0.50f) else Color.Transparent,
                shape = RoundedCornerShape(50),
            )
            .clickable { onClick() }
            .padding(horizontal = 8.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(icon, fontSize = 10.sp)
        Text(
            mkt.pick.take(14),
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold, color = color,
        )
        if (mkt.odds != null) {
            Text("@${"%.2f".format(mkt.odds)}", style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold, color = color)
        } else {
            Text("${mkt.prob.toInt()}%", style = MaterialTheme.typography.labelSmall,
                color = color.copy(alpha = 0.75f))
        }
    }
}

@Composable
private fun ConfChip(conf: String, color: Color) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(color.copy(alpha = 0.18f))
            .padding(horizontal = 5.dp, vertical = 2.dp),
    ) {
        Text(conf, style = MaterialTheme.typography.labelSmall,
            color = color.copy(alpha = when (conf) { "Forte" -> 0.90f; "Moyenne" -> 0.65f; else -> 0.40f }),
            fontWeight = FontWeight.SemiBold)
    }
}

// ── BestPickBanner ───────────────────────────────────────────────────────────

@Composable
private fun BestPickBanner(pick: InplayBestPick, onTake: () -> Unit = {}) {
    val pred = pick.prediction ?: return
    val fav = pred.favorite ?: return
    val favProb = if (fav == (pick.player1_resolved ?: pick.player1)) pred.prob1 else pred.prob2
    val favName = playerName(fav)
    val edgeText = pick.edge_pct?.let { "+${it.toInt()}% edge" }
    val oddsText = pick.fav_odds?.let { "@${String.format("%.2f", it)}" } ?: ""
    val setScore = if (pick.sets_home > 0 || pick.sets_away > 0)
        "${pick.sets_home}-${pick.sets_away}" else ""

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color(0xFF1A2E1A)),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Meilleur pick live", style = MaterialTheme.typography.labelMedium,
                    color = GreenEV, fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (edgeText != null) {
                        Text(edgeText, style = MaterialTheme.typography.labelSmall, color = GreenEV)
                    }
                    if (pick.minute > 0) {
                        Text("${pick.minute}'", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }

            Text(pick.league.ifBlank { "—" }.take(36),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(favName, style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold, color = GreenEV, maxLines = 1)
                    Text("favori ${String.format("%.1f", favProb)}%  $oddsText",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (setScore.isNotBlank()) {
                    Text(setScore, style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold, color = ScoreGold)
                }
            }

            val confPct = (pred.confidence * 100).toInt()
            Text("Confiance ${confPct}% · ${pred.confidence_label}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)

            // Bouton Prendre
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(GreenEV.copy(alpha = 0.15f))
                    .clickable { onTake() }
                    .padding(vertical = 6.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text("📌 Prendre ce pick", style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Bold, color = GreenEV)
            }
        }
    }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

private fun mktColor(type: String): Color = when (type) {
    "set_winner"    -> GreenEV
    "next_set"      -> TealMkt
    "total_games"   -> AmberMkt
    "aces"          -> PurpleMkt
    "total_points"  -> Color(0xFF4F8CFF)
    "double_faults" -> Color(0xFFFF6B6B)
    "handicap"      -> Color(0xFFFF9500)
    else            -> Color(0xFF888888)
}

private fun mktIcon(type: String): String = when (type) {
    "set_winner"    -> "🏆"
    "next_set"      -> "🎯"
    "total_games"   -> "🎮"
    "aces"          -> "💨"
    "total_points"  -> "🔢"
    "double_faults" -> "❌"
    "handicap"      -> "⚖️"
    else            -> "📊"
}

// Explication courte en français clair pour non-connaisseurs
private fun mktExplain(type: String, label: String): String = when (type) {
    "set_winner"   -> "Qui remporte ce set ? (premier à 6 jeux)"
    "next_set"     -> "Qui gagne le prochain set ?"
    "total_games"  -> {
        val thresh = label.substringAfterLast(" ").toDoubleOrNull()
        if (thresh != null) "Nombre total de jeux dans ce set : plus ou moins de ${thresh.toInt()}?"
        else "Total de jeux joués dans ce set"
    }
    "handicap"     -> "Avantage fictif donné au joueur le plus faible"
    "aces"         -> "Nombre de services gagnants directs (aces)"
    "total_points" -> "Total de points joués dans ce set"
    "double_faults"-> "Nombre de doubles fautes"
    else           -> ""
}

private fun playerName(raw: String): String {
    val parts = raw.split(",").map { it.trim() }
    return if (parts.size == 2) {
        val last = parts[0]
        val first = parts[1].firstOrNull()?.let { "$it." } ?: ""
        "$first $last".trim()
    } else {
        raw.split(" ").lastOrNull() ?: raw
    }
}

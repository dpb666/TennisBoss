package com.tennisboss.app.ui

import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.InplayBestPick
import com.tennisboss.app.data.LiveMatch
import com.tennisboss.app.data.LivePrediction
import com.tennisboss.app.ui.components.SkeletonList

private val LiveRed   = Color(0xFFFF3B3B)
private val GreenEV   = Color(0xFF00E5A0)
private val ScoreGold = Color(0xFFFFD600)
private val ServeClr  = Color(0xFF4FC3F7)

@Composable
fun LiveScreen(vm: LiveViewModel = viewModel()) {

    DisposableEffect(Unit) {
        vm.startAutoRefresh()
        onDispose { vm.stopAutoRefresh() }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // ── Header ───────────────────────────────────────────────────────────
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
            // Countdown auto-refresh
            val s = vm.state
            if (s is LiveUiState.Success) {
                Text(
                    "↺ ${s.refreshIn}s",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        // ── Content ──────────────────────────────────────────────────────────
        when (val s = vm.state) {
            is LiveUiState.Loading -> SkeletonList(count = 3)
            is LiveUiState.Error   -> Text(s.message, color = MaterialTheme.colorScheme.error)
            is LiveUiState.Success -> {
                if (s.data.matches.isEmpty()) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("Aucun match en cours", style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text("Prochain refresh dans ${s.refreshIn}s",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                } else {
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        s.bestPick?.let { pick ->
                            item(key = "best_pick") { BestPickBanner(pick) }
                        }
                        items(s.data.matches, key = { it.event_id }) { match ->
                            LiveMatchCard(match)
                        }
                    }
                }
            }
            else -> {}
        }
    }
}

@Composable
private fun LiveMatchCard(m: LiveMatch) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            // Ligue + statut
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

            // Scoreboard principal
            ScoreBoard(m)

            // Cotes live
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
                        Text(
                            "via ${odds.books.joinToString(", ")}",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.outline,
                        )
                    }
                }
            }

            // Prédiction pré-match
            m.prediction?.let { pred ->
                PreMatchPredRow(m, pred)
            }
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
        // Serve dot + nom
        Row(
            modifier = Modifier.weight(1f),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            if (isServing) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .clip(CircleShape)
                        .background(ServeClr),
                )
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

        // Sets précédents
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            setScores.dropLast(1).forEach { s ->
                SetScore(s.toString(), isCurrent = false)
            }
            // Set en cours (dernier)
            setScores.lastOrNull()?.let { s ->
                SetScore(s.toString(), isCurrent = true)
            }
        }

        // Jeu en cours (0 entre deux points = on affiche —)
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

        // Sets gagnés
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
            color = LiveRed,
            fontWeight = FontWeight.SemiBold,
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
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurface)
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
        Text(
            "Pré-match",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
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
        Text(
            name,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
        )
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

private fun playerName(raw: String): String {
    // "Pradkin, Lily" -> "L. Pradkin"  |  "Ugo Humbert" -> "Humbert"
    val parts = raw.split(",").map { it.trim() }
    return if (parts.size == 2) {
        val last = parts[0]
        val first = parts[1].firstOrNull()?.let { "$it." } ?: ""
        "$first $last".trim()
    } else {
        raw.split(" ").lastOrNull() ?: raw
    }
}

@Composable
private fun BestPickBanner(pick: InplayBestPick) {
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
                Text(
                    "Meilleur pick live",
                    style = MaterialTheme.typography.labelMedium,
                    color = GreenEV,
                    fontWeight = FontWeight.Bold,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (edgeText != null) {
                        Text(
                            edgeText,
                            style = MaterialTheme.typography.labelSmall,
                            color = GreenEV,
                        )
                    }
                    if (pick.minute > 0) {
                        Text(
                            "${pick.minute}'",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            Text(
                pick.league.ifBlank { "—" }.take(36),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        favName,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = GreenEV,
                        maxLines = 1,
                    )
                    Text(
                        "favori ${String.format("%.1f", favProb)}%  $oddsText",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (setScore.isNotBlank()) {
                    Text(
                        setScore,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                        color = ScoreGold,
                    )
                }
            }

            val confPct = (pred.confidence * 100).toInt()
            Text(
                "Confiance ${confPct}% · ${pred.confidence_label}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

package com.tennisboss.app.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** Dégradé animé pour l'effet « shimmer » de chargement. */
@Composable
fun rememberShimmerBrush(): Brush {
    val transition = rememberInfiniteTransition(label = "shimmer")
    val x by transition.animateFloat(
        initialValue = -400f,
        targetValue = 1200f,
        animationSpec = infiniteRepeatable(
            animation = tween(1200, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "x",
    )
    val colors = listOf(
        Color(0xFF1C2530),
        Color(0xFF2A3645),
        Color(0xFF1C2530),
    )
    return Brush.linearGradient(
        colors = colors,
        start = Offset(x - 300f, 0f),
        end = Offset(x, 0f),
    )
}

/** Bloc rectangulaire shimmer. */
@Composable
fun SkeletonBox(modifier: Modifier = Modifier, height: Dp = 14.dp, brush: Brush) {
    androidx.compose.foundation.layout.Box(
        modifier
            .height(height)
            .clip(RoundedCornerShape(7.dp))
            .background(brush),
    )
}

/** Carte squelette imitant une carte de liste (match / value / joueur). */
@Composable
fun SkeletonCard(brush: Brush) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            SkeletonBox(Modifier.fillMaxWidth(0.4f), 12.dp, brush)
            SkeletonBox(Modifier.fillMaxWidth(0.8f), 16.dp, brush)
            SkeletonBox(Modifier.fillMaxWidth(0.6f), 12.dp, brush)
            SkeletonBox(Modifier.fillMaxWidth(1f), 22.dp, brush)
        }
    }
}

/** Liste de cartes squelettes pendant le chargement. */
@Composable
fun SkeletonList(count: Int = 4) {
    val brush = rememberShimmerBrush()
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        repeat(count) { SkeletonCard(brush) }
    }
}

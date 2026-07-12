package com.tennisboss.app

import com.tennisboss.app.data.UpcomingMatch
import com.tennisboss.app.ui.sortForDashboard
import org.junit.Assert.assertEquals
import org.junit.Test

/** Tests de la fonction pure de tri "grand public" pour le Dashboard. */
class SortForDashboardTest {

    private fun match(tag: String, rank1: Int?, rank2: Int?) = UpcomingMatch(
        player1_raw = "a", player2_raw = "b", tournament = tag, round = "",
        date = "", time = "", live = false, tour = "atp", predictable = true,
        rank1 = rank1, rank2 = rank2,
    )

    @Test
    fun `les joueurs classes passent avant les qualifs obscures`() {
        val obscure = match("Q", null, null)
        val headline = match("H", 3, 8)

        val sorted = sortForDashboard(listOf(obscure, headline))

        assertEquals(listOf("H", "Q"), sorted.map { it.tournament })
    }

    @Test
    fun `le tri se base sur le meilleur des deux classements`() {
        val a = match("A", 45, 120)   // meilleur rank = 45
        val b = match("B", 12, 300)   // meilleur rank = 12
        val sorted = sortForDashboard(listOf(a, b))
        assertEquals(listOf("B", "A"), sorted.map { it.tournament })
    }

    @Test
    fun `un seul rang connu suffit a devancer un match sans rang`() {
        val partial = match("P", null, 200)
        val unknown = match("U", null, null)
        val sorted = sortForDashboard(listOf(unknown, partial))
        assertEquals(listOf("P", "U"), sorted.map { it.tournament })
    }

    @Test
    fun `liste vide ne plante pas`() {
        assertEquals(emptyList<UpcomingMatch>(), sortForDashboard(emptyList()))
    }
}

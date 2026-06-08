package com.tennisboss.app

import com.tennisboss.app.data.Prediction
import com.tennisboss.app.data.UpcomingMatch
import com.tennisboss.app.ui.sortUpcoming
import org.junit.Assert.assertEquals
import org.junit.Test

/** Tests de la fonction pure de tri des matchs à venir. */
class SortUpcomingTest {

    private fun match(tag: String, p1: Double?, p2: Double?) = UpcomingMatch(
        player1_raw = "a", player2_raw = "b", tournament = tag, round = "",
        date = "", time = "", live = false, tour = "atp",
        predictable = p1 != null,
        prediction = if (p1 != null) Prediction("a", "b", p1, p2 ?: 0.0, "a") else null,
    )

    @Test
    fun `les matchs predictibles passent avant les inconnus`() {
        val unknown = match("U", null, null)
        val weak = match("W", 55.0, 45.0)
        val strong = match("S", 80.0, 20.0)

        val sorted = sortUpcoming(listOf(unknown, weak, strong))

        assertEquals(listOf("S", "W", "U"), sorted.map { it.tournament })
    }

    @Test
    fun `le tri se base sur la proba du favori (max des deux)`() {
        // L'outsider a prob2 élevée -> doit primer.
        val a = match("A", 40.0, 60.0)   // favori à 60
        val b = match("B", 52.0, 48.0)   // favori à 52
        val sorted = sortUpcoming(listOf(b, a))
        assertEquals(listOf("A", "B"), sorted.map { it.tournament })
    }

    @Test
    fun `liste vide ne plante pas`() {
        assertEquals(emptyList<UpcomingMatch>(), sortUpcoming(emptyList()))
    }
}

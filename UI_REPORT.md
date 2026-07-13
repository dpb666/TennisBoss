# TennisBoss — UI Report

_Based on a live, hands-on emulator walkthrough this session (Dashboard → Predict → Chat, real backend, real data — not a static code read) plus the Android audit agent's screen inventory._

## Screens

13 screens total, all reachable via the 5-tab bottom nav + 3 in-tab sub-`TabRow`s (`NavGroups.kt`). No dead/unreachable screens found. No missing screens identified relative to the app's stated scope.

## Confirmed working (hands-on this session)

- **Dashboard**: loads real model status (55% précision, 4361 predictions, +13.8% ROI), CLV summary, followed players (Jannik Sinner card with live form%), and a "Meilleures opportunités" match card with real odds/EV — all populated from the live backend, not placeholders.
- **Predict**: pre-filled Iga Swiatek vs Aryna Sabalenka, "Analyser avec l'IA" returns a real prediction (39.9%/60.1%), decisive factor explanation ("Niveau ELO (historique) — avantage Aryna Sabalenka"), and factor breakdown (Service, etc.) — full round-trip to the model confirmed live.
- **Chat**: sent a real message ("Value bets WTA aujourdhui"), got a real, correctly-grounded response labeled "📊 Basé sur nos données (ELO, forme, H2H)" — confirms the anti-hallucination/grounding work from earlier this session is functioning on-device, not just in backend tests.

## Bugs found (real, observed on-device — not inferred)

1. **Contradictory tag combination** on the Dashboard's featured match card: `bonne` (good) + `Pas de value` (no value) + `HONEYPOT +23.0%` warning, all shown simultaneously on the same card. A real user cannot tell from this whether the app is recommending or warning against this match. See `MASTER_TODO.md` #3 for the fix approach. **Screenshot-verified, not a hypothetical.**
2. **`SurfaceBadge` name collision** — see `CLEANUP_REPORT.md`/`MASTER_TODO.md` #2. Not yet a visibly wrong badge on any screen sampled, but the collision exists in the code and is a live risk for the next change to either file.

## Navigation

Manual `tab: Int` + `AnimatedContent` (no `NavHost`) — verified working correctly for all 5 tabs during this session's walkthrough once correct tap coordinates were found. No broken transitions observed. The friction was entirely on the testing side (see below), not the app.

## UX observation from manual testing friction

**Zero Compose `testTag`/semantics anywhere in the app.** Every single interaction this session had to be located via `adb shell uiautomator dump` and hand-computed pixel bounds, because there's no stable identifier to target. This isn't a user-facing bug, but it's a real product-velocity cost: it means neither automated UI tests nor any future AI-driven QA pass can reliably interact with this app without the same slow dump-then-guess cycle. See `MASTER_TODO.md` #10.

## Accessibility

`contentDescription` used only 5 times across the sampled screens (`DashboardScreen.kt`, `PlayersScreen.kt`, `MatchDetailScreen.kt`), 4 of those 5 explicitly `null`. The bottom nav (`MainActivity.kt:184-187`) is the one place it's done correctly (real label as content description). Icon-heavy areas — signal cards in `PremiumSignalsSection`, badges, chips — are largely unlabeled for screen readers. See `MASTER_TODO.md` #11.

## Compose performance

No recomposition-storm patterns found in the 3 screens sampled (Dashboard, MatchDetail, Value) — network/heavy work is correctly confined to `LaunchedEffect`/ViewModel, not composition. Bounded list rendering (`.take(5)`, signal lists) throughout, no unbounded `.forEach` over large collections found.

## Recommendation priority

The tag-contradiction bug (#1 above) is the only user-facing issue found that a real user would notice today, and it directly touches the app's core value proposition (helping decide which bets are actually good) — it should be the first UI fix made, ahead of the cosmetic/structural items.

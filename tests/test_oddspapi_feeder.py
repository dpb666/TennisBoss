"""Tests du feeder OddsPapi — pool de clés + parsing (sans réseau réel)."""
import time
import unittest
from unittest import mock

from bot import oddspapi_feeder as op


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class TestKeyPool(unittest.TestCase):
    def setUp(self):
        op._KEY_POOL.clear()
        op._KEY_ORDER.clear()
        op._CACHE.clear()

    def tearDown(self):
        op._KEY_POOL.clear()
        op._KEY_ORDER.clear()
        op._CACHE.clear()

    def test_load_key_pool_lit_les_suffixes(self):
        env = {"ODDSPAPI_KEY": "k1", "ODDSPAPI_KEY_2": "k2", "ODDSPAPI_KEY_5": "k5"}
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch.object(op, "load_env"):
            op._load_key_pool()
        self.assertEqual(op._KEY_ORDER, ["k1", "k2", "k5"])

    def test_is_enabled_false_sans_cle(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(op, "load_env"):
            self.assertFalse(op.is_enabled())

    def test_pick_key_saute_les_cles_epuisees(self):
        op._KEY_ORDER = ["k1", "k2"]
        op._KEY_POOL["k1"] = {"remaining": 1, "checked_at": time.time()}  # <= RL_SAFETY
        op._KEY_POOL["k2"] = {"remaining": 100, "checked_at": time.time()}
        self.assertEqual(op._pick_key(), "k2")

    def test_pick_key_none_si_tout_epuise(self):
        op._KEY_ORDER = ["k1"]
        op._KEY_POOL["k1"] = {"remaining": 0, "checked_at": time.time()}
        self.assertIsNone(op._pick_key())

    def test_check_quota_appelle_account_et_calcule_remaining(self):
        resp = FakeResp(200, {"request_limit": 250, "request_count": 240})
        with mock.patch.object(op.requests, "get", return_value=resp) as m:
            remaining = op._check_quota("k1")
        self.assertEqual(remaining, 10)
        self.assertEqual(m.call_count, 1)

    def test_check_quota_cache_evite_second_appel(self):
        resp = FakeResp(200, {"request_limit": 250, "request_count": 0})
        with mock.patch.object(op.requests, "get", return_value=resp) as m:
            op._check_quota("k1")
            op._check_quota("k1")
        self.assertEqual(m.call_count, 1)  # 2e servi par le cache TTL_ACCOUNT


class TestParseFixtures(unittest.TestCase):
    def test_parse_fixture_atp(self):
        # Schéma réel confirmé (2026-07-12) : categoryName = palier du circuit
        # (ATP/WTA/Challenger...), pas un pays.
        raw = [{
            "fixtureId": "id123",
            "participant1Name": "Krumich, Martin",
            "participant2Name": "Ferreira Silva, Frederico",
            "tournamentName": "ATP Bastad, Sweden Men Singles",
            "categoryName": "ATP",
            "startTime": "2026-07-17T14:00:00.000Z",
            "statusId": op.STATUS_PRE_GAME,
        }]
        out = op.parse_fixtures(raw)
        self.assertEqual(len(out), 1)
        f = out[0]
        self.assertEqual(f["player1"], "Krumich, Martin")
        self.assertEqual(f["player2"], "Ferreira Silva, Frederico")
        self.assertEqual(f["tournament"], "ATP Bastad, Sweden Men Singles")
        self.assertEqual(f["date"], "2026-07-17")
        self.assertEqual(f["time"], "14:00")
        self.assertFalse(f["live"])
        self.assertFalse(f["is_doubles"])
        self.assertEqual(f["tour"], "atp")

    def test_parse_fixture_live_status_1(self):
        # statusId vérifié contre l'API réelle : 1 = Live (pas 3, comme la doc
        # publique le laissait croire — 3 = Cancelled).
        raw = [{
            "participant1Name": "A", "participant2Name": "B",
            "tournamentName": "WTA Iasi", "categoryName": "WTA",
            "startTime": "2026-07-17T09:00:00.000Z", "statusId": op.STATUS_LIVE,
        }]
        f = op.parse_fixtures(raw)[0]
        self.assertTrue(f["live"])
        self.assertEqual(f["tour"], "wta")

    def test_parse_fixture_finished_and_cancelled_excluded(self):
        raw = [
            {"participant1Name": "A", "participant2Name": "B", "tournamentName": "X",
             "categoryName": "ATP", "startTime": "2026-07-17T09:00:00.000Z",
             "statusId": op.STATUS_FINISHED},
            {"participant1Name": "C", "participant2Name": "D", "tournamentName": "Y",
             "categoryName": "ATP", "startTime": "2026-07-17T09:00:00.000Z",
             "statusId": op.STATUS_CANCELLED},
        ]
        self.assertEqual(op.parse_fixtures(raw), [])

    def test_parse_fixture_doubles_detected(self):
        raw = [{
            "participant1Name": "A / B", "participant2Name": "C / D",
            "tournamentName": "ATP Doubles", "categoryName": "ATP",
            "startTime": "2026-07-17T09:00:00.000Z", "statusId": op.STATUS_PRE_GAME,
        }]
        f = op.parse_fixtures(raw)[0]
        self.assertTrue(f["is_doubles"])

    def test_parse_fixture_sans_nom_joueur_ignore(self):
        raw = [{"participant1Name": "", "participant2Name": "B",
                "tournamentName": "X", "categoryName": "", "startTime": "",
                "statusId": op.STATUS_PRE_GAME}]
        self.assertEqual(op.parse_fixtures(raw), [])

    def test_parse_fixture_date_invalide_ne_plante_pas(self):
        raw = [{
            "participant1Name": "A", "participant2Name": "B",
            "tournamentName": "X", "categoryName": "", "startTime": "n'importe quoi",
            "statusId": 0,
        }]
        f = op.parse_fixtures(raw)[0]
        # Ne plante pas ; date/time dégradées mais présentes.
        self.assertIn("date", f)
        self.assertIn("time", f)


class TestFetchTennisFixtures(unittest.TestCase):
    def setUp(self):
        op._KEY_POOL.clear()
        op._KEY_ORDER.clear()
        op._CACHE.clear()

    def tearDown(self):
        op._KEY_POOL.clear()
        op._KEY_ORDER.clear()
        op._CACHE.clear()

    def test_fetch_renvoie_vide_sans_cle(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(op, "load_env"):
            self.assertEqual(op.fetch_tennis_fixtures(), [])

    def test_fetch_appelle_fixtures_avec_sport_id_tennis(self):
        account_resp = FakeResp(200, {"request_limit": 250, "request_count": 0})
        fixtures_resp = FakeResp(200, [{"fixtureId": "x"}])

        def fake_get(url, params=None, timeout=None):
            if url.endswith("/account"):
                return account_resp
            return fixtures_resp

        env = {"ODDSPAPI_KEY": "k1"}
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch.object(op, "load_env"), \
             mock.patch.object(op.requests, "get", side_effect=fake_get) as m:
            result = op.fetch_tennis_fixtures(days_ahead=3)

        self.assertEqual(result, [{"fixtureId": "x"}])
        fixtures_call = [c for c in m.call_args_list if c.args[0].endswith("/fixtures")][0]
        self.assertEqual(fixtures_call.kwargs["params"]["sportId"], op.SPORT_ID_TENNIS)


if __name__ == "__main__":
    unittest.main()

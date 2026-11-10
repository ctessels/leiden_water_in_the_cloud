"""Gerichte tests voor de analyse van de nawerking van watergeven."""

import unittest

import numpy as np
import pandas as pd

from data_analyse import watering_aftereffect_analysis as aftereffect

T0 = pd.Timestamp("2026-06-01 12:00")
HOUR = pd.Timedelta("1h")


def eps_series(values, start=T0, step="4h") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq=step), dtype=float)


def dry_hourly(start=T0 - pd.Timedelta("2D"), days=40) -> pd.Series:
    return pd.Series(0.0, index=pd.date_range(start, periods=days * 24, freq="h"))


def exponential_decay(days=35, half_life_days=2.0, base=5.0, jump=10.0) -> pd.Series:
    index = pd.date_range(T0, periods=days * 6 + 1, freq="4h")
    elapsed = (index - T0).total_seconds() / 86400
    return pd.Series(base + jump * 0.5 ** (elapsed / half_life_days), index=index)


class DecayHelpersTest(unittest.TestCase):
    def test_crossing_time_interpolates_between_samples(self):
        series = eps_series([10, 8, 6])
        self.assertEqual(aftereffect.crossing_time(series, 7), T0 + 6 * HOUR)
        self.assertIsNone(aftereffect.crossing_time(series, 5))

    def test_first_rain_time_only_counts_rain_after_start(self):
        rain = dry_hourly()
        rain[T0] = 5.0  # uurvak eindigt op het startmoment en telt niet mee
        rain[T0 + 30 * HOUR] = 1.5
        rain[T0 + 31 * HOUR] = 1.0
        self.assertEqual(aftereffect.first_rain_time(rain, T0, T0 + pd.Timedelta("10D")), T0 + 30 * HOUR)

    def test_rerise_time_returns_last_minimum_before_new_rise(self):
        series = eps_series([10, 9, 8, 8, 8.5, 9])
        self.assertEqual(aftereffect.rerise_time(series, 0.5), T0 + 12 * HOUR)
        self.assertIsNone(aftereffect.rerise_time(eps_series([10, 9, 8, 7]), 0.5))


class FollowDecayTest(unittest.TestCase):
    def test_reaches_all_levels_in_dry_period(self):
        result = aftereffect.follow_decay(exponential_decay(), T0, 5.0, 10.0, dry_hourly())
        self.assertEqual(result["stop_reden"], "einde volgperiode")
        self.assertTrue(result["t50_bereikt"] and result["t90_bereikt"])
        self.assertAlmostEqual(result["t50_dagen"], 2.0, delta=0.05)
        self.assertAlmostEqual(result["t90_dagen"], 2 * np.log2(10), delta=0.05)
        self.assertAlmostEqual(result["rest_2d"], 0.5, places=6)

    def test_rain_after_peak_censors_unless_disabled(self):
        rain = dry_hourly()
        rain[T0 + 36 * HOUR] = 3.0
        censored = aftereffect.follow_decay(exponential_decay(), T0, 5.0, 10.0, rain)
        self.assertEqual(censored["stop_reden"], "regen")
        self.assertFalse(censored["t50_bereikt"])
        self.assertAlmostEqual(censored["t50_dagen"], 35 / 24)
        self.assertTrue(np.isnan(censored["rest_2d"]))

        continued = aftereffect.follow_decay(exponential_decay(), T0, 5.0, 10.0, rain, censor_rain=False)
        self.assertTrue(continued["t50_bereikt"])

    def test_stops_at_data_gap_rerise_and_next_event(self):
        decay = exponential_decay()
        gap = decay.drop(decay.loc[T0 + pd.Timedelta("1D"):T0 + pd.Timedelta("4D")].index[1:])
        result = aftereffect.follow_decay(gap, T0, 5.0, 10.0, dry_hourly())
        self.assertEqual(result["stop_reden"], "datagat")
        self.assertAlmostEqual(result["volgduur_dagen"], 1.0)

        rerise = decay.copy()
        rerise.loc[T0 + pd.Timedelta("1D"):] += 3.0
        result = aftereffect.follow_decay(rerise, T0, 5.0, 10.0, dry_hourly())
        self.assertEqual(result["stop_reden"], "nieuwe stijging")
        self.assertAlmostEqual(result["volgduur_dagen"], 1 - 4 / 24)

        result = aftereffect.follow_decay(decay, T0, 5.0, 10.0, dry_hourly(), next_event=T0 + pd.Timedelta("3D"))
        self.assertEqual(result["stop_reden"], "nieuw event")
        self.assertFalse(result["t90_bereikt"])


class StatisticsTest(unittest.TestCase):
    def test_kaplan_meier_median_accounts_for_censoring(self):
        self.assertEqual(aftereffect.km_median([1, 2, 3, 4], [True, False, True, True]), 3)
        self.assertTrue(np.isnan(aftereffect.km_median([1, 2, 3], [True, False, False])))

    def test_percentile_rank_counts_ties_half(self):
        self.assertEqual(aftereffect.percentile_rank([0, 0, 1, 2], 0), 25)
        self.assertEqual(aftereffect.percentile_rank([1, 2, 3], 5), 100)
        self.assertTrue(np.isnan(aftereffect.percentile_rank([], 1)))

    def test_sign_test_ignores_ties(self):
        result = aftereffect.sign_test([3, 2, 0, -1, np.nan])
        self.assertEqual((result["n"], result["hoger"], result["lager"], result["gelijk"]), (4, 2, 1, 1))
        self.assertAlmostEqual(result["p"], 1.0)

    def test_score_uses_only_matching_controls(self):
        rows = [
            ("2026-06-10", 10, 5.0, True),   # te beoordelen bui
            ("2026-06-20", 8, 0.0, True),
            ("2026-07-05", 12, 2.0, True),
            ("2026-05-01", 15, 10.0, True),
            ("2026-06-15", 40, 0.0, True),   # te veel regen
            ("2026-12-01", 10, 0.0, True),   # ander seizoen
            ("2026-06-12", 10, 0.0, False),  # vlak na gieten
        ]
        responses = pd.DataFrame(rows, columns=["t0", "mm", "respons_mm", "controle"]).assign(
            t0=lambda frame: pd.to_datetime(frame["t0"]), device_id=1, probe_number=1)
        scored = aftereffect.score_responses(responses)
        self.assertEqual(scored.loc[0, "n_controles"], 3)
        self.assertAlmostEqual(scored.loc[0, "percentiel"], 200 / 3)
        self.assertEqual(scored.loc[0, "controles_mediaan_mm"], 2.0)


class RainEpisodeTest(unittest.TestCase):
    def test_episodes_are_grouped_and_need_dry_period(self):
        day = pd.Timestamp("2026-06-01")
        rain = pd.Series(0.0, index=pd.date_range(day, periods=10 * 24, freq="h"))
        for hour in (10, 11, 12):
            rain[day + hour * HOUR] = 1.0
        rain[day + 20 * HOUR] = 0.5  # binnen 12 uur: zelfde bui
        rain[day + pd.Timedelta("1D") + 12 * HOUR] = 3.0  # na 16 uur droog: te kort droog
        rain[day + pd.Timedelta("2D")] = 0.025  # spoor telt niet als nat uur
        rain[day + pd.Timedelta("4D") + 12 * HOUR] = 2.5
        rain[day + pd.Timedelta("7D") + 12 * HOUR] = 0.5  # te weinig

        episodes = aftereffect.find_rain_episodes(rain)
        self.assertEqual(len(episodes), 2)
        first, second = episodes.iloc[0], episodes.iloc[1]
        self.assertEqual((first["t0"], first["t1"], first["mm"]), (day + 9 * HOUR, day + 20 * HOUR, 3.5))
        self.assertEqual(first["t_1mm"], day + 9 * HOUR)
        self.assertEqual(second["t0"], day + pd.Timedelta("4D") + 11 * HOUR)

    def test_rise_before_rain_is_flagged(self):
        index = pd.date_range("2026-06-01", periods=10 * 12, freq="2h")
        episode = pd.DataFrame([{"t0": pd.Timestamp("2026-06-07 08:00"), "t1": pd.Timestamp("2026-06-07 14:00"),
                                 "t_1mm": pd.Timestamp("2026-06-07 12:00"), "mm": 5.0, "droog_voor_uur": 48}])
        watering = pd.DataFrame(columns=["device_id", "probe_number", "t_peak", "onset_to", "eps_base", "jump"])

        def responses(rise_at):
            eps = pd.Series(10.0, index=index)
            eps.loc[rise_at:] = 12.0
            frame = pd.DataFrame({"eps": eps, "temperature": 15.0, "location_name": "test", "depth": 30})
            return aftereffect.rain_responses({(1, 1): frame}, episode, watering).iloc[0]

        early = responses("2026-06-07 10:00")
        self.assertTrue(early["stijging_voor_regen"])
        self.assertFalse(early["controle"])

        late = responses("2026-06-07 14:00")
        self.assertFalse(late["stijging_voor_regen"])
        self.assertAlmostEqual(late["d_eps"], 2.0)
        self.assertGreater(late["respons_mm"], 0)
        self.assertTrue(late["controle"])


if __name__ == "__main__":
    unittest.main()

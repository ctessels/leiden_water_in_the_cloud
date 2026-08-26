"""Gerichte tests voor historische permittiviteitsgrafieken."""

import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from PIL import Image

from data_analyse import permittivity_data_exploration as exploration
from data_analyse import permittivity_prediction_model as model


class PermittivityDataExplorationTest(unittest.TestCase):
    def build_fixture(self):
        dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(6)]
        rows = []
        for probe_number, depth_cm, probe_dates in (
            (1, 60, dates),
            (2, 20, dates[1:]),
            (3, 40, dates[:2]),
        ):
            for index, measurement_date in enumerate(probe_dates):
                rows.append(
                    {
                        "device_id": 10,
                        "location_name": "Testlocatie",
                        "probe_number": probe_number,
                        "depth_cm": depth_cm,
                        "date": measurement_date,
                        "relative_permittivity": 12.0 - index * 0.2,
                    }
                )
        daily_data = pd.DataFrame(rows)
        weather = pd.DataFrame(
            {
                "date": dates,
                "rain_mm": [0.0, 4.0, 0.0, 2.0, 0.0, 1.0],
                "energy_proxy": np.linspace(100.0, 600.0, len(dates)),
            }
        )
        inventory = pd.DataFrame(
            [
                {
                    "device_id": 10,
                    "location_name": "Testlocatie",
                    "probe_number": probe_number,
                    "depth_cm": depth_cm,
                    "usable_from": None,
                }
                for probe_number, depth_cm in ((1, 60), (2, 20), (3, 40), (4, 80))
            ]
        )
        return daily_data, weather, inventory

    def test_parse_probe_number_accepts_positive_integer_and_all(self):
        self.assertEqual(exploration.parse_probe_number("3"), 3)
        self.assertEqual(exploration.parse_probe_number("ALL"), "all")
        for value in ("0", "-1", "probe"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    exploration.parse_probe_number(value)

    def test_all_probes_are_ordered_by_depth_and_old_png_is_preserved(self):
        daily_data, weather, inventory = self.build_fixture()
        calls = []

        def write_graph(**kwargs):
            calls.append(kwargs)
            kwargs["path"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["path"].write_bytes(b"new graph")

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            legacy_path = output_dir / "sensor_10" / "probe_1_60cm.png"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_bytes(b"legacy graph")
            overwritten_path = (
                output_dir / "sensor_10" / "probe_2_20cm_combined.png"
            )
            overwritten_path.write_bytes(b"previous graph")
            with (
                patch.object(exploration, "load_active_probe_inventory", return_value=inventory),
                patch.object(exploration, "load_daily_sensor_data", return_value=daily_data),
                patch.object(exploration, "load_historical_weather", return_value=weather),
                patch.object(exploration, "write_permittivity_weather_graph", side_effect=write_graph),
            ):
                output = io.StringIO()
                with redirect_stdout(output):
                    generated = exploration.generate_exploration_graphs(
                        device_id=10,
                        probe_selection="all",
                        start=None,
                        end=None,
                        weather_view="combined",
                        output_dir=output_dir,
                    )

            self.assertEqual(
                [path.name for _, path in generated],
                [
                    "probe_2_20cm_combined.png",
                    "probe_3_40cm_combined.png",
                    "probe_1_60cm_combined.png",
                ],
            )
            self.assertTrue(all(call["weather_columns"] == ("rain_mm", "energy_proxy") for call in calls))
            self.assertIn("probe 4 | 80 cm | overgeslagen", output.getvalue())
            self.assertEqual(legacy_path.read_bytes(), b"legacy graph")
            self.assertEqual(overwritten_path.read_bytes(), b"new graph")

    def test_all_skips_empty_period_but_exact_probe_fails(self):
        daily_data, weather, inventory = self.build_fixture()
        selected_start = date(2026, 1, 3)

        def write_graph(**kwargs):
            kwargs["path"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["path"].write_bytes(b"graph")

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(exploration, "load_active_probe_inventory", return_value=inventory),
                patch.object(exploration, "load_daily_sensor_data", return_value=daily_data),
                patch.object(exploration, "load_historical_weather", return_value=weather),
                patch.object(exploration, "write_permittivity_weather_graph", side_effect=write_graph),
            ):
                output = io.StringIO()
                with redirect_stdout(output):
                    generated = exploration.generate_exploration_graphs(
                        10,
                        "all",
                        selected_start,
                        None,
                        "rain",
                        Path(directory),
                    )
                self.assertEqual(len(generated), 2)
                self.assertIn("probe 3 | 40 cm | overgeslagen", output.getvalue())
                with self.assertRaisesRegex(ValueError, "binnen periode"):
                    exploration.generate_exploration_graphs(
                        10,
                        3,
                        selected_start,
                        None,
                        "rain",
                        Path(directory),
                    )
                with self.assertRaisesRegex(ValueError, "Geen probe bevat"):
                    exploration.generate_exploration_graphs(
                        10,
                        "all",
                        date(2027, 1, 1),
                        None,
                        "rain",
                        Path(directory),
                    )

    def test_weather_views_create_one_or_two_panel_png_files(self):
        daily_data, weather, _ = self.build_fixture()
        actual = daily_data[daily_data["probe_number"] == 1][
            ["date", "relative_permittivity"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            sizes = {}
            for view, columns in exploration.WEATHER_VIEWS.items():
                path = directory / f"{view}.png"
                model.write_permittivity_weather_graph(
                    path=path,
                    title="Testgrafiek",
                    actual=actual,
                    weather=weather,
                    weather_columns=columns,
                )
                self.assertTrue(path.exists())
                with Image.open(path) as image:
                    sizes[view] = image.size
            self.assertGreater(sizes["combined"][1], sizes["rain"][1])
            self.assertEqual(sizes["rain"], sizes["energy"])

    def test_single_probe_uses_exact_custom_output_and_inclusive_dates(self):
        daily_data, weather, inventory = self.build_fixture()
        calls = []

        def write_graph(**kwargs):
            calls.append(kwargs)
            kwargs["path"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["path"].write_bytes(b"custom graph")

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "gekozen_naam.png"
            selected_date = date(2026, 1, 3)
            with (
                patch.object(exploration, "load_active_probe_inventory", return_value=inventory),
                patch.object(exploration, "load_daily_sensor_data", return_value=daily_data),
                patch.object(exploration, "load_historical_weather", return_value=weather),
                patch.object(exploration, "write_permittivity_weather_graph", side_effect=write_graph),
            ):
                generated = exploration.generate_exploration_graphs(
                    10,
                    2,
                    selected_date,
                    selected_date,
                    "energy",
                    output_path=output_path,
                )
            self.assertEqual(generated[0][1], output_path.resolve())
            self.assertEqual(len(calls[0]["actual"]), 1)
            self.assertEqual(calls[0]["weather_columns"], ("energy_proxy",))
            self.assertEqual(output_path.read_bytes(), b"custom graph")

    def test_gallery_is_unique_and_contains_every_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            graphs = [
                ("Probe 1", directory / "probe_1.png"),
                ("Probe 2", directory / "probe_2.png"),
            ]
            for _, path in graphs:
                path.write_bytes(b"graph")
            with patch.object(exploration.tempfile, "gettempdir", return_value=directory):
                first = exploration.create_gallery(10, graphs)
                second = exploration.create_gallery(10, graphs)
            self.assertNotEqual(first, second)
            content = first.read_text(encoding="utf-8")
            self.assertIn("Probe 1", content)
            self.assertIn("Probe 2", content)
            self.assertIn(graphs[0][1].as_uri(), content)
            self.assertIn(graphs[1][1].as_uri(), content)

    def test_main_opens_unique_galleries_and_no_open_suppresses_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            graph_path = Path(directory) / "graph.png"
            graph_path.write_bytes(b"graph")
            graphs = [("Probe 1", graph_path)]
            opened = []
            arguments = [
                "permittivity_data_exploration.py",
                "--device-id",
                "10",
                "--probe-number",
                "1",
            ]
            with (
                patch("sys.argv", arguments),
                patch.object(exploration, "generate_exploration_graphs", return_value=graphs),
                patch.object(exploration.tempfile, "gettempdir", return_value=directory),
                patch.object(exploration.webbrowser, "open_new_tab", side_effect=lambda url: opened.append(url) or True),
            ):
                exploration.main()
                exploration.main()
            self.assertEqual(len(opened), 2)
            self.assertNotEqual(opened[0], opened[1])

            with (
                patch("sys.argv", [*arguments, "--no-open"]),
                patch.object(exploration, "generate_exploration_graphs", return_value=graphs),
                patch.object(exploration, "create_gallery") as create_gallery,
                patch.object(exploration.webbrowser, "open_new_tab") as open_browser,
            ):
                exploration.main()
            create_gallery.assert_not_called()
            open_browser.assert_not_called()

    def test_invalid_date_range_and_output_combinations_fail(self):
        with self.assertRaisesRegex(ValueError, "startdatum"):
            exploration.generate_exploration_graphs(
                10,
                1,
                date(2026, 1, 2),
                date(2026, 1, 1),
                "rain",
            )
        with (
            patch(
                "sys.argv",
                [
                    "permittivity_data_exploration.py",
                    "--device-id",
                    "10",
                    "--probe-number",
                    "all",
                    "--output",
                    "graph.png",
                ],
            ),
            self.assertRaises(SystemExit) as error,
        ):
            exploration.main()
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

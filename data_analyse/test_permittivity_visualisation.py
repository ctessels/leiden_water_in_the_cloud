"""Gerichte tests voor de operationele en trainingvisualisaties."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from PIL import Image

from data_analyse import visualise_permittivity_training as visualiser


class PermittivityVisualisationTest(unittest.TestCase):
    def build_fixture(self):
        start = date(2026, 1, 1)
        dates = [start + timedelta(days=index) for index in range(150)]
        daily_data = pd.DataFrame(
            {
                "device_id": 10,
                "location_name": "Testlocatie",
                "probe_number": 2,
                "depth_cm": 50,
                "date": dates,
                "relative_permittivity": np.linspace(12.0, 8.0, len(dates)),
                "ground_temperature": 15.0,
                "raw_readings": 24,
            }
        )
        weather = pd.DataFrame(
            {
                "date": dates,
                "rain_mm": [8.0 if index % 11 == 0 else 0.0 for index in range(150)],
                "energy_proxy": np.linspace(100.0, 900.0, len(dates)),
            }
        )
        artifact = {
            "version": 2,
            "prediction_target": "relative_permittivity",
            "holdout_weeks": 4,
            "probe_models": {
                "10:2:50": {
                    "device_id": 10,
                    "location_name": "Testlocatie",
                    "probe_number": 2,
                    "depth_cm": 50,
                    "status": "trained",
                    "training_end": (start + timedelta(days=114)).isoformat(),
                    "parameters": {
                        "rain_threshold_mm": 2.0,
                        "rain_response_strength": 0.5,
                        "max_rain_response_multiplier": 3.0,
                        "rain_memory_decay": 0.75,
                    },
                    "average_rise_per_day": 0.4,
                    "average_slope_per_day": -0.03,
                },
                "20:1:15": {
                    "device_id": 20,
                    "location_name": "Geen historie",
                    "probe_number": 1,
                    "depth_cm": 15,
                    "status": "insufficient_history",
                },
            },
        }
        inventory = pd.DataFrame(
            [
                {
                    "device_id": 10,
                    "location_name": "Testlocatie",
                    "probe_number": 2,
                    "depth_cm": 50,
                },
                {
                    "device_id": 20,
                    "location_name": "Geen historie",
                    "probe_number": 1,
                    "depth_cm": 15,
                },
            ]
        )
        return start, daily_data, weather, artifact, inventory

    def test_training_visualiser_writes_four_graphs_only_for_trained_probe(self):
        _, daily_data, weather, artifact, inventory = self.build_fixture()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model_path = directory / "model.json"
            output_dir = directory / "training_visualisation"
            model_path.write_text(json.dumps(artifact), encoding="utf-8")
            with (
                patch.object(
                    visualiser,
                    "load_daily_sensor_data",
                    return_value=daily_data,
                ),
                patch.object(
                    visualiser,
                    "load_historical_weather",
                    return_value=weather,
                ),
                patch.object(
                    visualiser,
                    "load_usable_sensor_ids",
                    return_value={10, 20},
                ),
                patch.object(
                    visualiser,
                    "load_active_probe_inventory",
                    return_value=inventory,
                ),
            ):
                messages = io.StringIO()
                with redirect_stdout(messages):
                    visualiser.generate_training_visualisations(
                        model_path,
                        output_dir,
                    )
            graph_dir = output_dir / "sensor_10" / "probe_2_50cm"
            graphs = sorted(graph_dir.glob("evaluation_week_*.png"))
            self.assertEqual(len(graphs), 4)
            self.assertFalse((output_dir / "sensor_20").exists())
            output_messages = messages.getvalue()
            self.assertIn("Trainingvisualisatie gestart", output_messages)
            self.assertIn("[1/2] sensor 20", output_messages)
            self.assertIn("overgeslagen: insufficient_history", output_messages)
            self.assertIn("Trainingvisualisatie voltooid", output_messages)
            with Image.open(graphs[0]) as image:
                self.assertGreater(image.width, 1_000)
                self.assertGreater(image.height, 700)
                self.assertNotEqual(image.getextrema(), ((255, 255),) * len(image.getbands()))

    def test_missing_holdout_week_writes_available_graphs_and_overwrites(self):
        start, daily_data, weather, artifact, inventory = self.build_fixture()
        artifact["probe_models"]["10:2:50"]["training_end"] = (
            start + timedelta(days=121)
        ).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model_path = directory / "model.json"
            output_dir = directory / "training_visualisation"
            output_dir.mkdir()
            marker = output_dir / "vorige_run.txt"
            marker.write_text("behouden", encoding="utf-8")
            model_path.write_text(json.dumps(artifact), encoding="utf-8")
            with (
                patch.object(
                    visualiser,
                    "load_daily_sensor_data",
                    return_value=daily_data,
                ),
                patch.object(
                    visualiser,
                    "load_historical_weather",
                    return_value=weather,
                ),
                patch.object(
                    visualiser,
                    "load_usable_sensor_ids",
                    return_value={10},
                ),
                patch.object(
                    visualiser,
                    "load_active_probe_inventory",
                    return_value=inventory,
                ),
            ):
                visualiser.generate_training_visualisations(
                    model_path,
                    output_dir,
                )
            graphs = list(
                (output_dir / "sensor_10" / "probe_2_50cm").glob("*.png")
            )
            self.assertEqual(len(graphs), 3)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()

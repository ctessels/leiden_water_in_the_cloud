"""Gerichte tests voor het sensorgewijze bodemvochtmodel."""

import io
import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from data_analyse import permittivity_prediction_model as model
from data_analyse import train_permittivity_prediction_model as trainer


class PredictionModelTest(unittest.TestCase):
    def setUp(self):
        self.parameters = {
            "rain_threshold_mm": 2.0,
            "rain_response_strength": 0.5,
            "max_rain_response_multiplier": 3.0,
            "rain_memory_decay": 0.75,
        }

    def test_all_duration_categories_are_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usable_sensors.json"
            path.write_text(
                json.dumps({"3months": [1, 2], "12months": [2, 3]}),
                encoding="utf-8",
            )
            self.assertEqual(model.load_usable_sensor_ids(path), {1, 2, 3})

    def test_probe_key_includes_exact_depth(self):
        self.assertEqual(model.probe_key(1393, 2, 30), "1393:2:30")
        self.assertNotEqual(
            model.probe_key(1393, 2, 30),
            model.probe_key(1393, 2, 50),
        )

    def test_progress_line_identifies_probe_and_remaining_count(self):
        line = trainer.format_progress_line(
            {
                "device_id": 1390,
                "probe_number": 2,
                "depth_cm": 50,
                "status": "trained",
                "evaluation": {"model_mae": 0.0123456},
            },
            completed_probes=7,
            total_probes=20,
        )
        self.assertIn("[7/20] sensor 1390", line)
        self.assertIn("probe 2", line)
        self.assertIn("50 cm", line)
        self.assertIn("evaluatie-MAE 0.012346", line)
        self.assertIn("13 probes te gaan", line)

    def test_archived_prediction_is_reproducible_and_responds_to_rain(self):
        origin = date(2026, 1, 1)
        dry_rain = {}
        wet_rain = {origin + timedelta(days=1): 10.0}
        arguments = (10.0, 8.0, 12.0, origin)
        dry = model.predict_archived_path(
            *arguments, dry_rain, self.parameters, 0.5, -0.1
        )
        wet = model.predict_archived_path(
            *arguments, wet_rain, self.parameters, 0.5, -0.1
        )
        repeated = model.predict_archived_path(
            *arguments, wet_rain, self.parameters, 0.5, -0.1
        )
        np.testing.assert_array_equal(wet, repeated)
        self.assertGreater(wet[0], dry[0])

    def test_vectorised_score_matches_production_equation(self):
        origin = date(2026, 1, 1)
        rain_window = np.zeros((7, 5), dtype=float)
        for index in range(5):
            rain_window[index, index] = 10.0
        rain_by_date = {
            origin + timedelta(days=day_number - lag): rain_window[day_number - 1, lag]
            for day_number in range(1, 8)
            for lag in range(5)
        }
        actual = model.predict_archived_path(
            10.0,
            8.0,
            12.0,
            origin,
            rain_by_date,
            self.parameters,
            0.5,
            -0.1,
        )
        cases = [
            {
                "origin_date": origin,
                "current_value": 10.0,
                "recent_min": 8.0,
                "recent_max": 12.0,
                "actual": actual,
                "rain_window": rain_window,
            }
        ]
        scores = trainer.score_candidate_batch(
            cases,
            2.0,
            [(0.5, 3.0, 0.75), (1.0, 3.0, 0.75)],
            0.5,
            -0.1,
        )
        self.assertAlmostEqual(scores[0], 0.0)
        self.assertGreater(scores[1], scores[0])

    def test_complete_trainer_flow_with_one_parameter_combination(self):
        start = date(2026, 1, 1)
        dates = [start + timedelta(days=index) for index in range(170)]
        rain_indexes = set(range(0, 170, 14))
        values = []
        for index in range(170):
            response = 0.0
            if index - 1 in rain_indexes:
                response = 0.5
            elif index - 2 in rain_indexes:
                response = 1.0
            values.append(10.0 - index * 0.01 + response)
        probe_data = pd.DataFrame(
            {
                "device_id": 1,
                "location_name": "Testlocatie",
                "probe_number": 2,
                "depth_cm": 50,
                "date": dates,
                "relative_permittivity": values,
                "ground_temperature": 15.0,
                "raw_readings": 24,
            }
        )
        weather = pd.DataFrame(
            {
                "date": dates,
                "rain_mm": [
                    10.0 if index in rain_indexes else 0.0
                    for index in range(170)
                ],
            }
        )
        single_value_grid = {
            "rain_threshold_mm": {"start": 2.0, "stop": 2.0, "step": 1.0},
            "rain_response_strength": {"start": 0.5, "stop": 0.5, "step": 1.0},
            "max_rain_response_multiplier": {"start": 3.0, "stop": 3.0, "step": 1.0},
            "rain_memory_decay": {"start": 0.75, "stop": 0.75, "step": 1.0},
        }
        result = trainer.train_probe(
            {
                "inventory": {
                    "device_id": 1,
                    "location_name": "Testlocatie",
                    "probe_number": 2,
                    "depth_cm": 50,
                },
                "probe_data": probe_data,
                "weather": weather,
                "method": "exhaustive",
                "config": {
                    "holdout_weeks": 2,
                    "critical_relative_permittivity_quantile": 0.2,
                    "minimum_parameter_training_cases": 5,
                    "batch_size": 16,
                    "coarse_origin_stride_days": 7,
                    "refinement_radius_in_coarse_steps": 1.0,
                    "exhaustive_grid": single_value_grid,
                    "coarse_grid": single_value_grid,
                },
            }
        )
        self.assertEqual(result["status"], "trained")
        self.assertEqual(result["combinations_tested"], 1)
        self.assertNotIn("starting_parameters", result)
        self.assertEqual(result["evaluation"]["cases"], 14)
        self.assertEqual(result["training_daily_observations"], 149)
        self.assertAlmostEqual(
            result["critical_relative_permittivity"],
            float(pd.Series(values[:149]).quantile(0.2)),
        )

    def test_archived_statistics_do_not_use_data_after_cutoff(self):
        start = date(2026, 1, 1)
        dates = [start + timedelta(days=index) for index in range(30)]
        probe_data = pd.DataFrame(
            {
                "date": dates,
                "relative_permittivity": np.linspace(10.0, 7.0, len(dates)),
            }
        )
        weather = pd.DataFrame(
            {
                "date": dates,
                "rain_mm": [
                    10.0 if index in {0, 10, 20} else 0.0
                    for index in range(30)
                ],
            }
        )
        cutoff = start + timedelta(days=19)
        before = model.calculate_archived_statistics(probe_data, weather, 2.0, cutoff)
        changed = probe_data.copy()
        changed.loc[changed["date"] > cutoff, "relative_permittivity"] = 1_000.0
        after = model.calculate_archived_statistics(changed, weather, 2.0, cutoff)
        self.assertEqual(before, after)

    def test_trainer_has_no_parameter_seed_interface(self):
        self.assertNotIn("--parameter-seeds", trainer.build_parser().format_help())

    def test_status_row_contains_training_metadata_without_forecast_days(self):
        inventory_row = SimpleNamespace(
            device_id=1,
            location_name="Testlocatie",
            probe_number=2,
            depth_cm=50,
        )
        row = model.status_row(
            inventory_row,
            date(2026, 8, 17),
            "insufficient_history",
        )
        self.assertEqual(row["status"], "insufficient_history")
        self.assertIn("days_since_retraining", row)
        self.assertIn("training_daily_observations", row)
        self.assertFalse(
            any(column.startswith("predicted_permittivity_day_") for column in row)
        )

    def test_historical_and_forecast_weather_use_matching_units(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            weather_path = directory / "weather.csv"
            weather_path.write_text(
                "DATE,neerslag,zonneschijnduur,temperatuur,maxtemperatuur\n"
                "2026-08-17,10,20,100,140\n",
                encoding="utf-8",
            )
            historical = model.load_historical_weather(weather_path)
            self.assertEqual(historical.loc[0, "rain_mm"], 1.0)
            self.assertEqual(historical.loc[0, "energy_proxy"], 1440.0)

            database_path = directory / "forecast.db"
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE TenDayForecast (
                        forecast_date TEXT,
                        forecast_for_date TEXT,
                        precipitation_mm REAL,
                        precipitation_perc INTEGER,
                        sunshine_minutes INTEGER,
                        avg_temp INTEGER,
                        max_temp INTEGER
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO TenDayForecast VALUES
                    ('2026-08-17', '2026-08-18', 1.0, 50, 120, 10, 14)
                    """
                )
            connection.close()
            _, forecast = model.load_forecast(
                date(2026, 8, 17),
                database_path,
            )
            self.assertEqual(forecast.loc[0, "rain_mm"], 1.0)
            self.assertEqual(forecast.loc[0, "energy_proxy"], 1440.0)

    def test_operator_workbook_is_per_probe_and_contains_training_age(self):
        as_of = date(2026, 8, 17)
        dates = [as_of - timedelta(days=100 - index) for index in range(100)]
        daily_data = pd.DataFrame(
            {
                "device_id": 1,
                "location_name": "Testlocatie",
                "probe_number": 2,
                "depth_cm": 50,
                "date": dates,
                "relative_permittivity": np.linspace(8.0, 10.0, 100),
                "ground_temperature": 15.0,
                "raw_readings": 24,
            }
        )
        historical_weather = pd.DataFrame(
            {
                "date": dates,
                "rain_mm": np.zeros(100),
                "energy_proxy": np.full(100, 500.0),
            }
        )
        future_dates = [as_of + timedelta(days=index) for index in range(7)]
        forecast = pd.DataFrame(
            {
                "date": future_dates,
                "rain_mm": np.zeros(7),
                "rain_probability": np.full(7, 50.0),
                "energy_proxy": np.full(7, 600.0),
            }
        )
        artifact = {
            "version": 2,
            "prediction_target": "relative_permittivity",
            "created_at": "2026-08-10T06:00:00+02:00",
            "trained_at": "2026-08-10T06:00:00+02:00",
            "training_method": "exhaustive",
            "probe_models": {
                "1:2:50": {
                    "status": "trained",
                    "trained_at": "2026-08-10T06:00:00+02:00",
                    "parameters": self.parameters,
                    "average_rise_per_day": 0.5,
                    "average_slope_per_day": -0.05,
                    "critical_relative_permittivity": 8.5,
                    "training_start": "2026-01-01",
                    "training_end": "2026-07-31",
                    "training_daily_observations": 212,
                    "training_raw_readings": 5_088,
                    "parameter_training_cases": 20,
                    "evaluation": {
                        "cases": 8,
                        "model_mae": 0.1,
                        "persistence_mae": 0.2,
                        "beats_persistence": True,
                    },
                    "evaluation_residuals_relative_permittivity": [[0.0] * 7],
                }
            },
        }
        inventory = pd.DataFrame(
            [
                {
                    "device_id": 1,
                    "location_name": "Testlocatie",
                    "probe_number": 2,
                    "depth_cm": 50,
                    "usable_from": None,
                }
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model_path = directory / "model.json"
            visualisation_dir = directory / "visualisations"
            visualisation_dir.mkdir()
            old_marker = visualisation_dir / "oude_run.txt"
            old_marker.write_text("vervangen", encoding="utf-8")
            model_path.write_text(json.dumps(artifact), encoding="utf-8")
            with (
                patch.object(model, "load_usable_sensor_ids", return_value={1}),
                patch.object(model, "load_active_probe_inventory", return_value=inventory),
                patch.object(model, "load_daily_sensor_data", return_value=daily_data),
                patch.object(model, "load_historical_weather", return_value=historical_weather),
                patch.object(model, "load_forecast", return_value=(as_of, forecast)),
            ):
                messages = io.StringIO()
                with redirect_stdout(messages):
                    output_path = model.run_model(
                        as_of,
                        simulations=10,
                        model_path=model_path,
                        output_dir=directory,
                        visualisation_dir=visualisation_dir,
                    )
            output_messages = messages.getvalue()
            self.assertIn("Dagelijkse voorspelling gestart", output_messages)
            self.assertIn("[1/1] Testlocatie", output_messages)
            self.assertIn("Dagelijkse voorspelling voltooid", output_messages)
            with pd.ExcelFile(output_path) as workbook:
                self.assertEqual(
                    workbook.sheet_names,
                    ["Predictions", "Run information"],
                )
            predictions = pd.read_excel(output_path, sheet_name="Predictions")
            self.assertEqual(len(predictions), 1)
            self.assertEqual(predictions.loc[0, "probe_number"], 2)
            self.assertEqual(predictions.loc[0, "depth_cm"], 50)
            self.assertEqual(predictions.loc[0, "days_since_retraining"], 7)
            self.assertEqual(predictions.loc[0, "training_daily_observations"], 212)
            self.assertEqual(
                predictions.loc[0, "critical_relative_permittivity"],
                8.5,
            )
            self.assertFalse(
                any(
                    column.startswith("predicted_permittivity_day_")
                    for column in predictions.columns
                )
            )
            graph_path = (
                visualisation_dir
                / "sensor_1"
                / "probe_2_50cm"
                / "prediction.png"
            )
            self.assertTrue(graph_path.exists())
            self.assertGreater(graph_path.stat().st_size, 0)
            self.assertFalse(old_marker.exists())

            stale_path = visualisation_dir / "stale.txt"
            stale_path.write_text("vorige volledige run", encoding="utf-8")
            with (
                patch.object(model, "load_usable_sensor_ids", return_value={1}),
                patch.object(model, "load_active_probe_inventory", return_value=inventory),
                patch.object(model, "load_daily_sensor_data", return_value=daily_data),
                patch.object(model, "load_historical_weather", return_value=historical_weather),
                patch.object(model, "load_forecast", return_value=(as_of, forecast)),
                patch.object(
                    model,
                    "write_permittivity_weather_graph",
                    side_effect=RuntimeError("plotfout"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "plotfout"):
                    model.run_model(
                        as_of,
                        simulations=10,
                        model_path=model_path,
                        output_dir=directory,
                        visualisation_dir=visualisation_dir,
                    )
            self.assertTrue(stale_path.exists())

    def test_operator_workbook_sorts_location_case_insensitively_then_depth(self):
        as_of = date(2026, 8, 17)
        inventory = pd.DataFrame(
            [
                {"device_id": 4, "location_name": "beta", "probe_number": 1, "depth_cm": 15},
                {"device_id": 2, "location_name": "Alpha", "probe_number": 1, "depth_cm": 70},
                {"device_id": 3, "location_name": "alpha", "probe_number": 2, "depth_cm": 15},
                {"device_id": 1, "location_name": "Alpha", "probe_number": 1, "depth_cm": 15},
            ]
        )
        artifact = {
            "version": 2,
            "prediction_target": "relative_permittivity",
            "created_at": "2026-08-10T06:00:00+02:00",
            "trained_at": "2026-08-10T06:00:00+02:00",
            "training_method": "exhaustive",
            "probe_models": {},
        }
        historical_weather = pd.DataFrame(
            columns=["date", "rain_mm", "energy_proxy"]
        )
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model_path = directory / "model.json"
            model_path.write_text(json.dumps(artifact), encoding="utf-8")
            with (
                patch.object(model, "load_usable_sensor_ids", return_value=set()),
                patch.object(model, "load_active_probe_inventory", return_value=inventory),
                patch.object(model, "load_daily_sensor_data", return_value=pd.DataFrame()),
                patch.object(model, "load_historical_weather", return_value=historical_weather),
                patch.object(model, "load_forecast", return_value=(None, pd.DataFrame())),
            ):
                output_path = model.run_model(
                    as_of,
                    model_path=model_path,
                    output_dir=directory,
                    visualisation_dir=directory / "visualisations",
                )
            predictions = pd.read_excel(output_path, sheet_name="Predictions")
            self.assertEqual(predictions["device_id"].tolist(), [1, 3, 2, 4])

    def test_invalid_artifact_requires_retraining(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "invalid_model.json"
            model_path.write_text(
                json.dumps({"version": 1, "probe_models": {}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Train het model opnieuw"):
                model.run_model(date(2026, 8, 17), model_path=model_path)


if __name__ == "__main__":
    unittest.main()

"""Vergelijk het gearchiveerde model met persistence op dezelfde eindtestweken."""

from __future__ import annotations

import argparse
import ast
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from permittivity_prediction_model import (
    ARTIFACT_DIR,
    FORECAST_HORIZON_DAYS,
    load_daily_sensor_data,
    load_historical_weather,
    load_usable_sensor_ids,
)
from train_permittivity_prediction_model import build_cases


ARCHIVED_MODEL_PATH = (
    Path(__file__).resolve().parent.parent
    / "legacy_data"
    / "model_experiments"
    / "permittivity_prediction_model_before_dynamic.py"
)
PARAMETER_NAMES = {
    "RAIN_EVENT_MM_PER_SENSOR",
    "RAIN_RESPONSE_STRENGTH_PER_SENSOR",
    "MAX_RAIN_RESPONSE_MULTIPLIER_PER_SENSOR",
    "RAIN_MEMORY_DECAY_PER_SENSOR",
}
HOLDOUT_WEEKS = 8


def load_archived_parameters(path: Path = ARCHIVED_MODEL_PATH) -> dict[str, dict[int, float]]:
    """Lees alleen letterlijke parameter-dictionaries zonder het archief uit te voeren."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parameters = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in PARAMETER_NAMES:
            parameters[target.id] = ast.literal_eval(node.value)
    missing = PARAMETER_NAMES.difference(parameters)
    if missing:
        raise ValueError(f"Ontbrekende parameter-dictionaries: {sorted(missing)}")
    return parameters


def build_archived_tables(sensor_data, weather, rain_thresholds, cutoff_date=None):
    """Bereken regenstijging en uitdroging volgens de oude implementatie."""
    if cutoff_date is not None:
        sensor_data = sensor_data[sensor_data["date"] <= cutoff_date]
    combined = sensor_data.merge(weather[["date", "rain_mm"]], on="date", how="left")
    combined["rain_threshold"] = combined["device_id"].map(rain_thresholds)
    combined = combined.dropna(
        subset=["relative_permittivity", "rain_mm", "rain_threshold"]
    ).sort_values(["device_id", "date"])
    combined["major_rain_event"] = combined["rain_mm"] > combined["rain_threshold"]
    combined["permittivity_plus_2"] = combined.groupby("device_id")[
        "relative_permittivity"
    ].shift(-2)
    combined["delta_2_days"] = (
        combined["permittivity_plus_2"] - combined["relative_permittivity"]
    )
    rise = (
        combined[combined["major_rain_event"]]
        .groupby("device_id")["delta_2_days"]
        .mean()
        .div(2.0)
        .to_dict()
    )

    slopes = []
    for device_id, group in combined.groupby("device_id"):
        group = group.sort_values("date").reset_index(drop=True)
        rain_indices = group.index[group["major_rain_event"]].tolist()
        for index in range(len(rain_indices) - 1):
            rain_index = rain_indices[index]
            next_rain_index = rain_indices[index + 1]
            peak_index = rain_index + 2
            if peak_index >= len(group) or next_rain_index <= peak_index:
                continue
            days = (
                group.loc[next_rain_index, "date"] - group.loc[peak_index, "date"]
            ).days
            if days <= 5:
                continue
            slopes.append(
                {
                    "device_id": int(device_id),
                    "slope": (
                        group.loc[next_rain_index, "relative_permittivity"]
                        - group.loc[peak_index, "relative_permittivity"]
                    ) / days,
                }
            )
    slope = (
        pd.DataFrame(slopes).groupby("device_id")["slope"].mean().to_dict()
        if slopes else {}
    )
    return rise, slope


def predict_archived_path(
    device_id,
    origin_date,
    sensor_data,
    weather,
    rise,
    slope,
    parameters,
):
    probe_data = sensor_data[sensor_data["device_id"] == device_id].sort_values("date")
    start = probe_data[probe_data["date"] == origin_date]
    if start.empty or device_id not in rise or device_id not in slope:
        return None
    current_value = float(start.iloc[0]["relative_permittivity"])
    recent = probe_data[
        (probe_data["date"] >= origin_date - timedelta(days=30))
        & (probe_data["date"] <= origin_date)
    ]["relative_permittivity"]
    recent_min = float(recent.min())
    recent_range = max(float(recent.max() - recent_min), 0.05)
    weather_by_date = weather.set_index("date")
    threshold = parameters["RAIN_EVENT_MM_PER_SENSOR"][device_id]
    strength = parameters["RAIN_RESPONSE_STRENGTH_PER_SENSOR"][device_id]
    cap = parameters["MAX_RAIN_RESPONSE_MULTIPLIER_PER_SENSOR"][device_id]
    decay = parameters["RAIN_MEMORY_DECAY_PER_SENSOR"][device_id]
    predictions = []

    for day in range(1, FORECAST_HORIZON_DAYS + 1):
        prediction_date = origin_date + timedelta(days=day)
        effective_rain = 0.0
        for lag in range(5):
            rain_date = prediction_date - timedelta(days=lag)
            rain = (
                float(weather_by_date.loc[rain_date, "rain_mm"])
                if rain_date in weather_by_date.index else 0.0
            )
            if rain >= threshold:
                effective_rain += (rain - threshold) * decay ** lag

        normalized_position = (current_value - recent_min) / recent_range
        if effective_rain >= threshold:
            response = min(cap, effective_rain / threshold * strength)
            dampening = 1.0 - normalized_position
            current_value += rise[device_id] * response * (0.3 + 0.7 * dampening)
        else:
            current_value += slope[device_id] * (0.5 + normalized_position)
        predictions.append(current_value)
    return np.asarray(predictions)


def evaluate_mode(mode, probe_number, sensor_data, weather, parameters):
    rain_thresholds = parameters["RAIN_EVENT_MM_PER_SENSOR"]
    full_rise, full_slope = build_archived_tables(
        sensor_data, weather, rain_thresholds
    )
    records = []

    for depth_cm in sorted(sensor_data["depth_cm"].dropna().unique()):
        depth_data = sensor_data[sensor_data["depth_cm"] == depth_cm]
        cases = []
        for device_id, probe_data in depth_data.groupby("device_id"):
            for case in build_cases(probe_data, weather)[::FORECAST_HORIZON_DAYS]:
                case["device_id"] = int(device_id)
                cases.append(case)
        origins = sorted({case["origin_date"] for case in cases})
        if len(origins) < 3:
            continue
        holdout_count = min(HOLDOUT_WEEKS, max(1, len(origins) // 4))
        holdout_origins = set(origins[-holdout_count:])
        for case in cases:
            if case["origin_date"] not in holdout_origins:
                continue
            device_id = case["device_id"]
            if mode == "leakage_free":
                rise, slope = build_archived_tables(
                    sensor_data,
                    weather,
                    rain_thresholds,
                    case["origin_date"],
                )
            else:
                rise, slope = full_rise, full_slope
            raw_prediction = predict_archived_path(
                device_id,
                case["origin_date"],
                sensor_data,
                weather,
                rise,
                slope,
                parameters,
            )
            if raw_prediction is None:
                continue
            probe_history = sensor_data[
                (sensor_data["device_id"] == device_id)
                & (sensor_data["date"] <= case["origin_date"])
            ]
            current_value = float(
                probe_history.loc[
                    probe_history["date"] == case["origin_date"],
                    "relative_permittivity",
                ].iloc[0]
            )
            records.append(
                {
                    "mode": mode,
                    "probe_number": int(probe_number),
                    "depth_cm": int(depth_cm),
                    "device_id": int(device_id),
                    "origin_date": case["origin_date"].isoformat(),
                    "model_mae": float(np.mean(np.abs(
                        raw_prediction - case["actual"]
                    ))),
                    "persistence_mae": float(np.mean(np.abs(
                        current_value - case["actual"]
                    ))),
                }
            )
    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ARTIFACT_DIR / "archived_model_benchmark.csv",
    )
    parser.add_argument("--probes", type=int, nargs="+", default=[1])
    arguments = parser.parse_args()
    parameters = load_archived_parameters()
    supported_sensors = set.intersection(
        load_usable_sensor_ids(),
        *[set(values) for values in parameters.values()],
    )
    all_sensor_data = load_daily_sensor_data()
    weather = load_historical_weather()
    benchmark_results = []
    for probe_number in arguments.probes:
        sensor_data = all_sensor_data[
            (all_sensor_data["probe_number"] == probe_number)
            & all_sensor_data["device_id"].isin(supported_sensors)
        ].copy()
        if sensor_data.empty:
            print(f"Probe {probe_number} heeft geen ondersteunde sensoren")
            continue
        benchmark_results.extend([
            evaluate_mode(
                "archived_full_history",
                probe_number,
                sensor_data,
                weather,
                parameters,
            ),
            evaluate_mode(
                "leakage_free",
                probe_number,
                sensor_data,
                weather,
                parameters,
            ),
        ])
    if not benchmark_results:
        raise ValueError("Geen benchmarkresultaten voor de gekozen probes")
    details = pd.concat(benchmark_results, ignore_index=True)
    summary = (
        details.groupby(["mode", "probe_number", "depth_cm"], as_index=False)
        .agg(
            sensors=("device_id", "nunique"),
            holdout_cases=("origin_date", "size"),
            model_mae=("model_mae", "mean"),
            persistence_mae=("persistence_mae", "mean"),
        )
    )
    summary["beats_persistence"] = summary["model_mae"] < summary["persistence_mae"]
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(arguments.output, index=False)
    details_output = arguments.output.with_name(
        f"{arguments.output.stem}_cases{arguments.output.suffix}"
    )
    details.to_csv(details_output, index=False)
    print(summary.to_string(index=False))
    print(f"Benchmark geschreven naar {arguments.output}")
    print(f"Onderliggende eindtests geschreven naar {details_output}")


if __name__ == "__main__":
    main()

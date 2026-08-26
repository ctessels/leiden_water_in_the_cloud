"""Maak vier onafhankelijke evaluatiegrafieken per getrainde sensor-probe."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .permittivity_prediction_model import (
        FORECAST_HORIZON_DAYS,
        MODEL_PATH,
        create_staging_directory,
        load_active_probe_inventory,
        load_daily_sensor_data,
        load_historical_weather,
        load_usable_sensor_ids,
        predict_archived_path,
        probe_key,
        probe_visualisation_directory,
        replace_generated_directory,
        write_permittivity_weather_graph,
    )
    from .train_permittivity_prediction_model import build_cases
except ImportError:
    from permittivity_prediction_model import (
        FORECAST_HORIZON_DAYS,
        MODEL_PATH,
        create_staging_directory,
        load_active_probe_inventory,
        load_daily_sensor_data,
        load_historical_weather,
        load_usable_sensor_ids,
        predict_archived_path,
        probe_key,
        probe_visualisation_directory,
        replace_generated_directory,
        write_permittivity_weather_graph,
    )
    from train_permittivity_prediction_model import build_cases


TRAINING_VISUALISATION_DIR = (
    Path(__file__).resolve().parent / "training_visualisation"
)
VISUALISATION_WEEKS = 4


def select_weekly_cases(
    cases: list[dict[str, object]],
    training_end: date,
) -> list[tuple[int, dict[str, object]]]:
    """Kies iedere beschikbare eerste voorspelsituatie per evaluatieweek."""
    evaluation_start = training_end + timedelta(days=1)
    selected = []
    for week_number in range(VISUALISATION_WEEKS):
        week_start = evaluation_start + timedelta(days=week_number * 7)
        week_end = week_start + timedelta(days=6)
        weekly_cases = [
            case
            for case in cases
            if week_start <= case["origin_date"] <= week_end
        ]
        if weekly_cases:
            selected.append(
                (
                    week_number + 1,
                    min(weekly_cases, key=lambda case: case["origin_date"]),
                )
            )
    return selected


def generate_training_visualisations(
    model_path: Path = MODEL_PATH,
    output_dir: Path = TRAINING_VISUALISATION_DIR,
) -> Path:
    """Schrijf alle beschikbare evaluatiegrafieken voor bruikbare sensoren."""
    print(
        f"Trainingvisualisatie gestart | model: {model_path}",
        flush=True,
    )
    with model_path.open(encoding="utf-8") as source:
        artifact = json.load(source)
    if artifact.get("prediction_target") != "relative_permittivity":
        raise ValueError("Ongeldig modelbestand")
    if int(artifact.get("holdout_weeks", 0)) != VISUALISATION_WEEKS:
        raise ValueError(
            "Het modelbestand moet precies vier evaluatieweken bevatten"
        )

    usable_sensor_ids = load_usable_sensor_ids()
    inventory = load_active_probe_inventory()
    inventory = inventory[inventory["device_id"].isin(usable_sensor_ids)].copy()
    inventory["_location_sort"] = (
        inventory["location_name"].fillna("").astype(str).str.casefold()
    )
    inventory = inventory.sort_values(
        ["_location_sort", "depth_cm", "device_id", "probe_number"],
        na_position="last",
    ).drop(columns="_location_sort")
    daily_data = load_daily_sensor_data()
    weather = load_historical_weather()
    prepared = []
    total_probes = len(inventory)
    print(
        f"Selectie geladen | {len(usable_sensor_ids)} bruikbare sensoren | "
        f"{total_probes} actieve {'probe' if total_probes == 1 else 'probes'}",
        flush=True,
    )
    for completed_probes, inventory_row in enumerate(
        inventory.itertuples(index=False),
        start=1,
    ):
        device_id = int(inventory_row.device_id)
        probe_number = int(inventory_row.probe_number)
        depth_text = (
            f"{float(inventory_row.depth_cm):g} cm"
            if not pd.isna(inventory_row.depth_cm)
            else "onbekende diepte"
        )
        prefix = (
            f"[{completed_probes}/{total_probes}] sensor {device_id} | "
            f"probe {probe_number} | {depth_text}"
        )
        if pd.isna(inventory_row.depth_cm):
            print(f"{prefix} | overgeslagen: ongeldige diepte", flush=True)
            continue
        depth_cm = inventory_row.depth_cm
        key = probe_key(device_id, probe_number, depth_cm)
        probe_model = artifact["probe_models"].get(key)
        if probe_model is None:
            print(f"{prefix} | overgeslagen: geen getraind model", flush=True)
            continue
        if probe_model.get("status") != "trained":
            print(
                f"{prefix} | overgeslagen: {probe_model.get('status', 'onbekend')}",
                flush=True,
            )
            continue
        probe_data = daily_data[
            (daily_data["device_id"] == device_id)
            & (daily_data["probe_number"] == probe_number)
            & (daily_data["depth_cm"] == depth_cm)
        ].sort_values("date")
        if probe_data.empty:
            print(f"{prefix} | overgeslagen: geen sensordata", flush=True)
            continue
        cases = build_cases(probe_data, weather)
        selected_cases = select_weekly_cases(
            cases,
            date.fromisoformat(probe_model["training_end"]),
        )
        if not selected_cases:
            print(
                f"{prefix} | overgeslagen: geen complete evaluatieweek",
                flush=True,
            )
            continue
        available_weeks = ", ".join(
            str(week_number) for week_number, _ in selected_cases
        )
        print(
            f"{prefix} | {len(selected_cases)} grafieken beschikbaar | "
            f"evaluatieweken {available_weeks}",
            flush=True,
        )
        prepared.append(
            (
                {
                    "device_id": device_id,
                    "location_name": inventory_row.location_name,
                    "probe_number": probe_number,
                    "depth_cm": depth_cm,
                },
                probe_model,
                probe_data,
                selected_cases,
            )
        )

    staging_dir = create_staging_directory(output_dir)
    rain_by_date = dict(zip(weather["date"], weather["rain_mm"]))
    total_graphs = sum(len(item[3]) for item in prepared)
    try:
        completed_graphs = 0
        for identity, probe_model, probe_data, selected_cases in prepared:
            device_id = identity["device_id"]
            probe_number = identity["probe_number"]
            depth_cm = identity["depth_cm"]
            graph_dir = probe_visualisation_directory(
                staging_dir,
                device_id,
                probe_number,
                depth_cm,
            )
            for week_number, case in selected_cases:
                origin_date = case["origin_date"]
                future_dates = [
                    origin_date + timedelta(days=day_number)
                    for day_number in range(1, FORECAST_HORIZON_DAYS + 1)
                ]
                prediction = predict_archived_path(
                    case["current_value"],
                    case["recent_min"],
                    case["recent_max"],
                    origin_date,
                    rain_by_date,
                    probe_model["parameters"],
                    float(probe_model["average_rise_per_day"]),
                    float(probe_model["average_slope_per_day"]),
                )
                start_date = origin_date - timedelta(days=30)
                end_date = origin_date + timedelta(days=FORECAST_HORIZON_DAYS)
                actual = probe_data[
                    (probe_data["date"] >= start_date)
                    & (probe_data["date"] <= end_date)
                ][["date", "relative_permittivity"]]
                graph_weather = weather[
                    (weather["date"] >= start_date)
                    & (weather["date"] <= end_date)
                ][["date", "rain_mm", "energy_proxy"]]
                graph_path = graph_dir / (
                    f"evaluation_week_{week_number}_{origin_date.isoformat()}.png"
                )
                write_permittivity_weather_graph(
                    path=graph_path,
                    title=(
                        f"{identity['location_name']} - sensor {device_id}, "
                        f"probe {probe_number}, {float(depth_cm):g} cm - "
                        f"evaluatieweek {week_number}"
                    ),
                    actual=actual,
                    weather=graph_weather,
                    prediction_dates=[origin_date, *future_dates],
                    prediction_values=np.concatenate(
                        ([case["current_value"]], prediction)
                    ),
                    origin_date=origin_date,
                )
                completed_graphs += 1
                print(
                    f"[{completed_graphs}/{total_graphs}] grafiek geschreven | "
                    f"sensor {device_id} | probe {probe_number} | "
                    f"evaluatieweek {week_number}",
                    flush=True,
                )
        replace_generated_directory(staging_dir, output_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    print(
        f"Trainingvisualisatie voltooid | {len(prepared)} "
        f"{'probe' if len(prepared) == 1 else 'probes'} | "
        f"{total_graphs} grafieken | uitvoer: {output_dir}",
        flush=True,
    )
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, default=MODEL_PATH)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=TRAINING_VISUALISATION_DIR,
    )
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    try:
        generate_training_visualisations(arguments.model_path, arguments.output_dir)
    except Exception as error:
        print(f"Trainingvisualisatie gestopt met fout | {error}", flush=True)
        raise


if __name__ == "__main__":
    main()

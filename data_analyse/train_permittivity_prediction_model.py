"""Train de parameters van het gearchiveerde model per sensor en probe."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .permittivity_prediction_model import (
        ARTIFACT_DIR,
        FORECAST_HORIZON_DAYS,
        MINIMUM_TRAINING_DAYS,
        MODEL_PATH,
        RAIN_MEMORY_DAYS,
        calculate_archived_statistics,
        calculate_critical_permittivity,
        load_active_probe_inventory,
        load_daily_sensor_data,
        load_historical_weather,
        load_usable_sensor_ids,
        predict_archived_path,
        probe_key,
        write_excel_workbook,
    )
except ImportError:
    from permittivity_prediction_model import (
        ARTIFACT_DIR,
        FORECAST_HORIZON_DAYS,
        MINIMUM_TRAINING_DAYS,
        MODEL_PATH,
        RAIN_MEMORY_DAYS,
        calculate_archived_statistics,
        calculate_critical_permittivity,
        load_active_probe_inventory,
        load_daily_sensor_data,
        load_historical_weather,
        load_usable_sensor_ids,
        predict_archived_path,
        probe_key,
        write_excel_workbook,
    )


CONFIG_PATH = Path(__file__).resolve().parent / "archived_model_training_config.json"
PARAMETER_NAMES = [
    "rain_threshold_mm",
    "rain_response_strength",
    "max_rain_response_multiplier",
    "rain_memory_decay",
]


def grid_values(specification: dict[str, float]) -> list[float]:
    """Maak een inclusief raster zonder cumulatieve afrondingsfouten."""
    start = float(specification["start"])
    stop = float(specification["stop"])
    step = float(specification["step"])
    count = int(round((stop - start) / step))
    return [round(start + index * step, 10) for index in range(count + 1)]


def build_cases(probe_data: pd.DataFrame, weather: pd.DataFrame) -> list[dict[str, object]]:
    """Bouw wekelijkse situaties met zeven complete toekomstige meetdagen."""
    probe_by_date = probe_data.sort_values("date").set_index("date")
    rain_by_date = weather.set_index("date")["rain_mm"].to_dict()
    origin = probe_by_date.index.min() + timedelta(days=MINIMUM_TRAINING_DAYS)
    last_origin = probe_by_date.index.max() - timedelta(days=FORECAST_HORIZON_DAYS)
    cases = []
    while origin <= last_origin:
        future_dates = [
            origin + timedelta(days=day_number)
            for day_number in range(1, FORECAST_HORIZON_DAYS + 1)
        ]
        recent = probe_by_date.loc[
            (probe_by_date.index >= origin - timedelta(days=30))
            & (probe_by_date.index <= origin)
        ]
        rain_dates = [
            [
                origin + timedelta(days=day_number - lag)
                for lag in range(RAIN_MEMORY_DAYS)
            ]
            for day_number in range(1, FORECAST_HORIZON_DAYS + 1)
        ]
        if (
            origin in probe_by_date.index
            and len(recent)
            and all(day in probe_by_date.index for day in future_dates)
            and all(day in rain_by_date for dates in rain_dates for day in dates)
        ):
            cases.append(
                {
                    "origin_date": origin,
                    "current_value": float(
                        probe_by_date.loc[origin, "relative_permittivity"]
                    ),
                    "recent_min": float(recent["relative_permittivity"].min()),
                    "recent_max": float(recent["relative_permittivity"].max()),
                    "actual": probe_by_date.loc[
                        future_dates, "relative_permittivity"
                    ].to_numpy(float),
                    "rain_window": np.asarray(
                        [
                            [float(rain_by_date[day]) for day in dates]
                            for dates in rain_dates
                        ],
                        dtype=float,
                    ),
                }
            )
        origin += timedelta(days=1)
    return cases


def score_candidate_batch(
    cases: list[dict[str, object]],
    threshold: float,
    candidates: list[tuple[float, float, float]],
    average_rise: float,
    average_slope: float,
) -> np.ndarray:
    """Score veel parametercombinaties tegelijk met exact dezelfde vergelijking."""
    strengths = np.asarray([value[0] for value in candidates], dtype=float)[:, None]
    caps = np.asarray([value[1] for value in candidates], dtype=float)[:, None]
    decays = np.asarray([value[2] for value in candidates], dtype=float)[:, None]
    current = np.broadcast_to(
        np.asarray([case["current_value"] for case in cases], dtype=float),
        (len(candidates), len(cases)),
    ).copy()
    recent_min = np.asarray([case["recent_min"] for case in cases], dtype=float)[None, :]
    recent_range = np.maximum(
        np.asarray(
            [case["recent_max"] - case["recent_min"] for case in cases],
            dtype=float,
        )[None, :],
        0.05,
    )
    rain = np.stack([case["rain_window"] for case in cases])
    actual = np.stack([case["actual"] for case in cases])
    absolute_error = np.zeros(len(candidates), dtype=float)

    for day_number in range(FORECAST_HORIZON_DAYS):
        day_rain = rain[:, day_number, :]
        excess = np.where(day_rain >= threshold, day_rain - threshold, 0.0)
        decay_weights = decays[:, :, None] ** np.arange(RAIN_MEMORY_DAYS)[None, None, :]
        effective_rain = np.sum(excess[None, :, :] * decay_weights, axis=2)
        normalized_position = (current - recent_min) / recent_range
        response = np.minimum(caps, effective_rain / threshold * strengths)
        wet_value = current + average_rise * response * (
            0.3 + 0.7 * (1.0 - normalized_position)
        )
        dry_value = current + average_slope * (0.5 + normalized_position)
        current = np.where(effective_rain >= threshold, wet_value, dry_value)
        absolute_error += np.sum(
            np.abs(current - actual[:, day_number][None, :]),
            axis=1,
        )
    return absolute_error / (len(cases) * FORECAST_HORIZON_DAYS)


def search_grid(
    cases: list[dict[str, object]],
    training_history: pd.DataFrame,
    weather: pd.DataFrame,
    grid: dict[str, list[float]],
    batch_size: int,
    keep: int = 5,
) -> tuple[list[dict[str, object]], int]:
    """Doorzoek een raster en bewaar de beste unieke combinaties."""
    leaderboard = []
    combinations_tested = 0
    tail_names = PARAMETER_NAMES[1:]
    tail_values = [grid[name] for name in tail_names]

    for threshold in grid["rain_threshold_mm"]:
        statistics = calculate_archived_statistics(
            training_history, weather, threshold
        )
        if statistics is None:
            continue
        average_rise, average_slope = statistics
        combinations = itertools.product(*tail_values)
        while True:
            batch = list(itertools.islice(combinations, batch_size))
            if not batch:
                break
            scores = score_candidate_batch(
                cases,
                threshold,
                batch,
                average_rise,
                average_slope,
            )
            combinations_tested += len(batch)
            best_indexes = np.argsort(scores)[: min(keep, len(scores))]
            for index in best_indexes:
                leaderboard.append(
                    {
                        "score": float(scores[index]),
                        "parameters": {
                            "rain_threshold_mm": float(threshold),
                            **{
                                name: float(value)
                                for name, value in zip(tail_names, batch[index])
                            },
                        },
                    }
                )

    unique = {}
    for result in sorted(leaderboard, key=lambda item: item["score"]):
        identity = tuple(result["parameters"][name] for name in PARAMETER_NAMES)
        unique.setdefault(identity, result)
    return list(unique.values())[:keep], combinations_tested


def refined_grid(
    leaders: list[dict[str, object]],
    exhaustive_grid: dict[str, list[float]],
    coarse_specification: dict[str, dict[str, float]],
    radius: float,
) -> dict[str, list[float]]:
    """Neem fijne rasterpunten rond meerdere sterke grove kandidaten."""
    result = {}
    for name in PARAMETER_NAMES:
        allowed = set()
        coarse_step = float(coarse_specification[name]["step"])
        for leader in leaders:
            centre = float(leader["parameters"][name])
            allowed.update(
                value
                for value in exhaustive_grid[name]
                if abs(value - centre) <= coarse_step * radius + 1e-12
            )
        result[name] = sorted(allowed)
    return result


def evaluate_cases(
    cases: list[dict[str, object]],
    parameters: dict[str, float],
    average_rise: float,
    average_slope: float,
) -> tuple[dict[str, object], list[dict[str, object]], list[list[float]]]:
    """Bereken onafhankelijke evaluatiecijfers en foutpaden."""
    model_errors = []
    persistence_errors = []
    details = []
    residuals = []
    for case in cases:
        rain_by_date = {}
        for day_number in range(FORECAST_HORIZON_DAYS):
            prediction_date = case["origin_date"] + timedelta(days=day_number + 1)
            for lag in range(RAIN_MEMORY_DAYS):
                rain_by_date[prediction_date - timedelta(days=lag)] = float(
                    case["rain_window"][day_number, lag]
                )
        prediction = predict_archived_path(
            case["current_value"],
            case["recent_min"],
            case["recent_max"],
            case["origin_date"],
            rain_by_date,
            parameters,
            average_rise,
            average_slope,
        )
        model_mae = float(np.mean(np.abs(prediction - case["actual"])))
        persistence_mae = float(
            np.mean(np.abs(case["current_value"] - case["actual"]))
        )
        model_errors.append(model_mae)
        persistence_errors.append(persistence_mae)
        residual = case["actual"] - prediction
        residuals.append([float(value) for value in residual])
        details.append(
            {
                "origin_date": case["origin_date"].isoformat(),
                "model_mae": model_mae,
                "persistence_mae": persistence_mae,
            }
        )
    metrics = {
        "cases": len(cases),
        "model_mae": float(np.mean(model_errors)) if model_errors else None,
        "persistence_mae": (
            float(np.mean(persistence_errors)) if persistence_errors else None
        ),
        "beats_persistence": (
            bool(np.mean(model_errors) < np.mean(persistence_errors))
            if model_errors and persistence_errors
            else False
        ),
    }
    return metrics, details, residuals


def train_probe(job: dict[str, object]) -> dict[str, object]:
    """Train een zelfstandig model voor precies een sensor-probe-diepte."""
    inventory = job["inventory"]
    probe_data = job["probe_data"].sort_values("date")
    weather = job["weather"]
    config = job["config"]
    cases = build_cases(probe_data, weather)
    minimum_cases = int(config["minimum_parameter_training_cases"])
    if len(cases) < minimum_cases + 1:
        return {**inventory, "status": "insufficient_model_history"}

    holdout_start = cases[-1]["origin_date"] - timedelta(
        days=int(config["holdout_weeks"]) * 7 - 1
    )
    training_cases = [
        case for case in cases if case["origin_date"] < holdout_start
    ]
    evaluation_cases = [
        case for case in cases if case["origin_date"] >= holdout_start
    ]
    if len(training_cases) < minimum_cases:
        return {**inventory, "status": "insufficient_model_history"}

    training_end = evaluation_cases[0]["origin_date"] - timedelta(days=1)
    training_history = probe_data[probe_data["date"] <= training_end]
    critical_permittivity = calculate_critical_permittivity(
        training_history["relative_permittivity"],
        float(config["critical_relative_permittivity_quantile"]),
    )
    if critical_permittivity is None:
        return {**inventory, "status": "invalid_permittivity_history"}
    exhaustive = {
        name: grid_values(config["exhaustive_grid"][name])
        for name in PARAMETER_NAMES
    }

    if job["method"] == "exhaustive":
        leaders, combinations_tested = search_grid(
            training_cases,
            training_history,
            weather,
            exhaustive,
            int(config["batch_size"]),
        )
    else:
        coarse = {
            name: grid_values(config["coarse_grid"][name])
            for name in PARAMETER_NAMES
        }
        coarse_cases = training_cases[:: int(config["coarse_origin_stride_days"])]
        coarse_leaders, coarse_tested = search_grid(
            coarse_cases,
            training_history,
            weather,
            coarse,
            int(config["batch_size"]),
        )
        if not coarse_leaders:
            return {**inventory, "status": "no_valid_parameter_combination"}
        fine = refined_grid(
            coarse_leaders,
            exhaustive,
            config["coarse_grid"],
            float(config["refinement_radius_in_coarse_steps"]),
        )
        leaders, fine_tested = search_grid(
            training_cases,
            training_history,
            weather,
            fine,
            int(config["batch_size"]),
        )
        combinations_tested = coarse_tested + fine_tested

    if not leaders:
        return {**inventory, "status": "no_valid_parameter_combination"}
    best = leaders[0]
    statistics = calculate_archived_statistics(
        training_history,
        weather,
        best["parameters"]["rain_threshold_mm"],
    )
    if statistics is None:
        return {**inventory, "status": "no_valid_event_statistics"}
    average_rise, average_slope = statistics
    evaluation, evaluation_details, residuals = evaluate_cases(
        evaluation_cases,
        best["parameters"],
        average_rise,
        average_slope,
    )
    return {
        **inventory,
        "status": "trained",
        "trained_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "parameters": best["parameters"],
        "training_score_mae": best["score"],
        "average_rise_per_day": average_rise,
        "average_slope_per_day": average_slope,
        "critical_relative_permittivity": critical_permittivity,
        "training_start": training_history["date"].min().isoformat(),
        "training_end": training_history["date"].max().isoformat(),
        "training_daily_observations": int(len(training_history)),
        "training_raw_readings": int(training_history["raw_readings"].sum()),
        "parameter_training_cases": len(training_cases),
        "combinations_tested": combinations_tested,
        "evaluation": evaluation,
        "evaluation_details": evaluation_details,
        "evaluation_residuals_relative_permittivity": residuals,
    }


def cache_signature(job: dict[str, object]) -> str:
    payload = {
        "method": job["method"],
        "inventory": job["inventory"],
        "config": job["config"],
        "code_hash": job["code_hash"],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
    probe_values = job["probe_data"][[
        "date", "relative_permittivity", "raw_readings"
    ]]
    weather_values = job["weather"][["date", "rain_mm"]]
    digest.update(pd.util.hash_pandas_object(probe_values, index=False).values.tobytes())
    digest.update(pd.util.hash_pandas_object(weather_values, index=False).values.tobytes())
    return digest.hexdigest()


def format_progress_line(
    result: dict[str, object],
    completed_probes: int,
    total_probes: int,
    source: str = "",
) -> str:
    """Maak een direct herkenbare voortgangsregel voor een probe."""
    remaining = total_probes - completed_probes
    depth = (
        f"{int(result['depth_cm'])} cm"
        if result.get("depth_cm") is not None
        else "onbekende diepte"
    )
    source_text = f" ({source})" if source else ""
    metric = ""
    if result.get("status") == "trained" and result.get("evaluation"):
        model_mae = result["evaluation"].get("model_mae")
        if model_mae is not None:
            metric = f" | evaluatie-MAE {float(model_mae):.6f}"
    probe_word = "probe" if remaining == 1 else "probes"
    return (
        f"[{completed_probes}/{total_probes}] sensor {result['device_id']} | "
        f"probe {result['probe_number']} | {depth} | {result['status']}{source_text}"
        f"{metric} | {remaining} {probe_word} te gaan"
    )


def train_all(
    method: str,
    config_path: Path,
    model_path: Path,
    artifact_dir: Path,
    workers: int,
    resume: bool,
    device_ids: list[int] | None,
    probe_numbers: list[int] | None,
) -> tuple[Path, Path]:
    """Train alle geselecteerde probes en schrijf model plus evaluatiewerkmap."""
    print(
        f"Parametertraining gestart | methode: {method} | workers: {workers} | "
        f"cache hervatten: {resume}",
        flush=True,
    )
    with config_path.open(encoding="utf-8") as source:
        config = json.load(source)
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    usable_sensor_ids = load_usable_sensor_ids()
    inventory = load_active_probe_inventory()
    daily_data = load_daily_sensor_data()
    weather = load_historical_weather()
    code_hash = hashlib.sha256(
        Path(__file__).read_bytes()
        + (Path(__file__).resolve().parent / "permittivity_prediction_model.py").read_bytes()
    ).hexdigest()
    if device_ids:
        inventory = inventory[inventory["device_id"].isin(device_ids)]
    if probe_numbers:
        inventory = inventory[inventory["probe_number"].isin(probe_numbers)]

    total_probes = len(inventory)
    if total_probes == 0:
        raise ValueError("Geen probes gevonden voor de gekozen filters")
    print(
        f"Invoer geladen | {total_probes} "
        f"{'sensor-probe' if total_probes == 1 else 'sensor-probes'} | "
        "na iedere afgeronde probe volgt een voortgangsregel",
        flush=True,
    )
    results = []
    completed_probes = 0

    def record_result(result: dict[str, object], source: str = "") -> None:
        nonlocal completed_probes
        results.append(result)
        completed_probes += 1
        print(
            format_progress_line(
                result,
                completed_probes,
                total_probes,
                source,
            ),
            flush=True,
        )

    jobs = []
    cache_dir = artifact_dir / "training_cache" / method
    cache_dir.mkdir(parents=True, exist_ok=True)
    for inventory_row in inventory.itertuples(index=False):
        identity = {
            "device_id": int(inventory_row.device_id),
            "location_name": inventory_row.location_name,
            "probe_number": int(inventory_row.probe_number),
            "depth_cm": (
                int(inventory_row.depth_cm)
                if not pd.isna(inventory_row.depth_cm)
                else None
            ),
        }
        if identity["device_id"] not in usable_sensor_ids:
            record_result({**identity, "status": "insufficient_history"})
            continue
        if identity["depth_cm"] is None:
            record_result({**identity, "status": "invalid_depth"})
            continue
        probe_data = daily_data[
            (daily_data["device_id"] == identity["device_id"])
            & (daily_data["probe_number"] == identity["probe_number"])
            & (daily_data["depth_cm"] == identity["depth_cm"])
        ].copy()
        if probe_data.empty:
            record_result({**identity, "status": "missing_sensor_data"})
            continue
        job = {
            "inventory": identity,
            "probe_data": probe_data,
            "weather": weather,
            "config": config,
            "method": method,
            "code_hash": code_hash,
        }
        signature = cache_signature(job)
        cache_path = cache_dir / (
            f"{identity['device_id']}_{identity['probe_number']}_{identity['depth_cm']}.json"
        )
        if resume and cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("cache_signature") == signature:
                record_result(cached["result"], "cache")
                continue
        jobs.append((job, signature, cache_path))

    if workers == 1:
        completed = ((train_probe(job), signature, path) for job, signature, path in jobs)
        for result, signature, cache_path in completed:
            cache_path.write_text(
                json.dumps(
                    {"cache_signature": signature, "result": result},
                    indent=2,
                    ensure_ascii=True,
                ) + "\n",
                encoding="utf-8",
            )
            record_result(result)
    elif jobs:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(train_probe, job): (signature, path)
                for job, signature, path in jobs
            }
            for future in as_completed(futures):
                signature, cache_path = futures[future]
                result = future.result()
                cache_path.write_text(
                    json.dumps(
                        {"cache_signature": signature, "result": result},
                        indent=2,
                        ensure_ascii=True,
                    ) + "\n",
                    encoding="utf-8",
                )
                record_result(result)

    results.sort(
        key=lambda item: (
            item.get("depth_cm") is None,
            item.get("depth_cm") or 0,
            item["device_id"],
            item["probe_number"],
        )
    )
    probe_models = {}
    evaluation_rows = []
    parameter_rows = []
    case_rows = []
    for result in results:
        key = (
            probe_key(result["device_id"], result["probe_number"], result["depth_cm"])
            if result.get("depth_cm") is not None
            else f"{result['device_id']}:{result['probe_number']}:unknown"
        )
        probe_models[key] = {
            name: value
            for name, value in result.items()
            if name not in {"evaluation_details"}
        }
        evaluation_row = {
            "device_id": result["device_id"],
            "location_name": result["location_name"],
            "probe_number": result["probe_number"],
            "depth_cm": result.get("depth_cm"),
            "status": result["status"],
            "method": method,
        }
        if result["status"] == "trained":
            evaluation_row.update(
                {
                    "trained_at": result["trained_at"],
                    "training_start": result["training_start"],
                    "training_end": result["training_end"],
                    "training_daily_observations": result["training_daily_observations"],
                    "training_raw_readings": result["training_raw_readings"],
                    "parameter_training_cases": result["parameter_training_cases"],
                    "evaluation_cases": result["evaluation"]["cases"],
                    "model_mae": result["evaluation"]["model_mae"],
                    "persistence_mae": result["evaluation"]["persistence_mae"],
                    "beats_persistence": result["evaluation"]["beats_persistence"],
                    "combinations_tested": result["combinations_tested"],
                }
            )
            parameter_rows.append(
                {
                    "device_id": result["device_id"],
                    "location_name": result["location_name"],
                    "probe_number": result["probe_number"],
                    "depth_cm": result["depth_cm"],
                    **result["parameters"],
                    "average_rise_per_day": result["average_rise_per_day"],
                    "average_slope_per_day": result["average_slope_per_day"],
                    "critical_relative_permittivity": result[
                        "critical_relative_permittivity"
                    ],
                    "training_score_mae": result["training_score_mae"],
                }
            )
            for detail in result["evaluation_details"]:
                case_rows.append(
                    {
                        "device_id": result["device_id"],
                        "location_name": result["location_name"],
                        "probe_number": result["probe_number"],
                        "depth_cm": result["depth_cm"],
                        **detail,
                    }
                )
        evaluation_rows.append(evaluation_row)

    artifact = {
        "version": 2,
        "model_equation": "archived_sensor_rain_response",
        "prediction_target": "relative_permittivity",
        "created_at": created_at,
        "trained_at": max(
            (
                result["trained_at"]
                for result in results
                if result["status"] == "trained"
            ),
            default=created_at,
        ),
        "training_method": method,
        "holdout_weeks": config["holdout_weeks"],
        "training_config": config,
        "probe_models": probe_models,
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    evaluation_path = artifact_dir / f"training_evaluation_{method}_{timestamp}.xlsx"
    run_information = pd.DataFrame(
        [
            {"item": "model_file_created_at", "value": created_at},
            {"item": "method", "value": method},
            {"item": "model_file", "value": str(model_path)},
            {"item": "holdout_weeks", "value": config["holdout_weeks"]},
            {"item": "workers", "value": workers},
            {"item": "resume_cache", "value": resume},
        ]
    )
    write_excel_workbook(
        evaluation_path,
        {
            "Evaluation": pd.DataFrame(evaluation_rows),
            "Parameters": pd.DataFrame(parameter_rows),
            "Evaluation cases": pd.DataFrame(case_rows),
            "Run information": run_information,
        },
    )
    trained_probes = sum(result["status"] == "trained" for result in results)
    print(
        f"Parametertraining voltooid | {len(results)} "
        f"{'probe' if len(results) == 1 else 'probes'} verwerkt | "
        f"{trained_probes} getraind | model: {model_path} | "
        f"evaluatie: {evaluation_path}",
        flush=True,
    )
    return model_path, evaluation_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--method",
        choices=["exhaustive", "coarse-to-fine"],
        required=True,
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--model-path", type=Path, default=MODEL_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=ARTIFACT_DIR)
    parser.add_argument(
        "--workers",
        type=int,
        default=min(4, max(1, (os.cpu_count() or 2) - 1)),
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--device-ids", type=int, nargs="+")
    parser.add_argument("--probe-numbers", type=int, nargs="+")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    try:
        if arguments.workers < 1:
            raise ValueError("--workers moet minimaal 1 zijn")
        train_all(
            arguments.method,
            arguments.config,
            arguments.model_path,
            arguments.artifact_dir,
            arguments.workers,
            arguments.resume,
            arguments.device_ids,
            arguments.probe_numbers,
        )
    except Exception as error:
        print(f"Parametertraining gestopt met fout | {error}", flush=True)
        raise


if __name__ == "__main__":
    main()

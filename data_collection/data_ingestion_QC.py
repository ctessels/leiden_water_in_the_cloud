"""
Checks whether sensor ingestion is complete enough for analysis.

The quality control includes:
- Battery level of at least 25%.
- At least one datapoint for every expected probe on at least 12 complete UTC
  days in the previous 14 days.
- Per-sensor plots of relative permittivity and soil temperature.
- Datapoint counts for the previous 14 days, compared with an expected
  four-hour reporting interval. These counts do not affect pass/fail.
- An approved, persistent list of usable sensors grouped into three-month
  history categories up to two years.

Data-range and sudden-jump validation are intentionally not implemented yet.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

import ImportExport


# Constants
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "sensor_data" / "database.db"
QC_DAYS = 14
MINIMUM_COMPLETE_DAYS = 12
DATAPOINT_INTERVAL_HOURS = 4
MINIMUM_BATTERY_PERCENTAGE = 25
PLOT_DIRECTORY = BASE_DIR / "sensor_data" / "quality_control_plots"
USABLE_SENSORS_PATH = BASE_DIR / "sensor_data" / "usable_sensors.json"
CATEGORY_MONTHS = tuple(range(24, 2, -3))
CATEGORY_ORDER = tuple(f"{months}months" for months in CATEGORY_MONTHS)


@dataclass(frozen=True)
class FrequencyResult:
    passed: bool
    complete_days_by_probe: dict[int, int]
    missing_dates_by_probe: dict[int, list[str]]
    datapoints_by_probe: dict[int, int]
    expected_datapoints_per_probe: int


@dataclass(frozen=True)
class SensorQCResult:
    device_id: int
    device_name: str
    measuring_points: int
    is_active: bool
    usable_from: date | None
    duration_category: str | None
    battery_percentage: float | None
    battery_passed: bool
    frequency: FrequencyResult

    @property
    def duration_eligible(self) -> bool:
        return self.is_active and self.duration_category is not None

    @property
    def passed(self) -> bool:
        return (
            self.duration_eligible
            and self.battery_passed
            and self.frequency.passed
        )


def _validate_columns(
    dataframe: pd.DataFrame,
    required_columns: set[str],
    table_name: str,
) -> None:
    missing_columns = required_columns.difference(dataframe.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"{table_name} is missing required columns: {missing}")


def _parse_date(value: object) -> date | None:
    if value is None or pd.isna(value):
        return None

    parsed_value = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed_value):
        return None

    return parsed_value.date()


def _get_duration_category(usable_from: date | None, current_date: date) -> str | None:
    if usable_from is None or usable_from >= current_date:
        return None

    current_timestamp = pd.Timestamp(current_date)
    usable_from_timestamp = pd.Timestamp(usable_from)

    for months in CATEGORY_MONTHS:
        if usable_from_timestamp <= current_timestamp - pd.DateOffset(months=months):
            return f"{months}months"

    return None


def _get_qc_window(current_date: date) -> tuple[datetime, datetime]:
    window_end = datetime.combine(current_date, time.min, tzinfo=timezone.utc)
    window_start = window_end - timedelta(days=QC_DAYS)
    return window_start, window_end


def _load_quality_control_data(
    db_path: Path = DB_PATH,
    current_date: date | None = None,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    datetime,
    datetime,
]:
    current_date = current_date or datetime.now(timezone.utc).date()
    window_start, window_end = _get_qc_window(current_date)

    with sqlite3.connect(db_path) as conn:
        dim_sensor = pd.read_sql_query("SELECT * FROM DimSensor", conn)
        dim_battery = pd.read_sql_query("SELECT * FROM DimBattery", conn)
        sensor_data = pd.read_sql_query(
            """
            SELECT
                device_id,
                probe_number,
                timestamp,
                temperature,
                relative_permittivity,
                electric_conductivity
            FROM FactSensorData
            WHERE timestamp >= ?
              AND timestamp < ?
            ORDER BY
                device_id,
                probe_number,
                timestamp
            """,
            conn,
            params=(int(window_start.timestamp()), int(window_end.timestamp())),
        )

    _validate_columns(
        dim_sensor,
        {
            "device_id",
            "device_name",
            "measuring_points",
            "is_active",
            "usable_from",
        },
        "DimSensor",
    )
    _validate_columns(
        dim_battery,
        {"device_id", "battery_percentage"},
        "DimBattery",
    )
    _validate_columns(
        sensor_data,
        {
            "device_id",
            "probe_number",
            "timestamp",
            "temperature",
            "relative_permittivity",
        },
        "FactSensorData",
    )

    sensor_data["timestamp_utc"] = pd.to_datetime(
        sensor_data["timestamp"],
        unit="s",
        utc=True,
        errors="coerce",
    )
    sensor_data = sensor_data.dropna(subset=["timestamp_utc"])
    sensor_data["data_date"] = sensor_data["timestamp_utc"].dt.floor("D")

    return dim_sensor, dim_battery, sensor_data, window_start, window_end


def get_battery_level(
    device_id: int,
    dim_battery: pd.DataFrame,
) -> float | None:
    battery_rows = dim_battery.loc[
        dim_battery["device_id"] == device_id,
        "battery_percentage",
    ]

    if battery_rows.empty or pd.isna(battery_rows.iloc[0]):
        return None

    return float(battery_rows.iloc[0])


def get_data_frequency(
    sensor_data: pd.DataFrame,
    measuring_points: int,
    window_start: datetime,
    window_end: datetime,
) -> FrequencyResult:
    expected_dates = pd.date_range(
        start=window_start,
        end=window_end - timedelta(days=1),
        freq="D",
        tz="UTC",
    )

    counts = (
        sensor_data.groupby(["probe_number", "data_date"])
        .size()
        .to_dict()
    )
    datapoint_counts = sensor_data.groupby("probe_number").size().to_dict()

    complete_days_by_probe: dict[int, int] = {}
    missing_dates_by_probe: dict[int, list[str]] = {}
    datapoints_by_probe: dict[int, int] = {}
    expected_datapoints_per_probe = int(
        (window_end - window_start).total_seconds()
        / timedelta(hours=DATAPOINT_INTERVAL_HOURS).total_seconds()
    )

    if measuring_points < 1:
        return FrequencyResult(
            passed=False,
            complete_days_by_probe={},
            missing_dates_by_probe={0: [date_.date().isoformat() for date_ in expected_dates]},
            datapoints_by_probe={},
            expected_datapoints_per_probe=expected_datapoints_per_probe,
        )

    for probe_number in range(1, measuring_points + 1):
        missing_dates = [
            date_.date().isoformat()
            for date_ in expected_dates
            if counts.get((probe_number, date_), 0) == 0
        ]
        missing_dates_by_probe[probe_number] = missing_dates
        complete_days_by_probe[probe_number] = QC_DAYS - len(missing_dates)
        datapoints_by_probe[probe_number] = int(
            datapoint_counts.get(probe_number, 0)
        )

    return FrequencyResult(
        passed=all(
            complete_days >= MINIMUM_COMPLETE_DAYS
            for complete_days in complete_days_by_probe.values()
        ),
        complete_days_by_probe=complete_days_by_probe,
        missing_dates_by_probe=missing_dates_by_probe,
        datapoints_by_probe=datapoints_by_probe,
        expected_datapoints_per_probe=expected_datapoints_per_probe,
    )


def evaluate_quality_control(
    db_path: Path = DB_PATH,
    current_date: date | None = None,
) -> tuple[list[SensorQCResult], pd.DataFrame, datetime, datetime]:
    current_date = current_date or datetime.now(timezone.utc).date()
    (
        dim_sensor,
        dim_battery,
        sensor_data,
        window_start,
        window_end,
    ) = _load_quality_control_data(db_path, current_date)

    results: list[SensorQCResult] = []

    for sensor in dim_sensor.itertuples(index=False):
        device_id = int(sensor.device_id)
        usable_from = _parse_date(sensor.usable_from)
        measuring_points = (
            int(sensor.measuring_points)
            if pd.notna(sensor.measuring_points)
            else 0
        )
        is_active = bool(sensor.is_active) if pd.notna(sensor.is_active) else False
        battery_percentage = get_battery_level(device_id, dim_battery)
        device_data = sensor_data.loc[sensor_data["device_id"] == device_id]

        results.append(
            SensorQCResult(
                device_id=device_id,
                device_name=str(sensor.device_name),
                measuring_points=measuring_points,
                is_active=is_active,
                usable_from=usable_from,
                duration_category=_get_duration_category(usable_from, current_date),
                battery_percentage=battery_percentage,
                battery_passed=(
                    battery_percentage is not None
                    and battery_percentage >= MINIMUM_BATTERY_PERCENTAGE
                ),
                frequency=get_data_frequency(
                    device_data,
                    measuring_points,
                    window_start,
                    window_end,
                ),
            )
        )

    return results, sensor_data, window_start, window_end


def get_usable_sensors(
    quality_control_results: list[SensorQCResult],
) -> dict[str, list[int]]:
    usable_sensors = {category: [] for category in CATEGORY_ORDER}

    for result in quality_control_results:
        if result.passed and result.duration_category is not None:
            usable_sensors[result.duration_category].append(result.device_id)

    for category in CATEGORY_ORDER:
        usable_sensors[category].sort()

    return usable_sensors


def _format_missing_dates(result: SensorQCResult) -> str:
    missing_parts = []
    for probe_number, missing_dates in result.frequency.missing_dates_by_probe.items():
        if missing_dates:
            missing_parts.append(f"probe {probe_number}: {', '.join(missing_dates)}")

    return "; ".join(missing_parts) if missing_parts else "none"


def _quality_control_summary(
    quality_control_results: list[SensorQCResult],
) -> pd.DataFrame:
    summary_rows = []

    for result in quality_control_results:
        if not result.duration_eligible:
            continue

        datapoints_received = sum(result.frequency.datapoints_by_probe.values())
        expected_datapoints = (
            result.measuring_points
            * result.frequency.expected_datapoints_per_probe
        )

        summary_rows.append(
            {
                "device_id": result.device_id,
                "device_name": result.device_name,
                "category": result.duration_category,
                "battery_percentage": result.battery_percentage,
                "battery_qc": "pass" if result.battery_passed else "fail",
                "frequency_qc": "pass" if result.frequency.passed else "fail",
                "datapoints_received": datapoints_received,
                "expected_datapoints": expected_datapoints,
                "missing_dates": _format_missing_dates(result),
                "overall_qc": "pass" if result.passed else "fail",
            }
        )

    return pd.DataFrame(summary_rows)


def plot_quality_control(
    result: SensorQCResult,
    sensor_data: pd.DataFrame,
    window_start: datetime,
    window_end: datetime,
    output_path: Path,
) -> None:
    device_data = sensor_data.loc[sensor_data["device_id"] == result.device_id]
    figure_height = max(6.5, result.measuring_points * 3.0 + 3.0)
    figure = plt.figure(figsize=(16, figure_height))
    grid = figure.add_gridspec(
        nrows=result.measuring_points + 1,
        ncols=2,
        height_ratios=[1] * result.measuring_points + [0.9],
    )

    for row_index, probe_number in enumerate(range(1, result.measuring_points + 1)):
        probe_data = device_data.loc[
            device_data["probe_number"] == probe_number
        ].sort_values("timestamp_utc")

        permittivity_axis = figure.add_subplot(grid[row_index, 0])
        temperature_axis = figure.add_subplot(grid[row_index, 1])

        if probe_data.empty:
            for axis in (permittivity_axis, temperature_axis):
                axis.text(
                    0.5,
                    0.5,
                    "No data in QC window",
                    horizontalalignment="center",
                    verticalalignment="center",
                    transform=axis.transAxes,
                )
        else:
            permittivity_axis.plot(
                probe_data["timestamp_utc"],
                probe_data["relative_permittivity"],
            )
            temperature_axis.plot(
                probe_data["timestamp_utc"],
                probe_data["temperature"],
            )

        permittivity_axis.set_title(
            f"Probe {probe_number} - Relative permittivity"
        )
        permittivity_axis.set_ylabel("Relative permittivity")
        temperature_axis.set_title(f"Probe {probe_number} - Soil temperature")
        temperature_axis.set_ylabel("Temperature")

        for axis in (permittivity_axis, temperature_axis):
            date_locator = mdates.AutoDateLocator(minticks=4, maxticks=10)
            axis.set_xlim(window_start, window_end)
            axis.grid(True, alpha=0.25)
            axis.xaxis.set_major_locator(date_locator)
            axis.xaxis.set_major_formatter(
                mdates.ConciseDateFormatter(date_locator)
            )

    details_axis = figure.add_subplot(grid[result.measuring_points, :])
    details_axis.axis("off")

    frequency_details = []
    for probe_number in range(1, result.measuring_points + 1):
        complete_days = result.frequency.complete_days_by_probe.get(probe_number, 0)
        missing_dates = result.frequency.missing_dates_by_probe.get(probe_number, [])
        datapoints_received = result.frequency.datapoints_by_probe.get(probe_number, 0)
        missing_text = ", ".join(missing_dates) if missing_dates else "none"
        frequency_details.append(
            [
                f"Probe {probe_number} ingestion",
                (
                    f"complete days: {complete_days}/{QC_DAYS}; "
                    f"datapoints: {datapoints_received}/"
                    f"{result.frequency.expected_datapoints_per_probe}; "
                    f"missing: {missing_text}"
                ),
            ]
        )

    total_datapoints_received = sum(result.frequency.datapoints_by_probe.values())
    total_expected_datapoints = (
        result.measuring_points
        * result.frequency.expected_datapoints_per_probe
    )

    detail_rows = [
        ["Device ID", str(result.device_id)],
        ["Device name", result.device_name],
        ["Usable from", result.usable_from.isoformat() if result.usable_from else "missing"],
        ["Duration category", result.duration_category or "not eligible"],
        [
            "Battery",
            (
                f"{result.battery_percentage:g}% - "
                f"{'pass' if result.battery_passed else 'fail'}"
                if result.battery_percentage is not None
                else "missing - fail"
            ),
        ],
        [
            "Datapoints in QC window",
            (
                f"{total_datapoints_received}/{total_expected_datapoints} expected "
                f"at one datapoint every {DATAPOINT_INTERVAL_HOURS} hours per probe; "
                "informational only"
            ),
        ],
        *frequency_details,
        [
            "Frequency QC",
            (
                f"{'pass' if result.frequency.passed else 'fail'} "
                f"(minimum {MINIMUM_COMPLETE_DAYS}/{QC_DAYS} complete days per probe)"
            ),
        ],
        ["Overall QC", "pass" if result.passed else "fail"],
    ]

    details_table = details_axis.table(
        cellText=detail_rows,
        colLabels=["Check", "Result"],
        cellLoc="left",
        colLoc="left",
        loc="center",
        colWidths=[0.25, 0.75],
    )
    details_table.auto_set_font_size(False)
    details_table.set_fontsize(9)
    details_table.scale(1, 1.35)

    figure.suptitle(
        f"Data-ingestion QC - device {result.device_id} ({result.device_name})",
        fontsize=14,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.97))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def generate_quality_control_plots(
    quality_control_results: list[SensorQCResult],
    sensor_data: pd.DataFrame,
    window_start: datetime,
    window_end: datetime,
    plot_directory: Path = PLOT_DIRECTORY,
) -> list[Path]:
    plot_directory.mkdir(parents=True, exist_ok=True)

    for old_plot in plot_directory.glob("device_*_qc.png"):
        old_plot.unlink()

    plot_paths = []
    for result in quality_control_results:
        if not result.duration_eligible:
            continue

        output_path = plot_directory / f"device_{result.device_id}_qc.png"
        plot_quality_control(
            result,
            sensor_data,
            window_start,
            window_end,
            output_path,
        )
        plot_paths.append(output_path)

    return plot_paths


def persist_usable_sensors(
    usable_sensors: dict[str, list[int]],
    output_path: Path = USABLE_SENSORS_PATH,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")

    with temporary_path.open("w", encoding="utf-8") as output_file:
        json.dump(usable_sensors, output_file, indent=2)
        output_file.write("\n")

    temporary_path.replace(output_path)


def _prompt_yes_no(prompt: str) -> bool:
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter 'y' or 'n'.")


def _print_proposal(
    quality_control_results: list[SensorQCResult],
    usable_sensors: dict[str, list[int]],
    plot_paths: list[Path],
) -> None:
    print("\nQuality-control results for duration-eligible sensors:")
    summary = _quality_control_summary(quality_control_results)
    if summary.empty:
        print("No sensors currently have at least three months of usable data.")
    else:
        print(summary.to_string(index=False))

    print("\nProposed usable sensors:")
    print(json.dumps(usable_sensors, indent=2))
    print(f"\nGenerated {len(plot_paths)} QC plot(s) in {PLOT_DIRECTORY}")


def update_usable_sensors(
    db_path: Path = DB_PATH,
    usable_sensors_path: Path = USABLE_SENSORS_PATH,
) -> dict[str, list[int]]:
    while True:
        (
            quality_control_results,
            sensor_data,
            window_start,
            window_end,
        ) = evaluate_quality_control(db_path)

        usable_sensors = get_usable_sensors(quality_control_results)
        plot_paths = generate_quality_control_plots(
            quality_control_results,
            sensor_data,
            window_start,
            window_end,
        )
        _print_proposal(quality_control_results, usable_sensors, plot_paths)

        if _prompt_yes_no("\nDo you approve this usable-sensor list? y/n: "):
            persist_usable_sensors(usable_sensors, usable_sensors_path)
            print(f"Usable sensors updated in {usable_sensors_path}")
            return usable_sensors

        excel_path = ImportExport.export_dimsensor_to_excel(db_path)
        print(
            "Please manually update the 'usable_from' dates in "
            f"{excel_path}."
        )

        while not _prompt_yes_no(
            "Has the Excel file been updated and is it ready for import? y/n: "
        ):
            pass

        ImportExport.import_dimsensor_from_excel(db_path)
        print("DimSensor reimported. Recalculating the proposal.")


def main() -> None:
    update_usable_sensors()


if __name__ == "__main__":
    main()


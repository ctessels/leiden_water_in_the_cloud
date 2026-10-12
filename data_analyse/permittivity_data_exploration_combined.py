"""Verken relatieve permittiviteit van meerdere sensoren in één grafiek."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

try:
    from .permittivity_prediction_model import (
        load_active_probe_inventory,
        load_daily_sensor_data,
        load_historical_weather,
    )
except ImportError:
    from permittivity_prediction_model import (
        load_active_probe_inventory,
        load_daily_sensor_data,
        load_historical_weather,
    )


OUTPUT_DIR = Path(__file__).resolve().parent / "data_exploration" / "combined"


def parse_device_ids(value: str) -> list[int]:
    """Lees een kommagescheiden lijst met sensor-id's."""
    try:
        device_ids = [
            int(device_id.strip())
            for device_id in value.split(",")
            if device_id.strip()
        ]
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "device-ids moet een kommagescheiden lijst met gehele getallen zijn"
        ) from error

    if not device_ids:
        raise argparse.ArgumentTypeError("Geef minimaal één sensor-id op")
    if any(device_id <= 0 for device_id in device_ids):
        raise argparse.ArgumentTypeError("Sensor-id's moeten positief zijn")
    return device_ids


def parse_probe_number(value: str) -> int:
    """Lees een positief probenummer."""
    try:
        probe_number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "probe-number moet een positief geheel getal zijn"
        ) from error
    if probe_number <= 0:
        raise argparse.ArgumentTypeError(
            "probe-number moet een positief geheel getal zijn"
        )
    return probe_number


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def sensor_label(inventory_row: pd.Series) -> str:
    """Maak een korte legenda-tekst voor één sensorlijn."""
    depth_text = (
        "onbekende diepte"
        if pd.isna(inventory_row["depth_cm"])
        else f"{float(inventory_row['depth_cm']):g} cm"
    )
    location = inventory_row["location_name"] or "Onbekende locatie"
    return (
        f"{location} | sensor {int(inventory_row['device_id'])} | "
        f"probe {int(inventory_row['probe_number'])} | {depth_text}"
    )


def default_output_path(
    device_ids: list[int],
    probe_number: int,
    start: date | None,
    end: date | None,
    output_dir: Path,
) -> Path:
    """Bepaal de standaard bestandsnaam voor de gecombineerde grafiek."""
    sensor_part = "_".join(str(device_id) for device_id in device_ids)
    period_part = ""
    if start is not None or end is not None:
        period_part = f"_{start or 'begin'}_tot_{end or 'einde'}"
    return output_dir / f"sensors_{sensor_part}_probe_{probe_number}{period_part}.png"


def write_combined_permittivity_graph(
    path: Path,
    title: str,
    series: list[tuple[str, pd.DataFrame]],
    weather: pd.DataFrame | None = None,
) -> None:
    """Schrijf één grafiek waarin iedere sensor een eigen lijn heeft."""
    if not series:
        raise ValueError("Geen sensordata om te tekenen")

    path.parent.mkdir(parents=True, exist_ok=True)

    figure, axis = plt.subplots(figsize=(14, 7))

    bar_axis = None
    if weather is not None and not weather.empty:
        bar_axis = axis.twinx()
        bar_axis.bar(
            weather["date"],
            weather["rain_mm"],
            width=0.8,
            alpha=0.22,
            color="#4C78A8",
            label="Neerslag (mm)",
            zorder=1,
        )
        bar_axis.set_ylabel("Neerslag (mm)")
        # Houd de sensorlijnen boven de neerslagstaven.
        axis.set_zorder(bar_axis.get_zorder() + 1)
        axis.patch.set_visible(False)

    for label, data in series:
        axis.plot(
            data["date"],
            data["relative_permittivity"],
            linewidth=2.0,
            marker="o",
            markersize=2.5,
            label=label,
        )

    axis.set_title(title)
    axis.set_xlabel("Datum")
    axis.set_ylabel("Relatieve permittiviteit")
    axis.grid(axis="y", alpha=0.2)
    lines, labels = axis.get_legend_handles_labels()
    if bar_axis is not None:
        bar_lines, bar_labels = bar_axis.get_legend_handles_labels()
        lines += bar_lines
        labels += bar_labels
    axis.legend(lines, labels, loc="best")
    axis.xaxis.set_major_locator(mdates.AutoDateLocator())
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))

    figure.autofmt_xdate(rotation=35)
    figure.tight_layout()
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def generate_combined_graph(
    device_ids: list[int],
    probe_number: int,
    start: date | None = None,
    end: date | None = None,
    output_dir: Path = OUTPUT_DIR,
    output_path: Path | None = None,
) -> Path:
    """Genereer een gecombineerde permittiviteitsgrafiek voor meerdere sensoren."""
    if start is not None and end is not None and start > end:
        raise ValueError("De startdatum mag niet na de einddatum liggen")

    inventory = load_active_probe_inventory()
    inventory = inventory[
        inventory["device_id"].isin(device_ids)
        & (inventory["probe_number"] == probe_number)
    ].copy()

    if inventory.empty:
        raise ValueError("Geen geregistreerde probes gevonden voor deze selectie")

    daily_data = load_daily_sensor_data()
    graph_series: list[tuple[str, pd.DataFrame]] = []

    for device_id in device_ids:
        matching_inventory = inventory[inventory["device_id"] == device_id]
        if matching_inventory.empty:
            print(
                f"Sensor {device_id} | probe {probe_number} | overgeslagen: "
                "niet geregistreerd",
                flush=True,
            )
            continue

        identity = matching_inventory.iloc[0]
        if pd.isna(identity["depth_cm"]):
            print(
                f"Sensor {device_id} | probe {probe_number} | overgeslagen: "
                "diepte ontbreekt",
                flush=True,
            )
            continue

        sensor_data = daily_data[
            (daily_data["device_id"] == device_id)
            & (daily_data["probe_number"] == probe_number)
            & (daily_data["depth_cm"] == identity["depth_cm"])
        ].copy()

        if start is not None:
            sensor_data = sensor_data[sensor_data["date"] >= start]
        if end is not None:
            sensor_data = sensor_data[sensor_data["date"] <= end]

        if sensor_data.empty:
            print(
                f"Sensor {device_id} | probe {probe_number} | overgeslagen: "
                "geen gegevens binnen periode",
                flush=True,
            )
            continue

        sensor_data = sensor_data.sort_values("date")
        graph_series.append(
            (
                sensor_label(identity),
                sensor_data[["date", "relative_permittivity"]],
            )
        )
        print(
            f"Sensor {device_id} | probe {probe_number} | "
            f"{len(sensor_data)} dagwaarden toegevoegd",
            flush=True,
        )

    if not graph_series:
        raise ValueError("Geen sensor bevat gegevens binnen de gekozen periode")

    path = output_path or default_output_path(
        device_ids=device_ids,
        probe_number=probe_number,
        start=start,
        end=end,
        output_dir=output_dir,
    )

    first_date = min(data["date"].min() for _, data in graph_series)
    last_date = max(data["date"].max() for _, data in graph_series)
    weather = load_historical_weather()
    weather = weather[
        (weather["date"] >= first_date) & (weather["date"] <= last_date)
    ]

    title = (
        f"Relatieve permittiviteit en neerslag per sensor - probe {probe_number} "
        f"({start or 'begin'} t/m {end or 'einde'})"
    )
    write_combined_permittivity_graph(path, title, graph_series, weather)
    return path.resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device-ids",
        type=parse_device_ids,
        required=True,
        help="Kommagescheiden sensor-id's, bijvoorbeeld: 356,397,414",
    )
    parser.add_argument("--probe-number", type=parse_probe_number, required=True)
    parser.add_argument("--start", type=parse_date)
    parser.add_argument("--end", type=parse_date)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.output is not None and arguments.output_dir != OUTPUT_DIR:
        parser.error("--output en --output-dir kunnen niet samen worden gebruikt")
    if arguments.output is not None and arguments.output.suffix.casefold() != ".png":
        parser.error("--output moet een .png-bestand zijn")

    print(
        "Gecombineerde dataverkenning gestart"
        f" | sensoren {', '.join(str(device_id) for device_id in arguments.device_ids)}"
        f" | probe {arguments.probe_number}"
        f" | periode {arguments.start or 'begin'} t/m {arguments.end or 'einde'}",
        flush=True,
    )

    try:
        graph_path = generate_combined_graph(
            device_ids=arguments.device_ids,
            probe_number=arguments.probe_number,
            start=arguments.start,
            end=arguments.end,
            output_dir=arguments.output_dir,
            output_path=arguments.output,
        )
        print(f"Gecombineerde dataverkenning voltooid | grafiek: {graph_path}", flush=True)
    except Exception as error:
        print(f"Gecombineerde dataverkenning mislukt | {error}", flush=True)
        raise


if __name__ == "__main__":
    main()

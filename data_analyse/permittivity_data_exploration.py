"""Verken relatieve permittiviteit en historische weersinvloeden per probe."""

from __future__ import annotations

import argparse
import html
import tempfile
import webbrowser
from datetime import date
from pathlib import Path
from uuid import uuid4

import pandas as pd

try:
    from .permittivity_prediction_model import (
        load_active_probe_inventory,
        load_daily_sensor_data,
        load_historical_weather,
        write_permittivity_weather_graph,
    )
except ImportError:
    from permittivity_prediction_model import (
        load_active_probe_inventory,
        load_daily_sensor_data,
        load_historical_weather,
        write_permittivity_weather_graph,
    )


EXPLORATION_DIR = Path(__file__).resolve().parent / "data_exploration"
WEATHER_VIEWS = {
    "rain": ("rain_mm",),
    "energy": ("energy_proxy",),
    "combined": ("rain_mm", "energy_proxy"),
}


def parse_probe_number(value: str) -> int | str:
    """Lees een positief probenummer of het woord all."""
    if value.casefold() == "all":
        return "all"
    try:
        probe_number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "probe-number moet een positief geheel getal of 'all' zijn"
        ) from error
    if probe_number <= 0:
        raise argparse.ArgumentTypeError(
            "probe-number moet een positief geheel getal of 'all' zijn"
        )
    return probe_number


def generate_exploration_graphs(
    device_id: int,
    probe_selection: int | str,
    start: date | None,
    end: date | None,
    weather_view: str,
    output_dir: Path = EXPLORATION_DIR,
    output_path: Path | None = None,
) -> list[tuple[str, Path]]:
    """Genereer de gekozen historische weergave voor een of alle probes."""
    if start is not None and end is not None and start > end:
        raise ValueError("De startdatum mag niet na de einddatum liggen")
    if weather_view not in WEATHER_VIEWS:
        raise ValueError(f"Onbekende weerweergave: {weather_view}")

    inventory = (
        load_active_probe_inventory()
        .loc[lambda data: data["device_id"] == device_id]
        .sort_values(["depth_cm", "probe_number"])
        .reset_index(drop=True)
    )
    if probe_selection != "all":
        inventory = inventory[
            inventory["probe_number"] == probe_selection
        ].reset_index(drop=True)
    if inventory.empty:
        raise ValueError("Geen geregistreerde gegevens voor deze sensor en probe")
    if output_path is not None and len(inventory) != 1:
        raise ValueError("--output kan alleen voor precies een probe worden gebruikt")

    daily_data = load_daily_sensor_data()
    device_data = daily_data[daily_data["device_id"] == device_id].copy()
    weather = load_historical_weather()
    print(
        f"Selectie geladen | {len(inventory)} "
        f"{'probe' if len(inventory) == 1 else 'probes'} gevonden",
        flush=True,
    )
    generated: list[tuple[str, Path]] = []
    total = len(inventory)
    for index, identity in enumerate(inventory.itertuples(index=False), start=1):
        depth_text = (
            "onbekend"
            if pd.isna(identity.depth_cm)
            else f"{float(identity.depth_cm):g}"
        )
        status = (
            f"[{index}/{total}] sensor {device_id} | "
            f"probe {int(identity.probe_number)} | {depth_text} cm"
        )
        if pd.isna(identity.depth_cm):
            if probe_selection == "all":
                print(f"{status} | overgeslagen: diepte ontbreekt", flush=True)
                continue
            raise ValueError("Geen diepte geregistreerd voor deze sensor en probe")
        probe_data = device_data[
            (device_data["probe_number"] == identity.probe_number)
            & (device_data["depth_cm"] == identity.depth_cm)
        ].copy()
        if start is not None:
            probe_data = probe_data[probe_data["date"] >= start]
        if end is not None:
            probe_data = probe_data[probe_data["date"] <= end]
        if probe_data.empty:
            if probe_selection == "all":
                print(f"{status} | overgeslagen: geen gegevens binnen periode", flush=True)
                continue
            raise ValueError("Geen bruikbare gegevens voor deze sensor en probe binnen periode")

        first_date = probe_data["date"].min()
        last_date = probe_data["date"].max()
        graph_weather = weather[
            (weather["date"] >= first_date) & (weather["date"] <= last_date)
        ]
        graph_path = output_path or (
            output_dir
            / f"sensor_{device_id}"
            / (
                f"probe_{int(identity.probe_number)}_{depth_text}cm_"
                f"{weather_view}.png"
            )
        )
        title = (
            f"{identity.location_name} - sensor {device_id}, "
            f"probe {int(identity.probe_number)}, {depth_text} cm"
        )
        write_permittivity_weather_graph(
            path=graph_path,
            title=title,
            actual=probe_data[["date", "relative_permittivity"]],
            weather=graph_weather,
            weather_columns=WEATHER_VIEWS[weather_view],
        )
        generated.append((title, graph_path.resolve()))
        print(
            f"{status} | {len(probe_data)} dagwaarden | grafiek: {graph_path}",
            flush=True,
        )

    if not generated:
        raise ValueError("Geen probe bevat gegevens binnen de gekozen periode")
    return generated


def create_gallery(device_id: int, graphs: list[tuple[str, Path]]) -> Path:
    """Maak een unieke tijdelijke browsergalerij voor deze uitvoering."""
    gallery_dir = Path(tempfile.gettempdir()) / "leiden_water_data_exploration"
    gallery_dir.mkdir(parents=True, exist_ok=True)
    gallery_path = gallery_dir / f"sensor_{device_id}_{uuid4().hex}.html"
    sections = "\n".join(
        (
            "<section>"
            f"<h2>{html.escape(title)}</h2>"
            f'<img src="{html.escape(path.as_uri(), quote=True)}" '
            f'alt="{html.escape(title, quote=True)}">'
            "</section>"
        )
        for title, path in graphs
    )
    gallery_path.write_text(
        "<!doctype html>"
        '<html lang="nl"><head><meta charset="utf-8">'
        f"<title>Dataverkenning sensor {device_id}</title>"
        "<style>"
        "body{font-family:Arial,sans-serif;margin:24px;background:#f5f5f3;color:#202020}"
        "h1{font-size:24px}h2{font-size:18px;margin:0 0 12px}"
        "section{margin:0 0 24px;padding:16px;background:#fff;border:1px solid #ccc}"
        "img{display:block;width:100%;height:auto}"
        "</style></head><body>"
        f"<h1>Dataverkenning sensor {device_id}</h1>{sections}"
        "</body></html>",
        encoding="utf-8",
    )
    return gallery_path


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", type=int, required=True)
    parser.add_argument("--probe-number", type=parse_probe_number, required=True)
    parser.add_argument("--start", type=parse_date)
    parser.add_argument("--end", type=parse_date)
    parser.add_argument(
        "--weather-view",
        choices=tuple(WEATHER_VIEWS),
        default="combined",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-open", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()
    if arguments.output is not None and arguments.output_dir is not None:
        parser.error("--output en --output-dir kunnen niet samen worden gebruikt")
    if arguments.output is not None and arguments.probe_number == "all":
        parser.error("--output kan niet met --probe-number all worden gebruikt")
    if arguments.output is not None and arguments.output.suffix.casefold() != ".png":
        parser.error("--output moet een .png-bestand zijn")

    print(
        "Dataverkenning gestart"
        f" | sensor {arguments.device_id} | probe {arguments.probe_number}"
        f" | weergave {arguments.weather_view}"
        f" | periode {arguments.start or 'begin'} t/m {arguments.end or 'einde'}",
        flush=True,
    )
    try:
        graphs = generate_exploration_graphs(
            device_id=arguments.device_id,
            probe_selection=arguments.probe_number,
            start=arguments.start,
            end=arguments.end,
            weather_view=arguments.weather_view,
            output_dir=arguments.output_dir or EXPLORATION_DIR,
            output_path=arguments.output,
        )
        if not arguments.no_open:
            gallery_path = create_gallery(arguments.device_id, graphs)
            if not webbrowser.open_new_tab(gallery_path.as_uri()):
                raise RuntimeError("De browser kon niet worden geopend")
            print(f"Browsergalerij geopend | {gallery_path}", flush=True)
        print(
            f"Dataverkenning voltooid | {len(graphs)} "
            f"{'grafiek' if len(graphs) == 1 else 'grafieken'}",
            flush=True,
        )
    except Exception as error:
        print(f"Dataverkenning mislukt | {error}", flush=True)
        raise


if __name__ == "__main__":
    main()

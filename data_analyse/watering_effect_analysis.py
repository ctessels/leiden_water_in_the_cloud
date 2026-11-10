"""Analyseer het effect van watergeven op de bodemvochtsensoren.

Het script zoekt in de probe-metingen naar plotselinge stijgingen van de
relatieve permittiviteit op momenten zonder neerslag. Zulke stijgingen worden
geclassificeerd als waarschijnlijke gietbeurt, neerslag of regionaal signaal.
Daarna worden de gift, de uitdroging, de EC-reactie, het tijdstip en de
weersomstandigheden vergeleken met regenbuien op dezelfde probe. Tot slot
wordt gecontroleerd of de bekende gietmomenten zichtbaar zijn in de data.

Uitvoer (CSV's, PNG's en ``samenvatting.txt``) komt in
``data_analyse/watering_analysis``.
"""

from __future__ import annotations

import argparse
import io
import sqlite3
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy.stats import binomtest

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data_collection" / "sensor_data"
DB_PATH = DATA_DIR / "database.db"
WEATHER_PATH = DATA_DIR / "voorschoten_weerdata.csv"
VALKENBURG_PATH = DATA_DIR / "valkenburg_precipitation.csv"
WATERING_LOG_PATH = PROJECT_DIR / "Documentation" / "watergeven_log.xlsx"
OUTPUT_DIR = Path(__file__).resolve().parent / "watering_analysis"
HOURLY_CACHE_NAME = "knmi_uurgegevens_215.csv"
KNMI_HOURLY_URL = "https://www.daggegevens.knmi.nl/klimatologie/uurgegevens"
KNMI_STATION = 215  # Voorschoten
LOCAL_TZ = "Europe/Amsterdam"

# Bekende gietmomenten uit Watergeven.py en het onderzoeksrapport fase 2.
VROLIJK_GROEN_DATES = (
    "2025-08-12", "2025-08-13", "2025-08-15", "2025-09-09",
    "2025-09-16", "2025-09-19", "2025-09-30",
)
DE_HEER_PERIOD = ("2025-08-15", "2025-08-26")
TIMELINE_2025_LOCATIONS = (
    "park_de_put", "Agrippinastraat", "Arendshorst_30",
    "van_der_paauwkade", "ing_driessenstraat", "gabriel_metzusstraat",
)

# Detectie van droge stijgingen
MAX_DEPTH_CM = 30  # diepere probes reageren vertraagd en worden niet gebruikt
MIN_READINGS_PER_PROBE = 200
MIN_DAYS_SINCE_PLACEMENT = 3
DRY_RAIN48_MM = 0.3
MIN_SOIL_TEMP = 1.0  # geen vorst of dooi
MIN_Z = 6.0
MIN_RESID_EPS = 0.3
MAX_RAIN24_MM = 0.3
MAX_RAIN72_MM = 10.0
EVENT_GAP = pd.Timedelta("36h")
MIN_SHARPNESS = 0.4
MIN_PERSISTENCE = 0.4
MAX_RAIN_AT_ONSET_MM = 0.2

# Classificatie
REGIONAL_Z = 4.0
REGIONAL_MIN_LOCATIONS = 3
RAIN_NEAR_VS_MM = 0.5
RAIN_NEAR_VK_MM = 1.0
DOSE_OVERRIDE_FACTOR = 5
DOSE_OVERRIDE_MIN_MM = 20
MIN_WATERING_JUMP_EPS = 1.0  # kleinere sprongen vallen binnen de regen- en temperatuurruis
CLASS_WATERING = "gieten waarschijnlijk"
CLASS_RAIN = "neerslag waarschijnlijk"
CLASS_REGIONAL = "regionaal signaal"
CLASS_WEAK = "zwak signaal"

# Omrekening en referenties
LAYER_MM = 200  # Δθ wordt uitgedrukt als waterschijf over 20 cm bodem
MIN_RAIN_SENSITIVITY = 0.0005  # θ per mm; daaronder geen regen-equivalent
RAIN_EPISODE_MIN_MM = 2.0
RAIN_EPISODE_DRY_BEFORE_H = 48
HALF_LIFE_MAX_DAYS = 21
MAX_TIMING_WINDOW = pd.Timedelta("8h")  # bredere beginvensters (datagat) geven geen bruikbaar tijdstip
DAY_START_HOUR, DAY_END_HOUR = 7, 19
WEEKDAYS_NL = ("ma", "di", "wo", "do", "vr", "za", "zo")


def topp_theta(eps):
    """Volumetrisch watergehalte volgens Topp et al. (1980)."""
    eps = np.asarray(eps, dtype=float)
    return -5.3e-2 + 2.92e-2 * eps - 5.5e-4 * eps**2 + 4.3e-6 * eps**3


def to_local(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_localize("UTC").dt.tz_convert(LOCAL_TZ)


def local_to_utc(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize(LOCAL_TZ).tz_convert("UTC").tz_localize(None)


# ---------------------------------------------------------------- inladen


def load_probe_data(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Lees bruikbare metingen van actieve sensoren met diepte per probe."""
    with closing(sqlite3.connect(db_path)) as connection:
        sensors = pd.read_sql_query(
            "SELECT device_id, location_name, mp_depth_1, mp_depth_2, mp_depth_3, "
            "usable_from, is_active FROM DimSensor",
            connection,
        )
        data = pd.read_sql_query(
            "SELECT device_id, probe_number, timestamp, temperature, "
            "relative_permittivity AS eps, electric_conductivity AS ec FROM FactSensorData",
            connection,
        )
    usable_from = sensors["usable_from"].astype(str).str.replace(r"-(\d)$", r"-0\1", regex=True)
    sensors["usable_from"] = pd.to_datetime(usable_from, errors="coerce")
    data["ts"] = pd.to_datetime(data["timestamp"], unit="s")
    df = data.merge(sensors[sensors["is_active"] == 1], on="device_id")
    df = df[df["ts"] >= df["usable_from"]].dropna(subset=["eps"]).copy()
    df["depth"] = np.select(
        [df["probe_number"] == 1, df["probe_number"] == 2, df["probe_number"] == 3],
        [df["mp_depth_1"], df["mp_depth_2"], df["mp_depth_3"]],
        default=np.nan,
    )
    df["days_since_placement"] = (df["ts"] - df["usable_from"]).dt.days
    columns = ["device_id", "probe_number", "location_name", "depth", "ts", "temperature",
               "eps", "ec", "days_since_placement"]
    df = df[columns].drop_duplicates(["device_id", "probe_number", "ts"])
    return df.sort_values(["device_id", "probe_number", "ts"]).reset_index(drop=True)


def load_daily_weather() -> pd.DataFrame:
    """Dagwaarden Voorschoten (neerslag, verdamping, Tmax) en Valkenburg (neerslag 08-08 UT)."""
    weather = pd.read_csv(WEATHER_PATH)
    weather.columns = weather.columns.str.strip()

    def number(column):
        return pd.to_numeric(weather[column], errors="coerce")

    daily = pd.DataFrame({
        "date": pd.to_datetime(weather["DATE"]),
        "rain_vs": number("neerslag").replace(-1, 0.25) / 10,
        "et": number("referentiegewasverdamping").clip(lower=0) / 10,
        "tmax": number("maxtemperatuur") / 10,
    })
    valkenburg = pd.read_csv(VALKENBURG_PATH)
    valkenburg.columns = valkenburg.columns.str.strip()
    valkenburg = pd.DataFrame({
        "date": pd.to_datetime(valkenburg["DATE"]),
        "rain_vk": pd.to_numeric(valkenburg["RD"], errors="coerce").replace(-1, 0) / 10,
    })
    daily = (daily.merge(valkenburg, on="date", how="outer")
             .drop_duplicates("date").sort_values("date").set_index("date"))
    daily = daily.asfreq("D")
    daily["p_min_et_14d"] = (daily["rain_vs"] - daily["et"]).rolling(14).sum()
    daily["tmax_3d"] = daily["tmax"].rolling(3).mean()
    wet_day = daily["rain_vs"] >= 2
    last_wet = pd.Series(daily.index, index=daily.index).where(wet_day).ffill()
    daily["dry_days"] = (daily.index.to_series() - last_wet).dt.days
    return daily


def parse_knmi_hourly(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    header = [line for line in lines if line.startswith("#") and "YYYYMMDD" in line][-1]
    columns = [column.strip() for column in header.lstrip("#").split(",")]
    rows = "\n".join(line for line in lines if line.strip() and not line.startswith("#"))
    hourly = pd.read_csv(io.StringIO(rows), header=None, names=columns, skipinitialspace=True)
    # HH is het uurvak dat eindigt op HH UT.
    hourly["ts"] = pd.to_datetime(hourly["YYYYMMDD"].astype(str)) + pd.to_timedelta(hourly["HH"], unit="h")
    hourly["rain"] = hourly["RH"].replace(-1, 0.25) / 10
    return hourly.set_index("ts")[["rain"]].sort_index()


def load_hourly_rain(start: pd.Timestamp, end: pd.Timestamp, output_dir: Path, refresh: bool) -> pd.Series:
    """Uurneerslag KNMI Voorschoten; wordt eenmalig opgehaald en in de uitvoermap bewaard."""
    cache = output_dir / HOURLY_CACHE_NAME
    if refresh or not cache.exists():
        payload = urllib.parse.urlencode({
            "stns": KNMI_STATION, "vars": "RH",
            "start": start.strftime("%Y%m%d") + "01", "end": end.strftime("%Y%m%d") + "24",
        }).encode()
        print(f"KNMI-uurgegevens ophalen ({start:%Y-%m-%d} t/m {end:%Y-%m-%d})...")
        try:
            with urllib.request.urlopen(urllib.request.Request(KNMI_HOURLY_URL, data=payload), timeout=180) as response:
                text = response.read().decode("utf-8")
            parse_knmi_hourly(text)
            cache.write_text(text, encoding="utf-8")
        except Exception as error:  # noqa: BLE001
            if not cache.exists():
                raise RuntimeError(f"KNMI-uurgegevens konden niet worden opgehaald: {error}") from error
            print(f"Waarschuwing: ophalen mislukt ({error}); bestaande cache wordt gebruikt.")
    rain = parse_knmi_hourly(cache.read_text(encoding="utf-8"))["rain"]
    if rain.index.max() < end - pd.Timedelta("2D"):
        print(f"Waarschuwing: uurneerslag loopt tot {rain.index.max():%Y-%m-%d}; "
              "gebruik --refresh-hourly voor recente data.")
    return rain


def load_watering_log(path: Path = WATERING_LOG_PATH) -> tuple[pd.DataFrame, dict[str, str]]:
    """Ingevulde regels uit het gietlogboek en de verantwoordelijke per locatie."""
    sheets = pd.read_excel(path, sheet_name=None, header=None)
    locations = sheets["Locaties"].iloc[1:, [0, 2]].dropna(subset=[0])
    responsible = dict(zip(locations[0].astype(str).str.strip(), locations[2].astype(str).str.strip()))

    grid = sheets["Watergeven"]
    header = grid.iloc[1]
    entries = []
    for _, row in grid.iloc[2:].iterrows():
        day = pd.to_datetime(row.iloc[0], errors="coerce")
        if pd.isna(day):
            continue
        for column in range(1, grid.shape[1]):
            cell = row.iloc[column]
            if not isinstance(cell, str) or "Tijd: []" in cell:
                continue
            entries.append({"date": day.normalize(), "location_name": str(header.iloc[column]).strip(), "note": cell})
    return pd.DataFrame(entries, columns=["date", "location_name", "note"]), responsible


# ---------------------------------------------------------------- detectie


def make_rain_sum(hourly_rain: pd.Series):
    cumulative = hourly_rain.fillna(0).cumsum()

    def rain_between(start, end):
        start = pd.DatetimeIndex(np.atleast_1d(start))
        end = pd.DatetimeIndex(np.atleast_1d(end))
        values = cumulative.reindex(end, method="ffill").to_numpy() - cumulative.reindex(start, method="ffill").to_numpy()
        return values
    return rain_between


def compute_daily_changes(df: pd.DataFrame, rain_between) -> pd.DataFrame:
    """24-uursverandering per meting, gecorrigeerd voor bodemtemperatuur en geschaald naar ruis."""
    frames = []
    for _, group in df.groupby(["device_id", "probe_number"]):
        if len(group) < MIN_READINGS_PER_PROBE:
            continue
        group = group.sort_values("ts")
        previous = group[["ts", "eps", "temperature", "ec"]].rename(
            columns={"eps": "eps0", "temperature": "temp0", "ec": "ec0"})
        previous["ts"] = previous["ts"] + pd.Timedelta("24h")
        merged = pd.merge_asof(group, previous, on="ts", direction="nearest", tolerance=pd.Timedelta("2h"))
        merged = merged.dropna(subset=["eps0"]).copy()
        merged["d_eps"] = merged["eps"] - merged["eps0"]
        merged["d_temp"] = merged["temperature"] - merged["temp0"]
        merged["soil_tmin48"] = group.set_index("ts")["temperature"].rolling("48h").min().reindex(merged["ts"]).to_numpy()
        frames.append(merged)
    changes = pd.concat(frames, ignore_index=True)
    for hours in (24, 48, 72):
        changes[f"rain{hours}"] = rain_between(changes["ts"] - pd.Timedelta(f"{hours}h"), changes["ts"])

    dry = (changes["rain48"] < DRY_RAIN48_MM) & (changes["soil_tmin48"] > MIN_SOIL_TEMP)

    def noise(group):
        slope = np.polyfit(group["d_temp"], group["d_eps"], 1)[0] if group["d_temp"].std() > 0 else 0.0
        residual = group["d_eps"] - slope * group["d_temp"]
        return pd.Series({"temp_slope": slope, "noise_median": residual.median(),
                          "noise_mad": 1.4826 * (residual - residual.median()).abs().median()})

    stats = changes[dry].groupby(["device_id", "probe_number"])[["d_eps", "d_temp"]].apply(noise)
    changes = changes.join(stats, on=["device_id", "probe_number"])
    changes["resid"] = changes["d_eps"] - changes["temp_slope"] * changes["d_temp"].fillna(0)
    changes["z"] = (changes["resid"] - changes["noise_median"]) / changes["noise_mad"]
    return changes


def detect_dry_rises(changes: pd.DataFrame, df: pd.DataFrame, rain_between) -> pd.DataFrame:
    """Groepeer opvallende droge stijgingen tot events en bepaal begin, sprong en vorm."""
    candidates = changes[
        (changes["rain24"] < MAX_RAIN24_MM) & (changes["rain72"] < MAX_RAIN72_MM)
        & (changes["soil_tmin48"] > MIN_SOIL_TEMP) & (changes["z"] > MIN_Z)
        & (changes["resid"] > MIN_RESID_EPS) & (changes["days_since_placement"] > MIN_DAYS_SINCE_PLACEMENT)
        & (changes["depth"] <= MAX_DEPTH_CM)
    ]
    events = []
    for (device_id, probe), group in candidates.groupby(["device_id", "probe_number"]):
        series = df[(df["device_id"] == device_id) & (df["probe_number"] == probe)].set_index("ts")
        eps = series["eps"].sort_index()
        group = group.sort_values("ts")
        for _, cluster in group.groupby((group["ts"].diff() > EVENT_GAP).cumsum()):
            t_resid = cluster.loc[cluster["resid"].idxmax(), "ts"]
            before = eps.loc[t_resid - pd.Timedelta("30h"):t_resid]
            t_base, base = before.idxmin(), before.min()
            segment = eps.loc[t_base:t_resid + pd.Timedelta("8h")]
            t_peak, peak = segment.idxmax(), segment.max()
            steps = eps.loc[t_base:t_peak].diff()
            if steps.dropna().empty:
                continue
            onset_to = steps.idxmax()
            onset_from = eps.index[eps.index.get_loc(onset_to) - 1]
            jump = peak - base
            after = eps.loc[t_peak + pd.Timedelta("12h"):t_peak + pd.Timedelta("20h")]
            events.append({
                "device_id": device_id, "probe_number": probe,
                "location_name": cluster["location_name"].iloc[0], "depth": cluster["depth"].iloc[0],
                "t_base": t_base, "onset_from": onset_from, "onset_to": onset_to, "t_peak": t_peak,
                "eps_base": base, "eps_peak": peak, "jump": jump, "z_max": cluster["z"].max(),
                "sharpness": steps.max() / jump,
                "persistence": (after.mean() - base) / jump if len(after) else np.nan,
                "rain_at_onset": rain_between(onset_from - pd.Timedelta("6h"), onset_to)[0],
                "ec_base": series.loc[t_base, "ec"], "ec_peak": series.loc[t_peak, "ec"],
            })
    events = pd.DataFrame(events)
    keep = (
        (events["persistence"].isna() | (events["persistence"] >= MIN_PERSISTENCE))
        & (events["sharpness"] >= MIN_SHARPNESS) & (events["rain_at_onset"] < MAX_RAIN_AT_ONSET_MM)
    )
    return events[keep].sort_values("onset_to").reset_index(drop=True)


def rain_reference(df: pd.DataFrame, hourly_rain: pd.Series) -> pd.DataFrame:
    """Reactie per probe op geisoleerde regenbuien (>= 2 mm na minstens 48 uur droog)."""
    wet = hourly_rain[hourly_rain >= 0.1]
    groups = (wet.index.to_series().diff() > pd.Timedelta("12h")).cumsum()
    episodes = pd.DataFrame([
        {"t0": block.index.min() - pd.Timedelta("1h"), "t1": block.index.max(), "mm": block.sum()}
        for _, block in wet.groupby(groups)
    ])
    episodes["dry_before_h"] = (episodes["t0"] - episodes["t1"].shift()).dt.total_seconds() / 3600
    episodes = episodes[(episodes["mm"] >= RAIN_EPISODE_MIN_MM) & (episodes["dry_before_h"] >= RAIN_EPISODE_DRY_BEFORE_H)]

    rows = []
    for (device_id, probe), group in df[df["depth"] <= MAX_DEPTH_CM].groupby(["device_id", "probe_number"]):
        series = group.set_index("ts").sort_index()
        for _, episode in episodes.iterrows():
            if episode["t0"] < series.index.min() + pd.Timedelta("4D") or episode["t1"] > series.index.max():
                continue
            before = series.loc[episode["t0"] - pd.Timedelta("6h"):episode["t0"]]
            after = series.loc[episode["t0"]:episode["t1"] + pd.Timedelta("18h")]
            if before.empty or len(after) < 3:
                continue
            if series.loc[episode["t0"] - pd.Timedelta("48h"):episode["t1"], "temperature"].min() < MIN_SOIL_TEMP:
                continue
            base, peak = before.iloc[-1], after.loc[after["eps"].idxmax()]
            rows.append({
                "device_id": device_id, "probe_number": probe, "location_name": group["location_name"].iloc[0],
                "t0": episode["t0"], "mm": episode["mm"], "eps_base": base["eps"], "d_eps": peak["eps"] - base["eps"],
                "d_theta": float(topp_theta(peak["eps"]) - topp_theta(base["eps"])), "d_ec": peak["ec"] - base["ec"],
            })
    reference = pd.DataFrame(rows)
    reference["theta_per_mm"] = reference["d_theta"] / reference["mm"]
    return reference


def summarise_rain_reference(reference: pd.DataFrame) -> pd.DataFrame:
    responding = reference[reference["d_eps"] > 1].assign(ec_per_eps=lambda x: x["d_ec"] / x["d_eps"])
    summary = reference.groupby(["device_id", "probe_number", "location_name"]).agg(
        regenbuien=("mm", "size"), mediaan_mm=("mm", "median"), mediaan_d_eps=("d_eps", "median"),
        max_d_eps=("d_eps", "max"), theta_per_mm=("theta_per_mm", "median"),
        fractie_reactie=("d_eps", lambda values: (values > MIN_RESID_EPS).mean()),
    )
    summary["ec_per_eps_regen"] = responding.groupby(["device_id", "probe_number", "location_name"])["ec_per_eps"].median()
    return summary.reset_index()


# ---------------------------------------------------------------- kenmerken


def classify_and_describe(events, changes, df, daily, rain_between, reference, rain_summary, responsible):
    """Voeg classificatie, gift, uitdroging, EC-signatuur, tijdstip en triggers toe."""
    events = events.copy()
    significant = changes[(changes["z"] > REGIONAL_Z) & (changes["resid"] > MIN_RESID_EPS)
                          & (changes["depth"] <= MAX_DEPTH_CM)
                          & (changes["days_since_placement"] > MIN_DAYS_SINCE_PLACEMENT)]
    bounds = df.groupby(["device_id", "probe_number"])["eps"].quantile([0.05, 0.95]).unstack()
    rain_lookup = rain_summary.set_index(["device_id", "probe_number"])
    # Probes van dezelfde sensor die tegelijk stijgen delen de dosistoets.
    layer_all = pd.Series(topp_theta(events["eps_peak"]) - topp_theta(events["eps_base"]), index=events.index) * LAYER_MM

    rows = []
    for _, event in events.iterrows():
        key = (event["device_id"], event["probe_number"])
        nearby = significant[
            significant["ts"].between(event["onset_to"] - pd.Timedelta("6h"), event["onset_to"] + pd.Timedelta("18h"))
            & (significant["location_name"] != event["location_name"])
        ]
        rain_vs = rain_between(event["onset_from"] - pd.Timedelta("12h"), event["onset_to"] + pd.Timedelta("6h"))[0]
        day = event["onset_to"].normalize()
        rain_vk = daily["rain_vk"].reindex([day, day + pd.Timedelta("1D")]).sum()
        d_theta = float(topp_theta(event["eps_peak"]) - topp_theta(event["eps_base"]))
        water_layer = d_theta * LAYER_MM

        probe_rain = reference[(reference["device_id"] == key[0]) & (reference["probe_number"] == key[1])]
        sensitivity = rain_lookup["theta_per_mm"].get(key, np.nan)
        rain_equivalent = d_theta / sensitivity if sensitivity >= MIN_RAIN_SENSITIVITY else np.nan

        later = df[(df["device_id"] == key[0]) & (df["probe_number"] == key[1])
                   & (df["ts"] > event["t_peak"])
                   & (df["ts"] <= event["t_peak"] + pd.Timedelta(f"{HALF_LIFE_MAX_DAYS}D"))].set_index("ts")["eps"]
        halfway = later[later <= event["eps_base"] + 0.5 * event["jump"]]
        half_life = (halfway.index[0] - event["t_peak"]).total_seconds() / 86400 if len(halfway) else np.nan

        lo, hi = bounds.loc[key]
        weather_day = daily.reindex([day]).iloc[0]

        n_regional = nearby["location_name"].nunique()
        rain_near = rain_vs >= RAIN_NEAR_VS_MM or rain_vk >= RAIN_NEAR_VK_MM
        same_moment = ((events["device_id"] == event["device_id"])
                       & ((events["onset_to"] - event["onset_to"]).abs() <= pd.Timedelta("6h")))
        group_layer = layer_all[same_moment].max()
        dose_dominates = (group_layer >= DOSE_OVERRIDE_MIN_MM
                          and group_layer >= DOSE_OVERRIDE_FACTOR * max(rain_vs, rain_vk))
        if n_regional >= REGIONAL_MIN_LOCATIONS:
            label = CLASS_REGIONAL
        elif rain_near and not dose_dominates:
            label = CLASS_RAIN
        elif event["jump"] < MIN_WATERING_JUMP_EPS:
            label = CLASS_WEAK
        else:
            label = CLASS_WATERING

        ec_per_eps = (event["ec_peak"] - event["ec_base"]) / event["jump"]
        rows.append({
            "klasse": label, "locaties_tegelijk": n_regional,
            "neerslag_voorschoten_mm": round(rain_vs, 2), "neerslag_valkenburg_mm": rain_vk,
            "d_theta": d_theta, "waterschijf_20cm_mm": water_layer, "regen_equivalent_mm": rain_equivalent,
            "pct_regenbuien_kleiner": (probe_rain["d_eps"] < event["jump"]).mean() * 100 if len(probe_rain) else np.nan,
            "max_regen_d_eps": probe_rain["d_eps"].max() if len(probe_rain) else np.nan,
            "halfwaardetijd_dagen": half_life,
            "ec_per_eps": ec_per_eps, "ec_per_eps_regen": rain_lookup["ec_per_eps_regen"].get(key, np.nan),
            "smi_start": (event["eps_base"] - lo) / (hi - lo),
            "droge_dagen": weather_day["dry_days"], "p_min_et_14d_mm": weather_day["p_min_et_14d"],
            "tmax_3d": weather_day["tmax_3d"],
            "watergeven_door_volgens_log": responsible.get(event["location_name"], "onbekend"),
        })
    events = pd.concat([events, pd.DataFrame(rows)], axis=1)
    events["ec_verhouding_t.o.v._regen"] = events["ec_per_eps"] / events["ec_per_eps_regen"]

    local_from, local_to = to_local(events["onset_from"]), to_local(events["onset_to"])
    middle = local_from + (local_to - local_from) / 2
    events["begin_lokaal"] = local_from.dt.strftime("%Y-%m-%d %H:%M")
    events["eind_lokaal"] = local_to.dt.strftime("%Y-%m-%d %H:%M")
    events["weekdag"] = middle.dt.weekday.map(dict(enumerate(WEEKDAYS_NL)))
    precise = (events["onset_to"] - events["onset_from"]) <= MAX_TIMING_WINDOW
    weekday_from, weekday_to = local_from.dt.weekday < 5, local_to.dt.weekday < 5
    events["werkdag"] = weekday_from.where(weekday_from == weekday_to).astype("boolean")
    events["overdag"] = middle.dt.hour.between(DAY_START_HOUR, DAY_END_HOUR - 1).where(precise).astype("boolean")
    events["datum_lokaal"] = middle.dt.strftime("%Y-%m-%d")
    return events


def timing_test(events: pd.DataFrame, hourly_rain: pd.Series) -> dict:
    """Vergelijk weekdag en tijdstip van gietevents met het tijdstip van regenuren."""
    rain_hours = hourly_rain[hourly_rain >= 0.1].index.tz_localize("UTC").tz_convert(LOCAL_TZ)
    rain_hours = rain_hours - pd.Timedelta("30min")
    p_weekday = float((rain_hours.weekday < 5).mean())
    p_daytime = float(((rain_hours.hour >= DAY_START_HOUR) & (rain_hours.hour < DAY_END_HOUR)).mean())
    watering = (events[events["klasse"] == CLASS_WATERING]
                .drop_duplicates(["location_name", "datum_lokaal"]))
    weekday, daytime = watering["werkdag"].dropna(), watering["overdag"].dropna()
    n_weekday, n_daytime = len(weekday), len(daytime)
    k_weekday, k_daytime = int(weekday.sum()), int(daytime.sum())
    return {
        "n": len(watering), "n_werkdag": n_weekday, "werkdag": k_weekday, "n_overdag": n_daytime, "overdag": k_daytime,
        "p_werkdag_regen": p_weekday, "p_overdag_regen": p_daytime,
        "pvalue_werkdag": binomtest(k_weekday, n_weekday, p_weekday, alternative="greater").pvalue if n_weekday else np.nan,
        "pvalue_overdag": binomtest(k_daytime, n_daytime, p_daytime, alternative="greater").pvalue if n_daytime else np.nan,
    }


def known_watering_check(changes, df, events, rain_between, log_entries, responsible) -> pd.DataFrame:
    """Maximale z-score en detectiegrens per probe rond bekende gietmomenten."""
    windows = [("Vrolijk Groen", date, date, None) for date in VROLIJK_GROEN_DATES]
    windows.append(("De Heer", *DE_HEER_PERIOD, None))
    for _, entry in log_entries.iterrows():
        date = entry["date"].strftime("%Y-%m-%d")
        windows.append(("gietlogboek", date, date, entry["location_name"]))

    shallow = changes[(changes["depth"] <= MAX_DEPTH_CM) & (changes["days_since_placement"] > MIN_DAYS_SINCE_PLACEMENT)]
    rows = []
    for source, first, last, only_location in windows:
        start = local_to_utc(f"{first} 06:00")
        end = local_to_utc(f"{(pd.Timestamp(last) + pd.Timedelta('1D')):%Y-%m-%d} 18:00")
        window = shallow[shallow["ts"].between(start, end)]
        if only_location:
            window = window[window["location_name"] == only_location]
        rain = rain_between(start, end)[0]
        for (device_id, probe), group in window.groupby(["device_id", "probe_number"]):
            best = group.loc[group["z"].idxmax()]
            location = best["location_name"]
            series = df[(df["device_id"] == device_id) & (df["probe_number"] == probe)].set_index("ts")["eps"]
            start_eps = series.loc[:start].iloc[-1] if len(series.loc[:start]) else series.iloc[0]
            limit_eps = max(best["noise_median"] + MIN_Z * best["noise_mad"], MIN_RESID_EPS)
            limit_theta = float(topp_theta(start_eps + limit_eps) - topp_theta(start_eps))
            detected = events[(events["device_id"] == device_id) & (events["probe_number"] == probe)
                              & events["onset_to"].between(start - pd.Timedelta("6h"), end)]
            rows.append({
                "bron": source, "periode": first if first == last else f"{first} t/m {last}",
                "location_name": location, "device_id": device_id, "probe_number": probe, "depth": best["depth"],
                "watergeven_door_volgens_log": responsible.get(location, "onbekend"),
                "neerslag_voorschoten_mm": round(rain, 1), "max_z": best["z"], "max_resid_eps": best["resid"],
                "eps_start": start_eps, "detectiegrens_eps": limit_eps,
                "detectiegrens_waterschijf_20cm_mm": limit_theta * LAYER_MM,
                "event_gedetecteerd": ", ".join(detected["klasse"].unique()) if len(detected) else "",
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- figuren


def plot_watering_events(events, df, hourly_rain, path):
    watering = events[events["klasse"] == CLASS_WATERING]
    groups = list(watering.groupby(["location_name", "datum_lokaal"], sort=False))
    columns = 3
    rows = int(np.ceil(len(groups) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(5.2 * columns, 3.0 * rows), squeeze=False)
    for ax, ((location, date), group) in zip(axes.flat, groups):
        device_id = group["device_id"].iloc[0]
        t0 = group["onset_to"].min()
        start, end = t0 - pd.Timedelta("3D"), t0 + pd.Timedelta("7D")
        probes = df[(df["device_id"] == device_id) & (df["depth"] <= MAX_DEPTH_CM) & df["ts"].between(start, end)]
        for (probe, depth), series in probes.groupby(["probe_number", "depth"]):
            ax.plot(series["ts"], series["eps"], lw=1.3, label=f"p{probe} ({depth:.0f} cm)")
        for _, event in group.iterrows():
            ax.axvspan(event["onset_from"], event["onset_to"], color="orange", alpha=0.3)
        rain_ax = ax.twinx()
        rain = hourly_rain.loc[start:end]
        rain_ax.bar(rain.index, rain.values, width=1 / 24, color="tab:blue", alpha=0.5)
        rain_ax.set_ylim(max(5, rain.max() * 1.5), 0)
        rain_ax.tick_params(labelsize=7)
        largest = group.loc[group["jump"].idxmax()]
        ax.set_title(f"{location} {date} ({largest['weekdag']})\n"
                     f"Δε {largest['jump']:.1f}, ≈{largest['waterschijf_20cm_mm']:.0f} mm/20 cm, "
                     f"log: {largest['watergeven_door_volgens_log'][:40]}", fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m"))
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=6, loc="upper right")
    for ax in axes.flat[len(groups):]:
        ax.axis("off")
    fig.suptitle("Waarschijnlijke gietbeurten: permittiviteit (lijnen), begin stijging (oranje), "
                 "uurneerslag Voorschoten (blauw, rechteras)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_known_2025(events, df, daily, path):
    start, end = pd.Timestamp("2025-08-01"), pd.Timestamp("2025-10-05")
    locations = [location for location in TIMELINE_2025_LOCATIONS if location in set(df["location_name"])]
    fig, axes = plt.subplots(len(locations) + 1, 1, figsize=(13, 1.9 * (len(locations) + 1)), sharex=True)
    rain = daily.loc[start:end]
    axes[0].bar(rain.index + pd.Timedelta("12h"), rain["rain_vs"], width=0.8, color="tab:blue", label="Voorschoten")
    axes[0].plot(rain.index - pd.Timedelta("4h"), rain["rain_vk"], "k.", ms=4, label="Valkenburg (08-08 UT)")
    axes[0].set_ylabel("mm/dag")
    axes[0].legend(fontsize=7, loc="upper left")
    for ax, location in zip(axes[1:], locations):
        subset = df[(df["location_name"] == location) & (df["depth"] <= MAX_DEPTH_CM) & df["ts"].between(start, end)]
        for (probe, depth), series in subset.groupby(["probe_number", "depth"]):
            ax.plot(series["ts"], series["eps"], lw=1, label=f"p{probe} ({depth:.0f} cm)")
        found = events[(events["location_name"] == location) & events["onset_to"].between(start, end)]
        ax.plot(found["onset_to"], found["eps_peak"], "v", color="crimson", ms=8, label="gedetecteerd")
        ax.set_ylabel(location, fontsize=8)
        ax.legend(fontsize=6, loc="upper right")
    for ax in axes:
        for date in VROLIJK_GROEN_DATES:
            ax.axvline(pd.Timestamp(date), color="green", lw=1, alpha=0.7)
        ax.axvspan(pd.Timestamp(DE_HEER_PERIOD[0]), pd.Timestamp(DE_HEER_PERIOD[1]) + pd.Timedelta("1D"),
                   color="red", alpha=0.08)
    axes[0].set_title("Bekende gietmomenten 2025: Vrolijk Groen (groene lijnen), De Heer (rode periode)")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d-%m"))
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_known_heatmap(check, path):
    table = check.sort_values("depth").drop_duplicates(["bron", "periode", "location_name"])
    table = table.assign(kolom=table["bron"] + "\n" + table["periode"])
    z = table.pivot(index="location_name", columns="kolom", values="max_z")
    z = z[sorted(z.columns, key=lambda column: column.split("\n")[1])]
    rain = table.drop_duplicates("kolom").set_index("kolom")["neerslag_voorschoten_mm"].reindex(z.columns)
    fig, ax = plt.subplots(figsize=(1.2 * len(z.columns) + 3, 0.42 * len(z) + 2))
    image = ax.imshow(z.clip(upper=20).to_numpy(dtype=float), cmap="viridis", aspect="auto", vmin=0, vmax=20)
    for i in range(z.shape[0]):
        for j in range(z.shape[1]):
            value = z.iat[i, j]
            if pd.notna(value):
                ax.text(j, i, f"{value:.0f}", ha="center", va="center", fontsize=7,
                        color="white" if value < 12 else "black")
    ax.set_xticks(range(len(z.columns)))
    ax.set_xticklabels([f"{column}\n{rain[column]:.1f} mm" for column in z.columns], fontsize=7)
    ax.set_yticks(range(len(z)))
    ax.set_yticklabels(z.index, fontsize=8)
    fig.colorbar(image, ax=ax, label=f"max z-score 24-uursstijging (drempel {MIN_Z:.0f})")
    ax.set_title("Reactie van de ondiepste probe rond bekende gietmomenten (neerslag Voorschoten in venster)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_ec_signature(events, path):
    data = events.dropna(subset=["ec_per_eps", "ec_per_eps_regen"])
    fig, ax = plt.subplots(figsize=(7, 6))
    colors = {CLASS_WATERING: "tab:orange", CLASS_RAIN: "tab:blue", CLASS_REGIONAL: "tab:gray", CLASS_WEAK: "tab:olive"}
    for label, group in data.groupby("klasse"):
        ax.scatter(group["ec_per_eps_regen"], group["ec_per_eps"], color=colors[label], label=label, s=45)
        for _, event in group.iterrows():
            ax.annotate(f"{event['location_name'][:12]} {event['datum_lokaal'][2:]}",
                        (event["ec_per_eps_regen"], event["ec_per_eps"]), fontsize=6, alpha=0.8)
    limit = max(data["ec_per_eps"].max(), data["ec_per_eps_regen"].max()) * 1.1
    ax.plot([0, limit], [0, limit], "k--", lw=0.8, label="gelijk aan regen")
    ax.set_xlabel("ΔEC/Δε bij regenbuien op dezelfde probe (mediaan)")
    ax.set_ylabel("ΔEC/Δε bij droog event")
    ax.set_title("EC-signatuur: kraan-/oppervlaktewater verhoogt EC sterker dan regen")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_triggers(events, daily, path):
    summer = daily[(daily.index.month >= 5) & (daily.index.month <= 9)].dropna(subset=["dry_days"])
    watering = events[events["klasse"] == CLASS_WATERING].drop_duplicates(["location_name", "datum_lokaal"])
    panels = [("droge_dagen", "dry_days", "dagen sinds >= 2 mm regen"),
              ("p_min_et_14d_mm", "p_min_et_14d", "neerslag - verdamping 14 dagen (mm)"),
              ("tmax_3d", "tmax_3d", "gemiddelde Tmax 3 dagen (°C)")]
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.8))
    for ax, (event_column, daily_column, label) in zip(axes, panels):
        ax.hist(summer[daily_column].dropna(), bins=25, color="lightgray", label="alle zomerdagen (mei-sep)")
        for value in watering[event_column].dropna():
            ax.axvline(value, color="tab:orange", lw=1.5, alpha=0.8)
        ax.set_xlabel(label)
    axes[0].plot([], [], color="tab:orange", label="waarschijnlijke gietbeurt")
    axes[0].legend(fontsize=7)
    fig.suptitle("Weersomstandigheden bij waarschijnlijke gietbeurten")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------- uitvoer


def format_days(value: float) -> str:
    return f"> {HALF_LIFE_MAX_DAYS} d of onderbroken" if pd.isna(value) else f"{value:.1f} d"


def format_summary(events, timing, check, rain_summary) -> str:
    watering = events[events["klasse"] == CLASS_WATERING]
    unique = watering.drop_duplicates(["location_name", "datum_lokaal"])
    lines = ["Analyse effect watergeven op bodemvochtprobes", "=" * 46, ""]
    lines.append(f"Droge stijgingen gevonden: {len(events)} probe-events "
                 f"({', '.join(f'{k}: {v}' for k, v in events['klasse'].value_counts().items())}).")
    lines.append(f"Waarschijnlijke gietbeurten: {len(unique)} (locatie-dagen).")
    lines.append("")
    for _, event in watering.iterrows():
        lines.append(
            f"  {event['begin_lokaal']} -> {event['eind_lokaal'][11:]} {event['weekdag']} "
            f"{event['location_name']} p{event['probe_number']} ({event['depth']:.0f} cm): "
            f"Δε {event['jump']:.1f}, Δθ {event['d_theta']:.3f} (≈{event['waterschijf_20cm_mm']:.0f} mm/20 cm), "
            f"groter dan {event['pct_regenbuien_kleiner']:.0f}% van regenbuien, "
            f"halfwaardetijd {format_days(event['halfwaardetijd_dagen'])}, EC x{event['ec_verhouding_t.o.v._regen']:.1f} t.o.v. regen, "
            f"SMI-start {event['smi_start']:.2f}, {event['droge_dagen']:.0f} droge dagen | log: {event['watergeven_door_volgens_log']}"
        )
    lines.append("")
    lines.append("Mediaan bij gietbeurten: "
                 f"Δθ {unique['d_theta'].median():.3f}, waterschijf {unique['waterschijf_20cm_mm'].median():.0f} mm/20 cm, "
                 f"halfwaardetijd {watering['halfwaardetijd_dagen'].median():.1f} dagen, "
                 f"EC-verhouding t.o.v. regen {watering['ec_verhouding_t.o.v._regen'].median():.1f}, "
                 f"SMI-start {unique['smi_start'].median():.2f}, droge dagen {unique['droge_dagen'].median():.0f}, "
                 f"P-ET 14 d {unique['p_min_et_14d_mm'].median():.0f} mm.")
    lines.append(f"Tijdstip: {timing['werkdag']}/{timing['n_werkdag']} op werkdag (regenuren {timing['p_werkdag_regen']:.0%}, "
                 f"p={timing['pvalue_werkdag']:.3f}); {timing['overdag']}/{timing['n_overdag']} overdag "
                 f"{DAY_START_HOUR}-{DAY_END_HOUR} uur (regenuren {timing['p_overdag_regen']:.0%}, "
                 f"p={timing['pvalue_overdag']:.3f}; events met beginvenster > 8 uur niet meegeteld).")
    lines.append("")
    lines.append("Bekende gietmomenten (ondiepste probe, max z; drempel 6):")
    shallow = check.sort_values("depth").drop_duplicates(["bron", "periode", "location_name"])
    for (period, source), group in shallow.groupby(["periode", "bron"]):
        hits = group[group["max_z"] > MIN_Z]
        hits_text = ", ".join(f"{row.location_name} ({row.max_z:.0f})" for row in hits.itertuples()) or "geen"
        rain = group["neerslag_voorschoten_mm"].iloc[0]
        note = " -> neerslag in venster, gieteffect niet te scheiden" if rain >= RAIN_EPISODE_MIN_MM else ""
        lines.append(f"  {source} {period} (regen {rain:.1f} mm, {len(group)} locaties): reactie bij {hits_text}{note}")
    watered = shallow[shallow["watergeven_door_volgens_log"].str.contains("De Heer", na=False)]
    if len(watered):
        lines.append("  Detectiegrens bij De Heer-locaties: "
                     + ", ".join(f"{row.location_name} {row.detectiegrens_eps:.2f} eps ≈ {row.detectiegrens_waterschijf_20cm_mm:.1f} mm"
                                 for row in watered.drop_duplicates("location_name").itertuples()))
    lines.append("")
    lines.append(f"Regenreferentie: {len(rain_summary)} probes, mediaan Δθ per mm regen "
                 f"{rain_summary['theta_per_mm'].median():.4f}.")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--refresh-hourly", action="store_true",
                        help="Haal de KNMI-uurneerslag opnieuw op in plaats van de cache te gebruiken.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    print("Analyse effect watergeven gestart.")

    df = load_probe_data()
    daily = load_daily_weather()
    hourly_rain = load_hourly_rain(df["ts"].min().normalize() - pd.Timedelta("4D"), df["ts"].max().normalize(),
                                   output_dir, args.refresh_hourly)
    rain_between = make_rain_sum(hourly_rain)
    log_entries, responsible = load_watering_log()
    print(f"{df['device_id'].nunique()} sensoren, {len(df):,} metingen, uurneerslag tot {hourly_rain.index.max():%Y-%m-%d}.")

    changes = compute_daily_changes(df, rain_between)
    reference = rain_reference(df, hourly_rain)
    rain_summary = summarise_rain_reference(reference)
    events = detect_dry_rises(changes, df, rain_between)
    events = classify_and_describe(events, changes, df, daily, rain_between, reference, rain_summary, responsible)
    timing = timing_test(events, hourly_rain)
    check = known_watering_check(changes, df, events, rain_between, log_entries, responsible)

    event_columns = [
        "klasse", "location_name", "device_id", "probe_number", "depth", "begin_lokaal", "eind_lokaal", "weekdag",
        "werkdag", "overdag", "eps_base", "eps_peak", "jump", "z_max", "sharpness", "persistence", "d_theta",
        "waterschijf_20cm_mm", "regen_equivalent_mm", "pct_regenbuien_kleiner", "max_regen_d_eps",
        "halfwaardetijd_dagen", "ec_base", "ec_peak", "ec_per_eps", "ec_per_eps_regen", "ec_verhouding_t.o.v._regen",
        "smi_start", "droge_dagen", "p_min_et_14d_mm", "tmax_3d", "locaties_tegelijk", "neerslag_voorschoten_mm",
        "neerslag_valkenburg_mm", "watergeven_door_volgens_log",
    ]
    events[event_columns].round(4).to_csv(output_dir / "droge_stijgingen.csv", index=False)
    check.round(3).to_csv(output_dir / "bekende_gietmomenten_controle.csv", index=False)
    rain_summary.round(5).to_csv(output_dir / "regenrespons_per_probe.csv", index=False)

    plot_watering_events(events, df, hourly_rain, output_dir / "gietbeurten.png")
    plot_known_2025(events, df, daily, output_dir / "bekende_gietmomenten_2025.png")
    plot_known_heatmap(check, output_dir / "bekende_gietmomenten_zscore.png")
    plot_ec_signature(events, output_dir / "ec_signatuur.png")
    plot_triggers(events, daily, output_dir / "weersomstandigheden_gietbeurten.png")

    summary = format_summary(events, timing, check, rain_summary)
    (output_dir / "samenvatting.txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)
    print(f"\nAnalyse voltooid. Uitvoer in {output_dir}")


if __name__ == "__main__":
    main()

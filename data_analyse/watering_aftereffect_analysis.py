"""Analyseer de nawerking van watergeven op de bodemvochtprobes.

Vraag 1: hoelang blijft de permittiviteit verhoogd na een gietbeurt?
Per gietbeurt wordt gevolgd hoe snel de stijging verdwijnt (t50, t75, t90:
het moment waarop nog 50, 25 of 10 procent van de stijging over is). Het
volgen stopt bij regen, een nieuwe stijging, een nieuwe gietbeurt of een
datagat; die events tellen als gecensureerd (Kaplan-Meier). Ter vergelijking
wordt hetzelfde gedaan voor duidelijke regenreacties op dezelfde probes.

Vraag 2: neemt de bodem regen beter op in de periode na een gietbeurt?
Regenbuien binnen 14 dagen na een gietbeurt worden vergeleken met vergelijkbare
buien op dezelfde probe (hoeveelheid tussen de helft en het dubbele, seizoen
binnen twee maanden, zonder gietbeurt ervoor) en met andere probes bij dezelfde
bui. Daarnaast wordt over alle buien getoetst of regen sterker doorwerkt als de
bodem vooraf vochtiger is, het mechanisme waarlangs gieten zou kunnen helpen.

De gietbeurten komen uit ``watering_effect_analysis.py``. Uitvoer (CSV's,
PNG's en ``samenvatting.txt``) komt in ``data_analyse/watering_analysis/nawerking``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy.stats import binomtest, spearmanr

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

try:
    from . import watering_effect_analysis as detection
except ImportError:
    import watering_effect_analysis as detection


OUTPUT_DIR = detection.OUTPUT_DIR / "nawerking"

# Verval na gieten
FOLLOW_MAX = pd.Timedelta("30D")
DECAY_LEVELS = {"t50": 0.5, "t75": 0.25, "t90": 0.1}  # resterend deel van de stijging
CENSOR_RAIN_MM = detection.RAIN_EPISODE_MIN_MM  # binnen 24 uur na de piek
RERISE_MIN_EPS = detection.MIN_RESID_EPS
RERISE_FRACTION = 0.1
MAX_GAP = pd.Timedelta("48h")
CURVE_DAYS = (1, 2, 3, 5, 7, 10, 14)
PRE_TREND = pd.Timedelta("72h")
RAIN_DECAY_MIN_JUMP = detection.MIN_WATERING_JUMP_EPS
SEASON_MONTHS = range(4, 11)  # april t/m oktober, het gietseizoen

# Regenopname
EPISODE_DRY_BEFORE_H = 24
WET_HOUR_MM = 0.1
EPISODE_SPLIT = pd.Timedelta("12h")
BASE_MAX_AGE = pd.Timedelta("6h")
RESPONSE_WINDOW = pd.Timedelta("24h")  # na het einde van de bui; 30 cm reageert vertraagd
NO_RESPONSE_EPS = detection.MIN_RESID_EPS
PRE_RAIN_MM = 1.0  # stijging voordat zoveel regen is gevallen wijst op gieten
PRE_RAIN_RISE_FRACTION = 0.5
POST_WATERING_MIN_DAYS = 0.5
POST_WATERING_MAX_DAYS = 14
CONTROL_EXCLUDE_DAYS = 21
MM_MATCH_FACTOR = 2.0
SEASON_MATCH_MONTHS = 2
MIN_CONTROLS = 3
SMI_BINS = (-np.inf, 0.2, 0.4, 0.6, np.inf)
SMI_LABELS = ("< 0.2", "0.2-0.4", "0.4-0.6", ">= 0.6")


def to_days(delta) -> float:
    return pd.Timedelta(delta).total_seconds() / 86400


def water_layer_mm(eps, eps_base) -> np.ndarray:
    return (detection.topp_theta(eps) - detection.topp_theta(eps_base)) * detection.LAYER_MM


# ---------------------------------------------------------------- verval


def crossing_time(series: pd.Series, threshold: float) -> pd.Timestamp | None:
    """Eerste moment waarop de reeks de drempel bereikt, lineair geinterpoleerd tussen metingen."""
    below = np.flatnonzero(series.to_numpy() <= threshold)
    if not len(below):
        return None
    i = below[0]
    if i == 0:
        return series.index[0]
    t0, t1 = series.index[i - 1], series.index[i]
    e0, e1 = series.iloc[i - 1], series.iloc[i]
    return t0 + (t1 - t0) * ((e0 - threshold) / (e0 - e1))


def first_rain_time(hourly_rain: pd.Series, start, end, min_mm: float = CENSOR_RAIN_MM) -> pd.Timestamp | None:
    """Begin van het uur waarin na ``start`` binnen 24 uur ``min_mm`` regen is gevallen."""
    # De index is het einde van het uurvak; alleen uurvakken die geheel na start vallen tellen.
    rain = hourly_rain.loc[start + pd.Timedelta("1h"):end].fillna(0)
    hits = rain.rolling("24h").sum()
    hits = hits[hits >= min_mm]
    return hits.index[0] - pd.Timedelta("1h") if len(hits) else None


def rerise_time(series: pd.Series, min_rise: float) -> pd.Timestamp | None:
    """Laatste dieptepunt voordat de reeks weer ``min_rise`` boven het lopende minimum komt."""
    rise = series - series.cummin()
    hits = rise[rise >= min_rise]
    if hits.empty:
        return None
    before = series.loc[:hits.index[0]]
    return before[before == before.min()].index[-1]


def follow_decay(eps: pd.Series, t_peak, eps_base: float, jump: float, hourly_rain: pd.Series,
                 rain_from=None, next_event=None, censor_rain: bool = True) -> dict:
    """Volg het verval van een stijging tot regen, nieuwe stijging, nieuw event, datagat of 30 dagen."""
    eps = eps.sort_index()
    candidates = {"einde volgperiode": t_peak + FOLLOW_MAX, "einde data": eps.index.max()}
    rain_time = first_rain_time(hourly_rain, rain_from if rain_from is not None else t_peak, t_peak + FOLLOW_MAX)
    if censor_rain and rain_time is not None:
        candidates["regen"] = max(rain_time, t_peak)
    if next_event is not None and pd.notna(next_event):
        candidates["nieuw event"] = next_event
    segment = eps.loc[t_peak:min(candidates.values())]
    gaps = segment.index.to_series().diff()
    gap_ends = gaps.index[gaps > MAX_GAP]
    if len(gap_ends):
        candidates["datagat"] = segment.index[segment.index.get_loc(gap_ends[0]) - 1]
    rerise = rerise_time(segment, max(RERISE_MIN_EPS, RERISE_FRACTION * jump))
    if rerise is not None:
        candidates["nieuwe stijging"] = rerise
    reason, stop = min(candidates.items(), key=lambda item: item[1])
    segment = eps.loc[t_peak:stop]

    result = {"stop_reden": reason, "volgduur_dagen": to_days(stop - t_peak)}
    for name, level in DECAY_LEVELS.items():
        reached = crossing_time(segment, eps_base + level * jump)
        result[f"{name}_dagen"] = to_days((reached if reached is not None else stop) - t_peak)
        result[f"{name}_bereikt"] = reached is not None

    elapsed = (segment.index - t_peak).total_seconds().to_numpy() / 86400
    fraction = (segment.to_numpy() - eps_base) / jump
    for day in CURVE_DAYS:
        inside = len(segment) > 1 and day <= elapsed[-1]
        value = np.interp(day, elapsed, segment.to_numpy()) if inside else np.nan
        result[f"rest_{day}d"] = (value - eps_base) / jump
        result[f"rest_water_{day}d_mm"] = float(water_layer_mm(value, eps_base)) if inside else np.nan
    result["curve"] = (elapsed, fraction)
    return result


def pre_trend(eps: pd.Series, t_base) -> float:
    """Helling (ε per dag) in de 72 uur voor het beginniveau."""
    before = eps.loc[t_base - PRE_TREND:t_base]
    if len(before) < 4:
        return np.nan
    return float(np.polyfit((before.index - before.index[0]).total_seconds() / 86400, before.to_numpy(), 1)[0])


def kaplan_meier(durations, observed) -> pd.DataFrame:
    """Aandeel events dat het niveau nog niet heeft bereikt, met censurering."""
    data = pd.DataFrame({"t": durations, "e": observed}).dropna().sort_values("t")
    at_risk, survival = len(data), 1.0
    rows = [(0.0, 1.0, at_risk)]
    for time, group in data.groupby("t"):
        events = int(group["e"].sum())
        if events:
            survival *= 1 - events / at_risk
            rows.append((float(time), survival, at_risk))
        at_risk -= len(group)
    return pd.DataFrame(rows, columns=["dagen", "aandeel", "at_risk"])


def km_median(durations, observed) -> float:
    curve = kaplan_meier(durations, observed)
    reached = curve[curve["aandeel"] <= 0.5]
    return float(reached["dagen"].iloc[0]) if len(reached) else np.nan


def percentile_rank(values, value: float) -> float:
    """Percentiel (0-100) van ``value`` binnen ``values``; gelijke waarden tellen voor de helft."""
    values = np.asarray(values, dtype=float)
    if not len(values):
        return np.nan
    return 100 * ((values < value).sum() + 0.5 * (values == value).sum()) / len(values)


# ---------------------------------------------------------------- inladen


def run_detection(refresh_hourly: bool):
    """Dezelfde stappen als ``watering_effect_analysis.main``, zonder uitvoer te schrijven."""
    detection.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = detection.load_probe_data()
    daily = detection.load_daily_weather()
    hourly_rain = detection.load_hourly_rain(df["ts"].min().normalize() - pd.Timedelta("4D"),
                                             df["ts"].max().normalize(), detection.OUTPUT_DIR, refresh_hourly)
    rain_between = detection.make_rain_sum(hourly_rain)
    _, responsible = detection.load_watering_log()
    changes = detection.compute_daily_changes(df, rain_between)
    reference = detection.rain_reference(df, hourly_rain)
    rain_summary = detection.summarise_rain_reference(reference)
    events = detection.detect_dry_rises(changes, df, rain_between)
    events = detection.classify_and_describe(events, changes, df, daily, rain_between, reference,
                                             rain_summary, responsible)
    return df, hourly_rain, events


def probe_frames(df: pd.DataFrame) -> dict:
    """Ondiepe probes met voldoende metingen, per (device_id, probe_number) gesorteerd op tijd."""
    shallow = df[df["depth"] <= detection.MAX_DEPTH_CM]
    return {key: group.set_index("ts").sort_index()
            for key, group in shallow.groupby(["device_id", "probe_number"])
            if len(group) >= detection.MIN_READINGS_PER_PROBE}


def next_event_start(events: pd.DataFrame, key, after) -> pd.Timestamp | None:
    same = events[(events["device_id"] == key[0]) & (events["probe_number"] == key[1])
                  & (events["onset_from"] > after)]
    return same["onset_from"].min() if len(same) else None


def describe(row) -> str:
    return f"{row['location_name']} p{int(row['probe_number'])} ({row['depth']:.0f} cm)"


# ---------------------------------------------------------------- vraag 1: duur verhoging


def decay_row(frame, key, t_peak, eps_base, jump, hourly_rain, events, rain_from=None) -> dict:
    """Verval met stop bij regen, plus een variant waarin alleen een nieuwe stijging het volgen stopt."""
    next_event = next_event_start(events, key, t_peak)
    result = follow_decay(frame["eps"], t_peak, eps_base, jump, hourly_rain, rain_from=rain_from, next_event=next_event)
    variant = follow_decay(frame["eps"], t_peak, eps_base, jump, hourly_rain, rain_from=rain_from,
                           next_event=next_event, censor_rain=False)
    for name in DECAY_LEVELS:
        result[f"{name}_dagen_zonder_regenstop"] = variant[f"{name}_dagen"]
        result[f"{name}_bereikt_zonder_regenstop"] = variant[f"{name}_bereikt"]
    result["stop_reden_zonder_regenstop"] = variant["stop_reden"]
    return result


def watering_decay(watering: pd.DataFrame, frames: dict, hourly_rain, events) -> tuple[pd.DataFrame, dict]:
    rows, curves = [], {}
    for index, event in watering.iterrows():
        key = (event["device_id"], event["probe_number"])
        result = decay_row(frames[key], key, event["t_peak"], event["eps_base"], event["jump"], hourly_rain, events)
        result["voortrend_eps_per_dag"] = pre_trend(frames[key]["eps"], event["t_base"])
        curves[index] = result.pop("curve")
        rows.append({
            "event": index, "location_name": event["location_name"], "device_id": key[0], "probe_number": key[1],
            "depth": event["depth"], "datum_lokaal": event["datum_lokaal"], "t_peak": event["t_peak"],
            "eps_base": event["eps_base"], "eps_peak": event["eps_peak"], "jump": event["jump"],
            "waterschijf_20cm_mm": event["waterschijf_20cm_mm"], "smi_start": event["smi_start"], **result,
        })
    return pd.DataFrame(rows), curves


def rain_decay(responses: pd.DataFrame, frames: dict, hourly_rain, events) -> tuple[pd.DataFrame, dict]:
    """Verval na duidelijke regenreacties in het gietseizoen, als referentie voor de gietbeurten."""
    selected = responses[
        (responses["d_eps"] >= RAIN_DECAY_MIN_JUMP) & ~responses["stijging_voor_regen"]
        & ~responses["gieten_in_venster"] & responses["t0"].dt.month.isin(SEASON_MONTHS)
    ]
    rows, curves = [], {}
    for index, response in selected.iterrows():
        key = (response["device_id"], response["probe_number"])
        rain_from = max(response["t_peak"], response["t1"])
        result = decay_row(frames[key], key, response["t_peak"], response["eps_base"], response["d_eps"],
                           hourly_rain, events, rain_from=rain_from)
        curves[index] = result.pop("curve")
        rows.append({
            "location_name": response["location_name"], "device_id": key[0], "probe_number": key[1],
            "depth": response["depth"], "t0": response["t0"], "mm": response["mm"], "t_peak": response["t_peak"],
            "eps_base": response["eps_base"], "jump": response["d_eps"],
            "waterschijf_20cm_mm": response["d_theta"] * detection.LAYER_MM, **result,
        })
    return pd.DataFrame(rows), curves


# ---------------------------------------------------------------- vraag 2: regenopname


def find_rain_episodes(hourly_rain: pd.Series, min_mm: float = detection.RAIN_EPISODE_MIN_MM,
                       dry_before_h: float = EPISODE_DRY_BEFORE_H) -> pd.DataFrame:
    """Buien van minstens ``min_mm`` na minstens ``dry_before_h`` uur zonder natte uren."""
    columns = ["t0", "t1", "t_1mm", "mm", "droog_voor_uur"]
    wet = hourly_rain[hourly_rain >= WET_HOUR_MM]
    if wet.empty:
        return pd.DataFrame(columns=columns)
    groups = (wet.index.to_series().diff() > EPISODE_SPLIT).cumsum()
    rows = []
    for _, block in wet.groupby(groups):
        cumulative = block.cumsum().to_numpy()
        reached = np.flatnonzero(cumulative >= PRE_RAIN_MM)
        t_1mm = block.index[reached[0]] - pd.Timedelta("1h") if len(reached) else pd.NaT
        rows.append({"t0": block.index.min() - pd.Timedelta("1h"), "t1": block.index.max(),
                     "t_1mm": t_1mm, "mm": block.sum()})
    episodes = pd.DataFrame(rows)
    episodes["droog_voor_uur"] = ((episodes["t0"] - episodes["t1"].shift()).dt.total_seconds() / 3600).fillna(np.inf)
    keep = (episodes["mm"] >= min_mm) & (episodes["droog_voor_uur"] >= dry_before_h)
    return episodes.loc[keep, columns].reset_index(drop=True)


def last_watering_before(watering: pd.DataFrame, moment, device_id, probe_number=None):
    mask = (watering["device_id"] == device_id) & (watering["t_peak"] < moment)
    if probe_number is not None:
        mask &= watering["probe_number"] == probe_number
    candidates = watering[mask]
    return candidates.loc[candidates["t_peak"].idxmax()] if len(candidates) else None


def rain_responses(frames: dict, episodes: pd.DataFrame, watering: pd.DataFrame) -> pd.DataFrame:
    """Reactie van elke ondiepe probe op elke bui, met vlaggen voor gieten rond de bui."""
    rows = []
    for key, frame in frames.items():
        times = frame.index.to_numpy()
        eps = frame["eps"].to_numpy()
        temperature = frame["temperature"].to_numpy()
        p5, p95 = np.nanpercentile(eps, [5, 95])
        start = frame.index.min() + pd.Timedelta(f"{detection.MIN_DAYS_SINCE_PLACEMENT + 1}D")
        own_watering = watering[(watering["device_id"] == key[0]) & (watering["probe_number"] == key[1])]
        for _, episode in episodes.iterrows():
            t0, t1, end = episode["t0"], episode["t1"], episode["t1"] + RESPONSE_WINDOW
            if t0 < start or end > frame.index.max():
                continue
            i_base = np.searchsorted(times, np.datetime64(t0), side="right") - 1
            i_end = np.searchsorted(times, np.datetime64(end), side="right")
            if i_base < 0 or times[i_base] < np.datetime64(t0 - BASE_MAX_AGE) or i_end - i_base - 1 < 3:
                continue
            i_temp = np.searchsorted(times, np.datetime64(t0 - pd.Timedelta("48h")))
            i_t1 = np.searchsorted(times, np.datetime64(t1), side="right")
            if np.nanmin(temperature[i_temp:max(i_t1, i_base + 1)]) < detection.MIN_SOIL_TEMP:
                continue
            base = eps[i_base]
            window = eps[i_base + 1:i_end]
            i_peak = i_base + 1 + int(np.argmax(window))
            d_eps = eps[i_peak] - base
            d_theta = float(detection.topp_theta(eps[i_peak]) - detection.topp_theta(base))

            pre_rain_rise = np.nan
            if pd.notna(episode["t_1mm"]):
                i_pre = np.searchsorted(times, np.datetime64(episode["t_1mm"]), side="right")
                if i_pre > i_base + 1:
                    pre_rain_rise = eps[i_base + 1:i_pre].max() - base
            rise_before_rain = bool(d_eps >= NO_RESPONSE_EPS and pre_rain_rise >= PRE_RAIN_RISE_FRACTION * d_eps)
            watering_in_window = bool(own_watering["onset_to"].between(t0 - BASE_MAX_AGE, end).any())

            row = {
                "device_id": key[0], "probe_number": key[1], "location_name": frame["location_name"].iloc[0],
                "depth": frame["depth"].iloc[0], "t0": t0, "t1": t1, "mm": episode["mm"],
                "eps_base": base, "t_peak": frame.index[i_peak], "d_eps": d_eps, "d_theta": d_theta,
                "smi_start": (base - p5) / (p95 - p5),
                "respons_mm": d_theta * detection.LAYER_MM if d_eps >= NO_RESPONSE_EPS else 0.0,
                "stijging_voor_regen": rise_before_rain, "gieten_in_venster": watering_in_window,
                "dagen_na_gieten": np.nan, "gietbeurt": np.nan, "rest_gietstijging": np.nan,
                "smi_door_gieten": np.nan, "dagen_na_gieten_sensor": np.nan,
            }
            previous = last_watering_before(watering, t0, key[0], key[1])
            if previous is not None:
                row["dagen_na_gieten"] = to_days(t0 - previous["t_peak"])
                row["gietbeurt"] = previous.name
                row["rest_gietstijging"] = (base - previous["eps_base"]) / previous["jump"]
                row["smi_door_gieten"] = (base - previous["eps_base"]) / (p95 - p5)
            sensor_previous = last_watering_before(watering, t0, key[0])
            if sensor_previous is not None:
                row["dagen_na_gieten_sensor"] = to_days(t0 - sensor_previous["t_peak"])
            rows.append(row)
    responses = pd.DataFrame(rows)
    responses["na_gieten"] = responses["dagen_na_gieten"].between(POST_WATERING_MIN_DAYS, POST_WATERING_MAX_DAYS)
    responses["controle"] = (~responses["stijging_voor_regen"] & ~responses["gieten_in_venster"]
                             & ~(responses["dagen_na_gieten_sensor"] <= CONTROL_EXCLUDE_DAYS))
    return responses


def score_responses(responses: pd.DataFrame) -> pd.DataFrame:
    """Percentiel van de waterschijf-respons t.o.v. vergelijkbare buien op dezelfde probe."""
    responses = responses.copy()
    responses["n_controles"] = 0
    responses["percentiel"] = np.nan
    responses["controles_mediaan_mm"] = np.nan
    for _, group in responses.groupby(["device_id", "probe_number"]):
        mm = group["mm"].to_numpy()
        month = group["t0"].dt.month.to_numpy()
        value = group["respons_mm"].to_numpy()
        control = group["controle"].to_numpy()
        for position, index in enumerate(group.index):
            month_gap = np.abs(month - month[position])
            month_gap = np.minimum(month_gap, 12 - month_gap)
            mask = (control & (mm >= mm[position] / MM_MATCH_FACTOR) & (mm <= mm[position] * MM_MATCH_FACTOR)
                    & (month_gap <= SEASON_MATCH_MONTHS))
            mask[position] = False
            responses.loc[index, "n_controles"] = int(mask.sum())
            if mask.sum() >= MIN_CONTROLS:
                responses.loc[index, "percentiel"] = percentile_rank(value[mask], value[position])
                responses.loc[index, "controles_mediaan_mm"] = np.median(value[mask])
    return responses


def compare_post_watering(responses: pd.DataFrame) -> pd.DataFrame:
    """Buien na gieten: eigen percentiel naast dat van probes op andere locaties bij dezelfde bui."""
    targets = responses[responses["na_gieten"] & ~responses["stijging_voor_regen"] & ~responses["gieten_in_venster"]]
    others_pool = responses[responses["controle"] & responses["percentiel"].notna()]
    rows = []
    for _, target in targets.iterrows():
        others = others_pool[(others_pool["t0"] == target["t0"])
                             & (others_pool["location_name"] != target["location_name"])]
        rows.append({
            **target[["location_name", "device_id", "probe_number", "depth", "gietbeurt", "t0", "mm",
                      "dagen_na_gieten", "rest_gietstijging", "smi_door_gieten", "smi_start", "eps_base", "d_eps",
                      "respons_mm",
                      "n_controles", "controles_mediaan_mm", "percentiel"]].to_dict(),
            "anderen_n": len(others),
            "anderen_mediaan_percentiel": others["percentiel"].median() if len(others) else np.nan,
            "anderen_fractie_reactie": (others["respons_mm"] > 0).mean() if len(others) else np.nan,
        })
    table = pd.DataFrame(rows)
    if not table.empty:
        table["verschil_met_anderen"] = table["percentiel"] - table["anderen_mediaan_percentiel"]
    return table


def sign_test(values) -> dict:
    values = pd.Series(values).dropna()
    above, below = int((values > 0).sum()), int((values < 0).sum())
    p_value = binomtest(above, above + below).pvalue if above + below else np.nan
    return {"n": len(values), "hoger": above, "lager": below, "gelijk": len(values) - above - below, "p": p_value}


def post_watering_tests(table: pd.DataFrame) -> dict:
    """Tekentoetsen per locatie en bui; probes van één sensor bij dezelfde bui zijn niet onafhankelijk."""
    if table.empty:
        return {}
    usable = table.dropna(subset=["percentiel"])
    per_episode = usable.groupby(["location_name", "t0"]).agg(
        percentiel=("percentiel", "mean"), verschil=("verschil_met_anderen", "mean"),
        respons_mm=("respons_mm", "mean"), controles_mm=("controles_mediaan_mm", "mean"))
    return {
        "probe_buien": len(table), "probe_buien_met_controles": len(usable),
        "locatie_buien": len(per_episode), "gietbeurten": usable["gietbeurt"].nunique(),
        "gemiddeld_percentiel": per_episode["percentiel"].mean(),
        "eigen_controles": sign_test(per_episode["percentiel"] - 50),
        "andere_locaties": sign_test(per_episode["verschil"]),
        "gemiddeld_verschil": per_episode["verschil"].mean(),
        "fractie_reactie": (usable["respons_mm"] > 0).mean(),
    }


def mechanism(responses: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Werkt regen sterker door als de bodem vooraf vochtiger is? Alleen controlebuien in het gietseizoen."""
    data = responses[responses["controle"] & responses["percentiel"].notna()
                     & responses["t0"].dt.month.isin(SEASON_MONTHS)].copy()
    data["smi_klasse"] = pd.cut(data["smi_start"], SMI_BINS, labels=SMI_LABELS)
    data["probe"] = data["device_id"].astype(str) + "_" + data["probe_number"].astype(str)
    table = data.groupby("smi_klasse", observed=False).agg(
        buien=("percentiel", "size"), probes=("probe", "nunique"),
        mediaan_mm=("mm", "median"), gemiddeld_percentiel=("percentiel", "mean"),
        fractie_reactie=("respons_mm", lambda x: (x > 0).mean()), gemiddelde_respons_mm=("respons_mm", "mean"),
    ).reset_index()
    rho, p_value = spearmanr(data["smi_start"], data["percentiel"]) if len(data) > 3 else (np.nan, np.nan)
    probe_rho = []
    for _, group in data.groupby(["device_id", "probe_number"]):
        if len(group) >= 8 and group["percentiel"].nunique() > 1 and group["smi_start"].nunique() > 1:
            probe_rho.append(spearmanr(group["smi_start"], group["percentiel"])[0])
    probe_rho = pd.Series(probe_rho, dtype=float)
    stats = {"buien": len(data), "probes": data["probe"].nunique(),
             "rho": rho, "p": p_value, "probes_rho": len(probe_rho),
             "probes_positief": int((probe_rho > 0).sum()), "mediaan_probe_rho": probe_rho.median(),
             "probe_toets": sign_test(probe_rho)}
    return table, stats


def km_summary(decay: pd.DataFrame, suffix: str = "") -> dict:
    summary = {"n": len(decay)}
    for name in DECAY_LEVELS:
        days, reached = decay[f"{name}_dagen{suffix}"], decay[f"{name}_bereikt{suffix}"]
        summary[name] = km_median(days, reached)
        summary[f"{name}_bereikt"] = int(reached.sum())
    return summary


# ---------------------------------------------------------------- figuren


def short_label(row) -> str:
    return f"{row['location_name']} p{int(row['probe_number'])} {pd.Timestamp(row['t_peak']):%d-%m-%y}"


def plot_decay(watering_table, watering_curves, rain_table, rain_curves, path: Path) -> None:
    fig, (ax_curve, ax_km) = plt.subplots(1, 2, figsize=(15, 6))
    for index, (elapsed, fraction) in rain_curves.items():
        inside = elapsed <= max(CURVE_DAYS)
        ax_curve.plot(elapsed[inside], fraction[inside], color="0.6", lw=0.6, alpha=0.35)
    colors = plt.cm.tab20(np.linspace(0, 1, max(len(watering_table), 1)))
    for color, (_, row) in zip(colors, watering_table.iterrows()):
        elapsed, fraction = watering_curves[row["event"]]
        inside = elapsed <= max(CURVE_DAYS)
        ax_curve.plot(elapsed[inside], fraction[inside], color=color, lw=1.6, label=short_label(row))
    ax_curve.plot([], [], color="0.6", lw=0.8, label=f"regenreacties (n={len(rain_curves)})")
    for level, text in ((0.5, "helft weg"), (0.1, "90% weg"), (0.0, "beginniveau")):
        ax_curve.axhline(level, color="k", ls=":" if level else "-", lw=0.8)
        ax_curve.text(max(CURVE_DAYS), level, f" {text}", va="center", fontsize=8)
    ax_curve.set(xlim=(0, max(CURVE_DAYS)), ylim=(-0.8, 1.15), xlabel="dagen na de piek",
                 ylabel="deel van de stijging dat nog over is",
                 title="Verval na gieten (kleur) en na regen (grijs), tot regen of nieuwe stijging")
    ax_curve.legend(fontsize=7, ncol=2, loc="upper right")

    styles = {"t50": "-", "t90": "--"}
    for table, color, name in ((watering_table, "tab:blue", "gieten"), (rain_table, "0.45", "regen")):
        for level, style in styles.items():
            curve = kaplan_meier(table[f"{level}_dagen"], table[f"{level}_bereikt"])
            curve = pd.concat([curve, pd.DataFrame({"dagen": [FOLLOW_MAX.days], "aandeel": [curve["aandeel"].iloc[-1]]})])
            median = km_median(table[f"{level}_dagen"], table[f"{level}_bereikt"])
            label = f"{name} {level} (n={len(table)}, mediaan {'n.b.' if pd.isna(median) else f'{median:.1f} d'})"
            ax_km.step(curve["dagen"], curve["aandeel"], where="post", color=color, ls=style, lw=1.8, label=label)
    ax_km.axhline(0.5, color="k", lw=0.6, ls=":")
    ax_km.set(xlim=(0, 14), ylim=(0, 1.02), xlabel="dagen na de piek",
              ylabel="aandeel events nog boven het niveau",
              title="Kaplan-Meier: t50 = helft van de stijging weg, t90 = 90% weg")
    ax_km.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_timeseries(watering, watering_table, frames, hourly_rain, comparison, path: Path) -> None:
    n = len(watering_table)
    ncols = 3
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(16, 3.3 * nrows), squeeze=False)
    for ax, (_, row) in zip(axes.flat, watering_table.iterrows()):
        event = watering.loc[row["event"]]
        frame = frames[(row["device_id"], row["probe_number"])]
        start, end = event["t_base"] - pd.Timedelta("2D"), event["t_peak"] + pd.Timedelta("21D")
        eps = frame.loc[start:end, "eps"]
        ax.plot(eps.index, eps, color="tab:green", lw=1)
        ax.axhline(event["eps_base"], color="0.3", ls="--", lw=0.8)
        for name, level in DECAY_LEVELS.items():
            if name == "t75":
                continue
            ax.axhline(event["eps_base"] + level * event["jump"], color="0.5", ls=":", lw=0.8)
            if row[f"{name}_bereikt"]:
                moment = event["t_peak"] + pd.Timedelta(days=row[f"{name}_dagen"])
                ax.plot(moment, event["eps_base"] + level * event["jump"], "o", color="tab:blue", ms=5)
                ax.annotate(name, (moment, event["eps_base"] + level * event["jump"]), xytext=(3, 3),
                            textcoords="offset points", fontsize=7, color="tab:blue")
        stop = event["t_peak"] + pd.Timedelta(days=row["volgduur_dagen"])
        ax.axvline(stop, color="tab:red", lw=1)
        ax.text(stop, ax.get_ylim()[1], f" stop: {row['stop_reden']}", color="tab:red", fontsize=7, va="top")

        episodes = comparison[(comparison["gietbeurt"] == row["event"])
                              & (comparison["probe_number"] == row["probe_number"])] if len(comparison) else comparison
        for _, episode in episodes.iterrows():
            ax.axvspan(episode["t0"], episode["t0"] + pd.Timedelta("1D"), color="tab:cyan", alpha=0.25)
            text = "n.v.t." if pd.isna(episode["percentiel"]) else f"P{episode['percentiel']:.0f}"
            ax.text(episode["t0"], ax.get_ylim()[0], f" {episode['mm']:.0f} mm\n {text}", fontsize=7, va="bottom")

        rain = hourly_rain.loc[start:end]
        twin = ax.twinx()
        twin.bar(rain.index - pd.Timedelta("30min"), rain, width=1 / 24, color="tab:blue", alpha=0.6)
        twin.set_ylim(max(rain.max(), 1) * 3, 0)
        twin.tick_params(labelsize=7)
        ax.set_title(f"{row['location_name']} p{int(row['probe_number'])} ({row['depth']:.0f} cm), "
                     f"gieten {row['datum_lokaal']}: +{row['jump']:.1f} ε", fontsize=9)
        ax.set_xlim(start, end)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m"))
        ax.tick_params(labelsize=7)
        ax.set_ylabel("ε", fontsize=8)
    for ax in list(axes.flat)[n:]:
        ax.set_visible(False)
    fig.suptitle("Permittiviteit na gieten (stippellijnen: helft en 10% van de stijging over; blauwe balken: "
                 "uurneerslag Voorschoten; cyaan: bui na gieten met percentiel t.o.v. vergelijkbare buien)", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_uptake(comparison, mechanism_table, mechanism_stats, path: Path) -> None:
    fig, (ax_pair, ax_smi) = plt.subplots(1, 2, figsize=(15, 6.5), gridspec_kw={"width_ratios": [1.3, 1]})
    usable = comparison.dropna(subset=["percentiel"]).sort_values("t0") if len(comparison) else comparison
    for y, (_, row) in enumerate(usable.iterrows()):
        ax_pair.plot([row["anderen_mediaan_percentiel"], row["percentiel"]], [y, y], color="0.6", lw=1)
        ax_pair.plot(row["anderen_mediaan_percentiel"], y, "o", color="0.6", ms=6)
        ax_pair.plot(row["percentiel"], y, "o", color="tab:blue", ms=7)
    ax_pair.set_yticks(range(len(usable)))
    ax_pair.set_yticklabels([
        f"{row['location_name']} p{int(row['probe_number'])} {row['t0']:%d-%m-%y} "
        f"({row['mm']:.0f} mm, {row['dagen_na_gieten']:.0f} d na gieten)" for _, row in usable.iterrows()
    ], fontsize=8)
    ax_pair.axvline(50, color="k", lw=0.8, ls=":")
    ax_pair.plot([], [], "o", color="tab:blue", label="na gieten t.o.v. eigen vergelijkingsbuien")
    ax_pair.plot([], [], "o", color="0.6", label="andere locaties bij dezelfde bui (mediaan)")
    ax_pair.set(xlim=(-3, 103), xlabel="percentiel respons (50 = gewone reactie)",
                title="Reactie op regen in de 14 dagen na gieten")
    ax_pair.invert_yaxis()
    ax_pair.legend(fontsize=8, loc="lower right")

    x = np.arange(len(mechanism_table))
    ax_smi.bar(x, mechanism_table["gemiddeld_percentiel"], color="tab:blue", alpha=0.7)
    for position, (_, row) in enumerate(mechanism_table.iterrows()):
        ax_smi.text(position, row["gemiddeld_percentiel"] + 1,
                    f"n={row['buien']}\n{row['fractie_reactie']:.0%} reageert", ha="center", fontsize=8)
    ax_smi.axhline(50, color="k", lw=0.8, ls=":")
    ax_smi.set_xticks(x)
    ax_smi.set_xticklabels(mechanism_table["smi_klasse"].astype(str))
    ax_smi.set(ylim=(0, 75), xlabel="bodemvochtindex vóór de bui (0 = droog, 1 = nat voor deze probe)",
               ylabel="gemiddeld percentiel respons",
               title=f"Regen in vochtiger grond (april-oktober, ρ = {mechanism_stats['rho']:.2f})")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------- samenvatting


def fmt_days(value: float) -> str:
    return "niet bereikt bij de helft van de events" if pd.isna(value) else f"{value:.1f} d"


def fmt_event_days(days: float, reached: bool) -> str:
    return f"{days:.1f} d" if reached else f"> {days:.1f} d"


def local_date(moment) -> str:
    return f"{pd.Timestamp(moment).tz_localize('UTC').tz_convert(detection.LOCAL_TZ):%Y-%m-%d}"


def compare_words(own: float, reference: float) -> str:
    if pd.isna(own) or pd.isna(reference):
        return "niet te vergelijken met"
    ratio = own / reference
    return "vergelijkbaar met" if 0.75 <= ratio <= 1.33 else ("langer dan" if ratio > 1 else "korter dan")


def format_summary(watering_table, rain_table, responses, comparison, tests, mechanism_table, mechanism_stats) -> str:
    km_water, km_water_all = km_summary(watering_table), km_summary(watering_table, "_zonder_regenstop")
    km_rain, km_rain_all = km_summary(rain_table), km_summary(rain_table, "_zonder_regenstop")
    remaining = watering_table[[f"rest_{day}d" for day in CURVE_DAYS]]
    remaining_mm = watering_table[[f"rest_water_{day}d_mm" for day in CURVE_DAYS]]
    rain_remaining = rain_table[[f"rest_{day}d" for day in CURVE_DAYS]]
    steep = watering_table[watering_table["voortrend_eps_per_dag"] < -0.2]
    lines = [
        "Nawerking van watergeven",
        "========================",
        "",
        f"Basis: {len(watering_table)} gietbeurten (probe-events met klasse '{detection.CLASS_WATERING}') op "
        f"{watering_table['location_name'].nunique()} locaties, gedetecteerd met watering_effect_analysis.py.",
        "",
        "1. Hoelang blijft de permittiviteit verhoogd?",
        "--------------------------------------------",
        f"Elke gietbeurt is gevolgd vanaf de piek tot regen (>= {CENSOR_RAIN_MM:g} mm binnen 24 uur), een nieuwe stijging,",
        f"een nieuw event, een datagat (> {MAX_GAP.total_seconds() / 3600:.0f} uur) of {FOLLOW_MAX.days} dagen. "
        "Wie eerder stopt telt mee als gecensureerd",
        "(Kaplan-Meier). t50/t75/t90 = moment waarop 50/75/90 procent van de stijging weer verdwenen is.",
        "",
        f"Kaplan-Meier-mediaan gieten (n = {km_water['n']}):",
    ]
    for name, text in (("t50", "helft weg"), ("t75", "driekwart weg"), ("t90", "vrijwel terug op beginniveau")):
        lines.append(f"  {name} ({text}): {fmt_days(km_water[name])} (bereikt bij {km_water[f'{name}_bereikt']} van "
                     f"{km_water['n']}), "
                     f"regen: {fmt_days(km_rain[name])} (bereikt bij {km_rain[f'{name}_bereikt']} van {km_rain['n']})")
    lines += [
        "  Regen = duidelijke regenreacties (>= 1 ε) van april t/m oktober op dezelfde soort probes, zelfde methode.",
        f"Als regen zonder nieuwe stijging het volgen niet stopt: gieten t50 {fmt_days(km_water_all['t50'])}, "
        f"t90 {fmt_days(km_water_all['t90'])}; regen t50 {fmt_days(km_rain_all['t50'])}, "
        f"t90 {fmt_days(km_rain_all['t90'])}.",
        "Resterend deel van de stijging (mediaan van de events die op dat moment nog gevolgd worden):",
        "  " + ", ".join(f"{day} d: {remaining[f'rest_{day}d'].median():.0%} (n={remaining[f'rest_{day}d'].notna().sum()})"
                         for day in CURVE_DAYS if remaining[f"rest_{day}d"].notna().sum()),
        "  regen: " + ", ".join(f"{day} d: {rain_remaining[f'rest_{day}d'].median():.0%}"
                                for day in CURVE_DAYS if rain_remaining[f"rest_{day}d"].notna().sum() >= 5),
        f"Extra waterschijf over 20 cm: mediaan {watering_table['waterschijf_20cm_mm'].median():.1f} mm bij de piek, "
        + ", ".join(f"{round(remaining_mm[f'rest_water_{day}d_mm'].median(), 1) + 0.0:.1f} mm na {day} d"
                    for day in (1, 3, 7) if remaining_mm[f"rest_water_{day}d_mm"].notna().sum()) + ".",
        f"Bij {len(steep)} gietbeurten daalde ε vooraf al met meer dan 0.2 per dag "
        f"({', '.join(short_label(row) for _, row in steep.iterrows()) or '-'}).",
        "Zonder gieten was de grond daar verder uitgedroogd; de duur t.o.v. het niveau vóór het gieten is dan een ondergrens.",
        "",
        "Per gietbeurt:",
    ]
    for _, row in watering_table.iterrows():
        lines.append(
            f"- {row['location_name']} p{int(row['probe_number'])} ({row['depth']:.0f} cm) {row['datum_lokaal']}: "
            f"+{row['jump']:.1f} ε ({row['waterschijf_20cm_mm']:.0f} mm over 20 cm); "
            f"t50 {fmt_event_days(row['t50_dagen'], row['t50_bereikt'])}, "
            f"t90 {fmt_event_days(row['t90_dagen'], row['t90_bereikt'])}; gevolgd {row['volgduur_dagen']:.1f} d, "
            f"stop: {row['stop_reden']}; voortrend {row['voortrend_eps_per_dag']:+.2f} ε/d")

    lines += [
        "",
        "2. Neemt de bodem regen beter op in de periode na gieten?",
        "--------------------------------------------------------",
        f"Buien van >= {detection.RAIN_EPISODE_MIN_MM:g} mm na >= {EPISODE_DRY_BEFORE_H} uur droog, "
        f"{POST_WATERING_MIN_DAYS:g}-{POST_WATERING_MAX_DAYS} dagen na een gietbeurt op dezelfde probe.",
        f"Respons = extra waterschijf (Topp, {detection.LAYER_MM} mm laag) tot {RESPONSE_WINDOW.total_seconds() / 3600:.0f} "
        f"uur na de bui; minder dan {NO_RESPONSE_EPS:g} ε telt als geen reactie.",
        f"Vergelijking met buien op dezelfde probe met {1 / MM_MATCH_FACTOR:g}-{MM_MATCH_FACTOR:g}x zoveel regen, "
        f"binnen {SEASON_MATCH_MONTHS} maanden van het seizoen en zonder gieten in de",
        f"{CONTROL_EXCLUDE_DAYS} dagen ervoor (percentiel 50 = gewone reactie), en met andere locaties bij dezelfde bui.",
    ]
    excluded = responses[responses["na_gieten"] & (responses["stijging_voor_regen"] | responses["gieten_in_venster"])]
    for _, row in excluded.iterrows():
        lines.append(f"Uitgesloten: {row['location_name']} p{int(row['probe_number'])} {local_date(row['t0'])}, "
                     "ε steeg al voordat 1 mm regen was gevallen (waarschijnlijk opnieuw gegoten).")
    if tests:
        own, others = tests["eigen_controles"], tests["andere_locaties"]
        lines += [
            "",
            f"{tests['probe_buien']} probe-buien na {tests['gietbeurten']} gietbeurten; "
            f"{tests['probe_buien_met_controles']} met minstens {MIN_CONTROLS} vergelijkingsbuien, "
            f"samen {tests['locatie_buien']} locatie-buien.",
            f"Gemiddeld percentiel na gieten: {tests['gemiddeld_percentiel']:.0f}. "
            f"Aandeel probe-buien met reactie: {tests['fractie_reactie']:.0%}.",
            f"Tekentoets t.o.v. eigen vergelijkingsbuien: {own['hoger']} hoger, {own['lager']} lager, "
            f"{own['gelijk']} gelijk, p = {own['p']:.2f}.",
            f"Tekentoets t.o.v. andere locaties bij dezelfde bui: {others['hoger']} hoger, {others['lager']} lager, "
            f"{others['gelijk']} gelijk, p = {others['p']:.2f}; gemiddeld verschil {tests['gemiddeld_verschil']:+.0f} "
            "percentielpunten.",
            "",
            "Per bui na gieten:",
        ]
    for _, row in comparison.iterrows():
        own_text = "te weinig vergelijkingsbuien" if pd.isna(row["percentiel"]) else (
            f"vergelijkingsbuien mediaan {row['controles_mediaan_mm']:.1f} mm -> P{row['percentiel']:.0f}")
        others_text = "" if pd.isna(row["anderen_mediaan_percentiel"]) else (
            f"; andere locaties P{row['anderen_mediaan_percentiel']:.0f}")
        lines.append(
            f"- {row['location_name']} p{int(row['probe_number'])} {local_date(row['t0'])}: {row['mm']:.1f} mm, "
            f"{row['dagen_na_gieten']:.1f} d na gieten (nog {row['rest_gietstijging']:.0%} van de gietstijging): "
            f"respons {row['respons_mm']:.1f} mm; {own_text}{others_text}")

    probe_test = mechanism_stats["probe_toets"]
    lines += [
        "",
        f"Mechanisme: werkt regen beter door als de grond vooraf vochtiger is? ({mechanism_stats['buien']} buien "
        f"april t/m oktober op {mechanism_stats['probes']} probes, zonder gieten in de buurt)",
        f"  Spearman ρ tussen bodemvochtindex vooraf en percentiel: {mechanism_stats['rho']:.2f} "
        f"(p = {mechanism_stats['p']:.1g}, buien niet onafhankelijk);",
        f"  per probe positief bij {probe_test['hoger']} van {probe_test['n']} probes "
        f"(tekentoets p = {probe_test['p']:.2f}, mediaan ρ {mechanism_stats['mediaan_probe_rho']:.2f}).",
    ]
    for _, row in mechanism_table.iterrows():
        lines.append(f"  bodemvochtindex {row['smi_klasse']}: {row['buien']} buien, gemiddeld percentiel "
                     f"{row['gemiddeld_percentiel']:.0f}, {row['fractie_reactie']:.0%} reageert, "
                     f"gemiddeld {row['gemiddelde_respons_mm']:.1f} mm")
    wetter = mechanism_table.iloc[1:]
    dry_gap = (np.average(wetter["gemiddeld_percentiel"], weights=wetter["buien"])
               - mechanism_table["gemiddeld_percentiel"].iloc[0])
    lines.append(f"  Buien op grond met index >= 0.2 scoren gemiddeld {dry_gap:.0f} percentielpunten hoger dan op de "
                 "droogste grond;")
    lines.append("  boven 0.2 maakt extra vocht weinig verschil.")
    smi_gain = comparison["smi_door_gieten"].mean() if len(comparison) else np.nan
    if pd.notna(smi_gain):
        lines.append(f"  Bij de buien na gieten lag de bodemvochtindex door het gieten nog gemiddeld {smi_gain:+.2f} "
                     "hoger dan vóór het gieten.")

    water_t50, rain_t50 = km_water["t50"], km_rain["t50"]
    significant = tests and min(tests["eigen_controles"]["p"], tests["andere_locaties"]["p"]) < 0.05
    lines += [
        "",
        "Conclusie",
        "---------",
        f"- De permittiviteit is na gieten na ongeveer {fmt_days(water_t50)} voor de helft en na ongeveer "
        f"{fmt_days(km_water['t90'])} grotendeels terug op het oude niveau;",
        f"  dat is {compare_words(water_t50, rain_t50)} de nawerking van een regenbui ({fmt_days(rain_t50)} en "
        f"{fmt_days(km_rain['t90'])}). Na ongeveer een week is van een gietbeurt in de meetdata weinig meer over.",
        ("- Regen in de twee weken na gieten werkt " + (
            "aantoonbaar sterker door dan normaal." if significant else
            "niet aantoonbaar beter door dan bij vergelijkbare buien zonder gieten vooraf.")),
        "  De richting is licht positief, maar het aantal buien na gieten is klein." if tests and
        tests["gemiddeld_verschil"] > 0 and not significant else None,
        "- Wel werkt regen iets beter door als de grond vooraf niet erg droog is (index < 0.2 tegenover hoger: "
        f"{dry_gap:.0f} percentielpunten).",
        f"  Gieten verhoogde de index bij de volgende bui gemiddeld met {smi_gain:.2f} en dat effect is na ongeveer "
        "een week grotendeels weg;",
        f"  het te verwachten voordeel is dus klein (orde {dry_gap:.0f} percentielpunten) en treedt alleen op als de "
        "grond anders erg droog zou zijn.",
        "",
        "Kanttekeningen",
        "--------------",
        "- Gietmomenten zijn afgeleid uit de sensordata; het logboek bevat vrijwel geen ingevulde gietbeurten.",
        "  Gietbeurten die samenvielen met regen worden niet herkend en kunnen controlebuien vervuilen.",
        "- Het aantal buien na gieten is klein en deels afhankelijk (zelfde gietbeurt, zelfde bui). Een effect van",
        "  ongeveer tien percentielpunten kan met deze data niet worden aangetoond en ook niet worden uitgesloten.",
        "- Probes op 15-30 cm reageren in de zomer zelden op buien onder 5 mm; daardoor zijn veel responsen 0.",
        "- Neerslag is gemeten in Voorschoten (uurwaarden), niet op de locaties zelf.",
        "- Verval na regen is afgekapt bij nieuwe regen; in natte periodes worden vooral korte stukken gevolgd.",
    ]
    return "\n".join(line for line in lines if line is not None)


# ---------------------------------------------------------------- hoofdprogramma


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
    print("Analyse nawerking watergeven gestart.")

    df, hourly_rain, events = run_detection(args.refresh_hourly)
    frames = probe_frames(df)
    watering = events[events["klasse"] == detection.CLASS_WATERING]
    if watering.empty:
        print("Geen gietbeurten gevonden; niets te analyseren.")
        return

    watering_table, watering_curves = watering_decay(watering, frames, hourly_rain, events)
    episodes = find_rain_episodes(hourly_rain)
    responses = score_responses(rain_responses(frames, episodes, watering))
    rain_table, rain_curves = rain_decay(responses, frames, hourly_rain, events)
    comparison = compare_post_watering(responses)
    tests = post_watering_tests(comparison)
    mechanism_table, mechanism_stats = mechanism(responses)
    print(f"{len(watering_table)} gietbeurten, {len(episodes)} buien, {len(responses)} probe-buien, "
          f"{len(comparison)} buien na gieten.")

    renames = {"t_peak": "piek_utc", "t0": "begin_bui_utc", "t1": "einde_bui_utc"}
    watering_table.drop(columns="event").rename(columns=renames).round(4).to_csv(
        output_dir / "duur_verhoging_per_gietbeurt.csv", index=False)
    rain_table.rename(columns=renames).round(4).to_csv(output_dir / "duur_verhoging_regen.csv", index=False)
    comparison.rename(columns=renames).round(4).to_csv(output_dir / "regenrespons_na_gieten.csv", index=False)
    responses.rename(columns=renames).round(4).to_csv(output_dir / "regenepisodes_respons.csv", index=False)

    plot_decay(watering_table, watering_curves, rain_table, rain_curves, output_dir / "verval_na_gieten.png")
    plot_timeseries(watering, watering_table, frames, hourly_rain, comparison, output_dir / "tijdreeksen_nawerking.png")
    plot_uptake(comparison, mechanism_table, mechanism_stats, output_dir / "regenopname_na_gieten.png")

    summary = format_summary(watering_table, rain_table, responses, comparison, tests, mechanism_table,
                             mechanism_stats)
    (output_dir / "samenvatting.txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)
    print(f"\nAnalyse voltooid. Uitvoer in {output_dir}")


if __name__ == "__main__":
    main()

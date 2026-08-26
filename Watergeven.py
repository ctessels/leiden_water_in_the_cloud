"""
One off script dat laat zien hoe het kleine beetje bewateringsdata zich verhoudt tot de regen- en sensordata
"""

# --- deps ---
import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data_collection" / "sensor_data"

water_dates_vrolijk = [
    "2025-08-12", "2025-08-13", "2025-08-15",
    "2025-09-09", "2025-09-16", "2025-09-19", "2025-09-30"
]
water_dates_vrolijk = pd.to_datetime(water_dates_vrolijk)

water_dates_heer_start = pd.to_datetime("2025-08-15")
water_dates_heer_end   = pd.to_datetime("2025-08-26")

# --- params ---
device_ids = [1432,1391,1392]
date_from = '2025-08-10'
date_to   = '2025-10-31'
PROBES = [1,2,3]       # we'll try these in order
CLIP_SMI = True        # clip SMI to [0,1] on plots

# --- 1) LOAD *ALL* DATA FOR ALL PROBES (no window here!) ---
conn = sqlite3.connect(DATA_DIR / "database.db")
device_ids_str = ",".join(map(str, device_ids))
query = f"""
SELECT
    F.device_id,
    D.location_name,
    F.probe_number,
    F.relative_permittivity,
    F.timestamp
FROM FactSensorData F
LEFT JOIN DimSensor D
    ON F.device_id = D.device_id
WHERE F.device_id IN ({device_ids_str})
  AND F.probe_number IN (1,2,3)
ORDER BY D.location_name, F.device_id, F.probe_number, F.timestamp;
"""
df_all = pd.read_sql_query(query, conn)
conn.close()

# --- 2) CLEAN TYPES ---
# relative_permittivity -> numeric
s = df_all["relative_permittivity"].astype(str).str.strip()
s = s.str.replace(r"\s+", "", regex=True)
s = s.str.replace(r"(?<=\d)[, ](?=\d{3}\b)", "", regex=True)  # thousands sep
s = s.str.replace(",", ".", regex=False)                      # decimal comma
df_all["relative_permittivity"] = pd.to_numeric(s, errors="coerce")

# epoch seconds -> datetime to minute (naive for display)
df_all["timestamp"] = pd.to_datetime(df_all["timestamp"], unit="s", utc=True).dt.floor("min")
df_all["timestamp"] = df_all["timestamp"].dt.tz_localize(None)

# --- 3) RAIN DATA (window only for plotting) ---
rain_df = pd.read_csv(DATA_DIR / "valkenburg_precipitation.csv")
rain_df.columns = rain_df.columns.str.strip()
rain_df["RD"] = rain_df["RD"] / 10.0  # tenth-mm -> mm
rain_df["date"] = pd.to_datetime(rain_df["DATE"]).dt.normalize()
rain_window = rain_df.loc[
    (rain_df["date"] >= pd.to_datetime(date_from)) &
    (rain_df["date"] <= pd.to_datetime(date_to)),
    ["date", "RD"]
].drop_duplicates(subset="date")

# --- 4) COMPUTE SMI BOUNDS OVER *ALL* DATA PER (location, probe) ---
bounds_alltime = (
    df_all.dropna(subset=["relative_permittivity"])
         .groupby(["location_name","probe_number"])["relative_permittivity"]
         .quantile([0.05, 0.95])
         .unstack()
         .rename(columns={0.05: "p05", 0.95: "p95"})
         .reset_index()
)

# --- 5) TRANSFORM *ALL* READINGS TO SMI USING ALL-TIME BOUNDS ---
df_all = df_all.merge(bounds_alltime, on=["location_name","probe_number"], how="left")
den = (df_all["p95"] - df_all["p05"]).replace(0, np.nan)
df_all["smi_raw"] = (df_all["relative_permittivity"] - df_all["p05"]) / den
df_all.loc[~np.isfinite(df_all["smi_raw"]), "smi_raw"] = np.nan
df_all["smi"] = df_all["smi_raw"].clip(0, 1) if CLIP_SMI else df_all["smi_raw"]

# --- 6) NOW SLICE TO WINDOW FOR DISPLAY, PER PROBE ---
start = pd.to_datetime(date_from)
end   = pd.to_datetime(date_to)

for probe in PROBES:
    df_probe = df_all[df_all["probe_number"] == probe].copy()
    if df_probe.empty:
        # no such probe among these sensors—skip
        continue

    # window for plotting only
    dfp = df_probe[(df_probe["timestamp"] >= start) & (df_probe["timestamp"] <= end)].copy()
    if dfp.empty:
        # probe exists historically but nothing in the window—skip the plot
        continue

    # daily mean SMI per location in the window
    dfp["date"] = dfp["timestamp"].dt.normalize()
    smi_mean_by_day = (
        dfp.groupby(["location_name", "date"])["smi"]
           .mean()
           .reset_index()
    )

    # wide table for lines
    smi_wide = (
        smi_mean_by_day
        .pivot_table(index="date", columns="location_name", values="smi", aggfunc="mean")
        .sort_index()
    )
    if smi_wide.empty:
        continue  # nothing to plot

    # align rain to x-axis
    rain_series = (
        rain_window.set_index("date")["RD"]
        .reindex(smi_wide.index)
    )

    # --- plot one figure per probe ---
    fig, ax1 = plt.subplots(figsize=(21, 9))
    # vertical green bars (full height)
    for d in water_dates_vrolijk:
        ax1.axvline(d, color="green", alpha=0.2, linewidth=8)  # adjust width/alpha as needed
    ax1.axvspan(
        water_dates_heer_start,
        water_dates_heer_end,
        color="red",  # pick a different color than the green bars
        alpha=0.15,
        zorder=0  # behind curves
    )
    smi_wide.plot(ax=ax1, linewidth=1)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("SMI")
    ax1.set_ylim(0, 1 if CLIP_SMI else None)
    ax1.set_title(f"Dagelijkse SMI per locatie — Probe {probe}")

    ax1.set_xlim(start, end)
    ax1.xaxis.set_major_locator(mdates.DayLocator(interval=5))
    ax1.xaxis.set_minor_locator(mdates.DayLocator(interval=1))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax1.xaxis.set_minor_formatter(mdates.DateFormatter("%d"))
    plt.setp(ax1.get_xticklabels(minor=False), rotation=45, ha="right")
    plt.setp(ax1.get_xticklabels(minor=True), rotation=45, ha="right")
    ax1.grid(which="both", linestyle="--", alpha=0.5)

    ax2 = ax1.twinx()
    ax2.bar(rain_series.index, rain_series.values, alpha=0.3)
    ax2.set_ylabel("Rain (mm)")

    ax1.legend(title="Location", bbox_to_anchor=(1.06, 1), loc="upper left")
    plt.tight_layout()
    plt.show()

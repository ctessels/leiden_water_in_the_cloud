""" In dit bestand wordt alle data-analyse gedaan. Om het overzichtelijk te houden wordt  alles onderverdeeld
in classes en functions."""

import pandas as pd
import sqlite3
from datetime import datetime, timezone, timedelta
import matplotlib.pyplot as plt
import numpy as np
import json
from pathlib import Path

# Options
pd.set_option('display.max_columns', None)
plt.ion()

#---------------------
# Set parameters
#---------------------


USABLE_SENSORS_PATH = (
    Path(__file__).resolve().parent
    / "../data_collection/sensor_data/usable_sensors.json"
).resolve()
DATA_DIR = Path(__file__).resolve().parent.parent / "data_collection" / "sensor_data"

def load_usable_sensors(minimum_months: int) -> list[int]:
    if minimum_months < 3 or minimum_months > 24:
        raise ValueError("minimum_months must be between 3 and 24")

    with USABLE_SENSORS_PATH.open(encoding="utf-8") as file:
        sensors_by_category = json.load(file)

    usable_sensors = {
        sensor_id
        for category, sensor_ids in sensors_by_category.items()
        if int(category.removesuffix("months")) >= minimum_months
        for sensor_id in sensor_ids
    }

    return sorted(usable_sensors)

START_DATE = datetime(2025, 1, 1).date()
END_DATE = datetime.now(timezone.utc).date()
# END_DATE = datetime(2026, 7, 7).date()
MINIMUM_TIME_SERIES_MONTHS = 6
USABLE_SENSORS = load_usable_sensors(MINIMUM_TIME_SERIES_MONTHS)
RAIN_EVENT_MM_PER_SENSOR = {
    356: 4.0,
    360: 10.0,
    361: 3.0,
    369: 3.0,
    416: 2.0,
    418: 3.0,
    1385: 4.5,
    1386: 2.5,
    1387: 4.5,
    1390: 2.5,
    1391: 4.5,
    1392: 2.0,
    1393: 10.0,
    1432: 3.0,
}
RAIN_RESPONSE_STRENGTH_PER_SENSOR = {
    356: 0.50,
    360: 1.25,
    361: 0.50,
    369: 0.50,
    416: 0.25,
    418: 0.25,
    1385: 0.50,
    1386: 0.25,
    1387: 0.50,
    1390: 0.25,
    1391: 0.50,
    1392: 0.25,
    1393: 1.00,
    1432: 0.50,
}
MAX_RAIN_RESPONSE_MULTIPLIER_PER_SENSOR = {
    356: 3.0,
    360: 3.0,
    361: 3.0,
    369: 3.0,
    416: 3.0,
    418: 1.0,
    1385: 1.0,
    1386: 1.0,
    1387: 1.0,
    1390: 1.0,
    1391: 3.0,
    1392: 0.75,
    1393: 1.5,
    1432: 3.0,
}
RAIN_MEMORY_DECAY_PER_SENSOR = {
    356: 0.65,
    360: 0.80,
    361: 0.75,
    369: 0.75,
    416: 0.50,
    418: 0.55,
    1385: 0.80,
    1386: 0.55,
    1387: 0.70,
    1390: 0.75,
    1391: 0.80,
    1392: 0.80,
    1393: 0.75,
    1432: 0.55,
}


#---------------------
# Get data
#---------------------
conn = sqlite3.connect(DATA_DIR / 'database.db')
cursor = conn.cursor()

# Sensor data
df_sensor = pd.read_sql_query(f"""
select
    fsd.device_id
    ,device_name
    ,location_name
    ,mp_depth_1
    ,mp_depth_2
    ,mp_depth_3
    ,probe_number
    ,timestamp
    ,temperature
    ,relative_permittivity
    ,is_active
from FactSensorData fsd
left join DimSensor ds
    on fsd.device_id = ds.device_id
where is_active = 1
and probe_number = 1
""", conn)

# Unix timestamp omzetten naar datum
df_sensor['datetime'] = (
    pd.to_datetime(df_sensor["timestamp"], unit="s")
)
# Aggregeren bij datum per device_id
df_sensor = (
    df_sensor
    .groupby("device_id")
    .resample("D", on="datetime")[["relative_permittivity", "temperature"]]
    .mean()
    .reset_index()
)

#Z-score normalisatie zodat variatie behouden blijft
df_sensor['perm_zscore'] = (
    df_sensor
    .groupby('device_id')['relative_permittivity']
    .transform(lambda x: (x - x.mean()) / x.std())
)

# Weather forecast data
df_weather_forecast = pd.read_sql_query("""
select
    forecast_date
    ,forecast_for_date
    ,avg_temp
    ,min_temp
    ,max_temp
    ,wind_direction_deg
    ,wind_kmh
    ,precipitation_mm
    ,precipitation_perc
    ,sunshine_minutes
    ,sunshine_pct
    ,condition
from TenDayForecast
""", conn)

# voorschoten historical weather data
df_weather = pd.read_csv(DATA_DIR / 'voorschoten_weerdata.csv')
df_weather = df_weather[pd.to_numeric(df_weather['windsnelheid'], errors='coerce').notnull()]
df_weather['neerslag'] = df_weather['neerslag'].replace(-1, 0)  # Since -1 means <0.05mm of rain.
df_weather[['neerslag', 'temperatuur', 'mintemperatuur', 'maxtemperatuur']] = df_weather[['neerslag', 'temperatuur',
                                                                                          'mintemperatuur',
                                                                                          'maxtemperatuur']].astype(
    float) / 10.0  # 0.1 graden vs 1
df_weather['windsnelheid'] = df_weather['windsnelheid'].astype(float) / 10.0 * 3.6  # 0.1 m/s to km/h
df_weather['zonneschijnduur'] = df_weather['zonneschijnduur'].astype(float) / 10.0 * 60  # 0.1 hours to minutes
df_weather.columns = df_weather.columns.str.strip()
df_weather['date'] = pd.to_datetime(df_weather['DATE']).dt.date
df_weather = df_weather[(df_weather['date'] >= START_DATE) & (df_weather['date'] <= END_DATE)]


#---------------------
# Grafiekfuncties
#---------------------
def plot_permittivity_with_rain(df_sensor, df_weather, device_id, start_date, end_date):
    # Filter sensor data
    df_device = df_sensor[df_sensor["device_id"] == device_id].sort_values("datetime")
    df_device = df_device[
        (df_device["datetime"].dt.date >= start_date) &
        (df_device["datetime"].dt.date <= end_date)
    ]

    datetimes = df_device["datetime"]
    values = df_device["relative_permittivity"]

    # Filter rain data
    df_rain = df_weather[["date", "neerslag"]].copy()
    df_rain = df_rain[
        (df_rain["date"] >= start_date) &
        (df_rain["date"] <= end_date)
    ]

    # Plot
    fig, ax1 = plt.subplots()

    ax1.plot(datetimes, values)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Relative Permittivity")
    ax1.tick_params(axis='x', rotation=70)

    ax2 = ax1.twinx()
    ax2.bar(
        df_rain["date"],
        df_rain["neerslag"],
        color="blue",
        alpha=0.3,
        width=1.0
    )
    ax2.set_ylabel("Rain (mm)")

    plt.title(f"Relative Permittivity + Rain (device {device_id})")
    plt.tight_layout()
    plt.show()
def plot_permittivity_with_rain_subplots(df_sensor, df_weather, device_ids, start_date, end_date):
    import math

    n = len(device_ids)
    ncols = 3
    nrows = math.ceil(n / ncols)

    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(18, 4 * nrows))
    axes = axes.flatten()

    # Rain data only needs to be filtered once
    df_rain = df_weather[["date", "neerslag"]].copy()
    df_rain = df_rain[
        (df_rain["date"] >= start_date) &
        (df_rain["date"] <= end_date)
    ]

    for i, device_id in enumerate(device_ids):
        ax1 = axes[i]

        # Filter sensor data for this device
        df_device = df_sensor[df_sensor["device_id"] == device_id].sort_values("datetime")
        df_device = df_device[
            (df_device["datetime"].dt.date >= start_date) &
            (df_device["datetime"].dt.date <= end_date)
        ]

        datetimes = df_device["datetime"]
        values = df_device["relative_permittivity"]

        # Permittivity line
        ax1.plot(datetimes, values)
        ax1.set_title(f"Device {device_id}")
        ax1.set_xlabel("Date")
        ax1.set_ylabel("Rel. Perm.")
        ax1.tick_params(axis="x", rotation=70)

        # Rain bars on second axis
        ax2 = ax1.twinx()
        ax2.bar(
            df_rain["date"],
            df_rain["neerslag"],
            color="blue",
            alpha=0.3,
            width=1.0
        )
        ax2.set_ylabel("Rain (mm)")

    # Hide unused subplots
    for j in range(len(device_ids), len(axes)):
        fig.delaxes(axes[j])

    fig.suptitle("Relative Permittivity + Rain per Device", fontsize=16)
    plt.tight_layout()
    plt.show()
def plot_permittivity_with_temperature(df_sensor, df_weather, device_id, start_date, end_date):
    # Filter sensor data
    df_device = df_sensor[df_sensor["device_id"] == device_id].sort_values("datetime")
    df_device = df_device[
        (df_device["datetime"].dt.date >= start_date) &
        (df_device["datetime"].dt.date <= end_date)
    ]

    datetimes = df_device["datetime"]
    permittivity_values = df_device["relative_permittivity"]
    temperature_values = df_device["temperature"]

    # Plot
    fig, ax1 = plt.subplots()

    ax1.plot(datetimes, permittivity_values)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Relative Permittivity")
    ax1.tick_params(axis='x', rotation=70)

    ax2 = ax1.twinx()
    ax2.bar(
        datetimes,
        temperature_values,
        alpha=0.3,
        width=1.0
    )
    ax2.set_ylabel("Temperature (°C)")

    plt.title(f"Relative Permittivity + Temperature (device {device_id})")
    plt.tight_layout()
    plt.show()
def plot_permittivity_with_temperature_subplots(df_sensor, df_weather, device_ids, start_date, end_date):
    import math

    n = len(device_ids)
    ncols = 3
    nrows = math.ceil(n / ncols)

    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(18, 4 * nrows))
    axes = axes.flatten()

    for i, device_id in enumerate(device_ids):
        ax1 = axes[i]

        # Filter sensor data for this device
        df_device = df_sensor[df_sensor["device_id"] == device_id].sort_values("datetime")
        df_device = df_device[
            (df_device["datetime"].dt.date >= start_date) &
            (df_device["datetime"].dt.date <= end_date)
        ]

        datetimes = df_device["datetime"]
        permittivity_values = df_device["relative_permittivity"]
        temperature_values = df_device["temperature"]

        # Permittivity line
        ax1.plot(datetimes, permittivity_values)
        ax1.set_title(f"Device {device_id}")
        ax1.set_xlabel("Date")
        ax1.set_ylabel("Rel. Perm.")
        ax1.tick_params(axis="x", rotation=70)

        # Temperature bars on second axis
        ax2 = ax1.twinx()
        ax2.bar(
            datetimes,
            temperature_values,
            alpha=0.3,
            width=1.0
        )
        ax2.set_ylabel("Temperature (°C)")

    # Hide unused subplots
    for j in range(len(device_ids), len(axes)):
        fig.delaxes(axes[j])

    fig.suptitle("Relative Permittivity + Temperature per Device", fontsize=16)
    plt.tight_layout()
    plt.show()
def plot_permittivity_with_rain_normalised(df_sensor, df_weather, device_id, start_date, end_date):
    # Filter sensor data
    df_device = df_sensor[df_sensor["device_id"] == device_id].sort_values("datetime")
    df_device = df_device[
        (df_device["datetime"].dt.date >= start_date) &
        (df_device["datetime"].dt.date <= end_date)
    ]

    datetimes = df_device["datetime"]
    values = df_device["perm_zscore"]

    # Filter rain data
    df_rain = df_weather[["date", "neerslag"]].copy()
    df_rain = df_rain[
        (df_rain["date"] >= start_date) &
        (df_rain["date"] <= end_date)
    ]

    # Plot
    fig, ax1 = plt.subplots()

    ax1.plot(datetimes, values)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("rel. perm. z-score")
    ax1.tick_params(axis='x', rotation=70)

    ax2 = ax1.twinx()
    ax2.bar(
        df_rain["date"],
        df_rain["neerslag"],
        color="blue",
        alpha=0.3,
        width=1.0
    )
    ax2.set_ylabel("Rain (mm)")

    plt.title(f"Z-score + Rain (device {device_id})")
    plt.tight_layout()
    plt.show()
def plot_permittivity_with_energy_proxy(df_sensor, df_weather, device_id, start_date, end_date):
    # Filter sensor data
    df_device = df_sensor[df_sensor["device_id"] == device_id].sort_values("datetime")
    df_device = df_device[
        (df_device["datetime"].dt.date >= start_date) &
        (df_device["datetime"].dt.date <= end_date)
    ].copy()

    df_device["date"] = df_device["datetime"].dt.date

    # Prepare weather data
    df_weather_local = df_weather.copy()
    df_weather_local["energy_proxy"] = (
        df_weather_local["zonneschijnduur"]
        * ((df_weather_local["temperatuur"] + df_weather_local["maxtemperatuur"]) / 2)
    )

    # Merge
    df_merged = df_device.merge(
        df_weather_local[["date", "energy_proxy"]],
        on="date",
        how="left"
    )

    datetimes = df_merged["datetime"]
    permittivity_values = df_merged["relative_permittivity"]
    energy_proxy_values = df_merged["energy_proxy"]

    # Plot
    fig, ax1 = plt.subplots()

    ax1.plot(datetimes, permittivity_values)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Relative Permittivity")
    ax1.tick_params(axis='x', rotation=70)

    ax2 = ax1.twinx()
    ax2.bar(
        datetimes,
        energy_proxy_values,
        alpha=0.3,
        width=1.0
    )
    ax2.set_ylabel("Energy Proxy")

    plt.title(f"Relative Permittivity + Energy Proxy (device {device_id})")
    plt.tight_layout()
    plt.show()
def plot_permittivity_with_wind_speed(df_sensor, df_weather, device_id, start_date, end_date):
    # Filter sensor data
    df_device = df_sensor[df_sensor["device_id"] == device_id].sort_values("datetime")
    df_device = df_device[
        (df_device["datetime"].dt.date >= start_date) &
        (df_device["datetime"].dt.date <= end_date)
    ]

    datetimes = df_device["datetime"]
    values = df_device["relative_permittivity"]

    # Filter wind speed data
    df_wind = df_weather[["date", "windsnelheid"]].copy()
    df_wind = df_wind[
        (df_wind["date"] >= start_date) &
        (df_wind["date"] <= end_date)
    ]

    # Plot
    fig, ax1 = plt.subplots()

    ax1.plot(datetimes, values)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Relative Permittivity")
    ax1.tick_params(axis='x', rotation=70)

    ax2 = ax1.twinx()
    ax2.bar(
        df_wind["date"],
        df_wind["windsnelheid"],
        alpha=0.3,
        width=1.0
    )
    ax2.set_ylabel("Wind speed (km/h)")

    plt.title(f"Relative Permittivity + Wind Speed (device {device_id})")
    plt.tight_layout()
    plt.show()


#---------------------
# Uitwerking model
#---------------------
"""
Als het meer dan een beetje (RAIN_EVENT_MM_PER_SENSOR) regent, dan verwacht ik dat de grond vochtiger wordt en de grafiek stijgt in de komende 2 dagen.
"""
# Regen en relative permittivity combineren
df_sensor['date'] = df_sensor['datetime'].dt.date
combi_df = df_sensor.merge(
    df_weather[['date', 'neerslag']],
    on='date',
    how='left'
)
# Sensor-specifieke drempel toevoegen
combi_df['rain_event_mm'] = combi_df['device_id'].map(RAIN_EVENT_MM_PER_SENSOR)
combi_df['major_rain_event'] = combi_df['neerslag'] > combi_df['rain_event_mm']
# NaNs verwijderen die relevant zijn voor deze berekening
combi_df = combi_df.dropna(subset=['relative_permittivity', 'neerslag', 'rain_event_mm'])
# Verandering over twee dagen berekenen
combi_df = combi_df.sort_values(['device_id', 'date'])
combi_df['perm_t_plus_2'] = (
    combi_df.groupby('device_id')['relative_permittivity']
    .shift(-2)
)
combi_df['delta_2d'] = combi_df['perm_t_plus_2'] - combi_df['relative_permittivity']
# Nogmaals NaNs verwijderen, nu ook die van shift(-2)
combi_df = combi_df.dropna(subset=['delta_2d'])
# Alleen regendagen > rain event mm
df_rain = combi_df[combi_df['major_rain_event']]
# Gemiddelde stijging per sensor
avg_rise_2d_per_sensor = (
    df_rain
    .groupby('device_id')['delta_2d']
    .mean()
    .reset_index(name='avg_rise_2d')
)
# Delta per dag per sensor
avg_rise_2d_per_sensor['delta_per_day'] = (
    avg_rise_2d_per_sensor['avg_rise_2d'] / 2
)

"""
Bereken decay slope tussen:
- start: 2 dagen na een regenevent (D2, piek)
- eind: een dag voor het volgende regenevent

Slope = (perm_end - perm_start) / aantal dagen
"""
results = []

for device_id, group in combi_df.groupby('device_id'):
    group = group.sort_values('date').reset_index(drop=True)

    rain_idx = group.index[group['major_rain_event']].tolist()

    for i in range(len(rain_idx) - 1):
        d0_idx = rain_idx[i]
        next_d0_idx = rain_idx[i + 1]
        d2_idx = d0_idx + 2

        if d2_idx >= len(group):
            continue
        if next_d0_idx <= d2_idx:
            continue

        perm_start = group.loc[d2_idx, 'relative_permittivity']
        perm_end = group.loc[next_d0_idx, 'relative_permittivity']

        date_start = group.loc[d2_idx, 'date']
        date_end = group.loc[next_d0_idx, 'date']

        days = (date_end - date_start).days
        if days <= 5:
            continue

        slope = (perm_end - perm_start) / days

        results.append({
            'device_id': device_id,
            'slope': slope,
            'days': days
        })

df_slopes = pd.DataFrame(results)
avg_slope_per_sensor = (
    df_slopes
    .groupby('device_id')
    .agg(
        avg_slope=('slope', 'mean'),
        n_events=('slope', 'count')
    )
    .reset_index()
)

def predict_next_7_days(
    df_sensor,
    df_weather,
    avg_slope_per_sensor,
    avg_rise_2d_per_sensor,
    device_id,
    train_date
):
    train_date = pd.to_datetime(train_date).date()

    rise_row = avg_rise_2d_per_sensor[avg_rise_2d_per_sensor['device_id'] == device_id]
    slope_row = avg_slope_per_sensor[avg_slope_per_sensor['device_id'] == device_id]

    if rise_row.empty or slope_row.empty:
        raise ValueError(f"Geen rise/slope gevonden voor sensor {device_id}")

    average_rise_per_day_after_rain = rise_row['delta_per_day'].iloc[0]
    average_decay_per_day_without_rain = slope_row['avg_slope'].iloc[0]

    df_device = (
        df_sensor[df_sensor['device_id'] == device_id]
        .sort_values('date')
        .copy()
    )

    sensor_rain_threshold_mm = RAIN_EVENT_MM_PER_SENSOR[device_id]
    rain_response_strength = RAIN_RESPONSE_STRENGTH_PER_SENSOR[device_id]
    max_rain_response_multiplier = MAX_RAIN_RESPONSE_MULTIPLIER_PER_SENSOR[device_id]
    rain_memory_decay = RAIN_MEMORY_DECAY_PER_SENSOR[device_id]

    df_weather_local = df_weather[['date', 'neerslag']].copy()
    df_weather_local = df_weather_local.sort_values('date').copy()

    start_row = df_device[df_device['date'] == train_date]
    if start_row.empty:
        raise ValueError(f"Trainingsdatum {train_date} niet gevonden voor sensor {device_id}")

    current_value = start_row['relative_permittivity'].iloc[0]
    preds = []

    window_size = 30

    recent_history = df_device[
        (df_device['date'] >= train_date - timedelta(days=window_size)) &
        (df_device['date'] <= train_date)
        ]['relative_permittivity']

    recent_min = recent_history.min()
    recent_max = recent_history.max()
    recent_range = max(recent_max - recent_min, 0.05)

    for i in range(1, 8):
        pred_date = train_date + timedelta(days=i)

        # --- build exponential rain memory ---
        effective_rain = 0.0

        for lag in range(0, 5):  # shorter memory window
            past_date = pred_date - timedelta(days=lag)

            rain_val = df_weather_local.loc[
                df_weather_local['date'] == past_date, 'neerslag'
            ]

            rain_val = float(rain_val.iloc[0]) if not rain_val.empty else 0.0

            # only count rain ABOVE threshold
            if rain_val >= sensor_rain_threshold_mm:
                excess_rain = rain_val - sensor_rain_threshold_mm

                effective_rain += excess_rain * (rain_memory_decay ** lag)

        # --- threshold + scaling ---
        if effective_rain >= sensor_rain_threshold_mm:
            rain_intensity_ratio = effective_rain / sensor_rain_threshold_mm
            scaled_rain_response = rain_intensity_ratio * rain_response_strength
            capped_rain_response = min(max_rain_response_multiplier, scaled_rain_response)

            predicted_rise = (
                average_rise_per_day_after_rain * capped_rain_response
            )

            normalized_position = (current_value - recent_min) / recent_range

            # dampen if already high
            dampening_factor = 1.0 - normalized_position

            adjusted_rise = predicted_rise * (0.3 + 0.7 * dampening_factor)

            current_value += adjusted_rise
        else:
            normalized_position = (current_value - recent_min) / recent_range

            # decay stronger when high, weaker when low
            decay_multiplier = 0.5 + normalized_position

            current_value += average_decay_per_day_without_rain * decay_multiplier

        preds.append({
            'device_id': device_id,
            'date': pred_date,
            'predicted_permittivity': current_value
        })

    df_pred = pd.DataFrame(preds)

    true_window = df_device[
        (df_device['date'] >= train_date - timedelta(days=30)) &
        (df_device['date'] <= train_date + timedelta(days=7))
    ][['date', 'relative_permittivity']].copy()

    return df_pred, true_window


def plot_prediction_7_days(
    df_sensor,
    df_weather,
    avg_slope_per_sensor,
    avg_rise_2d_per_sensor,
    device_id,
    train_date
):
    df_pred, true_window = predict_next_7_days(
        df_sensor=df_sensor,
        df_weather=df_weather,
        avg_slope_per_sensor=avg_slope_per_sensor,
        avg_rise_2d_per_sensor=avg_rise_2d_per_sensor,
        device_id=device_id,
        train_date=train_date
    )

    train_date = pd.to_datetime(train_date).date()

    hist_window = true_window[true_window['date'] <= train_date].copy()
    future_true = true_window[true_window['date'] > train_date].copy()

    weather_window = df_weather[
        (df_weather['date'] >= train_date - timedelta(days=30)) &
        (df_weather['date'] <= train_date + timedelta(days=7))
    ][['date', 'neerslag', 'temperatuur']].copy()

    fig, ax1 = plt.subplots(figsize=(12, 6))

    # Temperatuur als achtergrondschaduw
    ax_temp = ax1.twinx()
    ax_temp.fill_between(
        weather_window['date'],
        0,
        weather_window['temperatuur'],
        alpha=0.15
    )
    ax_temp.set_ylabel("Temperature (°C)")
    ax_temp.set_ylim(0, weather_window['temperatuur'].max() * 1.2)

    # Regen als barplot
    ax_rain = ax1.twinx()
    ax_rain.spines['right'].set_position(('outward', 60))
    ax_rain.bar(
        weather_window['date'],
        weather_window['neerslag'],
        alpha=0.3,
        width=1.0
    )
    ax_rain.set_ylabel("Rain (mm)")

    # Permittivity lijnen
    ax1.plot(
        hist_window['date'],
        hist_window['relative_permittivity'],
        label='Training data'
    )
    ax1.plot(
        future_true['date'],
        future_true['relative_permittivity'],
        label='True future'
    )
    ax1.plot(
        df_pred['date'],
        df_pred['predicted_permittivity'],
        linestyle='--',
        label='Predicted future'
    )

    ax1.axvline(train_date, linestyle=':', color='grey')
    ax1.set_title(f'7-day prediction for sensor {device_id}')
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Relative Permittivity')
    ax1.tick_params(axis='x', rotation=45)
    ax1.legend()

    plt.tight_layout()
    plt.show()

#---------------------
# Modelevaluatie
#---------------------

def calculate_rmse(df_pred, true_window):
    future_true = true_window[true_window['date'].isin(df_pred['date'])].copy()

    merged = df_pred.merge(
        future_true,
        on='date',
        how='inner'
    )

    if len(merged) < 7:
        return np.nan

    return np.sqrt(
        np.mean(
            (merged['predicted_permittivity'] - merged['relative_permittivity']) ** 2
        )
    )

def evaluate_model_rmse(
    df_sensor,
    df_weather,
    avg_slope_per_sensor,
    avg_rise_2d_per_sensor,
    device_ids,
    min_eval_dates=5
):
    results = []

    for device_id, counter in zip(device_ids, range(len(device_ids))):
        print(f"Evaluating model for device {device_id}...  [{counter+1}/{len(device_ids)}]")
        df_device = (
            df_sensor[df_sensor['device_id'] == device_id]
            .sort_values('date')
            .copy()
        )

        available_dates = sorted(df_device['date'].dropna().unique())
        if len(available_dates) < 40:
            continue

        valid_train_dates = available_dates[:-7]

        rmses = []

        for train_date in valid_train_dates:
            try:
                df_pred, true_window = predict_next_7_days(
                    df_sensor=df_sensor,
                    df_weather=df_weather,
                    avg_slope_per_sensor=avg_slope_per_sensor,
                    avg_rise_2d_per_sensor=avg_rise_2d_per_sensor,
                    device_id=device_id,
                    train_date=train_date
                )

                rmse = calculate_rmse(df_pred, true_window)

                if not np.isnan(rmse):
                    rmses.append(rmse)

            except Exception:
                continue

        if len(rmses) < min_eval_dates:
            continue

        results.append({
            'device_id': device_id,
            'avg_rmse': np.mean(rmses),
            'median_rmse': np.median(rmses),
            'n_eval_dates': len(rmses)
        })

    return pd.DataFrame(results).sort_values('avg_rmse').reset_index(drop=True)

# df_eval = evaluate_model_rmse(
#     df_sensor=df_sensor,
#     df_weather=df_weather,
#     avg_slope_per_sensor=avg_slope_per_sensor,
#     avg_rise_2d_per_sensor=avg_rise_2d_per_sensor,
#     device_ids=USABLE_SENSORS
# )
# print(df_eval)

#---------------------
# Grafieken printen
#---------------------
print(USABLE_SENSORS)
# plot_permittivity_with_rain(df_sensor, df_weather, 361, START_DATE, END_DATE)
# plot_permittivity_with_wind_speed(df_sensor, df_weather, 356, START_DATE, END_DATE)
# plot_permittivity_with_rain(df_sensor, df_weather, 1385,date(2025,7,19), END_DATE)
# plot_permittivity_with_rain_subplots(df_sensor, df_weather, USABLE_SENSORS, date(2025,2,1), date(2026,6,25))
# # plot_permittivity_with_temperature_subplots(df_sensor, df_weather, USABLE_SENSORS, date(2025,2,1), date(2026,5,1))
# plot_permittivity_with_temperature(df_sensor, df_weather, 356, START_DATE, END_DATE)
# plot_permittivity_with_energy_proxy(df_sensor, df_weather, 361, START_DATE, END_DATE)
# Oegstgeest
# plot_permittivity_with_rain(df_sensor, df_weather, 414, datetime(2026, 3, 1).date(), END_DATE)
# plot_permittivity_with_energy_proxy(df_sensor, df_weather, 414, datetime(2026, 3, 1).date(), END_DATE)

# plot_permittivity_with_rain_subplots(df_sensor, df_weather, USABLE_SENSORS, START_DATE, END_DATE)
# for sensorid in USABLE_SENSORS:
#     plot_permittivity_with_rain(df_sensor, df_weather, sensorid, START_DATE, END_DATE)
#     plot_permittivity_with_energy_proxy(df_sensor, df_weather, sensorid, START_DATE, END_DATE)
# Oegstgeest
plot_permittivity_with_rain(df_sensor, df_weather, 414, datetime(2026, 3, 1).date(), END_DATE)
plot_permittivity_with_energy_proxy(df_sensor, df_weather, 414, datetime(2026, 3, 1).date(), END_DATE)

plt.show(block=True)

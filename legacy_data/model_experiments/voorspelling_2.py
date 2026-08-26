import warnings
import pandas as pd
import sqlite3
from catboost import CatBoostRegressor, cv, Pool
from datetime import datetime, date, timedelta
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data_collection" / "sensor_data"

# Get data
conn = sqlite3.connect(DATA_DIR / "database.db")
cursor = conn.cursor()

def sensor_specific_model_2(sensor_id, start_date, end_date, probe_number, show_graphs = False):
    df_sensor = pd.read_sql_query(f"""
    select
        row_id
        ,fsd.device_id
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
    and fsd.device_id = {sensor_id}
    and probe_number = {probe_number}
    """, conn)

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

    # Prepare data for join
    df_sensor['timestamp'] = pd.to_datetime(df_sensor['timestamp'], unit='s')
    df_sensor['date'] = df_sensor['timestamp'].dt.date
    df_sensor  = df_sensor[(df_sensor['date'] >= start_date) & (df_sensor['date'] <= end_date)]
    df_sensor.rename(columns={'temperature': 'ground_temperature'}, inplace=True)

    df_weather = pd.read_csv(DATA_DIR / "voorschoten_weerdata.csv")
    df_weather = df_weather[pd.to_numeric(df_weather['windsnelheid'], errors='coerce').notnull()]
    df_weather['neerslag'] = df_weather['neerslag'].replace(-1, 0) # Since -1 means <0.05mm of rain.
    df_weather[['neerslag', 'temperatuur', 'mintemperatuur', 'maxtemperatuur']] = df_weather[['neerslag', 'temperatuur', 'mintemperatuur', 'maxtemperatuur']].astype(float) / 10.0 # 0.1 graden vs 1
    df_weather['windsnelheid'] = df_weather['windsnelheid'].astype(float) / 10.0 * 3.6 # 0.1 m/s to km/h
    df_weather['zonneschijnduur'] = df_weather['zonneschijnduur'].astype(float) / 10.0 * 60 # 0.1 hours to minutes
    df_weather.columns = df_weather.columns.str.strip()
    df_weather['date'] = pd.to_datetime(df_weather['DATE']).dt.date
    df_weather = df_weather[(df_weather['date'] >= start_date) & (df_weather['date'] <= end_date)]

    # Aggregate sensor data to the daily level to match with the weather data
    # Aggregate 4-hour readings to daily
    df_sensor_daily = df_sensor.groupby('date').agg({
        'relative_permittivity': ['mean', 'min', 'max', 'std'],
        'ground_temperature': 'mean'
    }).reset_index()
    df_sensor_daily.columns = ['date', 'relperv_mean', 'relperv_min', 'relperv_max', 'relperv_std', 'ground_temp_mean']

    print('df_weather:')
    print(df_weather.head())
    print()
    print('df_sensor:')
    print(df_sensor.head())

    df = df_sensor_daily.merge(df_weather, how='left', on='date')
    df = df.dropna(subset = ["relperv_mean"]).reset_index(drop=True)

    print('final df:')
    print(df.head())
    print()

    assert df['relperv_mean'].isna().sum() == 0

    # Calculate SMI
    theta = df['relperv_mean']
    thetaVP = theta.quantile(0.01)
    thetaGC = theta.quantile(0.99)
    print("thetaVP (5th percentile):", thetaVP)
    print("thetaGC (95th percentile):", thetaGC)
    df['SMI'] = (theta - thetaVP) / (thetaGC - thetaVP)
    df['SMI'] = df['SMI'].clip(0, 1)
    print(df['SMI'].describe())

    # --- Plot SMI over time with rainfall overlay ---
    if show_graphs:
        fig, ax1 = plt.subplots(figsize=(14, 6))
        # Main SMI line (0–1)
        ax1.plot(df['date'], df['SMI'], label='SMI', linewidth=2)
        ax1.set_xlabel('Datum')
        ax1.set_ylabel('SMI (0–1)')
        ax1.set_ylim(0, 1)
        ax1.grid(True, linestyle='--', alpha=0.4)
        # Fix x-axis start and end
        ax1.set_xlim(pd.to_datetime(start_date), pd.to_datetime(end_date))
        # Secondary axis for rainfall (mm)
        ax2 = ax1.twinx()
        ax2.bar(df['date'], df['neerslag'], alpha=0.3, label='Regen (mm)')
        ax2.set_ylabel('Regen (mm)')
        # Combine legends from both axes
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
        plt.title('Dagelijkse bodemvochtigheidsindex (SMI) met neerslag')
        plt.tight_layout()
        plt.show()

    # Make lag variables
    df = df.sort_values('date').reset_index(drop=True)
    df[f'SMI_lag_1'] = df['SMI'].shift(1) # This adds soil "memory" in the sense that yesterday's soil moisture explains most of today's
    df['SMI_lag_2'] = df['SMI'].shift(2)
    df['SMI_lag_3'] = df['SMI'].shift(3)
    df['SMI_roll_3'] = df['SMI'].shift(1).rolling(3).mean()   # 3-day smoothing
    df['SMI_roll_7'] = df['SMI'].shift(1).rolling(7).mean()   # week smoothing
    df['SMI_dry_rate'] = df['SMI'].diff()    # today's SMI - yesterday's SMI
    df['SMI_dry_rate'] = df['SMI_dry_rate'].shift(1)  # only expose history
    df['rain_lag_1'] = df['neerslag'].shift(1)
    df['rain_lag_2'] = df['neerslag'].shift(2)
    df['rain_lag_3'] = df['neerslag'].shift(3)
    df['rain_roll_2'] = df['neerslag'].shift(1).rolling(2).sum()
    df['rain_roll_3'] = df['neerslag'].shift(1).rolling(3).sum()
    df['rain_roll_5'] = df['neerslag'].shift(1).rolling(5).sum()
    df['rain_roll_7'] = df['neerslag'].shift(1).rolling(7).sum()
    df['no_rain_days'] = (df['neerslag'] == 0).astype(int).groupby(df['neerslag'].ne(0).cumsum()).cumsum()
    df['rain_effect'] = df['neerslag'].shift(1) * (1 - df['SMI_lag_1'])
    df = df.dropna(subset = ["relperv_mean"]).reset_index(drop=True)
    lag_features = [
        'SMI_lag_1', 'SMI_lag_2', 'SMI_lag_3',
        'SMI_roll_3','SMI_roll_7','SMI_dry_rate',
        'rain_lag_1','rain_lag_2','rain_lag_3',
        'rain_roll_2','rain_roll_3','rain_roll_5','rain_roll_7',
        'no_rain_days','rain_effect'
    ]

    # 1) Rename weather columns so they match forecast schema
    df = df.rename(columns={
        'windrichting': 'wind_dir',
        'windsnelheid': 'wind_speed',
        'temperatuur': 'temp_avg',
        'mintemperatuur': 'temp_min',
        'maxtemperatuur': 'temp_max',
        'zonneschijnduur': 'sunshine_min',
        'neerslag': 'rain_mm'
    })

    weather_base_cols = ['wind_dir', 'wind_speed',
                         'temp_avg', 'temp_min', 'temp_max',
                         'sunshine_min', 'rain_mm']

    # 2) Build wide multi-horizon targets + weather-for-horizon features
    H = 10  # forecast horizon (days)
    target_cols = []
    horizon_weather_cols = []

    for k in range(1, H + 1):
        # Targets: SMI at t+k
        tgt_col = f'SMI_t+{k}'
        df[tgt_col] = df['SMI'].shift(-k)
        target_cols.append(tgt_col)

        # Weather at t+k (forward shift)
        for col in weather_base_cols:
            hcol = f'{col}_h{k}'
            df[hcol] = df[col].shift(-k)
            horizon_weather_cols.append(hcol)

    # 3) Drop rows that don't have full future horizons
    df_model = df.dropna(subset=target_cols + horizon_weather_cols).reset_index(drop=True)
    df_model = df_model.sort_values('date').reset_index(drop=True)

    # 4) Final feature set for CatBoost (you can tweak this list later)
    feature_cols = (
            ['SMI'] +  # current SMI
            lag_features +  # your soil/precip lags & rolls
            weather_base_cols +  # today's weather
            horizon_weather_cols  # future weather for each horizon
    )

    X = df_model[feature_cols].copy()
    Y = df_model[target_cols].copy()

    print("X shape:", X.shape)
    print("Y shape:", Y.shape)
    print("Feature columns:", len(feature_cols))
    print("Target columns:", target_cols)

    # --- Prepare forecast table ---
    base_date = date(2025, 11, 24)  # "today" for the forecast run
    df_weather_forecast['forecast_for_date'] = pd.to_datetime(
        df_weather_forecast['forecast_for_date']
    ).dt.date
    df_weather_forecast = df_weather_forecast[df_weather_forecast['forecast_date'] == '2025-11-25']
    # Rename to match weather_base_cols
    df_weather_forecast = df_weather_forecast.rename(columns={
        'wind_direction_deg': 'wind_dir',
        'wind_kmh':           'wind_speed',
        'avg_temp':           'temp_avg',
        'min_temp':           'temp_min',
        'max_temp':           'temp_max',
        'sunshine_minutes':   'sunshine_min',
        'precipitation_mm':   'rain_mm'
    })

    # --- Take the row for base_date from df_model as the soil "state" ---
    row_today = df_model.loc[df_model['date'] == base_date]
    if row_today.empty:
        warnings.warn(f'No data found for base date for sensor {sensor_id}!')
        return None
    row_today = row_today.iloc[0]

    # Start X_forecast with soil + today's weather
    x_forecast = {}
    for col in ['SMI'] + lag_features + weather_base_cols:
        x_forecast[col] = row_today[col]

    # Initialize future-weather columns with NaN
    for k in range(1, H + 1):
        for col in weather_base_cols:
            x_forecast[f'{col}_h{k}'] = float('nan')

    # Fill future-weather columns from forecast table
    for _, r in df_weather_forecast.iterrows():
        k = (r['forecast_for_date'] - base_date).days   # horizon
        if 1 <= k <= H:
            for col in weather_base_cols:
                x_forecast[f'{col}_h{k}'] = r[col]

    # One-row dataframe with the same feature order as training
    X_forecast = pd.DataFrame([x_forecast], columns=feature_cols)

    # --- CatBoost multi-target model ---
    train_mask = df_model['date'] < base_date
    valid_mask = df_model['date'] >= base_date

    X_train, Y_train = X[train_mask], Y[train_mask]
    X_valid, Y_valid = X[valid_mask], Y[valid_mask]

    train_pool = Pool(
        X_train,
        Y_train
    )
    valid_pool = Pool(
        X_valid,
        Y_valid
    )

    model = CatBoostRegressor(
        loss_function='MultiRMSE',
        depth=1,
        learning_rate=0.05,
        iterations=2000,
        random_seed=42,
        od_type='Iter',          # early stopping
        od_wait=100
    )

    model.fit(
        train_pool,
        eval_set=valid_pool,
        verbose=100
    )

    # Get feature importance
    feature_importance = model.get_feature_importance(train_pool)
    feature_names = feature_cols
    fi_df = pd.DataFrame({
        'feature': feature_names,
        'importance': feature_importance
    }).sort_values('importance', ascending=False)
    print('\nFeature importance:')
    print(fi_df)

    # Predict 10-day SMI
    Y_forecast = model.predict(X_forecast)   # shape: (1, 10)
    print("Predicted SMI for days 1..10:", Y_forecast[0])

    dates_forecast = [base_date + timedelta(days=k) for k in range(1, H + 1)]

    # Get true SMI from your original df (not df_model, to be safe)
    df_smi = df[['date', 'SMI']].copy()

    smi_true = []
    for d in dates_forecast:
        m = df_smi.loc[df_smi['date'] == d, 'SMI']
        smi_true.append(m.iloc[0] if not m.empty else np.nan)

    smi_pred = Y_forecast[0]  # shape (10,)

    df_eval = pd.DataFrame({
        'date': dates_forecast,
        'SMI_true': smi_true,
        'SMI_pred': smi_pred
    })

    print(df_eval)

    # --- Simple error metric ---
    mae = np.nanmean(np.abs(df_eval['SMI_true'] - df_eval['SMI_pred']))
    print("MAE over 10 days:", mae)

    # --- Plot true vs predicted ---
    if show_graphs:
        plt.figure(figsize=(10, 5))
        plt.plot(df_eval['date'], df_eval['SMI_true'], marker='o', label='Werkelijke SMI')
        plt.plot(df_eval['date'], df_eval['SMI_pred'], marker='o', linestyle='--', label='Voorspelde SMI')
        plt.ylim(0, 1)
        plt.xlabel('Datum')
        plt.ylabel('SMI (0–1)')
        plt.title('10-daagse SMI-voorspelling versus werkelijkheid')
        plt.grid(True, linestyle='--', alpha=0.4)
        plt.legend()
        plt.tight_layout()
        plt.show()

    return mae

start_date = datetime(2025, 7, 20).date()
end_date   = datetime(2025, 12, 8).date()
usable_sensor_ids = [356, 361, 369, 395, 416, 1385, 1390, 1391, 1392, 1432]

# mae_list = []
# for usable_sensor_id in usable_sensor_ids:
#     mae_list.append((usable_sensor_id, sensor_specific_model_2(usable_sensor_id, start_date, end_date, probe_number=2, show_graphs=False)))
#
# print()
# print('MAE list:')
# for mae in mae_list:
#     print(mae[0], mae[1])

print(f'MAE for sensor 1390: {sensor_specific_model_2(1390, start_date, end_date, probe_number=1, show_graphs=True)}')

# 414 heeft geen data voor 2025-11-24?
























# --------------------------------------------
# Plot all sensors' SMI and rainfall together
# --------------------------------------------

# 1) Get daily SMI per sensor for the same timeframe
sensor_ids_str = ",".join(str(s) for s in usable_sensor_ids)

df_all = pd.read_sql_query(f"""
    SELECT
        fsd.device_id,
        fsd.timestamp,
        fsd.relative_permittivity
    FROM FactSensorData fsd
    JOIN DimSensor ds
        ON fsd.device_id = ds.device_id
    WHERE ds.is_active = 1
      AND fsd.probe_number = 1
      AND fsd.device_id IN ({sensor_ids_str})
""", conn)

df_all['timestamp'] = pd.to_datetime(df_all['timestamp'], unit='s')
df_all['date'] = df_all['timestamp'].dt.date
df_all = df_all[(df_all['date'] >= start_date) & (df_all['date'] <= end_date)]

# Aggregate 4-hour readings to daily per sensor
df_all_daily = (
    df_all.groupby(['device_id', 'date'])['relative_permittivity']
          .mean()
          .reset_index(name='relperv_mean')
)

# Compute SMI per sensor (5th–95th percentile scaling)
def compute_smi(group):
    theta = group['relperv_mean']
    thetaVP = theta.quantile(0.05)
    thetaGC = theta.quantile(0.95)
    group['SMI'] = ((theta - thetaVP) / (thetaGC - thetaVP)).clip(0, 1)
    return group

df_all_daily = df_all_daily.groupby('device_id', group_keys=False).apply(compute_smi)

# Pivot to wide format: index=date, columns=sensor_id, values=SMI
df_smi_pivot = df_all_daily.pivot(index='date', columns='device_id', values='SMI')
df_smi_pivot = df_smi_pivot.sort_index()

# 2) Load rainfall for the same dates
df_weather_plot = pd.read_csv(DATA_DIR / "voorschoten_weerdata.csv")
df_weather_plot = df_weather_plot[pd.to_numeric(df_weather_plot['windsnelheid'],
                                                errors='coerce').notnull()]

df_weather_plot['neerslag'] = df_weather_plot['neerslag'].replace(-1, 0)
df_weather_plot[['neerslag', 'temperatuur', 'mintemperatuur', 'maxtemperatuur']] = \
    df_weather_plot[['neerslag', 'temperatuur', 'mintemperatuur', 'maxtemperatuur']].astype(float) / 10.0
df_weather_plot['windsnelheid'] = df_weather_plot['windsnelheid'].astype(float) / 10.0 * 3.6
df_weather_plot['zonneschijnduur'] = df_weather_plot['zonneschijnduur'].astype(float) / 10.0 * 60
df_weather_plot.columns = df_weather_plot.columns.str.strip()
df_weather_plot['date'] = pd.to_datetime(df_weather_plot['DATE']).dt.date
df_weather_plot = df_weather_plot[(df_weather_plot['date'] >= start_date) &
                                  (df_weather_plot['date'] <= end_date)]

# 3) Plot all sensors + rainfall
plt.figure(figsize=(14, 6))
ax1 = plt.gca()

# Plot each sensor's SMI line
for sensor_id in usable_sensor_ids:
    if sensor_id in df_smi_pivot.columns:
        ax1.plot(
            df_smi_pivot.index,
            df_smi_pivot[sensor_id],
            label=f'Sensor {sensor_id}'
        )

ax1.set_xlabel('Datum')
ax1.set_ylabel('SMI (0–1)')
ax1.set_ylim(0, 1)
ax1.set_xlim(pd.to_datetime(start_date), pd.to_datetime(end_date))
ax1.grid(True, linestyle='--', alpha=0.4)

# Secondary axis for rainfall
ax2 = ax1.twinx()
ax2.bar(
    df_weather_plot['date'],
    df_weather_plot['neerslag'],
    alpha=0.25,
    label='Regen (mm)'
)
ax2.set_ylabel('Regen (mm)')

# Combined legend
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', ncol=2)

plt.title('SMI per sensor met regenval')
plt.tight_layout()
plt.show()

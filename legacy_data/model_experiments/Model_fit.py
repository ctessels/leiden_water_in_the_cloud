import pandas as pd
import sqlite3
from catboost import CatBoostRegressor, cv, Pool
from datetime import datetime
from sklearn.metrics import r2_score
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data_collection" / "sensor_data"

# Get data
conn = sqlite3.connect(DATA_DIR / "database.db")
cursor = conn.cursor()

# cursor.execute('''
# select
#     row_id
#     ,fsd.device_id
#     ,device_name
#     ,location_name
#     ,mp_depth_1
#     ,mp_depth_2
#     ,mp_depth_3
#     ,probe_number
#     ,timestamp
#     ,temperature
#     ,relative_permittivity
#     ,is_active
# from FactSensorData fsd
# left join DimSensor ds
#     on fsd.device_id = ds.device_id
# ''')
#
# cursor.execute('''
# select
#     forecast_date
#     ,forecast_for_date
#     ,avg_temp
#     ,min_temp
#     ,max_temp
#     ,wind_direction_deg
#     ,wind_kmh
#     ,precipitation_mm
#     ,precipitation_perc
#     ,sunshine_minutes
#     ,sunshine_pct
#     ,condition
# from TenDayForecast
# where is_actual = 1
# ''')

def sensor_specific_model(sensor_id, start_date, end_date):
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
    and probe_number = 1
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
    df_weather.columns = df_weather.columns.str.strip()
    df_weather['date'] = pd.to_datetime(df_weather['DATE']).dt.date
    df_weather = df_weather[(df_weather['date'] >= start_date) & (df_weather['date'] <= end_date)]

    df_weather_forecast = df_weather_forecast[df_weather_forecast['forecast_date'] == '2025-11-25']

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
    thetaVP = theta.quantile(0.05)
    thetaGC = theta.quantile(0.95)
    print("thetaVP (5th percentile):", thetaVP)
    print("thetaGC (95th percentile):", thetaGC)
    df['SMI'] = (theta - thetaVP) / (thetaGC - thetaVP)
    df['SMI'] = df['SMI'].clip(0, 1)
    print(df['SMI'].describe())

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

    # Make season variables
    df['doy'] = pd.to_datetime(df['date']).dt.dayofyear
    df['month'] = pd.to_datetime(df['date']).dt.month
    df['doy_sin'] = np.sin(2 * np.pi * df['doy'] / 365)
    df['doy_cos'] = np.cos(2 * np.pi * df['doy'] / 365)
    df = df.dropna(subset = ["relperv_mean"]).reset_index(drop=True)
    seasonal_features = ['month', 'doy_sin', 'doy_cos']

    # Choose variables
    print('columns:')
    print(df.columns)
    print()
    x_variables = df[['ground_temp_mean', 'temperatuur', 'mintemperatuur', 'maxtemperatuur', 'zonneschijnduur', 'neerslag', 'bewolking'] + lag_features + seasonal_features]
    y_variables = df['SMI']

    print('x_variables')
    print(x_variables)
    print()

    # Train model
    print('Starting model training')

    pool = Pool(x_variables, y_variables)

    cv_results = cv(
        pool=pool,
        params={
            "loss_function": "RMSE",
            "iterations": 500,
            "depth": 4,
            "learning_rate": 0.05,
            "verbose": False
        },
        fold_count=5,
        shuffle=False,          # keeps time order
        early_stopping_rounds=50
    )

    print("CV complete")
    print("Best test RMSE:", cv_results["test-RMSE-mean"].min())
    print("Corresponding iteration:", cv_results["test-RMSE-mean"].idxmin())


    model = CatBoostRegressor(
        iterations=500,
        depth=4,
        learning_rate=0.05,
        verbose=False,
    )

    model.fit(x_variables, y_variables)

    feature_importance = model.get_feature_importance()
    feature_names = x_variables.columns
    print(f'Training complete')
    print('Feature importance:')
    for name, importance in zip(feature_names, feature_importance):
        print(f'feature: {name.strip()}, importance: {importance:.2f}')

    # Validate model
    split_idx = int(len(df) * 0.8)

    X_train = x_variables.iloc[:split_idx]
    X_test  = x_variables.iloc[split_idx:]
    y_train = y_variables.iloc[:split_idx]
    y_test  = y_variables.iloc[split_idx:]

    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    residuals = y_test - y_pred

    print("R²:", r2_score(y_test, y_pred))
    print("Mean residual:", residuals.mean())
    print("Std residual:", residuals.std())

    sigma = residuals.std(ddof=1)
    z = 1.96 # Assuming residuals are normal, which they are most likely NOT.

    # Generate predictions for the same days that exist in your dataset
    df['SMI_pred'] = model.predict(x_variables)

    # Generate confidence bounds for those predictions
    df['SMI_lower'] = df['SMI_pred'] - z * sigma
    df['SMI_upper'] = df['SMI_pred'] + z * sigma
    df['SMI_lower'] = df['SMI_lower'].clip(0, 1)
    df['SMI_upper'] = df['SMI_upper'].clip(0, 1)

    # Plot actual vs predicted over time
    fig, ax1 = plt.subplots(figsize=(12,4))

    # SMI lines
    ax1.plot(df['date'], df['SMI'], label="Actual SMI")
    ax1.plot(df['date'], df['SMI_pred'], label="Predicted SMI")
    # Confidence band
    ax1.fill_between(
        df['date'],
        df['SMI_lower'],
        df['SMI_upper'],
        alpha=0.2,
        label="95% prediction band"
    )
    ax1.set_xlabel("Date")
    ax1.set_ylabel("SMI")
    ax1.set_title("Daily SMI – Actual vs Predicted with Rain")
    ax1.set_ylim(0, 1.05)

    # Rain as bars on second axis
    ax2 = ax1.twinx()
    ax2.bar(df['date'], df['neerslag'], alpha=0.3, width=1, label="Rain (mm)")
    ax2.set_ylabel("Rain (mm)")

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    plt.tight_layout()
    plt.show()

    # Residual plot (error over time)
    plt.figure(figsize=(10,3))
    plt.plot(df['date'], df['SMI'] - df['SMI_pred'], label="Residual (actual - pred)")
    plt.title("Residuals over time")
    plt.xlabel("Date")
    plt.ylabel("SMI error")
    plt.legend()
    plt.show()


start_date = datetime(2025, 1, 1).date()
end_date   = datetime(2025, 11, 30).date()
usable_sensor_ids = [356, 361, 369, 395, 397, 414, 416, 1385, 1390, 1391, 1392, 1432]
for usable_sensor_id in usable_sensor_ids:
    sensor_specific_model(usable_sensor_id, start_date, end_date)

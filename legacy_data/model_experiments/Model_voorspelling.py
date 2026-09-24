import sqlite3
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool
from sklearn.metrics import r2_score, mean_squared_error
from pathlib import Path

# TO DO
# Integreer weersverwachting
# Voorspel
# Maak mooie grafieken
# Schrijf rapport
# OPTIMALISEREN EN OPRUIMEN KOMT LATER WEL

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data_collection" / "sensor_data"
DB_PATH = DATA_DIR / "database.db"
WEATHER_CSV = DATA_DIR / "voorschoten_weerdata.csv"

SENSOR_ID_LIST = [1390] #356
TARGET_PROBE = 1  # depth selection
TRAIN_DAYS = 90  # last N days used for training
FORECAST_HORIZON = 10  # max days ahead to simulate

# ----------------------------------------------------------------------
# 1. LOAD SENSOR + WEATHER DATA
# ----------------------------------------------------------------------
conn = sqlite3.connect(DB_PATH)

# Pull ALL history for chosen probe_number (so SMI quantiles are robust)
train_date = (datetime.today() - timedelta(days=TRAIN_DAYS)).strftime("%Y-%m-%d")
sensor_id_string = ','.join(map(str, SENSOR_ID_LIST))
df_sensor = pd.read_sql_query(f"""
select
    fsd.row_id,
    fsd.device_id,
    ds.device_name,
    ds.location_name,
    fsd.probe_number,
    fsd.timestamp,
    fsd.temperature as ground_temperature,
    fsd.relative_permittivity,
    ds.is_active,
    ds.mp_depth_1,
    ds.mp_depth_2,
    ds.mp_depth_3
from FactSensorData fsd
left join DimSensor ds
    on fsd.device_id = ds.device_id
where ds.is_active = 1
  and fsd.probe_number = {TARGET_PROBE}
  and ds.last_placement_date < '{train_date}'
  and ds.last_placement_date is not null
  and fsd.device_id in ({sensor_id_string})
""", conn)

conn.close()

# Basic time handling
df_sensor["timestamp"] = pd.to_datetime(df_sensor["timestamp"], unit="s")
df_sensor["date"] = df_sensor["timestamp"].dt.date

# Unique sensor identifier (device + probe)
df_sensor["device_id"] = df_sensor["device_id"].astype(str) + "_p" + df_sensor["probe_number"].astype(str)

# Load daily weather data (already used in your code)
df_weather = pd.read_csv(WEATHER_CSV)
df_weather.columns = df_weather.columns.str.strip()
df_weather["date"] = pd.to_datetime(df_weather["DATE"]).dt.date

# Keep only relevant columns from weather
weather_cols = [
    "date",
    "temperatuur",
    "mintemperatuur",
    "maxtemperatuur",
    "zonneschijnduur",
    "neerslag",
    "bewolking",
]
df_weather = df_weather[weather_cols]

# ----------------------------------------------------------------------
# 2. COMPUTE SMI PER SENSOR (ACROSS FULL HISTORY)
# ----------------------------------------------------------------------
# θ = relative_permittivity here
df_sensor["theta"] = df_sensor["relative_permittivity"]

# Compute 5th and 95th percentiles per sensor (using full history)
theta_q = df_sensor.groupby("device_id")["theta"].quantile([0.05, 0.95]).unstack()
theta_q.columns = ["theta_vp", "theta_gc"]

df_sensor = df_sensor.merge(theta_q, on="device_id", how="left")

# SMI = (θ - θVP) / (θGC - θVP)
df_sensor["SMI"] = (df_sensor["theta"] - df_sensor["theta_vp"]) / (df_sensor["theta_gc"] - df_sensor["theta_vp"])
df_sensor["SMI"] = df_sensor["SMI"].clip(0, 1)

# ----------------------------------------------------------------------
# 3. AGGREGATE TO DAILY LEVEL (PER SENSOR)
# ----------------------------------------------------------------------
df_daily = (
    df_sensor
    .groupby(["device_id", "date"])
    .agg(
        SMI=("SMI", "mean"),
        ground_temp_mean=("ground_temperature", "mean"),
    )
    .reset_index()
)

# Merge weather on date
df_daily = df_daily.merge(df_weather, how="left", on="date")

# Drop days without weather
df_daily = df_daily.dropna(subset=["temperatuur", "neerslag"])

# ----------------------------------------------------------------------
# 4. LIMIT TO LAST N DAYS (TRAIN WINDOW)
# ----------------------------------------------------------------------
last_date = df_daily["date"].max()
train_start_date = last_date - timedelta(days=TRAIN_DAYS)

df_daily = df_daily[df_daily["date"] >= train_start_date].copy()
df_daily = df_daily.sort_values(["device_id", "date"]).reset_index(drop=True)


# ----------------------------------------------------------------------
# 5. FEATURE ENGINEERING: LAGS, RAIN DYNAMICS, ΔSMI
# ----------------------------------------------------------------------
# Lags and rolling features per sensor
def add_features_per_sensor(group: pd.DataFrame) -> pd.DataFrame:
    group = group.sort_values("date").reset_index(drop=True)

    # SMI lags (soil memory)
    for lag in [1, 2, 3, 7]:
        group[f"SMI_lag_{lag}"] = group["SMI"].shift(lag)

    # Rolling SMI (trend / background state)
    group["SMI_roll_3"] = group["SMI"].shift(1).rolling(3).mean()
    group["SMI_roll_7"] = group["SMI"].shift(1).rolling(7).mean()

    # SMI change (yesterday's drying/wetting rate)
    group["SMI_dry_rate"] = group["SMI"].diff().shift(1)

    # Rain lags and rolling windows (forecast driver)
    group["rain_lag_1"] = group["neerslag"].shift(1)
    group["rain_lag_2"] = group["neerslag"].shift(2)
    group["rain_lag_3"] = group["neerslag"].shift(3)

    for w in [2, 3, 5, 7]:
        group[f"rain_roll_{w}"] = group["neerslag"].shift(1).rolling(w).sum()

    # Days since last rain
    no_rain_flag = (group["neerslag"] == 0).astype(int)
    rain_event_groups = group["neerslag"].ne(0).cumsum()
    group["no_rain_days"] = no_rain_flag.groupby(rain_event_groups).cumsum()

    # Interaction: rain effectiveness depends on dryness
    group["rain_effect"] = group["neerslag"].shift(1) * (1 - group["SMI"].shift(1))

    # Target: ΔSMI = SMI(t) - SMI(t-1)
    group["SMI_lag_1"] = group["SMI"].shift(1)  # ensure it exists for target calculation
    group["delta_SMI"] = group["SMI"] - group["SMI_lag_1"]

    return group

df_features = df_daily.groupby("device_id", group_keys=False).apply(add_features_per_sensor, include_groups=True)

# Drop rows with insufficient history
df_features = df_features.dropna().reset_index(drop=True)

# ----------------------------------------------------------------------
# 6. BUILD TRAINING MATRICES
# ----------------------------------------------------------------------
# CatBoost categorical features
df_features["device_id_cat"] = df_features["device_id"].astype(str)

feature_cols = [
    # state
    "SMI_lag_1",
    "SMI_lag_2",
    "SMI_lag_3",
    "SMI_lag_7",
    "SMI_roll_3",
    "SMI_roll_7",
    "SMI_dry_rate",
    # weather
    "ground_temp_mean",
    "temperatuur",
    "mintemperatuur",
    "maxtemperatuur",
    "zonneschijnduur",
    "neerslag",
    "bewolking",
    # rain dynamics
    "rain_lag_1",
    "rain_lag_2",
    "rain_lag_3",
    "rain_roll_2",
    "rain_roll_3",
    "rain_roll_5",
    "rain_roll_7",
    "no_rain_days",
    "rain_effect",
]

X = df_features[feature_cols].copy()
y = df_features["delta_SMI"].copy()

# Time-based split: first 80% of rows as train, last 20% as validation
split_idx = int(len(df_features) * 0.8)
X_train, X_valid = X.iloc[:split_idx], X.iloc[split_idx:]
y_train, y_valid = y.iloc[:split_idx], y.iloc[split_idx:]

train_pool = Pool(X_train, y_train)
valid_pool = Pool(X_valid, y_valid)

# ----------------------------------------------------------------------
# 7. TRAIN HYBRID SIMULATOR (ΔSMI MODEL)
# ----------------------------------------------------------------------
model = CatBoostRegressor(
    loss_function="RMSE",
    iterations=400,  # 3 months of data, so no need for 1000+
    depth=4,
    learning_rate=0.05,
    verbose=False,
)

print("Starting model training...")
model.fit(train_pool, eval_set=valid_pool, use_best_model=True)
print("Training complete.")

# Validation metrics
y_valid_pred_delta = model.predict(X_valid)
rmse = np.sqrt(mean_squared_error(y_valid, y_valid_pred_delta))
print(f"ΔSMI RMSE (validation): {rmse:.4f}")

# Quick check: implied SMI accuracy on validation set
df_valid = df_features.iloc[split_idx:].copy()
df_valid["delta_SMI_pred"] = y_valid_pred_delta
df_valid["SMI_simulated"] = (df_valid["SMI_lag_1"] + df_valid["delta_SMI_pred"]).clip(0, 1)

r2_smi = r2_score(df_valid["SMI"], df_valid["SMI_simulated"])
rmse_smi = np.sqrt(mean_squared_error(df_valid["SMI"], df_valid["SMI_simulated"]))
print(f"SMI R² (validation): {r2_smi:.4f}")
print(f"SMI RMSE (validation): {rmse_smi:.4f}")

# Feature importance
print("\nFeature importance:")
for name, imp in zip(feature_cols, model.get_feature_importance(train_pool)):
    print(f"{name:15s}: {imp:.2f}")


# ----------------------------------------------------------------------
# 8. FORECASTING FUNCTION FOR ONE SENSOR
# ----------------------------------------------------------------------
def forecast_smi_for_sensor(
        model: CatBoostRegressor,
        history_df: pd.DataFrame,
        weather_forecast_df: pd.DataFrame,
        device_id: str,
        horizon: int = FORECAST_HORIZON,
):
    """
    history_df: df_feat-like rows for this device_id (must contain last known SMI, lags, rain vars).
    weather_forecast_df: dataframe with future dates + weather columns:
        ['date','temperatuur','mintemperatuur','maxtemperatuur',
         'zonneschijnduur','neerslag','bewolking']
    """
    # Ensure sorted
    history_df = history_df.sort_values("date").reset_index(drop=True)
    last_row = history_df.iloc[-1].copy()

    smi_current = float(last_row["SMI"])
    rain_history = list(history_df["neerslag"].values[-7:])  # up to last 7 days
    no_rain_days = int(last_row["no_rain_days"])

    forecasts = []

    device_id_cat = device_id  # same encoding as in training

    for _, row in weather_forecast_df.sort_values("date").iloc[:horizon].iterrows():
        date_f = row["date"]
        temp = row["temperatuur"]
        temp_min = row["mintemperatuur"]
        temp_max = row["maxtemperatuur"]
        sun = row["zonneschijnduur"]
        rain = row["neerslag"]
        cloud = row["bewolking"]

        # Update rain history
        rain_history.append(rain)
        if len(rain_history) > 7:
            rain_history = rain_history[-7:]

        # Compute rain lags & rolls based on forecast history
        rain_lag_1 = rain_history[-2] if len(rain_history) >= 2 else 0.0
        rain_lag_2 = rain_history[-3] if len(rain_history) >= 3 else 0.0
        rain_lag_3 = rain_history[-4] if len(rain_history) >= 4 else 0.0

        rain_roll_2 = sum(rain_history[-2:]) if len(rain_history) >= 2 else sum(rain_history)
        rain_roll_3 = sum(rain_history[-3:]) if len(rain_history) >= 3 else sum(rain_history)
        rain_roll_5 = sum(rain_history[-5:]) if len(rain_history) >= 5 else sum(rain_history)
        rain_roll_7 = sum(rain_history[-7:]) if len(rain_history) >= 7 else sum(rain_history)

        # Update no_rain_days
        if rain == 0:
            no_rain_days += 1
        else:
            no_rain_days = 0

        # Seasonality for forecast date
        doy = pd.to_datetime(date_f).timetuple().tm_yday
        doy_sin = np.sin(2 * np.pi * doy / 365)
        doy_cos = np.cos(2 * np.pi * doy / 365)
        month = pd.to_datetime(date_f).month

        # SMI lags: we only know the simulated smi_current
        SMI_lag_1 = smi_current
        # For SMI_lag_2,3,7, we approximate by using last known values from history if needed.
        # Simpler version: just reuse SMI_lag_1 as a proxy (or you can maintain a list of past simulated SMI).
        SMI_lag_2 = smi_current
        SMI_lag_3 = smi_current
        SMI_lag_7 = smi_current

        SMI_roll_3 = smi_current  # rough approximation
        SMI_roll_7 = smi_current

        SMI_dry_rate = 0.0  # unknown in forecast, set neutral

        rain_effect = rain_lag_1 * (1 - SMI_lag_1)

        # Build feature row in same order as training
        feat_row = pd.DataFrame([{
            "SMI_lag_1": SMI_lag_1,
            "SMI_lag_2": SMI_lag_2,
            "SMI_lag_3": SMI_lag_3,
            "SMI_lag_7": SMI_lag_7,
            "SMI_roll_3": SMI_roll_3,
            "SMI_roll_7": SMI_roll_7,
            "SMI_dry_rate": SMI_dry_rate,
            "ground_temp_mean": temp,  # no separate ground forecast: approximate with air temp
            "temperatuur": temp,
            "mintemperatuur": temp_min,
            "maxtemperatuur": temp_max,
            "zonneschijnduur": sun,
            "neerslag": rain,
            "bewolking": cloud,
            "rain_lag_1": rain_lag_1,
            "rain_lag_2": rain_lag_2,
            "rain_lag_3": rain_lag_3,
            "rain_roll_2": rain_roll_2,
            "rain_roll_3": rain_roll_3,
            "rain_roll_5": rain_roll_5,
            "rain_roll_7": rain_roll_7,
            "no_rain_days": no_rain_days,
            "rain_effect": rain_effect,
            "doy_sin": doy_sin,
            "doy_cos": doy_cos,
            "month": month,
            "device_id_cat": device_id_cat,
        }])

        # Predict ΔSMI and update SMI
        delta_smi_pred = model.predict(feat_row)[0]
        smi_current = float(np.clip(smi_current + delta_smi_pred, 0.0, 1.0))

        forecasts.append({
            "date": date_f,
            "SMI_forecast": smi_current,
            "delta_SMI_pred": delta_smi_pred,
            "rain": rain,
        })

    return pd.DataFrame(forecasts)

# Plot that shit yo
plt.figure(figsize=(12,4))
plt.plot(df_valid["date"], df_valid["SMI"], label="Actual SMI")
plt.plot(df_valid["date"], df_valid["SMI_simulated"], label="Simulated SMI (model)", alpha=0.8)
plt.title("Actual vs Simulated SMI (Validation Period)")
plt.xlabel("Date")
plt.ylabel("SMI")
plt.legend()
plt.tight_layout()
plt.show()

plt.figure(figsize=(12,3))
plt.plot(df_valid["date"], df_valid["delta_SMI"], label="Actual ΔSMI")
plt.plot(df_valid["date"], df_valid["delta_SMI_pred"], label="Predicted ΔSMI", alpha=0.8)
plt.title("Predicted vs Actual ΔSMI")
plt.xlabel("Date")
plt.ylabel("ΔSMI")
plt.legend()
plt.tight_layout()
plt.show()

fig, ax1 = plt.subplots(figsize=(12,4))
ax1.plot(df_valid["date"], df_valid["SMI"], label="Actual SMI")
ax1.plot(df_valid["date"], df_valid["SMI_simulated"], label="Simulated SMI", alpha=0.8)
ax1.set_ylabel("SMI")
ax2 = ax1.twinx()
ax2.bar(df_valid["date"], df_valid["neerslag"], width=1.0, alpha=0.3, label="Rain (mm)")
ax2.set_ylabel("Rain (mm)")
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
plt.title("SMI with Rainfall (Validation Period)")
plt.tight_layout()
plt.show()


plt.figure(figsize=(12,3))
plt.plot(df_valid["date"], df_valid["delta_SMI"] - df_valid["delta_SMI_pred"], label="ΔSMI residual")
plt.axhline(0, color="black", linewidth=1)
plt.title("ΔSMI Residuals Over Time")
plt.xlabel("Date")
plt.ylabel("Residual")
plt.legend()
plt.tight_layout()
plt.show()

plt.figure(figsize=(12,3))
plt.plot(df_valid["date"], df_valid["SMI"] - df_valid["SMI_simulated"], label="SMI residual")
plt.axhline(0, color="black", linewidth=1)
plt.title("SMI Residuals Over Time")
plt.xlabel("Date")
plt.ylabel("Residual")
plt.legend()
plt.tight_layout()
plt.show()

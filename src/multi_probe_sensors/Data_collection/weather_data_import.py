import requests
import zipfile
import io
import os
import pandas as pd
import sqlite3, datetime
from passwordnemail import meteoserver_key
from datetime import date, datetime

print('HISTORICAL WEATHER DATA\n')

# Make sure the data folder exists
data_folder = 'multi_probe_data'
os.makedirs(data_folder, exist_ok=True)

# Download Valkenburg daily weather data
url = "https://cdn.knmi.nl/knmi/map/page/klimatologie/gegevens/monv_reeksen/neerslaggeg_VALKENBURG_474.zip"
response = requests.get(url)

# Extract and save this data
with zipfile.ZipFile(io.BytesIO(response.content)) as z:
    filename = z.namelist()[0]  # name inside the zip
    with z.open(filename) as f:
        data = f.read().decode("utf-8")

    # Save extracted text file to project data folder
    save_path = os.path.join(data_folder, filename)
    with open(save_path, "w", encoding="utf-8") as out_file:
        out_file.write(data)

print(f"File saved to {save_path}")

# Read the CSV into a dataframe
valkenburg_precip_df = pd.read_csv(
    save_path,
    skiprows=40,  # skip all the explanation before the header
)
# remove unnamed last column
valkenburg_precip_df = valkenburg_precip_df.iloc[:, :-1]
# Cut unused data, and convert to date
valkenburg_precip_df = valkenburg_precip_df[valkenburg_precip_df["YYYYMMDD"] >= 20250701]
valkenburg_precip_df["YYYYMMDD"] = pd.to_datetime(valkenburg_precip_df["YYYYMMDD"], format="%Y%m%d")
valkenburg_precip_df = valkenburg_precip_df.rename(columns={"YYYYMMDD": "DATE"})
valkenburg_precip_df.reset_index(inplace=True, drop=True)

print("""
Source: ROYAL NETHERLANDS METEOROLOGICAL INSTITUTE (KNMI)
STN      = stationsnummer/stationnumber
YYYYMMDD = datum/date (YYYY=jaar/year MM=maand/month DD=dag/day)
RD       = 24-uur som van de neerslag in tiende millimeters van 08.00 voorafgaande dag- 08.00 UTC huidige dag/
           daily precipitation amount in 0.1 mm over the period 08.00 preceding day - 08.00 UTC present day
SX       = codecijfer sneeuwdek om 08.00 uur UTC/code for the snow cover at 08.00 UTC.

""")

print('Sample of Valkenburg precipitation data:')
print('HEAD')
print(valkenburg_precip_df.head())
print("TAIL")
print(valkenburg_precip_df.tail())

valkenburg_precip_df.to_csv('multi_probe_data/valkenburg_precipitation.csv', index=False)
print('Valkenburg dataframe saved to csv\n')

# ---------------------------------------------------------------------------------------- #

print("""
# STN         LON(east)   LAT(north)  ALT(m)      NAME
# 215         4.437       52.141      -1.10       Voorschoten 
# DDVEC     : Vectorgemiddelde windrichting in graden (360=noord; 90=oost; 180=zuid; 270=west; 0=windstil/variabel). Zie http://www.knmi.nl/kennis-en-datacentrum/achtergrond/klimatologische-brochures-en-boeken / Vector mean wind direction in degrees (360=north; 90=east; 180=south; 270=west; 0=calm/variable)
# FG        : Etmaalgemiddelde windsnelheid (in 0.1 m/s) / Daily mean windspeed (in 0.1 m/s)
# TG        : Etmaalgemiddelde temperatuur (in 0.1 graden Celsius) / Daily mean temperature in (0.1 degrees Celsius)
# TN        : Minimum temperatuur (in 0.1 graden Celsius) / Minimum temperature (in 0.1 degrees Celsius)
# TX        : Maximum temperatuur (in 0.1 graden Celsius) / Maximum temperature (in 0.1 degrees Celsius)
# SQ        : Zonneschijnduur (in 0.1 uur) berekend uit de globale straling (-1 voor <0.05 uur) / Sunshine duration (in 0.1 hour) calculated from global radiation (-1 for <0.05 hour)
# Q         : Globale straling (in J/cm2) / Global radiation (in J/cm2)
# RH        : Etmaalsom van de neerslag (in 0.1 mm) (-1 voor <0.05 mm) / Daily precipitation amount (in 0.1 mm) (-1 for <0.05 mm)
# NG        : Etmaalgemiddelde bewolking (bedekkingsgraad van de bovenlucht in achtsten; 9=bovenlucht onzichtbaar) / Mean daily cloud cover (in octants; 9=sky invisible)
# UG        : Etmaalgemiddelde relatieve vochtigheid (in procenten) / Daily mean relative atmospheric humidity (in percents)
# EV24      : Referentiegewasverdamping (Makkink) (in 0.1 mm) / Potential evapotranspiration (Makkink) (in 0.1 mm)

""")

url = "https://www.daggegevens.knmi.nl/klimatologie/daggegevens"
payload = {
    "start": "20250101",
    "end": f"{datetime.today().strftime('%Y%m%d')}",
    "stns": "215",
    "vars": "DDVEC:FG:TG:TN:TX:SQ:Q:RH:NG:UG:EV24",
    "fmt": "csv",
}

r = requests.post(url, data=payload)
r.raise_for_status()
raw = r.text

# split header (# lines) and the real header row + data
header_lines = [line for line in raw.splitlines() if line.startswith("#")]
data_part = "\n".join(line for line in raw.splitlines() if not line.startswith("#"))

# save normal csv with header + data
with open("../multi_probe_data/voorschoten_weerdata.csv", "w", encoding="utf-8") as f:
    f.write(header_lines[18].replace('# ','') + "\n")
    for row in data_part.splitlines():
        f.write(row + "\n")

# Format dates
voorschoten_weather_df = pd.read_csv("../multi_probe_data/voorschoten_weerdata.csv")
voorschoten_weather_df["YYYYMMDD"] = pd.to_datetime(voorschoten_weather_df["YYYYMMDD"], format="%Y%m%d")
voorschoten_weather_df = voorschoten_weather_df.rename(columns={"YYYYMMDD": "DATE"})
# Rename columns
voorschoten_weather_df.columns = voorschoten_weather_df.columns.str.strip()
voorschoten_weather_df.rename(
    columns={
        'DDVEC' : 'windrichting',
        'FG' : 'windsnelheid',
        'TG' : 'temperatuur',
        'TN': 'mintemperatuur',
        'TX' : 'maxtemperatuur',
        'SQ' : 'zonneschijnduur',
        'Q' : 'globalestraling',
        'RH' : 'neerslag',
        'NG' : 'bewolking',
        'UG' : 'luchtvochtigheid',
        'EV24' : 'referentiegewasverdamping',
    },
    inplace=True
)

print('Sample of Voorschoten weather data:')
print('HEAD')
print(voorschoten_weather_df.head())
print("TAIL")
print(voorschoten_weather_df.tail())

voorschoten_weather_df.to_csv('multi_probe_data/voorschoten_weerdata.csv', index=False)
print('Voorschoten dataframe saved to csv\n')

# ---------------------------------------------------------------------------------------- #

print('FUTURE EXPECTED WEATHER DATA\n')

conn = sqlite3.connect('../multi_probe_data/database.db')
cursor = conn.cursor()
sqlite3.register_adapter(datetime.date, lambda d: d.isoformat())

url = f'https://data.meteoserver.nl/api/dagverwachting.php?locatie=Leiden&key={meteoserver_key}'
response = requests.get(url)
data = response.json()

today_iso = date.today().isoformat()

cursor.execute("UPDATE TenDayForecast SET is_actual = 0")

for row in data["data"]:
    d, m, y = row["dag"].split("-")
    forecast_for_date = f"{y}-{m}-{d}"

    cursor.execute("""
        INSERT OR REPLACE INTO TenDayForecast (
            forecast_date,
            forecast_for_date,
            avg_temp,
            min_temp,
            max_temp,
            wind_direction_deg,
            wind_direction_txt,
            wind_scale,
            wind_beaufort,
            wind_kmh,
            wind_knots,
            precipitation_mm,
            precipitation_perc,
            sunshine_minutes,
            sunshine_pct,
            sunrise,
            sunset,
            condition,
            is_actual
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        today_iso,
        forecast_for_date,
        row["avg_temp"],
        row["min_temp"],
        row["max_temp"],
        row["windr"],
        row["windrltr"],
        row["winds"],
        row["windb"],
        row["windkmh"],
        row["windknp"],
        row["tot_neersl"],
        row["neersl_perc_dag"],
        row["tot_zond"],
        row["zond_perc_dag"],
        row["sup"],
        row["sunder"],
        row["toestand"],
        1
    ))

conn.commit()
conn.close()

print('Deze weerdata wordt mede mogelijk gemaakt door meteoserver.nl')
print('Forecast saved to database')
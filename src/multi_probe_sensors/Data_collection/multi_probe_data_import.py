"""
Imports multi probe data, and single probe data of sensors placed at the same time as multi probe sensors.
"""

import sqlite3
from pathlib import Path
import requests
from passwordnemail import secrets
from time import mktime
from datetime import datetime, timedelta, timezone

# Functions
def get_data(endpoint, api_headers, api_params):
    api_response = requests.get(endpoint, headers=api_headers, params=api_params)
    if api_response.status_code == 200:
        data = api_response.json()
        returned_records = data.get("results", [])
        return returned_records
    else:
        print("Error:", api_response.status_code, api_response.text)
        exit('Bad response')

# Connect to sqlite3 database
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'multi_probe_data' / 'database.db'
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# The URL for the token API
login_url = 'https://insight.quantified.eu/api/token/login/'

# Make the POST request
response = requests.post(login_url, auth=(secrets['EMAIL'], secrets['PASSWORD']))

# Check if the request was successful
if response.status_code == 200:
    # Extract the token from the response
    token = response.json().get('token')
else:
    token = None
    print("Failed to retrieve token:", response.status_code, response.text)

# Set sensor ID's to fetch data for
cursor.execute("""
select device_id from DimSensor
""")
rows = cursor.fetchall()
id_list = [row[0] for row in rows]
single_probe_id_list = ",".join(str(i) for i in [j for j in id_list if len(str(j)) == 3])
multi_probe_id_list = ",".join(str(i) for i in [j for j in id_list if len(str(j)) == 4])
print(f"ID's to fetch data for:\n"
      f"Single probe: {single_probe_id_list}\n"
      f"Multi probe: {multi_probe_id_list}\n")

now = datetime.now(timezone.utc)
time = (now - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
time_until = now.strftime("%Y-%m-%dT%H:%M:%SZ")
# Set time manually if needed
# time = "2025-08-01T00:00:00Z"
print(f"Delta timestamp: {time}\n")

# Input into API parameters
params = {
    "device_id": multi_probe_id_list,
    "gateway_receive_time_after": f"{time}",
    "gateway_receive_time_before": f"{time_until}",
}
headers = {
    "Authorization": f"Bearer {token}",
    "accept": "application/json"
}

# Get multi probe response
print("Fetching multi probe data...")
multi_soil_probe_events_endpoint = 'https://insight.quantified.eu/api/multi_soil_probe_events/'
records = get_data(multi_soil_probe_events_endpoint, headers, params)
print("Got", len(records), "results")

# Format response to FactSensorData table
insert_sql = """
INSERT OR IGNORE INTO FactSensorData 
(device_id, probe_number, timestamp, gateway_receive_time, temperature, relative_permittivity, electric_conductivity)
VALUES (?, ?, ?, ?, ?, ?, ?);
"""

values = [
    (
        r['device'],
        r['probe'],
        r['timestamp'],
        r['gateway_receive_time'],
        r['temperature'],
        r['relative_permittivity'],
        r['electric_conductivity']
    )
    for r in records
]

# Insert response into table
changes_before_insert = conn.total_changes
cursor.executemany(insert_sql, values)
rows_inserted = conn.total_changes - changes_before_insert
conn.commit()
print(f'{rows_inserted} rows inserted')
print("Data fetched\n")


# Set parameters for single probe API
params = {
    "device_id": single_probe_id_list,
    "gateway_receive_time_after": f"{time}",
    "gateway_receive_time_before": f"{time_until}",
}

# Get single probe response
print("Fetching single probe data...")

# Endpoints for single probe sensors
single_probe_endpoints = {
    "temperature": "https://insight.quantified.eu/api/soil_temperature_events/",
    "relative_permittivity": "https://insight.quantified.eu/api/soil_relative_permittivity_events/",
    "electric_conductivity": "https://insight.quantified.eu/api/soil_electric_conductivity_events/"
}

# Fetch records for each sensor type
single_probe_data = {}
for sensor_type, url in single_probe_endpoints.items():
    records = get_data(url, headers, params)
    print(f"{sensor_type}: got {len(records)} results")
    single_probe_data[sensor_type] = records

# Merge results by (device, timestamp)
merged_records = {}
for sensor_type, records in single_probe_data.items():
    for r in records:
        key = (r['device'], r['timestamp'])
        if key not in merged_records:
            merged_records[key] = {
                "device_id": r['device'],
                "probe_number": 1,  # single probe
                "timestamp": r['timestamp'],
                "gateway_receive_time": r['gateway_receive_time'],
                "temperature": None,
                "relative_permittivity": None,
                "electric_conductivity": None
            }
        merged_records[key][sensor_type] = r['value']

# Format response to FactSensorData table
insert_sql = """
INSERT OR IGNORE INTO FactSensorData 
(device_id, probe_number, timestamp, gateway_receive_time, temperature, relative_permittivity, electric_conductivity)
VALUES (?, ?, ?, ?, ?, ?, ?);
"""

# Convert merged dict to list of tuples for DB insert
values = [
    (
        r["device_id"],
        r["probe_number"],
        r["timestamp"],
        r["gateway_receive_time"],
        r["temperature"],
        r["relative_permittivity"],
        r["electric_conductivity"]
    )
    for r in merged_records.values()
    if not (
        r["temperature"] is None and
        r["relative_permittivity"] is None and
        r["electric_conductivity"] is None
    )
]

changes_before_insert = conn.total_changes
cursor.executemany(insert_sql, values)
rows_inserted = conn.total_changes - changes_before_insert
conn.commit()
print(f"{rows_inserted} rows inserted")
print("Data fetched")
print()

# Data cleaning
print('Start data cleaning')

cutoff = int(mktime(datetime(2025, 9, 20).timetuple())) # Aangezien deze sensor iets voor deze datum opnieuw is ingegraven.
conn.cursor().execute(f"""
    DELETE FROM FactSensorData
    WHERE device_id = 1386
      AND timestamp < {cutoff};
""")

# Alle andere sensoren moeten ook opgeruimd worden adhv dimsensor.

print("Data cleaned")
print()


### Get battery data
"""
For diagnostic and maintenance purposes, a battery dimension will be kept.
"""

print("Fetching battery data...")

battery_from_time = (
    datetime.now(timezone.utc).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )
    - timedelta(days=1)
).strftime("%Y-%m-%dT%H:%M:%SZ")

battery_voltage_events_endpoint = (
    "https://insight.quantified.eu/api/battery_voltage_events/"
)

params = {
    "device_id": ",".join(str(device_id) for device_id in id_list),
    "gateway_receive_time_after": battery_from_time,
}

records = get_data(battery_voltage_events_endpoint, headers, params)

# Keep the most recent battery measurement for each device
latest_battery_records = {}

for record in records:
    device_id = record["device"]

    if (
        device_id not in latest_battery_records
        or record["timestamp"] > latest_battery_records[device_id]["timestamp"]
    ):
        latest_battery_records[device_id] = record

values = [
    (
        record["device"],
        record["percentage"]
    )
    for record in latest_battery_records.values()
]

insert_sql = """
INSERT INTO DimBattery (
    device_id,
    battery_percentage
)
VALUES (?, ?)
ON CONFLICT(device_id) DO UPDATE SET
    battery_percentage = excluded.battery_percentage;
"""

cursor.executemany(insert_sql, values)
conn.commit()

print("Battery data updated")

conn.close()

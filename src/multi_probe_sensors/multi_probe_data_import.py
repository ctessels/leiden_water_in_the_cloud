import sqlite3
from datetime import datetime, timezone
import requests
from passwordnemail import secrets

"""
TODO:
Binnenhalen data enkele probes
Eerste data-analyse
Binnenhalen van weerdata
Warnings voor batterij en missende data
Weerdata integreren in analyse
Integratie van data-analyse met vorige sensoren
Integratie van multi-sensor code met rest van codebase
"""

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
conn = sqlite3.connect('database.db')
cursor = conn.cursor()

# The URL for the token API
login_url = 'https://insight.quantified.eu/api/token/login/'
 
# Make the POST request
response = requests.post(login_url, auth=(secrets['EMAIL'], secrets['PASSWORD']))

# Check if the request was successful
if response.status_code == 200:
    # Extract the token from the response
    token = response.json().get('token')
    print(f"Token: {token}\n")
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

# Set delta timestamp
cursor.execute("""
select max(timestamp) from FactSensorData
""")
rows = cursor.fetchall()
unix_time = rows[0][0]
time = datetime.fromtimestamp(unix_time, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
# Set time manually if needed
time = "2025-08-01T00:00:00Z"
print(f"Delta timestamp: {time}\n")

# Set fetchable record limit
record_limit = 10000

# Input into API parameters
params = {
    "device_id": multi_probe_id_list,
    "gateway_receive_time_after": f"{time}",
    'limit': record_limit,
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
if len(records) > record_limit:
    print(f"Records limit reached")

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
cursor.executemany(insert_sql, values)
rows_inserted = cursor.rowcount
conn.commit()
print(f'{rows_inserted} rows inserted')
print("Data fetched\n")


# Set parameters for single probe API
params = {
    "device_id": single_probe_id_list,
    "gateway_receive_time_after": f"{time}",
    'limit': record_limit,
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

cursor.executemany(insert_sql, values)
rows_inserted = cursor.rowcount
conn.commit()
print(f"{rows_inserted} rows inserted")
conn.close()
print("Data fetched")
import sqlite3
from datetime import datetime, timezone

import requests

from passwordnemail import secrets

"""
TODO:
Eerste data-analyse
Binnenhalen van weerdata
Warnings voor batterij en missende data
Weerdata integreren in analyse
Integratie van data-analyse met vorige sensoren
Integratie van multi-sensor code met rest van codebase
"""

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

# Set endpoint url
multi_soil_probe_events_endpoint = 'https://insight.quantified.eu/api/multi_soil_probe_events/'

# Set sensor ID's to fetch data for
cursor.execute("""
select device_id from DimSensor
""")
rows = cursor.fetchall()
id_list = [row[0] for row in rows]
id_list_str = ",".join(str(i) for i in id_list)
print(f"ID's to fetch data for: \n{id_list_str}\n")

# Set delta timestamp
cursor.execute("""
select max(timestamp) from FactSensorData
""")
rows = cursor.fetchall()
unix_time = rows[0][0]
time = datetime.fromtimestamp(unix_time, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
print(f"Delta timestamp: {time}\n")

# Set fetchable record limit
record_limit = 10000

# Input into API parameters
params = {
    "device_id": id_list_str,
    "gateway_receive_time_after": f"{time}",
    'limit': record_limit,
}
headers = {
    "Authorization": f"Bearer {token}",
    "accept": "application/json"
}

# Get response
print("Fetching data...")
response = requests.get(multi_soil_probe_events_endpoint, headers=headers, params=params)
if response.status_code == 200:
    data = response.json()
    records = data.get("results", [])
    print("Got", len(records), "results")
    if len(records) > record_limit:
        print(f"Records limit reached")
else:
    print("Error:", response.status_code, response.text)
    exit('Bad response')

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
conn.close()
print("Data fetched")
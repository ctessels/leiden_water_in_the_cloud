import requests
import zipfile
import pandas as pd
import numpy as np
from datetime import datetime
from default_parameters import get_parameters
from io import BytesIO
import time
import pytz

# -------------------------- #
# ---------- KNMI ---------- #
# -------------------------- #

# Download de zip van de URL
url = "http://cdn.knmi.nl/knmi/map/page/klimatologie/gegevens/uurgegevens/jaar.zip"
url = "https://cdn.knmi.nl/knmi/map/page/klimatologie/gegevens/daggegevens/jaar.zip"
url = "https://cdn.knmi.nl/knmi/map/page/klimatologie/gegevens/daggegevens/etmgeg_240.zip"

response = requests.get(url)

# Pak de inhoud van het zipbestand uit in de data folder
with zipfile.ZipFile(BytesIO(response.content)) as zip_file:
    zip_file.extractall('./data/')

# ---------------------------------------- #
# ---------- Weerstation Leiden ---------- #
# ---------------------------------------- #

# Haal de informatie op via de URL van weerstation Zusterhof
url = "https://langbrom.home.xs4all.nl/weer/archief/archiefdata.txt"
response = requests.get(url)
data = response.text

# Split the data into lines and remove the first seven lines
lines = data.split("\n")[7:]

# Extract the headers and rows
headers = ["Date", "Max Temp (C)", "Min Temp (C)", "Avg Temp (C)",
           "Rainfall (mm)", "Max Pressure (hPa)", "Min Pressure (hPa)"]
rows = [line.split(",") for line in lines if line.strip() != ""]

# Remove '\r' from the last column values
for row in rows:
    row[-1] = row[-1].rstrip('\r')

# Create a DataFrame using the extracted headers and rows
df_weer_leiden = pd.DataFrame(rows, columns=headers)
df_weer_leiden = df_weer_leiden[df_weer_leiden['Date'] != "1900-01-00"]
df_weer_leiden['Date'] = pd.to_datetime(df_weer_leiden['Date'])
df_weer_leiden[df_weer_leiden.columns[1:]
               ] = df_weer_leiden[df_weer_leiden.columns[1:]].astype(float)

# Display the DataFrame
df_weer_leiden = df_weer_leiden[df_weer_leiden['Date'] > datetime(2022, 2, 18)]

# Lowercase kolommen
lowercase_column_names = {col: col.lower() for col in df_weer_leiden.columns}
df_weer_leiden.rename(columns=lowercase_column_names, inplace=True)

# Sla dataframe op als excel
df_weer_leiden.to_excel('./data/weerdata_leiden.xlsx',
                        index=False, sheet_name='weerdata')

# # ------------------------------------------ #
# # ---------- Senor dim informatie ---------- #
# # ------------------------------------------ #
# # laad sensor id dictionairy. Deze bevat per device_name de bijbehoren device_ic
# device_name_ids = get_parameters()
# df_sensor_id_name = pd.DataFrame.from_dict(device_name_ids, orient='index', columns=[
#                                            'device_id']).reset_index().set_index('device_id')
# df_sensor_id_name.columns = ['device_name']

# df_sensor_info_org = pd.read_excel(
#     './data/Water in the cloud (Responses).xlsx')
# sensor_dim_cols = ['locatie', 'device_name', 'datum_geplaatst', 'datum_weggehaald',
#                    'diepte_plaatsing', 'leeftijd_plant', 'soort_plant', 'locatie_regio',
#                    'extra_omschrijving']

# df_sensor_info_org.columns = ['timestamp', 'device_name', 'locatie', 'omschrijving', 'foto_1', 'foto_2',
#                               'diepte_plaatsing', 'lat_lon', 'located_datum_old', 'datum_geplaatst', 'located_tijd',
#                               'datum_weggehaald', 'foto_3', 'foto_4',
#                               'leeftijd_plant', 'soort_plant', 'locatie_regio', 'extra_omschrijving']

# df_dim_sensor = df_sensor_info_org[sensor_dim_cols].copy()
# df_dim_sensor['old'] = pd.Series(
#     np.where(df_dim_sensor['locatie'].str[-4:-1] == 'old', 'Yes', 'No'))

# df_dim_sensor['device_name_org'] = df_dim_sensor['device_name']
# # df_dim_sensor['device_name'] = 'firefly2_' + df_dim_sensor['device_name'].str[-4:]
# df_dim_sensor = df_dim_sensor.merge(
#     df_sensor_id_name.reset_index(), how='left')
# df_dim_sensor['locatie'] = df_dim_sensor['locatie'] + \
#     '_' + df_dim_sensor['diepte_plaatsing'].str[:2]

# large_date = pd.to_datetime(pd.Timestamp.max.date())
# df_dim_sensor['datum_weggehaald'] = df_dim_sensor['datum_weggehaald'].fillna(
#     large_date)

# df_dim_sensor.to_excel('./data/dim_sensor.xlsx',
#                        index=False, sheet_name='dim_sensor')

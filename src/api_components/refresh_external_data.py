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
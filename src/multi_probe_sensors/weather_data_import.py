import requests
import zipfile
import io
import os
import pandas as pd

"""
TODO:
Save file after unpacking
Format into dataframe from 2025/07/01
Find other data
"""

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
SX       = codecijfer sneeuwdek om 08.00 uur UTC/code for the snow cover at 08.00 UTC:
""")

print('Sample of Valkenburg precipitation data:')
print('HEAD')
print(valkenburg_precip_df.head())
print("TAIL")
print(valkenburg_precip_df.tail())

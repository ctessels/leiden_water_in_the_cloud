import requests
import zipfile
import io

"""
TODO:
Save file after unpacking
Format into dataframe from 2025/07/01
Find other data
"""

# Download Valkenburg daily weather data
url = "https://cdn.knmi.nl/knmi/map/page/klimatologie/gegevens/monv_reeksen/neerslaggeg_VALKENBURG_474.zip"
response = requests.get(url)

# Extract and save this data
with zipfile.ZipFile(io.BytesIO(response.content)) as z:
    filename = z.namelist()[0]
    with z.open(filename) as f:
        data = f.read().decode("utf-8")


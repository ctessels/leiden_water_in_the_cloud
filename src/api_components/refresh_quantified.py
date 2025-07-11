import requests
import pandas as pd
from datetime import datetime
from default_parameters import get_parameters
import time
import pytz
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
import os
from io import StringIO

# ------------------------------------------- #
# ---------- Senor fact informatie ---------- #
# ------------------------------------------- #

load_dotenv()

# The URL for the token API
login_url = 'https://insight.quantified.eu/api/token/login/'
 
# Make the POST request
response = requests.post(login_url, auth=HTTPBasicAuth(os.getenv("EMAIL"), os.getenv("PASSWORD")))

# Check if the request was successful
if response.status_code == 200:
    # Extract the token from the response
    token = response.json().get('token')
    print("Token:", token)
else:
    print("Failed to retrieve token:", response.status_code, response.text)

# laad sensor id dictionairy. Deze bevat per device_name de bijbehoren device_ic
device_name_ids = get_parameters()
df_sensor_id_name = pd.DataFrame.from_dict(device_name_ids, orient='index', columns=[
                                           'device_id']).reset_index().set_index('device_id')
df_sensor_id_name.columns = ['device_name']

authorization_key = f'Bearer {token}'

df_permittivity = pd.read_excel('./data/Permittivity_updated.xlsx')
df_battery = pd.read_excel('./data/Battery_updated.xlsx')

df_sensor_id_name = pd.DataFrame.from_dict(device_name_ids, orient='index', columns=[
                                           'device_id']).reset_index().set_index('device_id')
df_sensor_id_name.columns = ['device_name']


def get_max_gateway(df):
    df_max_gateway_time = pd.DataFrame(
        df.groupby('device')['gateway_receive_time'].max())
    df_max_gateway_time.columns = ['max_gateway_receive_time']
    df_max_gateway_time.index.name = 'device_id'
    df_max_gateway_time = df_max_gateway_time.join(df_sensor_id_name)
    df_max_gateway_time.sort_values('max_gateway_receive_time')

    return df_max_gateway_time


df_max_gateway_permittivity = get_max_gateway(df_permittivity)
df_max_gateway_battery = get_max_gateway(df_battery)

df_final_permittivity = pd.DataFrame()
df_final_battery = pd.DataFrame()

resp = 200

url_list = [r"https://insight.quantified.eu/api/soil_relative_permittivity_events/",
            r"https://insight.quantified.eu/api/battery_voltage_events/"]

max_gateway_list = [df_max_gateway_permittivity, df_max_gateway_battery]

c = -1
for url_path in url_list:
    c += 1

    if resp == 401:
        print('Autorization failed')
        break

    for device_name, device_ID in device_name_ids.items():
        if resp == 401:
            break

        url = url_path

        try:
            gateway_receive_time_after = max_gateway_list[c].loc[device_ID]['max_gateway_receive_time'].strftime(
                '%Y-%m-%dT%H:%M:%SZ')
        except:
            gateway_receive_time_after = datetime(
                2020, 1, 1).strftime('%Y-%m-%dT%H:%M:%SZ')  # type: ignore

        while url != None:

            headers = {
                "accept": "application/json",
                "authorization": authorization_key,
            }

            params = {
                "device_id": device_ID,
                "limit": 100,
                "gateway_receive_time_after": gateway_receive_time_after
            }

            response = requests.get(url, headers=headers, params=params)
            time.sleep(2)

            resp = response.status_code

            if resp == 200:
                df = pd.read_json(StringIO(response.text))
                print(f'device: {device_ID}, count measures: {len(df)}')
                if url_path == url_list[0]:
                    df_final_permittivity = pd.concat(
                        [df_final_permittivity, df])
                elif url_path == url_list[1]:
                    df_final_battery = pd.concat([df_final_battery, df])

                txt_json = response.json()
                url = txt_json['next']
            elif resp == 401:
                break
            else:
                print(resp)
                break


def quantified_to_dataframe(df):
    df = pd.json_normalize(df['results'])
    df['gateway_receive_time'] = pd.to_datetime(
        df['gateway_receive_time'], utc=True)
    # replace with your local timezone
    local_tz = pytz.timezone('Europe/Amsterdam')
    df['gateway_receive_time'] = df['gateway_receive_time'].dt.tz_convert(
        local_tz)
    df['gateway_receive_time'] = df['gateway_receive_time'].dt.strftime(
        '%Y-%m-%d %H:%M:%S')
    df['gateway_receive_time'] = pd.to_datetime(df['gateway_receive_time'])

    return df


df_results_permittivity = quantified_to_dataframe(df_final_permittivity)
df_results_battery = quantified_to_dataframe(df_final_battery)

df_permittivity_update = pd.concat([df_permittivity, df_results_permittivity])
df_battery_update = pd.concat([df_battery, df_results_battery])

df_permittivity_update.to_excel(
    './data/Permittivity_updated.xlsx', index=False)
df_battery_update.to_excel('./data/Battery_updated.xlsx', index=False)
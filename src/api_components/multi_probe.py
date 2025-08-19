import requests
from secrets import secrets

# The URL for the token API
login_url = 'https://insight.quantified.eu/api/token/login/'
 
# Make the POST request
response = requests.post(login_url, auth=(secrets['EMAIL'], secrets['PASSWORD']))

# Check if the request was successful
if response.status_code == 200:
    # Extract the token from the response
    token = response.json().get('token')
    print("Token:", token)
else:
    token = None
    print("Failed to retrieve token:", response.status_code, response.text)

# Set data request parameters
multi_soil_probe_events_endpoint = 'https://insight.quantified.eu/api/multi_soil_probe_events/'
params = {
    "device_id": 1393,
    "gateway_receive_time_after": "2025-08-01T00:00:00Z"
}
headers = {
    "Authorization": f"Bearer {token}",
    "accept": "application/json"
}

# Get response
response = requests.get(multi_soil_probe_events_endpoint, headers=headers, params=params)
if response.status_code == 200:
    data = response.json()
    print("Got", len(data.get("results", [])), "results")
    for event in data.get("results", []):
        print(event)
else:
    print("Error:", response.status_code, response.text)
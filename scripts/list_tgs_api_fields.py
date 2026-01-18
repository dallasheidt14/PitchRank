#!/usr/bin/env python3
"""List all available fields from TGS API"""
import requests
import json

BASE = "https://api.athleteone.com/api"
headers = {
    "Origin": "https://public.totalglobalsports.com",
    "Referer": "https://public.totalglobalsports.com/",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0"
}

# Get a real game
event_id = 3900
url = f"{BASE}/Event/get-event-schedule-or-standings/{event_id}"
r = requests.get(url, headers=headers, timeout=10)
data = r.json() if r.status_code == 200 else {}

boys = data.get('data', {}).get('boysDivAndFlightList', []) if isinstance(data, dict) else []
flight = boys[0].get('flightList', [])[0] if boys and boys[0].get('flightList') else {}
flight_id = flight.get('flightID')

if flight_id:
    games_url = f"{BASE}/Event/get-schedules-by-flight/{event_id}/{flight_id}/0"
    games_r = requests.get(games_url, headers=headers, timeout=10)
    games_data = games_r.json() if games_r.status_code == 200 else {}
    game = games_data.get('data', [{}])[0] if isinstance(games_data, dict) and games_data.get('data') else (games_data[0] if isinstance(games_data, list) and len(games_data) > 0 else {})
    
    print("=" * 80)
    print("GAME DATA FIELDS (from get-schedules-by-flight endpoint)")
    print("=" * 80)
    print(json.dumps(game, indent=2))
    
    # Get division data
    div_url = f"{BASE}/Event/get-flight-division-by-flightID/{flight_id}"
    div_r = requests.get(div_url, headers=headers, timeout=10)
    div_data = div_r.json() if div_r.status_code == 200 else {}
    
    print("\n" + "=" * 80)
    print("DIVISION/FLIGHT DATA FIELDS (from get-flight-division-by-flightID endpoint)")
    print("=" * 80)
    print(json.dumps(div_data, indent=2))










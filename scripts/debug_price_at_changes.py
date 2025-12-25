"""Check what the sensor state was at times of heating switch changes yesterday."""

import sys
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

import requests

HA_URL = os.getenv("HA_URL", "https://ha.ketunmetsa.fi")
HA_TOKEN = os.getenv("HA_API_TOKEN")
PRICE_SENSOR = os.getenv("PRICE_SENSOR", "sensor.nordpool_kwh_fi_eur_3_10_0255")
CENTRAL_HEATING_SWITCH = os.getenv("CENTRAL_HEATING_SHUTOFF_SWITCH", "switch.shelly1minig3_5432045dd3f0_switch_0")

if not HA_TOKEN:
    print("ERROR: HA_API_TOKEN not set")
    sys.exit(1)

headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

print("=" * 80)
print("PRICE SENSOR HISTORY AT SWITCH CHANGE TIMES")
print("=" * 80)

# Get yesterday's dates
yesterday_start = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

# Fetch switch history
print(f"\nFetching switch history...")
url = f"{HA_URL}/api/history/period/{yesterday_start.isoformat()}?filter_entity_id={CENTRAL_HEATING_SWITCH}&end_time={today_start.isoformat()}"
resp = requests.get(url, headers=headers, timeout=10)
resp.raise_for_status()
history = resp.json()

switch_changes = []
if history and len(history) > 0:
    for state in history[0]:
        timestamp = state.get('last_changed')
        value = state.get('state')
        switch_changes.append({'timestamp': timestamp, 'value': value})

print(f"Found {len(switch_changes)} switch changes yesterday")

# For each switch change, fetch price history around that time
tz = ZoneInfo("Europe/Helsinki")

print(f"\n" + "=" * 80)
print("ANALYSIS OF EACH SWITCH CHANGE:")
print("=" * 80)

for i, change in enumerate(switch_changes):
    change_utc_str = change['timestamp']
    change_utc = datetime.fromisoformat(change_utc_str.replace('Z', '+00:00'))
    change_local = change_utc.astimezone(tz)
    
    print(f"\n[{i+1}] {change['value'].upper()} at {change_local.strftime('%H:%M:%S')} (UTC: {change_utc_str})")
    
    # Fetch price sensor history around this time
    # Get a 1-hour window: 30 min before to 30 min after
    window_start = change_utc - timedelta(minutes=30)
    window_end = change_utc + timedelta(minutes=30)
    
    url = f"{HA_URL}/api/history/period/{window_start.isoformat()}?filter_entity_id={PRICE_SENSOR}&end_time={window_end.isoformat()}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        price_history = resp.json()
        
        if price_history and len(price_history) > 0 and len(price_history[0]) > 0:
            print(f"  Price sensor changes in ±30min window:")
            for state in price_history[0]:
                ts = state.get('last_changed')
                state_val = state.get('state')
                ts_utc = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                ts_local = ts_utc.astimezone(tz)
                
                # Check if this is the state at the switch change time
                if abs((ts_utc - change_utc).total_seconds()) < 1:
                    marker = " ← AT SWITCH CHANGE TIME"
                else:
                    marker = ""
                
                print(f"    {ts_local.strftime('%H:%M:%S')}  state={state_val} c/kWh{marker}")
        else:
            print(f"  No price history found in window")
    except Exception as e:
        print(f"  Error fetching price history: {e}")

# Also get the raw_today array to see what prices were available
print(f"\n" + "=" * 80)
print("YESTERDAY'S FULL PRICE ARRAY (raw_today):")
print("=" * 80)

yesterday_noon = (datetime.now() - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
url = f"{HA_URL}/api/history/period/{yesterday_noon.isoformat()}?filter_entity_id={PRICE_SENSOR}&end_time={yesterday_noon.replace(minute=1).isoformat()}"
resp = requests.get(url, headers=headers, timeout=10)
resp.raise_for_status()
history = resp.json()

raw_today = []
if history and len(history) > 0 and len(history[0]) > 0:
    state = history[0][0]
    raw_today = state.get('attributes', {}).get('raw_today', [])

if raw_today and len(raw_today) == 96:
    print(f"\nPrices for Dec 24 (showing 06:00-13:30):")
    for i in range(24, 54):  # 06:00 to 13:30
        h = i // 4
        m = (i % 4) * 15
        value = float(raw_today[i]['value'])
        print(f"  {h:02d}:{m:02d}  {value:6.2f} c/kWh")

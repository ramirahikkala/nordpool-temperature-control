"""Verify that sensor state matches raw_today[current_quarter] consistently."""

import sys
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

import requests
import time

HA_URL = os.getenv("HA_URL", "https://ha.ketunmetsa.fi")
HA_TOKEN = os.getenv("HA_API_TOKEN")
PRICE_SENSOR = os.getenv("PRICE_SENSOR", "sensor.nordpool_kwh_fi_eur_3_10_0255")

if not HA_TOKEN:
    print("ERROR: HA_API_TOKEN not set")
    sys.exit(1)

headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

print("=" * 80)
print("VERIFYING CURRENT PRICE ALIGNMENT")
print("=" * 80)

tz = ZoneInfo("Europe/Helsinki")

# Sample 10 times throughout the day
sample_times = [
    (6, 0),   # 06:00
    (8, 15),  # 08:15
    (10, 30), # 10:30
    (12, 45), # 12:45
    (15, 0),  # 15:00
]

for hour, minute in sample_times:
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    if target > now:
        # Target time is in the future, skip
        print(f"\n{hour:02d}:{minute:02d}  SKIPPED (future)")
        continue
    
    # Calculate what quarter_index should be
    quarter_index = hour * 4 + (minute // 15)
    expected_price = None
    
    # Get today's prices
    now_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    url = f"{HA_URL}/api/history/period/{now_noon.isoformat()}?filter_entity_id={PRICE_SENSOR}&end_time={now_noon.replace(minute=1).isoformat()}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        history = resp.json()
        if history and len(history) > 0 and len(history[0]) > 0:
            state = history[0][0]
            raw_today = state.get('attributes', {}).get('raw_today', [])
            if quarter_index < len(raw_today):
                expected_price = float(raw_today[quarter_index]['value'])
    except Exception as e:
        print(f"  Error fetching raw_today: {e}")
        continue
    
    # Get sensor state AT that time by fetching history
    try:
        # Fetch sensor history for a window around target time
        window_start = target - timedelta(minutes=5)
        window_end = target + timedelta(minutes=5)
        url = f"{HA_URL}/api/history/period/{window_start.isoformat()}?filter_entity_id={PRICE_SENSOR}&end_time={window_end.isoformat()}"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        history = resp.json()
        
        # Find the state that was active at target time
        state_at_time = None
        if history and len(history) > 0:
            for state in history[0]:
                state_time = datetime.fromisoformat(state.get('last_changed').replace('Z', '+00:00')).astimezone(tz)
                if state_time <= target:
                    state_at_time = float(state.get('state'))
        
        if state_at_time is not None and expected_price is not None:
            match = "✓" if abs(state_at_time - expected_price) < 0.01 else "✗"
            print(f"{hour:02d}:{minute:02d}  sensor_state={state_at_time:6.2f}  raw_today[{quarter_index}]={expected_price:6.2f}  {match}")
        else:
            print(f"{hour:02d}:{minute:02d}  sensor_state={state_at_time}  raw_today[{quarter_index}]={expected_price}")
    except Exception as e:
        print(f"  Error: {e}")

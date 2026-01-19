#!/usr/bin/env python3
"""Test the endpoint logic standalone."""

import os
from datetime import datetime, timedelta, timezone
import pytz
import requests

# Load env
from dotenv import load_dotenv
load_dotenv()

HA_URL = os.getenv('HA_URL')
HA_API_TOKEN = os.getenv('HA_API_TOKEN')
SWITCH_ENTITY = os.getenv('SWITCH_ENTITY')

headers = {
    'Authorization': f'Bearer {HA_API_TOKEN}',
    'Content-Type': 'application/json'
}

print(f"Entity: {SWITCH_ENTITY}")
print(f"HA URL: {HA_URL}\n")

# Fetch history
local_tz = pytz.timezone('Europe/Helsinki')
now_utc = datetime.now(timezone.utc)
lookback_hours = 72
start_utc = now_utc - timedelta(hours=lookback_hours)
start_iso = start_utc.replace(tzinfo=None).isoformat()
end_utc = now_utc + timedelta(hours=1)
end_iso = end_utc.replace(tzinfo=None).isoformat()

url = f"{HA_URL}/api/history/period/{start_iso}?filter_entity_id={SWITCH_ENTITY}&end_time={end_iso}"
print(f"Fetching: {start_iso} to {end_iso}")
print(f"URL: {url}\n")

resp = requests.get(url, headers=headers, timeout=30)
if resp.status_code != 200:
    print(f"ERROR: {resp.status_code}")
    print(resp.text)
    exit(1)

history = resp.json()

# Parse all state changes
points = []
if history and len(history) > 0 and len(history[0]) > 0:
    for s in history[0]:
        ts_str = s.get('last_changed')
        state = s.get('state')
        try:
            dt_utc = datetime.fromisoformat(ts_str)
            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            dt_local = dt_utc.astimezone(local_tz)
            points.append({"ts": dt_local, "state": state})
        except Exception as e:
            print(f"Error parsing {ts_str}: {e}")

points.sort(key=lambda p: p['ts'])

print(f"Found {len(points)} state changes\n")
for p in points:
    print(f"  {p['ts']} -> {p['state']}")

# Calculate period for hours=24
hours = 24
target_date_end = datetime.now(local_tz).replace(microsecond=0)
target_date_start = target_date_end - timedelta(hours=hours)

print(f"\nPeriod (hours={hours}):")
print(f"  Start: {target_date_start}")
print(f"  End:   {target_date_end}")

# Find initial state
state_at_period_start = 'off'
for p in points:
    if p['ts'] <= target_date_start:
        state_at_period_start = p['state']
        print(f"\nInitial state found: {p['ts']} = {p['state']}")
    else:
        break

print(f"Initial state for period: {state_at_period_start}")

# Initialize quarters
quarters = [state_at_period_start] * 96

# Apply state changes during period
print(f"\nState changes during period:")
for p in points:
    if not (target_date_start < p['ts'] <= target_date_end):
        continue
    
    time_into_period = p['ts'] - target_date_start
    minutes_into_period = int(time_into_period.total_seconds() / 60)
    quarter_idx = minutes_into_period // 15
    
    print(f"  {p['ts']} -> {p['state']} (Q{quarter_idx})")
    
    for i in range(quarter_idx, 96):
        quarters[i] = p['state']

# Display result
print("\nQuarters (X=on, .=off):")
for i in range(0, 96, 6):
    chunk = ''.join(['X' if q == 'on' else '.' for q in quarters[i:i+6]])
    print(f"  Q{i:2d}-{i+5:2d}: {chunk}")

on_count = sum(1 for q in quarters if q == 'on')
off_count = sum(1 for q in quarters if q == 'off')
print(f"\nResult: {on_count} ON, {off_count} OFF")

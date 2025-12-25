"""Debug script to understand Nordpool sensor state vs raw_today array."""

import sys
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

import requests

HA_URL = os.getenv("HA_URL", "https://ha.ketunmetsa.fi")
HA_TOKEN = os.getenv("HA_API_TOKEN")
PRICE_SENSOR = os.getenv("PRICE_SENSOR", "sensor.nordpool_kwh_fi_eur_3_10_0255")

if not HA_TOKEN:
    print("ERROR: HA_API_TOKEN not set")
    sys.exit(1)

headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

print("=" * 80)
print("NORDPOOL SENSOR DEBUG")
print("=" * 80)

# Get current sensor state
print(f"\nFetching sensor state from: {PRICE_SENSOR}")
resp = requests.get(f"{HA_URL}/api/states/{PRICE_SENSOR}", headers=headers, timeout=10)
resp.raise_for_status()
data = resp.json()

print(f"\nSensor 'state' (current price): {data['state']}")
print(f"Sensor state_class: {data.get('attributes', {}).get('state_class')}")
print(f"Sensor unit: {data.get('attributes', {}).get('unit_of_measurement')}")
print(f"Last updated: {data.get('last_updated')}")
print(f"Last changed: {data.get('last_changed')}")

# Get raw_today from attributes
attributes = data.get('attributes', {})
raw_today = attributes.get('raw_today', [])

print(f"\nraw_today array has {len(raw_today)} entries (expect 96 for 24h @ 15-min intervals)")

# Get timezone
tz = ZoneInfo("Europe/Helsinki")
now_local = datetime.now(tz)

print(f"\nCurrent local time: {now_local.strftime('%Y-%m-%d %H:%M:%S %Z (UTC%z)')}")

# Calculate which quarter we're in
hour = now_local.hour
minute = now_local.minute
quarter = minute // 15
quarter_index = hour * 4 + quarter

print(f"Current quarter: {hour:02d}:{quarter * 15:02d} (index {quarter_index})")

# Show raw_today array around current index
print(f"\nraw_today entries around current quarter (±5):")
start_idx = max(0, quarter_index - 5)
end_idx = min(len(raw_today), quarter_index + 6)

for i in range(start_idx, end_idx):
    h = i // 4
    m = (i % 4) * 15
    value = raw_today[i]['value']
    marker = " ← CURRENT" if i == quarter_index else ""
    print(f"  [{i:2d}] {h:02d}:{m:02d}  {value:6.2f} c/kWh{marker}")

# Compare state vs raw_today[current_index]
current_quarter_price = float(raw_today[quarter_index]['value'])
state_price = float(data['state'])

print(f"\n" + "=" * 80)
print(f"COMPARISON:")
print(f"  Sensor state:              {state_price:.2f} c/kWh")
print(f"  raw_today[{quarter_index}]:          {current_quarter_price:.2f} c/kWh")

if abs(state_price - current_quarter_price) < 0.01:
    print(f"  ✓ MATCH - sensor state == current quarter price")
else:
    print(f"  ✗ MISMATCH - sensor state != current quarter price")
    # Check if state matches a different quarter
    for i, entry in enumerate(raw_today):
        if abs(float(entry['value']) - state_price) < 0.01:
            h = i // 4
            m = (i % 4) * 15
            diff = i - quarter_index
            print(f"    State matches raw_today[{i}] ({h:02d}:{m:02d}), which is {diff:+d} quarters away")

print("=" * 80)

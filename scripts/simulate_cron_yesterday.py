"""Simulate what the cron job would decide at each execution time yesterday."""

import sys
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, '/home/rami/omat/ha_rest_api/ha-api-test')

import requests
from main import should_central_heating_run

HA_URL = os.getenv("HA_URL", "https://ha.ketunmetsa.fi")
HA_TOKEN = os.getenv("HA_API_TOKEN")
PRICE_SENSOR = os.getenv("PRICE_SENSOR", "sensor.nordpool_kwh_fi_eur_3_10_0255")

if not HA_TOKEN:
    print("ERROR: HA_API_TOKEN not set")
    sys.exit(1)

headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

print("=" * 80)
print("SIMULATING CRON JOB DECISIONS YESTERDAY")
print("=" * 80)

# Get yesterday's prices
yesterday_noon = (datetime.now() - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
url = f"{HA_URL}/api/history/period/{yesterday_noon.isoformat()}?filter_entity_id={PRICE_SENSOR}&end_time={yesterday_noon.replace(minute=1).isoformat()}"
resp = requests.get(url, headers=headers, timeout=10)
resp.raise_for_status()
history = resp.json()

raw_today = []
if history and len(history) > 0 and len(history[0]) > 0:
    state = history[0][0]
    raw_today = state.get('attributes', {}).get('raw_today', [])

if not raw_today or len(raw_today) != 96:
    print("ERROR: Could not get raw_today array")
    sys.exit(1)

prices = [float(entry['value']) for entry in raw_today]

print(f"\nSimulating cron execution at :00, :15, :30, :45 on Dec 24:")
print("=" * 80)
print("Time   Price  Decision  Reason")
print("-" * 80)

# Simulate cron at each 15-min mark yesterday (06:00 - 23:45)
tz = ZoneInfo("Europe/Helsinki")
yesterday = datetime.now(tz) - timedelta(days=1)

decision_history = []

for hour in range(6, 24):
    for minute in [0, 15, 30, 45]:
        quarter_index = hour * 4 + (minute // 15)
        
        if quarter_index >= len(prices):
            break
        
        current_price = prices[quarter_index]
        should_run, reason = should_central_heating_run(current_price, prices)
        decision = "HEAT" if should_run else "BLOCK"
        
        decision_history.append({
            'time': f"{hour:02d}:{minute:02d}",
            'quarter': quarter_index,
            'price': current_price,
            'decision': decision
        })
        
        print(f"{hour:02d}:{minute:02d}  {current_price:5.2f}  {decision:5s}   {reason[:40]}")

# Now analyze what actually happened
print(f"\n" + "=" * 80)
print("COMPARING PREDICTIONS vs ACTUAL SWITCH CHANGES:")
print("=" * 80)

# Get switch history
yesterday_start = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

url = f"{HA_URL}/api/history/period/{yesterday_start.isoformat()}?filter_entity_id={os.getenv('CENTRAL_HEATING_SHUTOFF_SWITCH', 'switch.shelly1minig3_5432045dd3f0_switch_0')}&end_time={today_start.isoformat()}"
resp = requests.get(url, headers=headers, timeout=10)
resp.raise_for_status()
history = resp.json()

switch_changes = []
if history and len(history) > 0:
    for state in history[0]:
        timestamp = state.get('last_changed')
        value = state.get('state')
        switch_changes.append({'timestamp': timestamp, 'value': value})

print(f"\nSwitch actually changed {len(switch_changes)} times:")
for change in switch_changes:
    ts_utc = datetime.fromisoformat(change['timestamp'].replace('Z', '+00:00'))
    ts_local = ts_utc.astimezone(tz)
    action = "BLOCKED heating" if change['value'] == "on" else "ALLOWED heating"
    print(f"  {ts_local.strftime('%H:%M:%S')}  {action}")

# Predict what the decisions should have caused
print(f"\nPredicted switch transitions from cron decisions:")
current_state = None
for i, decision in enumerate(decision_history):
    should_run = decision['decision'] == "HEAT"
    expected_switch_state = "off" if should_run else "on"
    
    # Check if this differs from previous
    if i == 0 or decision_history[i-1]['decision'] != decision['decision']:
        print(f"  {decision['time']}  → {decision['decision']:5s}  (switch should be: {expected_switch_state})")

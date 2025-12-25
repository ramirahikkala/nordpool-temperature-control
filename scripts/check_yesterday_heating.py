"""Check yesterday's central heating decisions against actual prices.

Fetches:
1. Yesterday's prices (96 quarters)
2. Yesterday's central heating switch history
3. Runs should_central_heating_run() logic for each quarter
4. Shows: predicted decision vs actual switch state vs prices

This helps verify the logic matches reality.
"""

import json
import sys
import os
from datetime import datetime, timedelta, timezone

# Load env BEFORE importing main
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, '/home/rami/omat/ha_rest_api/ha-api-test')

import requests

HA_URL = os.getenv("HA_URL", "https://ha.ketunmetsa.fi")
HA_TOKEN = os.getenv("HA_API_TOKEN")
PRICE_SENSOR = os.getenv("PRICE_SENSOR", "sensor.nordpool_kwh_fi_eur_3_10_0255")
CENTRAL_HEATING_SWITCH = os.getenv("CENTRAL_HEATING_SHUTOFF_SWITCH", "switch.shelly1minig3_5432045dd3f0_switch_0")

if not HA_TOKEN:
    print("ERROR: HA_API_TOKEN not set")
    sys.exit(1)

from main import should_central_heating_run, MAX_SHUTOFF_HOURS, PRICE_ALWAYS_ON_THRESHOLD

headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


def fetch_yesterday_prices():
    """Get yesterday's prices (raw_today attribute)."""
    yesterday_noon = (datetime.now() - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    url = f"{HA_URL}/api/history/period/{yesterday_noon.isoformat()}?filter_entity_id={PRICE_SENSOR}&end_time={yesterday_noon.replace(minute=1).isoformat()}"
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    history = resp.json()
    if history and len(history) > 0 and len(history[0]) > 0:
        state = history[0][0]
        raw_today = state.get('attributes', {}).get('raw_today', [])
        if raw_today and len(raw_today) == 96:
            return [float(entry['value']) for entry in raw_today]
    return None


def fetch_yesterday_switch_history():
    """Get yesterday's central heating switch state changes."""
    yesterday_start = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    url = f"{HA_URL}/api/history/period/{yesterday_start.isoformat()}?filter_entity_id={CENTRAL_HEATING_SWITCH}&end_time={today_start.isoformat()}"
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    history = resp.json()
    
    changes = []
    if history and len(history) > 0:
        for state in history[0]:
            timestamp = state.get('last_changed')
            value = state.get('state')
            changes.append({'timestamp': timestamp, 'value': value})
    return changes


def get_switch_state_at_time(changes, target_time):
    """Get switch state at a specific time from change history."""
    relevant = [c for c in changes if c['timestamp'] <= target_time]
    if relevant:
        state = relevant[-1]['value']
        # DEBUG
        # print(f"  Time {target_time}: Found {len(relevant)} relevant changes, latest={state}")
        return state
    return None


def main():
    print("=" * 80)
    print("YESTERDAY'S CENTRAL HEATING ANALYSIS")
    print("=" * 80)
    
    prices = fetch_yesterday_prices()
    if not prices:
        print("ERROR: Could not fetch yesterday's prices")
        return
    
    history = fetch_yesterday_switch_history()
    if not history:
        print("ERROR: Could not fetch yesterday's switch history")
        return
    
    print(f"\nConfig:")
    print(f"  MAX_SHUTOFF_HOURS: {MAX_SHUTOFF_HOURS}")
    print(f"  PRICE_ALWAYS_ON_THRESHOLD: {PRICE_ALWAYS_ON_THRESHOLD}")
    print(f"  Total price changes: {len(history)}")
    
    print(f"\nPrice changes yesterday:")
    for change in history:  # All changes
        print(f"  {change['timestamp']}: {change['value']}")
    
    print(f"\nHourly analysis (06:00 - 12:00):")
    print("Time   Price  Logic Pred  Actual  Match")
    print("-" * 50)
    
    yesterday = datetime.now() - timedelta(days=1)
    
    for hour in range(6, 13):
        for quarter in range(4):
            i = hour * 4 + quarter
            h, m = i // 4, (i % 4) * 15
            
            price = prices[i]
            should_run, reason = should_central_heating_run(price, prices)
            logic_pred = "ON" if should_run else "OFF"
            
            # Get actual switch state at this time
            quarter_time = yesterday.replace(hour=h, minute=m, second=0, microsecond=0)
            quarter_time_iso = quarter_time.isoformat()
            actual_state = get_switch_state_at_time(history, quarter_time_iso)
            
            # Switch state is inverted: ON=blocked (heating OFF), OFF=heating ON
            actual_heating = "OFF" if actual_state == "on" else ("ON" if actual_state == "off" else "???")
            
            match = "✓" if logic_pred == actual_heating else "✗ MISMATCH"
            
            print(f"{h:02d}:{m:02d}  {price:5.2f}  {logic_pred:8s}  {actual_heating:7s}  {match}")
    
    print("\n" + "=" * 80)
    print("KEY:")
    print("  Logic Pred: What should_central_heating_run() predicts")
    print("  Actual: What the switch was actually in (derived from history)")
    print("  Switch ON = heating blocked (OFF), Switch OFF = heating runs (ON)")
    print("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

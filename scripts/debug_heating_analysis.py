"""Debug version of heating analysis with detailed timestamp logging."""

import json
import sys
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


def parse_timestamp(ts_str):
    """Parse ISO timestamp string to local datetime."""
    # Parse ISO format
    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    # Convert to local timezone (EET = UTC+2)
    eet = ZoneInfo("Europe/Helsinki")
    return dt.astimezone(eet)


def main():
    print("=" * 80)
    print("DEBUG: HEATING ANALYSIS WITH TIMESTAMPS")
    print("=" * 80)
    
    prices = fetch_yesterday_prices()
    if not prices:
        print("ERROR: Could not fetch yesterday's prices")
        return
    
    history = fetch_yesterday_switch_history()
    if not history:
        print("ERROR: Could not fetch yesterday's switch history")
        return
    
    print(f"\nSwitch history (raw timestamps):")
    for change in history:
        utc_ts = change['timestamp']
        local_ts = parse_timestamp(utc_ts)
        print(f"  {utc_ts}")
        print(f"    → Local: {local_ts.strftime('%Y-%m-%d %H:%M:%S %Z')} = {change['value']}")
    
    print(f"\nParsing analysis for 07:00-12:00 local time:")
    print("=" * 80)
    
    # Get yesterday's date in local time
    tz = ZoneInfo("Europe/Helsinki")
    now_local = datetime.now(tz)
    yesterday_local = now_local - timedelta(days=1)
    
    for hour in range(7, 13):
        for quarter in range(4):
            i = hour * 4 + quarter
            m = quarter * 15
            
            # Create local time
            quarter_local = yesterday_local.replace(hour=hour, minute=m, second=0, microsecond=0)
            quarter_local_str = quarter_local.strftime('%Y-%m-%d %H:%M:%S')
            
            price = prices[i]
            should_run, reason = should_central_heating_run(price, prices)
            logic_pred = "HEAT" if should_run else "BLOCK"
            
            # Find state at this time
            # Compare against local times of changes
            state_at_time = None
            for change in history:
                change_local = parse_timestamp(change['timestamp'])
                if change_local <= quarter_local:
                    state_at_time = change['value']
            
            actual_heating = "HEAT" if state_at_time == "off" else ("BLOCK" if state_at_time == "on" else "???")
            
            match = "✓" if logic_pred == actual_heating else "✗ MISMATCH"
            
            print(f"{hour:02d}:{m:02d}  Price {price:5.2f}  Logic: {logic_pred:5s}  Actual: {actual_heating:5s}  {match}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

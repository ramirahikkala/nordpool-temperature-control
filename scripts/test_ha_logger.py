"""Diagnostic script to check why logs aren't appearing."""

import sys
import os
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("HEATING SYSTEM DIAGNOSTIC")
print("=" * 80)

# Check 1: Environment variables
print("\n[CHECK 1] Environment Variables:")
print("-" * 80)

required_vars = [
    "HA_URL",
    "HA_API_TOKEN",
    "CENTRAL_HEATING_SHUTOFF_SWITCH",
    "TEMPERATURE_SENSOR"
]

for var in required_vars:
    value = os.getenv(var)
    if value:
        # Mask sensitive values
        if "TOKEN" in var:
            print(f"  ✓ {var}: {'*' * 10}")
        else:
            print(f"  ✓ {var}: {value}")
    else:
        print(f"  ✗ {var}: NOT SET")

# Check 2: Configuration values
print("\n[CHECK 2] Heating Control Configuration:")
print("-" * 80)

sys.path.insert(0, '/home/rami/omat/ha_rest_api/ha-api-test')

try:
    from main import (
        CENTRAL_HEATING_SHUTOFF_SWITCH,
        MAX_SHUTOFF_HOURS,
        PRICE_ALWAYS_ON_THRESHOLD,
    )
    
    if CENTRAL_HEATING_SHUTOFF_SWITCH:
        print(f"  ✓ Central heating is CONFIGURED")
        print(f"    - Switch entity: {CENTRAL_HEATING_SHUTOFF_SWITCH}")
        print(f"    - Max shutoff: {MAX_SHUTOFF_HOURS}h")
        print(f"    - Always-on threshold: {PRICE_ALWAYS_ON_THRESHOLD} c/kWh")
    else:
        print(f"  ✗ Central heating is NOT CONFIGURED (CENTRAL_HEATING_SHUTOFF_SWITCH not set)")
        print(f"    - Logs won't appear because log_heating_decision_to_ha() returns early if not configured")
except Exception as e:
    print(f"  ✗ Error importing config: {e}")

# Check 3: Can we connect to HA?
print("\n[CHECK 3] Home Assistant Connectivity:")
print("-" * 80)

try:
    import requests
    ha_url = os.getenv("HA_URL", "https://ha.ketunmetsa.fi")
    ha_token = os.getenv("HA_API_TOKEN")
    
    if not ha_token:
        print(f"  ✗ No HA_API_TOKEN configured")
    else:
        headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
        
        # Try to reach HA
        try:
            response = requests.get(f"{ha_url}/api/", headers=headers, timeout=5)
            if response.status_code == 200:
                print(f"  ✓ Connected to HA at {ha_url}")
                print(f"    - API response: 200 OK")
            else:
                print(f"  ✗ HA API returned status {response.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"  ✗ Cannot connect to HA at {ha_url}")
        except requests.exceptions.Timeout:
            print(f"  ✗ Connection to HA timed out")
except Exception as e:
    print(f"  ✗ Error checking HA connectivity: {e}")

# Check 4: Test the logging function
print("\n[CHECK 4] Testing Logging Function:")
print("-" * 80)

try:
    from main import log_heating_decision_to_ha
    
    print("  Testing log_heating_decision_to_ha()...")
    log_heating_decision_to_ha(False, "Test: In top-24 expensive quarters (rank ~11)", 6.29)
    print("  ✓ Logging function executed (check output above for [HEATING_DECISION])")
except Exception as e:
    print(f"  ✗ Error executing logging function: {e}")
    import traceback
    traceback.print_exc()

# Check 5: Cron status
print("\n[CHECK 5] Cron/Scheduler Status:")
print("-" * 80)

try:
    # Try to import APScheduler and check if it's working
    from apscheduler.schedulers.background import BackgroundScheduler
    print(f"  ✓ APScheduler is available")
    print(f"    - Location: {BackgroundScheduler.__module__}")
except ImportError:
    print(f"  ✗ APScheduler not available")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print("""
Logs appear in these places:

1. **Application stdout** (docker logs or direct console output)
   - Look for lines starting with: [HEATING_DECISION]
   - Command: docker logs -f your-container | grep HEATING_DECISION

2. **HA input_text entity** (if configured)
   - Entity: input_text.heating_decision_log
   - Only updated if entity exists in HA

If you don't see [HEATING_DECISION] logs:

1. Check if CENTRAL_HEATING_SHUTOFF_SWITCH is set
2. Check if the application is actually running
3. Verify the cron job is executing (should run at :00, :15, :30, :45 each hour)
4. Look for any Python errors in the application logs
""")
print("=" * 80)

"""Test the updated HA logging locally."""

import sys
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, '/home/rami/omat/ha_rest_api/ha-api-test')

# Import the logging function
from main import log_heating_decision_to_ha

print("=" * 80)
print("TESTING UPDATED LOGGING FUNCTION")
print("=" * 80)

# Test scenarios
test_cases = [
    (True, "Price 3.39 c/kWh < threshold 5.00 c/kWh (always on)", 3.39),
    (False, "In top-24 expensive quarters (rank ~11, price 6.29 c/kWh)", 6.29),
    (True, "Price 0.78 c/kWh < threshold 5.00 c/kWh (always on)", 0.78),
    (False, "In top-24 expensive quarters (rank ~1, price 9.23 c/kWh)", 9.23),
]

print("\nTest outputs (will appear in logs with [HEATING_DECISION] label):\n")

for should_run, reason, price in test_cases:
    print(f"Calling log_heating_decision_to_ha({should_run}, '{reason[:40]}...', {price})")
    log_heating_decision_to_ha(should_run, reason, price)
    print()

print("=" * 80)
print("If you see '[HEATING_DECISION]' messages above, logging is working!")
print("=" * 80)

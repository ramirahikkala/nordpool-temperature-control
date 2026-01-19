#!/usr/bin/env python3
"""Test the switch history logic with simulated data."""

from datetime import datetime, timedelta, timezone
import pytz

# Simulate the logic
local_tz = pytz.timezone('Europe/Helsinki')

# Simulated state changes (already converted to local time)
# Scenario: heater ON for 9:06-11:45 on Dec 27, then OFF after
simulated_changes = [
    ("2025-12-27 09:06:00", "on"),   # Heater turns on
    ("2025-12-27 11:45:00", "off"),  # Heater turns off
    ("2025-12-27 23:00:00", "on"),   # Heater turns on again
    ("2025-12-28 01:00:00", "off"),  # Heater turns off (this is in our 24h window!)
    ("2025-12-28 05:00:00", "on"),   # Heater turns on (this is in our 24h window!)
]

# Parse to datetime objects with local timezone
points = []
for ts_str, state in simulated_changes:
    # Parse naive datetime and add local timezone
    naive_dt = datetime.fromisoformat(ts_str)
    dt_local = local_tz.localize(naive_dt)
    points.append({"ts": dt_local, "state": state})

# Current time: Dec 28 07:47
now = local_tz.localize(datetime(2025, 12, 28, 7, 47, 0))
target_date_end = now
target_date_start = target_date_end - timedelta(hours=24)

print(f"Period: {target_date_start} to {target_date_end}")
print(f"Period length: {(target_date_end - target_date_start).total_seconds() / 3600} hours\n")

# Find initial state
state_at_period_start = 'off'
for p in points:
    if p['ts'] <= target_date_start:
        state_at_period_start = p['state']
        print(f"State at/before start: {p['ts']} = {p['state']}")
    else:
        break

print(f"Initial state for period: {state_at_period_start}\n")

# Initialize quarters
quarters = [state_at_period_start] * 96

# Apply state changes during period
print("State changes in period:")
for p in points:
    if not (target_date_start < p['ts'] <= target_date_end):
        continue
    
    print(f"  {p['ts']} -> {p['state']}")
    
    # Calculate quarter index
    time_into_period = p['ts'] - target_date_start
    minutes_into_period = int(time_into_period.total_seconds() / 60)
    quarter_idx = minutes_into_period // 15
    
    print(f"    Minutes into period: {minutes_into_period}, Quarter: {quarter_idx}")
    
    # From this quarter onwards, use new state
    for i in range(quarter_idx, 96):
        quarters[i] = p['state']

# Display result
print("\nQuarters visualization (X=on, .=off):")
for i in range(0, 96, 4):
    chunk = ''.join(['X' if q == 'on' else '.' for q in quarters[i:i+4]])
    hour = target_date_start.hour + (i * 15) // 60
    minute = (i * 15) % 60
    print(f"  Q{i:2d}-{i+3:2d} ({hour:02d}:{minute:02d}): {chunk}")

# Summary
on_count = sum(1 for q in quarters if q == 'on')
off_count = sum(1 for q in quarters if q == 'off')
print(f"\nSummary: {on_count} quarters ON, {off_count} quarters OFF")

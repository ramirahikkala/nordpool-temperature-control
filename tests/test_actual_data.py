#!/usr/bin/env python3
"""Test with ACTUAL HA data."""

from datetime import datetime, timedelta, timezone
import pytz

local_tz = pytz.timezone('Europe/Helsinki')

# ACTUAL state changes from HA (converted to local times)
actual_changes = [
    ("2025-12-27T07:06:50.597195", "on"),   # 09:06 local - heater ON
    ("2025-12-27T09:45:00.455001", "off"),  # 11:45 local - heater OFF
    ("2025-12-27T21:00:00.541160", "on"),   # 23:00 local - heater ON
]

# Parse to datetime objects with local timezone
points = []
for ts_str, state in actual_changes:
    # Parse UTC timestamp  
    naive_dt = datetime.fromisoformat(ts_str)
    dt_utc = naive_dt.replace(tzinfo=timezone.utc)
    dt_local = dt_utc.astimezone(local_tz)
    points.append({"ts": dt_local, "state": state})
    print(f"  {ts_str} UTC -> {dt_local} local = {state}")

print()

# Current time: Dec 28 07:47
now = local_tz.localize(datetime(2025, 12, 28, 7, 47, 0))
target_date_end = now
target_date_start = target_date_end - timedelta(hours=24)

print(f"Period: {target_date_start} to {target_date_end}")
print(f"Period length: {(target_date_end - target_date_start).total_seconds() / 3600} hours\n")

# Find initial state (state before period starts)
state_at_period_start = 'off'
for p in points:
    if p['ts'] <= target_date_start:
        state_at_period_start = p['state']
        print(f"Found state at/before start: {p['ts']} = {p['state']}")
    else:
        print(f"Point after start, stopping search: {p['ts']} = {p['state']}")
        break

print(f"Initial state for period: {state_at_period_start}\n")

# Initialize quarters
quarters = [state_at_period_start] * 96

# Apply state changes during period
print("State changes DURING period:")
for p in points:
    if not (target_date_start < p['ts'] <= target_date_end):
        print(f"  {p['ts']} -> OUTSIDE period")
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
    offset_hours = (i * 15) // 60
    offset_mins = (i * 15) % 60
    display_time = target_date_start + timedelta(hours=offset_hours, minutes=offset_mins)
    print(f"  Q{i:2d}-{i+3:2d} ({display_time.strftime('%H:%M')}): {chunk}")

# Summary
on_count = sum(1 for q in quarters if q == 'on')
off_count = sum(1 for q in quarters if q == 'off')
print(f"\nSummary: {on_count} quarters ON, {off_count} quarters OFF")
print(f"Expected for correct data: ~15 ON (09:45-21:00 is ~11h15min = 45 quarters OFF)")

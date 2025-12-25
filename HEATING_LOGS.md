# Heating Decision Logging

The system logs every heating decision with a clear label: `[HEATING_DECISION]`. Each decision includes timestamp, action (HEAT/BLOCK), price, and reason.

## Example Log Format

```
2025-12-24 08:15:01 - INFO - [HEATING_DECISION] BLOCK 08:15:01 @ 6.29 c/kWh | In top-24 expensive quarters (rank ~11)
2025-12-24 08:30:01 - INFO - [HEATING_DECISION] BLOCK 08:30:01 @ 6.99 c/kWh | In top-24 expensive quarters (rank ~8)
2025-12-24 08:45:01 - INFO - [HEATING_DECISION] BLOCK 08:45:01 @ 8.80 c/kWh | In top-24 expensive quarters (rank ~2)
2025-12-24 09:00:01 - INFO - [HEATING_DECISION] BLOCK 09:00:01 @ 7.08 c/kWh | In top-24 expensive quarters (rank ~7)
```

## How to View Logs

### Option 1: Docker Container Logs (Easiest)
If running in Docker, view logs with:
```bash
docker logs -f ha-api-test
# or with filtering
docker logs -f ha-api-test | grep HEATING_DECISION
```

### Option 2: Check Application Logs on Server
```bash
# If running directly (not Docker)
tail -f /path/to/logs/heating.log | grep HEATING_DECISION
```

### Option 3: Home Assistant UI
1. Go to **Settings** → **Developer Tools** → **Logs**
2. Scroll to find entries with `[HEATING_DECISION]`
3. If Home Assistant environment variable `input_text.heating_decision_log` is configured, the latest decision will update there

## Log Entry Breakdown

Each log entry shows:

| Component | Example | Meaning |
|-----------|---------|---------|
| Timestamp | `2025-12-24 08:15:01` | When decision was made (HH:MM:SS) |
| Label | `[HEATING_DECISION]` | Identifies this as a heating decision |
| Decision | `BLOCK` or `HEAT` | BLOCK = heating OFF, HEAT = heating ON |
| Time (repeat) | `08:15:01` | Redundant timestamp for grepping |
| Price | `@ 6.29 c/kWh` | Current electricity price |
| Reason | `In top-24 expensive quarters (rank ~11)` | Why that decision was made |

## Decision Types

### HEAT Messages
Heating is allowed to run. Examples:
```
[HEATING_DECISION] HEAT 12:30:01 @ 3.39 c/kWh | Price 3.39 c/kWh < threshold 5.00 c/kWh (always on)
[HEATING_DECISION] HEAT 14:15:01 @ 0.78 c/kWh | Price 0.78 c/kWh < threshold 5.00 c/kWh (always on)
```

### BLOCK Messages
Heating is blocked (switch turned on). Examples:
```
[HEATING_DECISION] BLOCK 08:15:01 @ 6.29 c/kWh | In top-24 expensive quarters (rank ~11, price 6.29 c/kWh)
[HEATING_DECISION] BLOCK 11:00:01 @ 9.23 c/kWh | In top-24 expensive quarters (rank ~1, price 9.23 c/kWh)
```

## Frequency

- Logs appear **exactly 4 times per hour** (at :00, :15, :30, :45 minutes)
- One entry per cron execution
- Total: **96 entries per day** (24 hours × 4 quarters)

## Filtering Logs

### Command Line (grep)
```bash
# Show only BLOCK decisions
docker logs ha-api-test | grep "HEATING_DECISION.*BLOCK"

# Show only HEAT decisions
docker logs ha-api-test | grep "HEATING_DECISION.*HEAT"

# Show expensive periods (prices > 10 c/kWh)
docker logs ha-api-test | grep "HEATING_DECISION" | grep -E "@ [0-9]{2}\.[0-9]{2}"

# Show decisions from specific hour
docker logs ha-api-test | grep "HEATING_DECISION" | grep "14:.*BLOCK"
```

### Searching for Price Ranges
```bash
# Show very cheap periods (< 1 c/kWh)
docker logs ha-api-test | grep "HEATING_DECISION.*@ 0\\.[0-9]"

# Show expensive periods (> 8 c/kWh)
docker logs ha-api-test | grep "HEATING_DECISION.*@ [89]\\.[0-9]"
```

## Testing Locally

To test the logging system before full deployment:
```bash
python scripts/test_logging_local.py
```

This will generate 4 sample log entries with the correct format.

## Optional: Home Assistant Integration

To display the last heating decision in Home Assistant UI, create this in your `configuration.yaml`:

```yaml
input_text:
  heating_decision_log:
    name: "Last Heating Decision"
    icon: mdi:heating-coil
```

Then in a dashboard, add a card to display `input_text.heating_decision_log` to see the real-time decision.

## Troubleshooting

### No Logs Appearing?
1. Check that the cron job is actually running (should run at :00, :15, :30, :45)
2. Verify that `CENTRAL_HEATING_SHUTOFF_SWITCH` environment variable is set
3. Check application start logs for any configuration errors
4. Review the full application logs for errors before the decision time

### Logs Appearing But Not Updating?
1. The cron job may not be running - check APScheduler status
2. The HA API may be unreachable - check connectivity to `HA_URL`
3. Check for any Python exceptions in the logs

### Can't Filter/Search Logs?
Each log entry contains `[HEATING_DECISION]` which is consistent and easy to grep/search for:
```bash
docker logs ha-api-test 2>&1 | grep HEATING_DECISION
```


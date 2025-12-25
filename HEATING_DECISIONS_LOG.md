# Heating Decision Logging - Local File Storage

The system now logs all heating decisions to a local JSON file and displays them in the web dashboard.

## How It Works

1. **Decision Storage**: Every 15 minutes when the cron job runs, the decision is logged to `data/heating_decisions.jsonl`
2. **Automatic Rotation**: Only today's and yesterday's decisions are kept (older logs are deleted)
3. **Web API**: Access via `/api/heating-decisions` REST endpoint
4. **Web UI**: Display in the dashboard with color-coded decisions

## Viewing Decisions

### Via Web Dashboard
1. Open the web UI (default: `http://localhost:5000`)
2. Look for the "📋 Keskuslämmityksen päätökset" (Heating Decisions) card
3. View the last 20 decisions with:
   - Time of decision
   - HEAT (🔥) or BLOCK (❄️) action
   - Price at decision time
   - Reason for the decision

### Via API
```bash
# Get last 20 decisions
curl http://localhost:5000/api/heating-decisions?limit=20

# Get all decisions
curl http://localhost:5000/api/heating-decisions

# Get decisions from specific date
curl http://localhost:5000/api/heating-decisions?date=2025-12-24

# Limit results
curl http://localhost:5000/api/heating-decisions?limit=10
```

Response format:
```json
{
  "decisions": [
    {
      "timestamp": "2025-12-25T08:30:50.012266+02:00",
      "decision": "BLOCK",
      "price": 9.23,
      "reason": "In top-24 expensive quarters (rank ~1, price 9.23 c/kWh)"
    },
    {
      "timestamp": "2025-12-25T08:30:50.011100+02:00",
      "decision": "HEAT",
      "price": 3.39,
      "reason": "Price 3.39 c/kWh < threshold 5.00 c/kWh (always on)"
    }
  ],
  "count": 2
}
```

### Via Command Line
```bash
# View raw log file
cat data/heating_decisions.jsonl

# Pretty print
cat data/heating_decisions.jsonl | python3 -m json.tool

# Count decisions by type
cat data/heating_decisions.jsonl | grep -c '"decision": "HEAT"'
cat data/heating_decisions.jsonl | grep -c '"decision": "BLOCK"'

# Get latest 10 decisions
tail -10 data/heating_decisions.jsonl
```

## File Storage Details

### Location
`data/heating_decisions.jsonl`

### Format
JSONL (JSON Lines) - one decision object per line:
```json
{"timestamp": "2025-12-25T08:30:50.012266+02:00", "decision": "BLOCK", "price": 9.23, "reason": "..."}
{"timestamp": "2025-12-25T08:30:50.011100+02:00", "decision": "HEAT", "price": 3.39, "reason": "..."}
```

### Rotation Policy
- **Keeps**: Today's + Yesterday's decisions (48 hours)
- **Deletes**: Anything older than 2 days
- **When**: Automatically checked after each decision is logged
- **Format**: ISO 8601 timestamp with local timezone

### Size Estimate
- 96 decisions per day (every 15 minutes × 24 hours)
- ~200 bytes per decision (avg)
- ~19 KB per day
- ~38 KB total (2 days kept)

## Decision Types

### HEAT 🔥
Heating is allowed to run. Appears when:
- Price is below `PRICE_ALWAYS_ON_THRESHOLD` (default: 5.0 c/kWh)
- Any other time outside expensive periods

### BLOCK ❄️
Heating is blocked (switch turned ON, which blocks central heating). Appears when:
- Current price is in the top N most expensive quarters
- Where N = `MAX_SHUTOFF_HOURS` × 4 (e.g., 6 hours × 4 = 24 quarters)

## Implementation Details

### Code Location
- **Logger module**: `heating_logger.py`
- **Main integration**: `main.py` - calls `log_decision_to_file()` after each decision
- **Web API**: `web_app.py` - `/api/heating-decisions` endpoint
- **UI display**: `templates/index.html` - decision card + JavaScript

### Key Functions

#### heating_logger.py
```python
log_heating_decision(should_run, reason, current_price)
  # Log a single decision to file

get_decisions(limit=None)
  # Get all decisions (most recent first)

get_decisions_by_date(date_str)
  # Get decisions for specific date (YYYY-MM-DD)

rotate_old_logs()
  # Remove decisions older than 2 days (automatic)
```

#### main.py
```python
log_heating_decision_to_ha(should_run, reason, current_price)
  # Main integration point
  # Logs to both stdout (console) and local file
  # Called immediately after each control decision
```

## Testing

```bash
# Test logging locally
python scripts/test_logging_local.py

# Check what's in the log file
python3 -c "from heating_logger import get_decisions; import json; print(json.dumps(get_decisions(), indent=2))"

# Test API endpoint
curl http://localhost:5000/api/heating-decisions?limit=5 | python3 -m json.tool

# Clear all logs (for testing/reset)
python3 -c "from heating_logger import clear_all_logs; clear_all_logs()"
```

## Troubleshooting

### No Decisions Showing in Web UI?
1. **Check file exists**: `ls -la data/heating_decisions.jsonl`
2. **Check permissions**: File should be readable by the app
3. **Check API**: `curl http://localhost:5000/api/heating-decisions`
4. **Check app logs**: Look for `[HEATING_DECISION]` messages

### Decisions Not Being Logged?
1. **Check CENTRAL_HEATING_SHUTOFF_SWITCH** is configured in .env
2. **Check app is running**: `docker ps | grep ha-api-test`
3. **Check cron schedule**: Should run every 15 minutes at :00, :15, :30, :45
4. **Check for errors**: `docker logs your-container | grep -i error`

### File Growing Too Large?
1. Rotation should keep max 2 days
2. Check rotation is working: `wc -l data/heating_decisions.jsonl`
3. If file is large, manually clean: `python3 -c "from heating_logger import clear_all_logs; clear_all_logs()"`

### Wrong Decisions Showing?
1. **Verify decision logic**: Check the `should_central_heating_run()` function output
2. **Test with script**: `python scripts/test_logging_local.py`
3. **Check reason field**: Should explain the logic

## Data Export

To export decisions for analysis:

```bash
# Export as CSV
python3 << 'EOF'
import json
import csv
from heating_logger import get_decisions

decisions = get_decisions()
with open('heating_decisions_export.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['timestamp', 'decision', 'price', 'reason'])
    writer.writeheader()
    writer.writerows(decisions)
print(f"Exported {len(decisions)} decisions to heating_decisions_export.csv")
EOF

# Export as JSON
python3 -c "from heating_logger import get_decisions; import json; print(json.dumps(get_decisions(), indent=2))" > decisions_export.json
```

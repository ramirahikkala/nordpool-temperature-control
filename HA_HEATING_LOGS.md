# How to View Heating Decision Logs in Home Assistant

## The Logs ARE Being Generated ✅

The heating system is logging decisions with the `[HEATING_DECISION]` label. They appear in **two places**:

### 1. Application Logs (Always Available)
View in docker/container output:
```bash
docker logs -f your-container | grep HEATING_DECISION
```

Output example:
```
2025-12-25 08:24:18 - INFO - [HEATING_DECISION] BLOCK 08:24:18 @ 6.29 c/kWh | In top-24 expensive quarters
```

### 2. Home Assistant UI (If Configured)
To see logs in your HA dashboard, you need to create an `input_text` entity.

## Setup: Add input_text Entity to HA

Edit your HA `configuration.yaml` or use the UI:

**Option A: Via YAML (configuration.yaml)**
```yaml
input_text:
  heating_decision_log:
    name: "Last Heating Decision"
    icon: mdi:heating-coil
    max: 500
```

**Option B: Via HA UI**
1. Go to **Settings** → **Devices & Services** → **Helpers**
2. Click **Create Helper** → **Text**
3. Name: `Last Heating Decision`
4. Entity ID: `heating_decision_log`
5. Max length: 500
6. Save

## View in HA

After creating the entity, the latest decision will update there automatically. You can:

1. **View in Developer Tools:**
   - Go to **Developer Tools** → **States**
   - Search for `input_text.heating_decision_log`
   - See the latest decision

2. **View on Dashboard:**
   - Create a new dashboard card
   - Choose **Entities** card
   - Add `input_text.heating_decision_log`
   - See real-time decision updates

3. **View in History:**
   - Click on the entity in Developer Tools
   - Click **History** to see all past decisions

## Example Dashboard Card

Create a dashboard card with this YAML:

```yaml
type: entities
title: Heating Decisions
show_header_toggle: false
entities:
  - entity: input_text.heating_decision_log
    name: Last Decision
```

## What You'll See

Every 15 minutes (at :00, :15, :30, :45), the entity will update with:

```
[HEATING_DECISION] BLOCK 08:24:18 @ 6.29 c/kWh | In top-24 expensive quarters (rank ~11)
```

Breaking it down:
- **[HEATING_DECISION]**: Label identifying this as a heating decision
- **BLOCK/HEAT**: Decision (BLOCK = turn off heating, HEAT = allow heating)
- **08:24:18**: Time of decision
- **@ 6.29 c/kWh**: Current electricity price
- **Reason**: Why that decision was made

## Decision History

To see a history of all decisions:

1. In HA, go to **Settings** → **Developer Tools** → **Statistics**
2. Select `input_text.heating_decision_log`
3. View historical changes

Or via CLI:
```bash
# Get all changes (last 10)
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-ha-url/api/history/period/TIMESTAMP \
  | grep -i heating
```

## Troubleshooting

### Entity Won't Update?
1. **Check entity exists:** Developer Tools → States, search for `heating_decision_log`
2. **Check logs:** `docker logs | grep "HEATING_DECISION"`
3. **Verify app is running:** `docker ps | grep ha-api-test`

### Not Seeing Any Decisions?
1. Entity might not exist - create it using instructions above
2. App might not be running at :00, :15, :30, :45 - check cron
3. Check full logs: `docker logs your-container | tail -100`

### Want to See Historical Decisions?
Use the analysis scripts:
```bash
python scripts/check_yesterday_heating.py
python scripts/simulate_cron_yesterday.py
```

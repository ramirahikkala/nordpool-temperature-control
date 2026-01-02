"""
Web GUI for Temperature Control System
"""
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from flask_caching import Cache
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import requests
import threading
import time

# Import functions from main.py
from main import (
    get_base_temperature,
    get_current_price,
    get_current_temperature,
    get_setpoint_temperature,
    get_daily_prices,
    should_central_heating_run,
    HA_URL,
    headers,
    PRICE_SENSOR,
    SWITCH_ENTITY,
    TEMPERATURE_SENSOR,
    CENTRAL_HEATING_SHUTOFF_SWITCH,
    BASE_TEMPERATURE_FALLBACK,
    BASE_TEMPERATURE_INPUT,
    MAX_SHUTOFF_HOURS,
    PRICE_ALWAYS_ON_THRESHOLD,
    PRICE_LOW_THRESHOLD,
    PRICE_HIGH_THRESHOLD,
    TEMP_VARIATION,
    SETPOINT_OUTPUT,
)

# Import heating logger
from heating_logger import get_decisions, get_decisions_by_date

load_dotenv()

# Outdoor temperature sensor (optional - leave empty to disable outdoor temp display)
OUTDOOR_TEMP_SENSOR = os.getenv("OUTDOOR_TEMP_SENSOR", "")


def get_yesterday_prices():
    """Get yesterday's prices from Nordpool sensor via history API.
    
    The Nordpool sensor's raw_today attribute is already indexed by local time,
    just like the 'today' and 'tomorrow' attributes.
    """
    try:
        from datetime import timedelta
        
        # Get yesterday at noon (to ensure we're in the middle of the day)
        yesterday_noon = (datetime.now() - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
        
        # Query history API for a single state from yesterday
        # The raw_today attribute from yesterday contains yesterday's full 96 prices
        url = f"{HA_URL}/api/history/period/{yesterday_noon.isoformat()}?filter_entity_id={PRICE_SENSOR}&end_time={yesterday_noon.replace(minute=1).isoformat()}"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            history_data = response.json()
            if history_data and len(history_data) > 0 and len(history_data[0]) > 0:
                # Get the first state entry
                state = history_data[0][0]
                raw_today = state.get('attributes', {}).get('raw_today', [])
                
                if raw_today and len(raw_today) == 96:
                    # Extract just the values from the raw_today array
                    # Data is already in local time format, no rotation needed
                    prices = [entry['value'] for entry in raw_today]
                    return prices
        
        return None
    except Exception as e:
        print(f"Error fetching yesterday prices: {e}")
        return None


def get_tomorrow_prices():
    """Get tomorrow's prices from Nordpool sensor if available."""
    try:
        response = requests.get(f"{HA_URL}/api/states/{PRICE_SENSOR}", headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            tomorrow_valid = data.get('attributes', {}).get('tomorrow_valid', False)
            if tomorrow_valid:
                tomorrow = data.get('attributes', {}).get('tomorrow', [])
                if tomorrow and len(tomorrow) == 96:
                    return tomorrow
        return None
    except Exception as e:
        print(f"Error fetching tomorrow prices: {e}")
        return None

def get_base_temperature_from_input():
    """Get base temperature from Home Assistant input_number entity."""
    if BASE_TEMPERATURE_INPUT:
        try:
            response = requests.get(f"{HA_URL}/api/states/{BASE_TEMPERATURE_INPUT}", headers=headers, timeout=5)
            if response.status_code == 200:
                state = response.json().get("state")
                if state:
                    temp = float(state)
                    print(f"Base temperature from HA ({BASE_TEMPERATURE_INPUT}): {temp}°C")
                    return temp
        except Exception as e:
            print(f"Error fetching base temperature from {BASE_TEMPERATURE_INPUT}: {e}")
    
    # Fallback to calculated base temperature
    base_temp = get_base_temperature()
    print(f"Using fallback base temperature: {base_temp}°C")
    return base_temp


app = Flask(__name__)
CORS(app)  # Enable CORS for API endpoints

# Initialize caching with 15-minute timeout for history data
# 15 minutes aligns with the control cycle frequency
# Using 'simple' in-memory cache (adequate with single gunicorn worker)
cache = Cache(app, config={'CACHE_TYPE': 'simple', 'CACHE_DEFAULT_TIMEOUT': 900})

# Track if cache warmer has been started (to prevent multiple instances)
_cache_warmer_started = False


def start_cache_warmer_once():
    """Start cache warmer only once, even if module is loaded multiple times."""
    global _cache_warmer_started
    if not _cache_warmer_started:
        thread = threading.Thread(target=warm_cache, daemon=True)
        thread.start()
        _cache_warmer_started = True


@app.route('/')
def index():
    """Render the main dashboard."""
    return render_template('index.html')


@app.route('/api/current-state')
@cache.cached(timeout=60, query_string=True)
def api_current_state():
    """Get current temperature, price, and setpoint.
    
    Returns: {temperature: float, price: float, setpoint: float, adjustment: float}
    Cached for 1 minute (real-time updates)
    """
    try:
        base_temp = get_base_temperature_from_input()
        current_price = get_current_price()
        current_temp = get_current_temperature()
        
        if current_price is None or current_temp is None:
            return jsonify({"error": "Failed to fetch sensor data"}), 500
        
        setpoint_temp, adjustment = get_setpoint_temperature(current_price, base_temp)
        
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "temperature": current_temp,
            "base_temperature": base_temp,
            "price": current_price,
            "setpoint": setpoint_temp,
            "adjustment": adjustment
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/switches-state')
@cache.cached(timeout=60, query_string=True)
def api_switches_state():
    """Get current state of all switches (room heater, central heating).
    
    Returns: {room_heater: {state, entity_id}, central_heating: {state, is_running, entity_id}}
    Cached for 1 minute (real-time updates)
    """
    try:
        result = {
            "timestamp": datetime.now().isoformat(),
            "switches": {}
        }
        
        # Room heater state
        if SWITCH_ENTITY:
            try:
                response = requests.get(f"{HA_URL}/api/states/{SWITCH_ENTITY}", headers=headers, timeout=5)
                if response.status_code == 200:
                    state = response.json().get("state")
                    result["switches"]["room_heater"] = {
                        "state": state,
                        "entity_id": SWITCH_ENTITY
                    }
            except Exception as e:
                print(f"Error fetching room heater state: {e}")
        
        # Central heating state
        if CENTRAL_HEATING_SHUTOFF_SWITCH:
            try:
                response = requests.get(f"{HA_URL}/api/states/{CENTRAL_HEATING_SHUTOFF_SWITCH}", headers=headers, timeout=5)
                if response.status_code == 200:
                    state = response.json().get("state")
                    # Inverted: OFF = running, ON = blocked
                    result["switches"]["central_heating"] = {
                        "state": state,
                        "is_running": (state == "off"),
                        "entity_id": CENTRAL_HEATING_SHUTOFF_SWITCH
                    }
            except Exception as e:
                print(f"Error fetching central heating state: {e}")
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/prices')
@cache.cached(timeout=900, query_string=True)
def api_prices():
    """Get electricity prices: today, yesterday, tomorrow.
    
    Returns: {current: float, daily_prices: [96], yesterday_prices: [96], tomorrow_prices: [96], daily_min: float, daily_max: float}
    Cached for 5 minutes
    """
    try:
        current_price = get_current_price()
        daily_prices = get_daily_prices()
        yesterday_prices = get_yesterday_prices()
        tomorrow_prices = get_tomorrow_prices()
        
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "current": current_price,
            "daily_prices": daily_prices,
            "yesterday_prices": yesterday_prices,
            "tomorrow_prices": tomorrow_prices,
            "daily_min": min(daily_prices) if daily_prices else None,
            "daily_max": max(daily_prices) if daily_prices else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/central-heating-decision')
@cache.cached(timeout=900, query_string=True)
def api_central_heating_decision():
    """Get central heating run/block decision logic.
    
    Returns: {should_run: bool, reason: str, current_price: float}
    Cached for 5 minutes
    """
    try:
        current_price = get_current_price()
        daily_prices = get_daily_prices()
        
        if not daily_prices or CENTRAL_HEATING_SHUTOFF_SWITCH is None:
            return jsonify({"should_run": None, "reason": "Insufficient data or not configured", "current_price": current_price}), 200
        
        should_run, reason = should_central_heating_run(current_price, daily_prices)
        
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "should_run": should_run,
            "reason": reason,
            "current_price": current_price
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/status')
@cache.cached(timeout=60, query_string=True)
def api_status():
    """Get combined current status (aggregates all focused endpoints).
    
    This endpoint combines data from multiple focused endpoints for convenience.
    For specific data, use dedicated endpoints: /api/current-state, /api/switches-state, /api/prices, /api/central-heating-decision
    
    Cached for 1 minute.
    """
    try:
        # Get all focused endpoint data
        base_temp = get_base_temperature_from_input()
        current_price = get_current_price()
        current_temp = get_current_temperature()
        
        if current_price is None or current_temp is None:
            return jsonify({"error": "Failed to fetch sensor data"}), 500
        
        setpoint_temp, adjustment = get_setpoint_temperature(current_price, base_temp)
        
        # Get outdoor temperature
        outdoor_temp = None
        try:
            response = requests.get(f"{HA_URL}/api/states/{OUTDOOR_TEMP_SENSOR}", headers=headers, timeout=5)
            if response.status_code == 200:
                outdoor_temp = float(response.json().get("state"))
        except Exception:
            pass
        
        # Get room heater switch state
        room_heater_state = None
        if SWITCH_ENTITY:
            try:
                response = requests.get(f"{HA_URL}/api/states/{SWITCH_ENTITY}", headers=headers, timeout=5)
                if response.status_code == 200:
                    room_heater_state = response.json().get("state")
            except Exception as e:
                print(f"Error fetching room heater state: {e}")
        
        # Get central heating switch state
        central_heating_state = None
        central_heating_running = None
        if CENTRAL_HEATING_SHUTOFF_SWITCH:
            try:
                response = requests.get(f"{HA_URL}/api/states/{CENTRAL_HEATING_SHUTOFF_SWITCH}", headers=headers, timeout=5)
                if response.status_code == 200:
                    central_heating_state = response.json().get("state")
                    # Inverted: OFF = running, ON = blocked
                    central_heating_running = (central_heating_state == "off")
            except Exception:
                pass
        
        # Get daily prices and central heating decision
        daily_prices = get_daily_prices()
        yesterday_prices = get_yesterday_prices()
        tomorrow_prices = get_tomorrow_prices()
        central_heating_decision = None
        if daily_prices and CENTRAL_HEATING_SHUTOFF_SWITCH:
            should_run, reason = should_central_heating_run(current_price, daily_prices)
            central_heating_decision = {
                "should_run": should_run,
                "reason": reason
            }
        
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "temperature": {
                "current": current_temp,
                "outdoor": outdoor_temp,
                "base": base_temp,
                "setpoint": setpoint_temp,
                "adjustment": adjustment
            },
            "price": {
                "current": current_price,
                "daily_prices": daily_prices,
                "yesterday_prices": yesterday_prices,
                "tomorrow_prices": tomorrow_prices,
                "daily_min": min(daily_prices) if daily_prices else None,
                "daily_max": max(daily_prices) if daily_prices else None
            },
            "switches": {
                "room_heater": {
                    "state": room_heater_state,
                    "entity_id": SWITCH_ENTITY
                },
                "central_heating": {
                    "shutoff_switch_state": central_heating_state,
                    "is_running": central_heating_running,
                    "entity_id": CENTRAL_HEATING_SHUTOFF_SWITCH,
                    "decision": central_heating_decision
                }
            },
            "config": {
                "base_temperature_fallback": BASE_TEMPERATURE_FALLBACK,
                "base_temperature_input": BASE_TEMPERATURE_INPUT,
                "max_shutoff_hours": MAX_SHUTOFF_HOURS,
                "price_always_on_threshold": PRICE_ALWAYS_ON_THRESHOLD,
                "price_low_threshold": PRICE_LOW_THRESHOLD,
                "price_high_threshold": PRICE_HIGH_THRESHOLD,
                "temp_variation": TEMP_VARIATION,
                "setpoint_output": SETPOINT_OUTPUT if 'SETPOINT_OUTPUT' in globals() else None
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/switch-history-debug')
def api_switch_history_debug():
    """Debug endpoint to show detailed processing of switch history."""
    try:
        from datetime import timedelta, timezone
        import pytz
        
        entity_id = request.args.get('entity_id')
        hours_str = request.args.get('hours', '24')
        
        if not entity_id:
            return jsonify({"error": "entity_id parameter required"}), 400
        
        try:
            hours = int(hours_str)
        except (ValueError, TypeError):
            hours = 24
        
        local_tz = pytz.timezone('Europe/Helsinki')
        
        # Fetch 72h of history
        now_utc = datetime.now(timezone.utc)
        lookback_hours = max(hours * 2 + 12, 72)
        start_utc = now_utc - timedelta(hours=lookback_hours)
        start_iso = start_utc.replace(tzinfo=None).isoformat()
        end_utc = now_utc + timedelta(hours=1)
        end_iso = end_utc.replace(tzinfo=None).isoformat()
        
        url = f"{HA_URL}/api/history/period/{start_iso}?filter_entity_id={entity_id}&end_time={end_iso}"
        resp = requests.get(url, headers=headers, timeout=60)
        
        if resp.status_code != 200:
            return jsonify({"error": f"HA API returned {resp.status_code}"}), 500
        
        history = resp.json()
        
        # Parse all state changes
        points = []
        raw_points = []
        if history and len(history) > 0 and len(history[0]) > 0:
            for s in history[0]:
                ts_str = s.get('last_changed')
                state = s.get('state')
                raw_points.append({"timestamp": ts_str, "state": state})
                try:
                    dt_utc = datetime.fromisoformat(ts_str)
                    if dt_utc.tzinfo is None:
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                    dt_local = dt_utc.astimezone(local_tz)
                    points.append({"ts": dt_local, "state": state})
                except Exception as e:
                    print(f"DEBUG: Error parsing {ts_str}: {e}")
        
        points.sort(key=lambda p: p['ts'])
        
        # Calculate period
        target_date_end = datetime.now(local_tz).replace(microsecond=0)
        target_date_start = target_date_end - timedelta(hours=hours)
        
        # Find initial state
        state_at_period_start = 'off'
        for p in points:
            if p['ts'] <= target_date_start:
                state_at_period_start = p['state']
            else:
                break
        
        # Count state changes in period
        changes_in_period = [p for p in points if target_date_start < p['ts'] <= target_date_end]
        
        return jsonify({
            "entity_id": entity_id,
            "hours": hours,
            "lookback_hours": lookback_hours,
            "period_start": target_date_start.isoformat(),
            "period_end": target_date_end.isoformat(),
            "state_at_period_start": state_at_period_start,
            "total_points": len(points),
            "points_in_period": len(changes_in_period),
            "raw_points": raw_points[-10:],  # Last 10 points
            "parsed_points": [{"ts": str(p['ts']), "state": p['state']} for p in points[-10:]],  # Last 10
            "changes_in_period": [{"ts": str(p['ts']), "state": p['state']} for p in changes_in_period]
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500



@app.route('/api/switch-history')
@cache.cached(timeout=900, query_string=True)
def api_switch_history():
    """Get switch ON/OFF state for each quarter-hour (0-95) for a given period and entity.
    
    Query parameters:
    - entity_id: Home Assistant entity ID (e.g., switch.central_heating) [REQUIRED]
    - date: YYYY-MM-DD (optional) - specific date to analyze
    - hours: number of hours to look back (optional, default: 24) - if used, date is ignored
    
    Returns for date mode:
    {
        "entity_id": "switch.xxx",
        "date": "2025-12-27",
        "quarters": [0-95 values, one per 15-min interval],
        "mode": "date"
    }
    
    Returns for hours mode:
    {
        "entity_id": "switch.xxx",
        "hours": 24,
        "quarters": [0-95 values for last 24 hours],
        "mode": "hours"
    }
    
    Perfect for displaying switch states aligned with 15-minute price/control cycles.
    NOTE: HA returns UTC timestamps, we convert to local time for accurate quarter calculation.
    """
    try:
        from datetime import timedelta, timezone
        import pytz
        
        entity_id = request.args.get('entity_id')
        date_str = request.args.get('date')
        hours_str = request.args.get('hours', '24')
        
        if not entity_id:
            return jsonify({"error": "entity_id parameter required"}), 400
        
        try:
            hours = int(hours_str)
        except (ValueError, TypeError):
            hours = 24
        
        # Use Finland timezone (Europe/Helsinki: UTC+2 in winter, UTC+3 in summer)
        local_tz = pytz.timezone('Europe/Helsinki')
        
        # Fetch history (get extra buffer to ensure we capture all changes)
        now_utc = datetime.now(timezone.utc)
        # For 24h mode, we need at least 48h lookback (24h buffer + 24h for analysis)
        # Add extra time for safety margin and timezone edge cases
        lookback_hours = max(hours * 2 + 12, 72)  # Generous lookback
        start_utc = now_utc - timedelta(hours=lookback_hours)
        start_iso = start_utc.replace(tzinfo=None).isoformat()
        end_utc = now_utc + timedelta(hours=1)
        end_iso = end_utc.replace(tzinfo=None).isoformat()
        
        url = f"{HA_URL}/api/history/period/{start_iso}?filter_entity_id={entity_id}&end_time={end_iso}"
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code != 200:
            return jsonify({"error": f"HA API returned {resp.status_code}"}), 500
        
        history = resp.json()
        
        # Parse all state changes and convert from UTC to local time
        points = []
        if history and len(history) > 0 and len(history[0]) > 0:
            for s in history[0]:
                ts_str = s.get('last_changed')
                state = s.get('state')
                try:
                    # Parse UTC timestamp (includes +00:00 timezone info)
                    dt_utc = datetime.fromisoformat(ts_str)
                    
                    # Ensure it has UTC timezone info
                    if dt_utc.tzinfo is None:
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                    
                    # Convert to local timezone
                    dt_local = dt_utc.astimezone(local_tz)
                    
                    points.append({"ts": dt_local, "state": state})
                except Exception as e:
                    print(f"DEBUG: Error parsing timestamp {ts_str}: {e}")
                    continue
        
        # Sort points by timestamp to ensure correct order
        points.sort(key=lambda p: p['ts'])
        
        # Determine target period
        if date_str:
            # Date mode: analyze specific date YYYY-MM-DD
            target_date = datetime.fromisoformat(date_str).date()
            # Create timezone-aware datetimes for consistent comparison
            target_date_start = local_tz.localize(datetime.combine(target_date, datetime.min.time()))
            target_date_end = local_tz.localize(datetime.combine(target_date, datetime.max.time()))
            period_label = date_str
            mode = "date"
        else:
            # Hours mode: analyze last N hours (default 24)
            target_date_end = datetime.now(local_tz).replace(microsecond=0)
            target_date_start = target_date_end - timedelta(hours=hours)
            target_date = target_date_end.date()  # For compatibility
            period_label = str(hours)
            mode = "hours"
        
        # Find state at start of period
        # We need the state that was active at target_date_start
        # Since points are sorted chronologically, find the last point <= target_date_start
        state_at_period_start = 'off'  # Default: assume OFF if no data
        
        for p in points:
            if p['ts'] <= target_date_start:
                # This point is at or before the period start
                # Keep updating to get the most recent point before period start
                state_at_period_start = p['state']
            else:
                # We've passed the target start, stop looking
                break
        
        # Initialize all 96 quarters with the starting state
        quarters = [state_at_period_start] * 96
        
        # Apply state changes during the period
        for p in points:
            if not (target_date_start <= p['ts'] <= target_date_end):
                continue
            
            # Calculate which quarter this change happened in
            # Quarter 0 = start of period, Quarter 95 = end of period (for 24h mode)
            time_into_period = p['ts'] - target_date_start
            minutes_into_period = int(time_into_period.total_seconds() / 60)
            quarter_idx = minutes_into_period // 15
            
            # Clamp to valid range (should normally be 0-95 for 24h)
            if quarter_idx < 0:
                quarter_idx = 0
            elif quarter_idx >= 96:
                quarter_idx = 95
            
            # From this quarter onwards, use the new state
            for i in range(quarter_idx, 96):
                quarters[i] = p['state']
        
        result = {
            "entity_id": entity_id,
            "quarters": quarters,
            "mode": mode
        }
        
        if mode == "date":
            result["date"] = date_str
        else:
            result["hours"] = hours
        
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """Get or update configuration."""
    if request.method == 'GET':
        # Return current config including entity IDs
        return jsonify({
            "BASE_TEMPERATURE": BASE_TEMPERATURE_FALLBACK,
            "MAX_SHUTOFF_HOURS": MAX_SHUTOFF_HOURS,
            "PRICE_ALWAYS_ON_THRESHOLD": PRICE_ALWAYS_ON_THRESHOLD,
            "PRICE_LOW_THRESHOLD": PRICE_LOW_THRESHOLD,
            "PRICE_HIGH_THRESHOLD": PRICE_HIGH_THRESHOLD,
            "TEMP_VARIATION": TEMP_VARIATION,
            "TEMPERATURE_SENSOR": TEMPERATURE_SENSOR,
            "OUTDOOR_TEMP_SENSOR": OUTDOOR_TEMP_SENSOR,
            "SWITCH_ENTITY": SWITCH_ENTITY,
            "CENTRAL_HEATING_SHUTOFF_SWITCH": CENTRAL_HEATING_SHUTOFF_SWITCH,
            "PRICE_SENSOR": PRICE_SENSOR
        })
    
    elif request.method == 'POST':
        # Update .env file (simplified - in production use a proper config library)
        data = request.json
        
        # TODO: Implement .env file update
        # For now, return success (actual implementation would need to update .env safely)
        return jsonify({"status": "Configuration update not yet implemented"}), 501


@app.route('/api/trigger', methods=['POST'])
def api_trigger():
    """Manually trigger a control cycle."""
    try:
        # Import and run the control function
        from main import run_control
        run_control()
        return jsonify({"status": "success", "message": "Control cycle executed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/history')
@cache.cached(timeout=900, query_string=True)
def api_history():
    """Get historical data from Home Assistant (cached for 5 minutes).
    
    Query parameters:
    - hours: Number of hours to look back (default: 24)
    
    Note: Results are cached based on the hours parameter to avoid repeated slow HA API calls.
    Cache key includes query string so different hour values get cached separately.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        hours = int(request.args.get('hours', 24))
        
        # Calculate start time (hours ago from now)
        # NOTE: HA API interprets timestamps without timezone info as UTC
        # So we must convert local time to UTC before sending to HA
        from datetime import timedelta, timezone
        import time as time_module
        
        # Get current time in UTC
        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - timedelta(hours=hours)
        # Format as ISO string without timezone info (HA will interpret as UTC)
        start_time_iso = start_time.replace(tzinfo=None).isoformat()
        
        # Build list of entities to query
        entities = []
        if TEMPERATURE_SENSOR:
            entities.append(TEMPERATURE_SENSOR)
        if OUTDOOR_TEMP_SENSOR:
            entities.append(OUTDOOR_TEMP_SENSOR)
        if SWITCH_ENTITY:
            entities.append(SWITCH_ENTITY)
        if CENTRAL_HEATING_SHUTOFF_SWITCH:
            entities.append(CENTRAL_HEATING_SHUTOFF_SWITCH)
        if PRICE_SENSOR:
            entities.append(PRICE_SENSOR)
        # Include calculated setpoint output entity if configured
        if SETPOINT_OUTPUT:
            if SETPOINT_OUTPUT not in entities:
                entities.append(SETPOINT_OUTPUT)
        # Include base temperature input entity if configured
        if BASE_TEMPERATURE_INPUT:
            if BASE_TEMPERATURE_INPUT not in entities:
                entities.append(BASE_TEMPERATURE_INPUT)
        
        logger.info(f"api_history: Querying {len(entities)} entities for {hours}h")
        logger.info(f"api_history: Entities: {entities}")
        
        # Query HA history API
        # Format: /api/history/period/<start_time>?filter_entity_id=entity1,entity2&end_time=<end_time>
        # NOTE: HA API requires explicit end_time for complete results, otherwise it limits responses
        # Use end_time as "tomorrow" to ensure we get all current data including real-time updates
        entity_filter = ','.join(entities)
        end_time_utc = now_utc + timedelta(hours=24)
        end_time = end_time_utc.replace(tzinfo=None).isoformat()
        url = f"{HA_URL}/api/history/period/{start_time_iso}?filter_entity_id={entity_filter}&end_time={end_time}"
        
        logger.info(f"api_history: URL: {url}")
        
        response = requests.get(url, headers=headers, timeout=60)
        
        if response.status_code != 200:
            logger.error(f"api_history: HA API error {response.status_code}")
            logger.error(f"api_history: Response: {response.text[:500]}")
            return jsonify({"error": f"HA API returned {response.status_code}: {response.text[:200]}"}), 500
        
        history_data = response.json()
        logger.info(f"api_history: Got {len(history_data)} entity histories")
        
        # Transform the data into a more usable format
        result = {
            "start_time": start_time_iso,
            "end_time": datetime.now().isoformat(),
            "hours": hours,
            "entities": {},
            "temperature_entity": TEMPERATURE_SENSOR,
            "outdoor_temperature_entity": OUTDOOR_TEMP_SENSOR,
            "setpoint_entity": SETPOINT_OUTPUT,
            "base_temperature_entity": BASE_TEMPERATURE_INPUT,
            "room_heater_entity": SWITCH_ENTITY,
            "central_heating_entity": CENTRAL_HEATING_SHUTOFF_SWITCH
        }
        
        # HA returns an array where each element is the history for one entity
        for entity_history in history_data:
            if not entity_history:
                continue
            
            entity_id = entity_history[0].get('entity_id')
            
            # Extract timestamps and states
            points = []
            for state in entity_history:
                try:
                    timestamp = state.get('last_changed')
                    value = state.get('state')
                    
                    # Convert numeric states to float
                    if value not in ['on', 'off', 'unavailable', 'unknown']:
                        try:
                            value = float(value)
                        except (ValueError, TypeError):
                            pass
                    
                    points.append({
                        'timestamp': timestamp,
                        'value': value
                    })
                except Exception:
                    continue
            
            result['entities'][entity_id] = points
        
        return jsonify(result)
    
    except Exception as e:
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"api_history exception: {str(e)}")
        logger.error(f"api_history traceback: {traceback.format_exc()}")
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/api/heating-decisions')
@cache.cached(timeout=900, query_string=True)
def api_heating_decisions():
    """Get heating decisions log (cached for 5 minutes).
    
    Query parameters:
    - date: Date in YYYY-MM-DD format (default: today)
    - limit: Maximum number of decisions to return (default: all)
    
    Returns:
        List of decisions with timestamp, decision (HEAT/BLOCK), price, and reason
    """
    try:
        date_str = request.args.get('date')
        limit = request.args.get('limit', type=int)
        
        if date_str:
            # Get decisions for specific date
            decisions = get_decisions_by_date(date_str)
        else:
            # Get all recent decisions
            decisions = get_decisions(limit=limit)
        
        return jsonify({
            "decisions": decisions,
            "count": len(decisions)
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    """Clear the API cache. Useful when you need fresh data immediately."""
    try:
        cache.clear()
        return jsonify({"status": "success", "message": "Cache cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def warm_cache():
    """Pre-warm the cache by fetching all key endpoints every 15 minutes.
    
    This background task runs every 15 minutes (synchronized with the main
    control cycle) to ensure fresh data is cached before users load the page.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Endpoints to warm
    endpoints_to_warm = [
        '/api/current-state',
        '/api/switches-state',
        '/api/prices',
        '/api/central-heating-decision',
        '/api/status',
        '/api/history?hours=24',
        '/api/switch-history?entity_id=switch.shelly1minig3_5432044efb74_switch_0&hours=24',
        '/api/heating-decisions?limit=20',
    ]
    
    while True:
        try:
            with app.test_client() as client:
                for endpoint in endpoints_to_warm:
                    try:
                        response = client.get(endpoint)
                        if response.status_code == 200:
                            logger.debug(f"Warmed {endpoint}")
                        else:
                            logger.warning(f"Failed to warm {endpoint}: HTTP {response.status_code}")
                    except Exception as e:
                        logger.error(f"Error warming {endpoint}: {e}")
                
                logger.info("Cache warming cycle completed")
            
            # Wait 15 minutes (900 seconds) between cache warming
            time.sleep(900)
        except Exception as e:
            logger.error(f"Error in cache warmer: {e}")
            # Still sleep even if there's an error
            time.sleep(900)


# Start cache warmer when module is imported (runs for both gunicorn and __main__)
# This must be after warm_cache() is defined
start_cache_warmer_once()


def start_cache_warmer():
    """Start the background cache warming thread."""
    start_cache_warmer_once()


if __name__ == '__main__':
    # Start cache warming background task
    start_cache_warmer()
    
    # Run Flask development server
    port = int(os.getenv('WEB_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

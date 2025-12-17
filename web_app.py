"""
Web GUI for Temperature Control System
"""
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import requests

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

load_dotenv()

# Outdoor temperature sensor
OUTDOOR_TEMP_SENSOR = os.getenv("OUTDOOR_TEMP_SENSOR", "sensor.ruuvitag_dc2d_temperature")


def get_yesterday_prices():
    """Get yesterday's prices from Nordpool sensor via history API."""
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


@app.route('/')
def index():
    """Render the main dashboard."""
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    """Get current system status."""
    try:
        # Get current values
        base_temp = get_base_temperature_from_input()
        current_price = get_current_price()
        current_temp = get_current_temperature()
        
        if current_price is None or current_temp is None:
            return jsonify({"error": "Failed to fetch sensor data"}), 500
        
        # Calculate setpoint
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
                else:
                    print(f"Failed to get room heater state: HTTP {response.status_code}")
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


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """Get or update configuration."""
    if request.method == 'GET':
        # Return current config
        return jsonify({
            "BASE_TEMPERATURE": BASE_TEMPERATURE_FALLBACK,
            "MAX_SHUTOFF_HOURS": MAX_SHUTOFF_HOURS,
            "PRICE_ALWAYS_ON_THRESHOLD": PRICE_ALWAYS_ON_THRESHOLD,
            "PRICE_LOW_THRESHOLD": PRICE_LOW_THRESHOLD,
            "PRICE_HIGH_THRESHOLD": PRICE_HIGH_THRESHOLD,
            "TEMP_VARIATION": TEMP_VARIATION
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
def api_history():
    """Get historical data from Home Assistant.
    
    Query parameters:
    - hours: Number of hours to look back (default: 24)
    """
    try:
        hours = int(request.args.get('hours', 24))
        
        # Calculate start time (hours ago from now)
        from datetime import timedelta
        start_time = datetime.now() - timedelta(hours=hours)
        start_time_iso = start_time.isoformat()
        
        # Build list of entities to query
        entities = []
        if TEMPERATURE_SENSOR:
            entities.append(TEMPERATURE_SENSOR)
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
        
        # Query HA history API
        # Format: /api/history/period/<start_time>?filter_entity_id=entity1,entity2
        entity_filter = ','.join(entities)
        url = f"{HA_URL}/api/history/period/{start_time_iso}?filter_entity_id={entity_filter}"
        
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            return jsonify({"error": f"HA API returned {response.status_code}"}), 500
        
        history_data = response.json()
        
        # Transform the data into a more usable format
        result = {
            "start_time": start_time_iso,
            "end_time": datetime.now().isoformat(),
            "hours": hours,
            "entities": {},
            "temperature_entity": TEMPERATURE_SENSOR,
            "setpoint_entity": SETPOINT_OUTPUT,
            "base_temperature_entity": BASE_TEMPERATURE_INPUT,
            "room_heater_entity": SWITCH_ENTITY
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
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # Run Flask development server
    port = int(os.getenv('WEB_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

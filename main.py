import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration from environment variables
HA_URL = os.getenv("HA_URL", "https://ha.ketunmetsa.fi")
API_TOKEN = os.getenv("HA_API_TOKEN")

if not API_TOKEN:
    raise ValueError("HA_API_TOKEN environment variable is required")

# Price-based temperature control configuration
BASE_TEMPERATURE_FALLBACK = float(os.getenv("BASE_TEMPERATURE", "21.0"))
BASE_TEMPERATURE_INPUT = os.getenv("BASE_TEMPERATURE_INPUT")  # Optional input_number entity
PRICE_SENSOR = os.getenv("PRICE_SENSOR", "sensor.nordpool_kwh_fi_eur_3_10_0255")
SWITCH_ENTITY = os.getenv("SWITCH_ENTITY", "switch.shelly1minig3_5432044efb74")
TEMPERATURE_SENSOR = os.getenv("TEMPERATURE_SENSOR")  # Current temperature sensor
SETPOINT_OUTPUT = os.getenv("SETPOINT_OUTPUT")  # Optional output to write setpoint

if not TEMPERATURE_SENSOR:
    raise ValueError("TEMPERATURE_SENSOR environment variable is required")

# Temperature adjustment based on electricity price (in c/kWh)
# Price 0-10 c/kWh: +0.5°C (cheap electricity - heat more)
# Price 10 c/kWh: 0°C (baseline)
# Price 20+ c/kWh: -0.5°C (expensive electricity - heat less)
PRICE_LOW_THRESHOLD = float(os.getenv("PRICE_LOW_THRESHOLD", "10.0"))
PRICE_HIGH_THRESHOLD = float(os.getenv("PRICE_HIGH_THRESHOLD", "20.0"))
TEMP_VARIATION = float(os.getenv("TEMP_VARIATION", "0.5"))

# Headers for authentication
headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json",
}


def get_base_temperature():
    """
    Get base temperature setpoint.
    First tries to read from HA input_number entity if configured,
    otherwise uses fallback value from environment variable.
    """
    if BASE_TEMPERATURE_INPUT:
        try:
            response = requests.get(
                f"{HA_URL}/api/states/{BASE_TEMPERATURE_INPUT}",
                headers=headers,
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                temp = float(data['state'])
                print(f"✓ Base temperature from HA ({BASE_TEMPERATURE_INPUT}): {temp}°C")
                return temp
            else:
                print(f"⚠ Warning: Could not read {BASE_TEMPERATURE_INPUT}, using fallback")
        except Exception as e:
            print(f"⚠ Warning: Error reading base temperature from HA: {e}")
    
    # Use fallback value
    print(f"✓ Base temperature (fallback): {BASE_TEMPERATURE_FALLBACK}°C")
    return BASE_TEMPERATURE_FALLBACK


def get_current_price():
    """Get current electricity price from the price sensor."""
    try:
        response = requests.get(
            f"{HA_URL}/api/states/{PRICE_SENSOR}",
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            current_price = float(data['state'])
            return current_price
        else:
            print(f"Error getting price: Status {response.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching price: {e}")
        return None


def get_current_temperature():
    """Get current temperature from the temperature sensor."""
    try:
        response = requests.get(
            f"{HA_URL}/api/states/{TEMPERATURE_SENSOR}",
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            current_temp = float(data['state'])
            return current_temp
        else:
            print(f"Error getting temperature: Status {response.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching temperature: {e}")
        return None


def calculate_temperature_adjustment(price):
    """
    Calculate temperature adjustment based on electricity price.
    
    Linear formula: adjustment = 0.5 - (price * 0.05)
    - price = 0 c/kWh  → +0.5°C (cheap/free)
    - price = 10 c/kWh → 0°C (baseline)
    - price = 20 c/kWh → -0.5°C (expensive)
    
    Clamped to ±0.5°C range.
    """
    # Simple linear calculation
    adjustment = TEMP_VARIATION - (price * (TEMP_VARIATION / PRICE_LOW_THRESHOLD))
    
    # Clamp to bounds
    adjustment = max(-TEMP_VARIATION, min(TEMP_VARIATION, adjustment))
    return round(adjustment, 2)


def get_setpoint_temperature(price, base_temp):
    """Calculate the target setpoint temperature based on current price and base temperature."""
    adjustment = calculate_temperature_adjustment(price)
    setpoint = base_temp + adjustment
    return round(setpoint, 2), adjustment


def control_heating(should_heat):
    """Turn the heating switch on or off."""
    try:
        service_data = {
            "entity_id": SWITCH_ENTITY
        }
        
        service_name = "turn_on" if should_heat else "turn_off"
        response = requests.post(
            f"{HA_URL}/api/services/switch/{service_name}",
            headers=headers,
            json=service_data,
            timeout=5
        )
        
        if response.status_code == 200:
            status = "ON" if should_heat else "OFF"
            print(f"✓ Heating switched {status}")
            return True
        else:
            print(f"✗ Error controlling heating: Status {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Error controlling heating: {e}")
        return False


def update_setpoint_in_ha(setpoint_value):
    """Publish the calculated setpoint to Home Assistant as a read-only sensor.

    We use the REST states API to create/update a sensor entity (for example
    `sensor.heating_target_setpoint`). This keeps the value visible in HA but
    not editable by users in the UI.
    """
    if not SETPOINT_OUTPUT:
        return False  # Skip if not configured

    try:
        # Prepare payload for the states API
        payload = {
            "state": str(setpoint_value),
            "attributes": {
                "unit_of_measurement": "°C",
                "friendly_name": "Calculated Heating Setpoint",
                "source": "price_based_controller"
            }
        }

        response = requests.post(
            f"{HA_URL}/api/states/{SETPOINT_OUTPUT}",
            headers=headers,
            json=payload,
            timeout=5
        )

        if 200 <= response.status_code < 300:
            print(f"✓ Published setpoint to HA ({SETPOINT_OUTPUT}): {setpoint_value}°C")
            return True
        else:
            print(f"⚠ Warning: Could not publish setpoint to HA: Status {response.status_code}")
            return False
    except Exception as e:
        print(f"⚠ Warning: Error publishing setpoint in HA: {e}")
        return False


# Main execution
print("=" * 60)
print("Electricity Price-Based Temperature Control System")
print("=" * 60)

# Get base temperature
print(f"\nFetching base temperature setpoint...")
base_temperature = get_base_temperature()

# Get current electricity price
print(f"\nFetching current electricity price from {PRICE_SENSOR}...")
current_price = get_current_price()

# Get current temperature
print(f"Fetching current temperature from {TEMPERATURE_SENSOR}...")
current_temperature = get_current_temperature()

if current_price is not None and current_temperature is not None:
    print(f"\n✓ Current electricity price: {current_price} c/kWh")
    print(f"✓ Current temperature: {current_temperature}°C")
    
    # Calculate target temperature
    setpoint_temp, adjustment = get_setpoint_temperature(current_price, base_temperature)
    
    print(f"\nTemperature Calculation:")
    print(f"  Base temperature: {base_temperature}°C")
    print(f"  Price adjustment: {adjustment:+.2f}°C")
    print(f"  → Target setpoint: {setpoint_temp}°C")
    
    # Update setpoint in HA
    update_setpoint_in_ha(setpoint_temp)
    
    # Decision logic: heat if current temperature is below target setpoint
    should_heat = current_temperature < setpoint_temp
    temp_diff = setpoint_temp - current_temperature
    
    print(f"\nControl Decision:")
    print(f"  Current: {current_temperature}°C")
    print(f"  Target:  {setpoint_temp}°C")
    print(f"  Difference: {temp_diff:+.2f}°C")
    if should_heat:
        print(f"  → HEAT ON (current < target)")
    else:
        print(f"  → HEAT OFF (current ≥ target)")
    
    # Apply control
    print(f"\nApplying control...")
    control_heating(should_heat)
    
    print("\n" + "=" * 60)
    print("Temperature control executed successfully!")
    print("=" * 60)
else:
    if current_price is None:
        print("\n✗ Failed to get electricity price.")
    if current_temperature is None:
        print("\n✗ Failed to get current temperature.")
    print("Aborting temperature control.")
    print("=" * 60)

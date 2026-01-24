"""
Home Assistant API Client.

All communication with Home Assistant goes through this module:
- Getting sensor values (temperature, prices)
- Controlling switches
- Reading/writing state
- Fetching history
"""
import logging
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import (
    HA_URL,
    HA_HEADERS,
    TEMPERATURE_SENSOR,
    OUTDOOR_TEMP_SENSOR,
    BASE_TEMPERATURE_INPUT,
    BASE_TEMPERATURE_FALLBACK,
    SETPOINT_OUTPUT,
    SWITCH_ENTITY,
    CENTRAL_HEATING_SHUTOFF_SWITCH,
    SPOT_HINTA_API_JUSTNOW,
    SPOT_HINTA_API_URL,
)

logger = logging.getLogger(__name__)


def retry_request(func, max_retries=3, initial_delay=1.0):
    """Retry a function with exponential backoff.
    
    Args:
        func: Function to retry (should return None on failure)
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds (doubles each retry)
    
    Returns:
        Result from func, or None if all retries failed
    """
    for attempt in range(max_retries):
        result = func()
        if result is not None:
            return result
        
        if attempt < max_retries - 1:  # Don't sleep after last attempt
            delay = initial_delay * (2 ** attempt)
            logger.warning(f"Retry {attempt + 1}/{max_retries} after {delay}s...")
            time.sleep(delay)
    
    return None


# =============================================================================
# Temperature Sensors
# =============================================================================

def get_current_temperature():
    """Get current indoor temperature from the temperature sensor with retry logic."""
    def _fetch():
        try:
            response = requests.get(
                f"{HA_URL}/api/states/{TEMPERATURE_SENSOR}",
                headers=HA_HEADERS,
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                current_temp = float(data['state'])
                return current_temp
            else:
                logger.error(f"Error getting temperature: Status {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching temperature: {e}")
            return None
    
    return retry_request(_fetch, max_retries=3, initial_delay=1.0)


def get_outdoor_temperature():
    """Get current outdoor temperature (optional sensor)."""
    if not OUTDOOR_TEMP_SENSOR:
        return None
    
    try:
        response = requests.get(
            f"{HA_URL}/api/states/{OUTDOOR_TEMP_SENSOR}",
            headers=HA_HEADERS,
            timeout=5
        )
        if response.status_code == 200:
            return float(response.json().get("state"))
    except Exception:
        pass
    return None


def get_base_temperature():
    """Get base temperature setpoint.
    
    First tries to read from HA input_number entity if configured,
    otherwise uses fallback value from environment variable.
    """
    if BASE_TEMPERATURE_INPUT:
        try:
            response = requests.get(
                f"{HA_URL}/api/states/{BASE_TEMPERATURE_INPUT}",
                headers=HA_HEADERS,
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                temp = float(data['state'])
                logger.info(f"Base temperature from HA ({BASE_TEMPERATURE_INPUT}): {temp}°C")
                return temp
            else:
                logger.warning(f"Could not read {BASE_TEMPERATURE_INPUT}, using fallback")
        except Exception as e:
            logger.warning(f"Error reading base temperature from HA: {e}")
    
    # Use fallback value
    logger.info(f"Base temperature (fallback): {BASE_TEMPERATURE_FALLBACK}°C")
    return BASE_TEMPERATURE_FALLBACK


def update_setpoint_in_ha(setpoint_value):
    """Publish the calculated setpoint to Home Assistant as a read-only sensor.

    Uses the REST states API to create/update a sensor entity.
    """
    if not SETPOINT_OUTPUT:
        return False  # Skip if not configured

    try:
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
            headers=HA_HEADERS,
            json=payload,
            timeout=5
        )

        if 200 <= response.status_code < 300:
            logger.info(f"Published setpoint to HA ({SETPOINT_OUTPUT}): {setpoint_value}°C")
            return True
        else:
            logger.warning(f"Could not publish setpoint to HA: Status {response.status_code}")
            return False
    except Exception as e:
        logger.warning(f"Error publishing setpoint in HA: {e}")
        return False


# =============================================================================
# Price API
# =============================================================================

def get_current_price():
    """Get current electricity price from Spot-Hinta API /JustNow endpoint.
    
    Returns:
        float: Current price in c/kWh, or None on error
    """
    def _fetch():
        try:
            response = requests.get(SPOT_HINTA_API_JUSTNOW, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # API returns: {"DateTime": "...", "PriceNoTax": 0.09947, "PriceWithTax": 0.12483}
                price_eur = data.get('PriceNoTax')
                if price_eur is not None:
                    price_cents = price_eur * 100  # Convert EUR/kWh to c/kWh
                    logger.debug(f"Current price from API: {price_cents:.2f} c/kWh")
                    return price_cents
                else:
                    logger.error("No PriceNoTax in API response")
                    return None
            else:
                logger.error(f"Error getting price from API: Status {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching price: {e}")
            return None
    
    return retry_request(_fetch, max_retries=3, initial_delay=1.0)


def get_daily_prices():
    """Get all quarter-hourly prices for today from Spot-Hinta API.
    
    Uses /TodayAndDayForward endpoint and extracts today's prices.
    
    Returns:
        list: List of prices (96 values for 24 hours at 15-minute resolution), or None on error
    """
    try:
        response = requests.get(SPOT_HINTA_API_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            # Get today's date in local timezone
            tz = ZoneInfo("Europe/Helsinki")
            today = datetime.now(tz).date()
            
            # Extract today's prices
            today_prices = []
            for price_point in data:
                dt = datetime.fromisoformat(price_point['DateTime'])
                if dt.date() == today:
                    price_eur = price_point['PriceNoTax']
                    price_cents = price_eur * 100  # Convert EUR/kWh to c/kWh
                    today_prices.append(price_cents)
            
            if len(today_prices) >= 96:  # 24 hours * 4 quarters
                return today_prices
            else:
                logger.warning(f"Unexpected number of prices: {len(today_prices)} (expected 96)")
                return today_prices if today_prices else None
        else:
            logger.error(f"Error getting daily prices from API: Status {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error fetching daily prices: {e}")
        return None


def get_tomorrow_prices():
    """Get tomorrow's prices from Spot-Hinta API if available.
    
    Returns:
        list: List of 96 prices for tomorrow (c/kWh), or None if not available
    """
    try:
        response = requests.get(SPOT_HINTA_API_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            tz = ZoneInfo("Europe/Helsinki")
            tomorrow = (datetime.now(tz).date().toordinal() + 1)
            tomorrow_date = datetime.fromordinal(tomorrow).date()
            
            # Extract tomorrow's prices
            tomorrow_prices = []
            for price_point in data:
                dt = datetime.fromisoformat(price_point['DateTime'])
                if dt.date() == tomorrow_date:
                    price_eur = price_point['PriceNoTax']
                    price_cents = price_eur * 100
                    tomorrow_prices.append(price_cents)
            
            if len(tomorrow_prices) >= 96:
                return tomorrow_prices
        return None
    except Exception as e:
        logger.warning(f"Error fetching tomorrow prices: {e}")
        return None


# =============================================================================
# Switch Control
# =============================================================================

def get_switch_state(entity_id):
    """Get current state of a switch entity.
    
    Returns:
        str: 'on', 'off', or None on error
    """
    try:
        response = requests.get(
            f"{HA_URL}/api/states/{entity_id}",
            headers=HA_HEADERS,
            timeout=5
        )
        if response.status_code == 200:
            return response.json().get("state")
    except Exception as e:
        logger.error(f"Error getting switch state for {entity_id}: {e}")
    return None


def control_switch(entity_id, turn_on):
    """Control a switch entity (turn on or off).
    
    Args:
        entity_id: HA entity ID of the switch
        turn_on: True to turn on, False to turn off
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        service_data = {"entity_id": entity_id}
        service_name = "turn_on" if turn_on else "turn_off"
        
        response = requests.post(
            f"{HA_URL}/api/services/switch/{service_name}",
            headers=HA_HEADERS,
            json=service_data,
            timeout=5
        )

        if 200 <= response.status_code < 300:
            # Service accepted — verify the switch state (retry a few times)
            expected_state = "on" if turn_on else "off"
            for attempt in range(10):
                try:
                    time.sleep(0.5 if attempt == 0 else 1)
                    state = get_switch_state(entity_id)
                    if state == expected_state:
                        logger.info(f"Switch {entity_id} turned {expected_state.upper()} (confirmed)")
                        return True
                    elif state is None:
                        # Entity not found
                        logger.error(f"Switch entity '{entity_id}' not found in Home Assistant")
                        return False
                except Exception:
                    pass  # Retry

            # Service accepted but state not confirmed
            logger.warning(f"Service accepted but switch state not confirmed (expected: {expected_state})")
            return True
        else:
            logger.error(f"Error controlling switch {entity_id}: Status {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error controlling switch {entity_id}: {e}")
        return False


def control_heating(should_heat):
    """Turn the room heating switch on or off."""
    return control_switch(SWITCH_ENTITY, should_heat)


def control_central_heating(should_run):
    """Control the central heating switch.
    
    NOTE: The switch is inverted - when switch is ON, central heating is OFF (blocked).
    
    Args:
        should_run: True if central heating should run (switch OFF), 
                   False if heating should be blocked (switch ON)
    """
    if not CENTRAL_HEATING_SHUTOFF_SWITCH:
        return  # Central heating control not configured
    
    # INVERTED: Turn switch OFF to allow heating, ON to block heating
    return control_switch(CENTRAL_HEATING_SHUTOFF_SWITCH, not should_run)


def get_room_heater_state():
    """Get current room heater switch state."""
    if SWITCH_ENTITY:
        return get_switch_state(SWITCH_ENTITY)
    return None


def get_central_heating_state():
    """Get central heating switch state.
    
    Returns:
        dict: {state: str, is_running: bool} or None
    """
    if not CENTRAL_HEATING_SHUTOFF_SWITCH:
        return None
    
    state = get_switch_state(CENTRAL_HEATING_SHUTOFF_SWITCH)
    if state:
        # Inverted: OFF = running, ON = blocked
        return {
            "state": state,
            "is_running": (state == "off")
        }
    return None


# =============================================================================
# Healthcheck
# =============================================================================

def ping_healthcheck(success=True):
    """Ping healthcheck service to indicate the script is running.
    
    Args:
        success: True if control cycle completed successfully, False if it failed
    """
    from .config import HEALTHCHECK_URL
    
    if not HEALTHCHECK_URL:
        return  # Healthcheck not configured
    
    try:
        # Append /fail to URL if control cycle failed
        url = HEALTHCHECK_URL if success else f"{HEALTHCHECK_URL}/fail"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            logger.debug(f"Healthcheck ping sent successfully ({'success' if success else 'failure'})")
        else:
            logger.warning(f"Healthcheck ping returned status {response.status_code}")
    except Exception as e:
        logger.warning(f"Failed to ping healthcheck: {e}")

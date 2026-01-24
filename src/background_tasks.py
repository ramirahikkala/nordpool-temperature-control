"""
Background Tasks for Temperature Control System.

Contains long-running background tasks:
- Cache warmer: Pre-fetches API data to speed up web UI
- Bathroom thermostat: Sends price-adjusted temperature to Shelly TRV
"""
import logging
import time
import requests

from .config import BATHROOM_THERMOSTAT_URL, BATHROOM_TEMP_SENSOR, HA_URL, HA_HEADERS
from .ha_client import get_current_price

logger = logging.getLogger(__name__)


def get_bathroom_raw_temperature():
    """Get raw temperature from bathroom sensor (Ruuvitag).
    
    Returns:
        float: Raw temperature in Celsius, or None if unavailable
    """
    if not BATHROOM_TEMP_SENSOR:
        return None
    
    try:
        response = requests.get(
            f"{HA_URL}/api/states/{BATHROOM_TEMP_SENSOR}",
            headers=HA_HEADERS,
            timeout=5
        )
        if response.status_code == 200:
            state = response.json().get('state')
            if state and state != 'unavailable' and state != 'unknown':
                return float(state)
    except Exception as e:
        logger.warning(f"Error reading {BATHROOM_TEMP_SENSOR}: {e}")
    return None


def calculate_bathroom_adjusted_temperature(raw_temp: float, price: float) -> float:
    """Calculate price-adjusted temperature for bathroom thermostat.
    
    Same logic as HA template sensor:
    adjusted_temp = base_temp + (electricity_price - 5) / 5
    
    This makes the thermostat think it's warmer when electricity is expensive
    (so it heats less) and cooler when electricity is cheap (so it heats more).
    
    Args:
        raw_temp: Raw temperature from sensor
        price: Current electricity price in c/kWh
        
    Returns:
        Adjusted temperature to send to thermostat
    """
    adjustment = (price - 5) / 5
    return raw_temp + adjustment


def send_temperature_to_bathroom_thermostat():
    """Send price-adjusted temperature to bathroom thermostat.
    
    This function sends the current bathroom temperature (adjusted for electricity
    price) to a Shelly TRV via HTTP GET request. The TRV uses this external 
    temperature for room control.
    
    Called from main control cycle every 15 minutes.
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not BATHROOM_THERMOSTAT_URL:
        return False
    
    try:
        # Get raw temperature from Ruuvitag
        raw_temp = get_bathroom_raw_temperature()
        if raw_temp is None:
            logger.warning("Could not get bathroom temperature, skipping thermostat update")
            return False
        
        # Get current electricity price
        price = get_current_price()
        if price is None:
            logger.warning("Could not get electricity price, using raw temperature")
            adjusted_temp = raw_temp
        else:
            # Apply price adjustment (same formula as HA template)
            adjusted_temp = calculate_bathroom_adjusted_temperature(raw_temp, price)
            logger.info(f"Bathroom temp: {raw_temp:.1f}°C raw, {adjusted_temp:.1f}°C adjusted (price: {price:.2f} c/kWh)")
        
        # Send to Shelly TRV
        url = f"{BATHROOM_THERMOSTAT_URL}{adjusted_temp:.1f}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            logger.info(f"Sent {adjusted_temp:.1f}°C to bathroom thermostat")
            return True
        else:
            logger.warning(f"Failed to send temperature to bathroom thermostat: HTTP {response.status_code}")
            return False
    
    except requests.exceptions.Timeout:
        logger.warning("Timeout sending temperature to bathroom thermostat")
    except requests.exceptions.ConnectionError:
        logger.warning("Connection error sending temperature to bathroom thermostat")
    except Exception as e:
        logger.warning(f"Error sending temperature to bathroom thermostat: {e}")
    
    return False


def warm_cache(app, endpoints):
    """Pre-warm the Flask cache by fetching key endpoints.
    
    This background task runs every 15 minutes (synchronized with the main
    control cycle) to ensure fresh data is cached before users load the page.
    
    Args:
        app: Flask application instance
        endpoints: List of endpoint URLs to warm
    """
    logger.info("Starting cache warmer...")
    
    while True:
        try:
            with app.test_client() as client:
                for endpoint in endpoints:
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

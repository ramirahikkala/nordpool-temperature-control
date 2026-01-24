"""
Background Tasks for Temperature Control System.

Contains long-running background tasks:
- Cache warmer: Pre-fetches API data to speed up web UI
- Bathroom thermostat: Sends temperature to Shelly TRV
"""
import logging
import time
import requests

from .config import BATHROOM_THERMOSTAT_URL, BATHROOM_TEMP_SENSOR, HA_URL, HA_HEADERS
from .ha_client import get_current_temperature

logger = logging.getLogger(__name__)


def get_bathroom_temperature():
    """Get temperature to send to bathroom thermostat.
    
    Uses BATHROOM_TEMP_SENSOR if configured, otherwise falls back to TEMPERATURE_SENSOR.
    """
    if BATHROOM_TEMP_SENSOR:
        # Use dedicated bathroom sensor
        try:
            response = requests.get(
                f"{HA_URL}/api/states/{BATHROOM_TEMP_SENSOR}",
                headers=HA_HEADERS,
                timeout=5
            )
            if response.status_code == 200:
                return float(response.json().get('state'))
        except Exception as e:
            logger.warning(f"Error reading {BATHROOM_TEMP_SENSOR}: {e}")
        return None
    else:
        # Fall back to main temperature sensor
        return get_current_temperature()


def send_temperature_to_bathroom_thermostat():
    """Send current temperature to bathroom thermostat every 5 minutes.
    
    This background task sends the current bathroom temperature reading to a 
    Shelly TRV (thermostatic radiator valve) via HTTP GET request. The TRV uses
    this external temperature instead of its built-in sensor for more accurate
    room temperature control.
    
    Failures are logged but don't stop the loop - the device may be temporarily
    unavailable or network issues may occur.
    """
    if not BATHROOM_THERMOSTAT_URL:
        logger.info("Bathroom thermostat sender disabled (BATHROOM_THERMOSTAT_URL not configured)")
        return
    
    sensor_info = f" (sensor: {BATHROOM_TEMP_SENSOR})" if BATHROOM_TEMP_SENSOR else ""
    logger.info(f"Starting bathroom thermostat sender (URL: {BATHROOM_THERMOSTAT_URL}){sensor_info}")
    
    while True:
        try:
            # Get temperature to send (from dedicated sensor or main sensor)
            temp = get_bathroom_temperature()
            
            if temp is not None:
                # Send to Shelly TRV
                url = f"{BATHROOM_THERMOSTAT_URL}{temp}"
                response = requests.get(url, timeout=5)
                
                if response.status_code == 200:
                    logger.debug(f"Sent temperature {temp}°C to bathroom thermostat")
                else:
                    logger.warning(f"Failed to send temperature to bathroom thermostat: HTTP {response.status_code}")
            else:
                logger.warning("Could not get bathroom temperature from HA, skipping thermostat update")
        
        except requests.exceptions.Timeout:
            logger.warning("Timeout sending temperature to bathroom thermostat")
        except requests.exceptions.ConnectionError:
            logger.warning("Connection error sending temperature to bathroom thermostat")
        except Exception as e:
            logger.warning(f"Error sending temperature to bathroom thermostat: {e}")
        
        # Wait 5 minutes (300 seconds) between updates
        time.sleep(300)


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

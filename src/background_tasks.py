"""
Background Tasks for Temperature Control System.

Contains long-running background tasks:
- Cache warmer: Pre-fetches API data to speed up web UI
- Shelly temperature sender: Sends temperature to Shelly device
"""
import logging
import time
import requests

from .config import SHELLY_TEMP_URL
from .ha_client import get_current_temperature

logger = logging.getLogger(__name__)


def send_temperature_to_shelly():
    """Send current temperature to Shelly device every 5 minutes.
    
    This background task sends the current temperature reading to a Shelly device
    via HTTP GET request. The Shelly device can use this for external temperature
    control (e.g., radiator thermostat).
    
    Failures are logged but don't stop the loop - the device may be temporarily
    unavailable or network issues may occur.
    """
    if not SHELLY_TEMP_URL:
        logger.info("Shelly temperature sender disabled (SHELLY_TEMP_URL not configured)")
        return
    
    logger.info(f"Starting Shelly temperature sender (URL: {SHELLY_TEMP_URL})")
    
    while True:
        try:
            # Get current temperature from Home Assistant
            temp = get_current_temperature()
            
            if temp is not None:
                # Send to Shelly device
                url = f"{SHELLY_TEMP_URL}{temp}"
                response = requests.get(url, timeout=5)
                
                if response.status_code == 200:
                    logger.debug(f"Sent temperature {temp}°C to Shelly device")
                else:
                    logger.warning(f"Failed to send temperature to Shelly: HTTP {response.status_code}")
            else:
                logger.warning("Could not get current temperature from HA, skipping Shelly update")
        
        except requests.exceptions.Timeout:
            logger.warning("Timeout sending temperature to Shelly device")
        except requests.exceptions.ConnectionError:
            logger.warning("Connection error sending temperature to Shelly device")
        except Exception as e:
            logger.warning(f"Error sending temperature to Shelly: {e}")
        
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

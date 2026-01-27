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
    
    The adjustment is capped to ±1°C to avoid extreme changes.
    
    Args:
        raw_temp: Raw temperature from sensor
        price: Current electricity price in c/kWh
        
    Returns:
        Adjusted temperature to send to thermostat
    """
    adjustment = (price - 5) / 5
    # Cap adjustment to ±1°C
    adjustment = max(-1.0, min(1.0, adjustment))
    return raw_temp + adjustment


def _send_to_thermostat(url: str, timeout: int = 5) -> bool:
    """Send HTTP GET request to thermostat.
    
    Args:
        url: Full URL including temperature parameter
        timeout: Request timeout in seconds
        
    Returns:
        True if successful (HTTP 200), False otherwise
        
    Raises:
        requests.exceptions.RequestException on network errors
    """
    response = requests.get(url, timeout=timeout)
    return response.status_code == 200


def _send_with_retry(url: str, adjusted_temp: float, max_retry_time: int = 840):
    """Background thread function to send temperature with exponential backoff.
    
    Args:
        url: Full URL to send to
        adjusted_temp: Temperature value being sent (for logging)
        max_retry_time: Maximum total time to retry in seconds
    """
    # Exponential backoff parameters
    initial_delay = 5
    max_delay = 120
    delay = initial_delay
    attempt = 1
    start_time = time.time()
    
    while True:
        try:
            if _send_to_thermostat(url):
                if attempt == 1:
                    logger.info(f"Sent {adjusted_temp:.1f}°C to bathroom thermostat")
                else:
                    logger.info(f"Sent {adjusted_temp:.1f}°C to bathroom thermostat (attempt {attempt})")
                return
            else:
                logger.info(f"Bathroom thermostat returned non-200, attempt {attempt}")
                
        except requests.exceptions.Timeout:
            logger.info(f"Bathroom thermostat timeout, attempt {attempt}")
        except requests.exceptions.ConnectionError:
            logger.info(f"Bathroom thermostat connection error, attempt {attempt}")
        except Exception as e:
            logger.info(f"Bathroom thermostat error: {e}, attempt {attempt}")
        
        # Check if we've exceeded max retry time
        elapsed = time.time() - start_time
        if elapsed + delay > max_retry_time:
            logger.warning(f"Failed to send temperature to bathroom thermostat after {attempt} attempts over {elapsed:.0f}s")
            return
        
        # Wait before next retry (exponential backoff)
        logger.info(f"Retrying bathroom thermostat in {delay}s...")
        time.sleep(delay)
        delay = min(delay * 2, max_delay)
        attempt += 1


def send_temperature_to_bathroom_thermostat():
    """Send price-adjusted temperature to bathroom thermostat.
    
    This function calculates the adjusted temperature and spawns a background
    thread to send it with exponential backoff retries. This way the main
    control loop is not blocked by network issues.
    
    The background thread uses exponential backoff:
    - Initial delay: 5 seconds
    - Max delay: 120 seconds (2 minutes)
    - Total retry time: 14 minutes (before next 15-min cycle)
    
    Called from main control cycle every 15 minutes.
    """
    import threading
    
    if not BATHROOM_THERMOSTAT_URL:
        return
    
    # Get raw temperature from Ruuvitag
    raw_temp = get_bathroom_raw_temperature()
    if raw_temp is None:
        logger.warning("Could not get bathroom temperature, skipping thermostat update")
        return
    
    # Get current electricity price
    price = get_current_price()
    if price is None:
        logger.warning("Could not get electricity price, using raw temperature")
        adjusted_temp = raw_temp
    else:
        # Apply price adjustment (same formula as HA template)
        adjusted_temp = calculate_bathroom_adjusted_temperature(raw_temp, price)
        logger.info(f"Bathroom temp: {raw_temp:.1f}°C raw, {adjusted_temp:.1f}°C adjusted (price: {price:.2f} c/kWh)")
    
    # Build URL and spawn background thread for sending with retry
    url = f"{BATHROOM_THERMOSTAT_URL}{adjusted_temp:.1f}"
    thread = threading.Thread(
        target=_send_with_retry,
        args=(url, adjusted_temp),
        daemon=True,
        name="bathroom-thermostat-sender"
    )
    thread.start()
    logger.debug("Spawned background thread for bathroom thermostat update")


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

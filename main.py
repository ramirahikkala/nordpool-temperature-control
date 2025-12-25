import requests
import json
import os
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Import heating logger for file-based decision logging
from heating_logger import log_heating_decision as log_decision_to_file

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

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

# Central heating control configuration
CENTRAL_HEATING_SHUTOFF_SWITCH = os.getenv("CENTRAL_HEATING_SHUTOFF_SWITCH")  # Optional switch to block central heating (ON = heating blocked)
MAX_SHUTOFF_HOURS = float(os.getenv("MAX_SHUTOFF_HOURS", "6.0"))  # Max hours per day to turn off heating
PRICE_ALWAYS_ON_THRESHOLD = float(os.getenv("PRICE_ALWAYS_ON_THRESHOLD", "5.0"))  # Below this price, always keep heating on

# Healthcheck/watchdog configuration
HEALTHCHECK_URL = os.getenv("HEALTHCHECK_URL")  # Optional healthcheck ping URL (e.g., from healthchecks.io)

# Headers for authentication
headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json",
}


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
                logger.info(f"Base temperature from HA ({BASE_TEMPERATURE_INPUT}): {temp}°C")
                return temp
            else:
                logger.warning(f"Could not read {BASE_TEMPERATURE_INPUT}, using fallback")
        except Exception as e:
            logger.warning(f"Error reading base temperature from HA: {e}")
    
    # Use fallback value
    logger.info(f"Base temperature (fallback): {BASE_TEMPERATURE_FALLBACK}°C")
    return BASE_TEMPERATURE_FALLBACK


def get_price_from_day_array(prices_array):
    """Extract current quarter-hour price from the day's price array.
    
    Args:
        prices_array: List of 96 prices (one per quarter-hour, 00:00-23:45)
    
    Returns:
        Price in c/kWh (converted from EUR/kWh)
    """
    tz = ZoneInfo("Europe/Helsinki")
    now = datetime.now(tz)
    
    # Calculate which quarter we're in (0-95)
    quarter = (now.hour * 4) + (now.minute // 15)
    
    if 0 <= quarter < len(prices_array):
        # Price is in EUR/kWh, convert to c/kWh
        price_eur = prices_array[quarter]
        price_cents = price_eur * 100
        logger.debug(f"Quarter {quarter}: {price_eur} EUR/kWh = {price_cents:.2f} c/kWh")
        return price_cents
    else:
        logger.error(f"Invalid quarter index {quarter}")
        return None


def get_current_price():
    """Get current electricity price from the price sensor.
    
    Fetches from the Nordpool sensor's 'today' array (96 quarter-hour prices)
    to get the actual price for the current quarter, avoiding caching issues.
    Prices are in EUR/kWh, converted to c/kWh for use in thresholds.
    """
    def _fetch():
        try:
            response = requests.get(
                f"{HA_URL}/api/states/{PRICE_SENSOR}",
                headers=headers,
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                attributes = data.get('attributes', {})
                today_prices = attributes.get('today', [])
                
                if len(today_prices) == 96:
                    # Use the day array for accurate quarter-hour price
                    price_cents = get_price_from_day_array(today_prices)
                    return price_cents
                else:
                    logger.warning(f"Unexpected 'today' array length: {len(today_prices)}")
                    # Fallback: use state value (in EUR/kWh, convert to c/kWh)
                    state_price_eur = float(data['state'])
                    return state_price_eur * 100
            else:
                logger.error(f"Error getting price: Status {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching price: {e}")
            return None
    
    return retry_request(_fetch, max_retries=3, initial_delay=1.0)


def get_current_temperature():
    """Get current temperature from the temperature sensor with retry logic."""
    def _fetch():
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
                logger.error(f"Error getting temperature: Status {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching temperature: {e}")
            return None
    
    return retry_request(_fetch, max_retries=3, initial_delay=1.0)


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

        if 200 <= response.status_code < 300:
            # Service accepted — verify the switch state (retry a few times)
            expected_state = "on" if should_heat else "off"
            for attempt in range(10):
                try:
                    # small backoff
                    time.sleep(0.5 if attempt == 0 else 1)
                    s = requests.get(f"{HA_URL}/api/states/{SWITCH_ENTITY}", headers=headers, timeout=5)
                    if s.status_code == 200:
                        state = s.json().get("state")
                        if state == expected_state:
                            logger.info(f"Heating switched {expected_state.upper()} (confirmed)")
                            return True
                    elif s.status_code == 404:
                        # Entity not found — probably wrong entity id
                        logger.error(f"Switch entity '{SWITCH_ENTITY}' not found in Home Assistant (404). Please verify SWITCH_ENTITY in .env")
                        return False
                except Exception as e:
                    pass  # Retry

            # Service accepted but state not confirmed — warn but return success
            logger.warning(f"Service accepted but switch state not confirmed (expected: {expected_state})")
            return True
        else:
            logger.error(f"Error controlling heating: Status {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error controlling heating: {e}")
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
            logger.info(f"Published setpoint to HA ({SETPOINT_OUTPUT}): {setpoint_value}°C")
            return True
        else:
            logger.warning(f"Could not publish setpoint to HA: Status {response.status_code}")
            return False
    except Exception as e:
        logger.warning(f"Error publishing setpoint in HA: {e}")
        return False


def ping_healthcheck(success=True):
    """Ping healthcheck service to indicate the script is running.
    
    Args:
        success: True if control cycle completed successfully, False if it failed
    """
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


def get_daily_prices():
    """Get all quarter-hourly prices for today from the Nordpool sensor.
    
    Returns:
        list: List of prices (96 values for 24 hours at 15-minute resolution), or None on error
    """
    try:
        response = requests.get(
            f"{HA_URL}/api/states/{PRICE_SENSOR}",
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            prices = data.get('attributes', {}).get('today', [])
            if len(prices) == 96:  # 24 hours * 4 quarters
                return prices
            else:
                logger.warning(f"Unexpected number of prices: {len(prices)} (expected 96)")
                return prices if prices else None
        else:
            logger.error(f"Error getting daily prices: Status {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error fetching daily prices: {e}")
        return None


def should_central_heating_run(current_price, daily_prices):
    """Determine if central heating should be running based on price ranking.
    
    Logic:
    - If current price < PRICE_ALWAYS_ON_THRESHOLD: always return True (heating ON)
    - Otherwise: return False (heating OFF) only if current quarter is among the
      top MAX_SHUTOFF_HOURS*4 most expensive quarters of the day
    
    Args:
        current_price: Current electricity price (c/kWh)
        daily_prices: List of all prices for today
    
    Returns:
        tuple: (should_run: bool, reason: str)
    """
    # If price is cheap enough, always keep heating on
    if current_price < PRICE_ALWAYS_ON_THRESHOLD:
        return True, f"Price {current_price:.2f} c/kWh < threshold {PRICE_ALWAYS_ON_THRESHOLD:.2f} c/kWh (always on)"
    
    if not daily_prices or len(daily_prices) == 0:
        logger.warning("No daily prices available, defaulting to heating ON")
        return True, "No price data available"
    
    # Calculate how many quarters to shut off (max shutoff hours * 4 quarters per hour)
    max_shutoff_quarters = int(MAX_SHUTOFF_HOURS * 4)
    
    # Sort prices to find the most expensive quarters
    sorted_prices = sorted(daily_prices, reverse=True)  # Highest first
    
    # Get the threshold price (the Nth most expensive quarter)
    if max_shutoff_quarters < len(sorted_prices):
        shutoff_threshold = sorted_prices[max_shutoff_quarters - 1]
    else:
        # If we want to shut off more quarters than exist, use the minimum price
        shutoff_threshold = min(daily_prices)
    
    # Check if current price is in the top N most expensive
    # We need to be careful with equal prices - count how many prices are >= current
    expensive_quarters_count = sum(1 for p in daily_prices if p >= current_price)
    
    if expensive_quarters_count <= max_shutoff_quarters and current_price >= shutoff_threshold:
        # Current quarter is in the top-N most expensive
        rank = expensive_quarters_count
        return False, f"In top-{max_shutoff_quarters} expensive quarters (rank ~{rank}, price {current_price:.2f} c/kWh)"
    else:
        # Not in the most expensive quarters
        return True, f"Not in top-{max_shutoff_quarters} expensive quarters (price {current_price:.2f} c/kWh, threshold {shutoff_threshold:.2f} c/kWh)"


def log_heating_decision_to_ha(should_run, reason, current_price):
    """Log heating decision to local file and stdout.
    
    Stores decision in local JSON file (viewable via web API).
    Also logs to stdout (for container logs).
    
    Args:
        should_run: True if heating should run, False if blocked
        reason: Reason for the decision (explanation string)
        current_price: Current electricity price in c/kWh
    """
    if not CENTRAL_HEATING_SHUTOFF_SWITCH:
        return  # Central heating not configured, don't log
    
    decision = "HEAT" if should_run else "BLOCK"
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    
    # Format: [HEATING_DECISION] HEAT|BLOCK 12:34:56 @ 6.29 c/kWh | reason
    message = f"[HEATING_DECISION] {decision} {timestamp} @ {current_price:.2f} c/kWh | {reason[:60]}"
    
    # Log to stdout/container logs
    logger.info(message)
    
    # Log to local file (for web API and persistence)
    try:
        log_decision_to_file(should_run, reason, current_price)
    except Exception as e:
        logger.warning(f"Could not write decision to file: {e}")


def control_central_heating(should_run):
    """Control the central heating switch.
    
    NOTE: The switch is inverted - when switch is ON, central heating is OFF (blocked).
    
    Args:
        should_run: True if central heating should run (switch OFF), False if heating should be blocked (switch ON)
    """
    if not CENTRAL_HEATING_SHUTOFF_SWITCH:
        return  # Central heating control not configured
    
    try:
        service_data = {
            "entity_id": CENTRAL_HEATING_SHUTOFF_SWITCH
        }
        # INVERTED: Turn switch OFF to allow heating, ON to block heating
        service_name = "turn_off" if should_run else "turn_on"
        response = requests.post(
            f"{HA_URL}/api/services/switch/{service_name}",
            headers=headers,
            json=service_data,
            timeout=5
        )

        if 200 <= response.status_code < 300:
            # Service accepted — verify the switch state (retry a few times)
            # INVERTED: expect OFF when heating should run, ON when blocked
            expected_state = "off" if should_run else "on"
            for attempt in range(10):
                try:
                    # small backoff
                    time.sleep(0.5 if attempt == 0 else 1)
                    s = requests.get(f"{HA_URL}/api/states/{CENTRAL_HEATING_SHUTOFF_SWITCH}", headers=headers, timeout=5)
                    if s.status_code == 200:
                        state = s.json().get("state")
                        if state == expected_state:
                            heating_status = "RUNNING (switch off)" if should_run else "BLOCKED (switch on)"
                            logger.info(f"Central heating {heating_status} (confirmed)")
                            return True
                    elif s.status_code == 404:
                        # Entity not found — probably wrong entity id
                        logger.error(f"Central heating entity '{CENTRAL_HEATING_SHUTOFF_SWITCH}' not found in Home Assistant (404). Please verify CENTRAL_HEATING_SHUTOFF_SWITCH in .env")
                        return False
                except Exception as e:
                    pass  # Retry

            # Service accepted but state not confirmed — warn but return success
            logger.warning(f"Central heating service accepted but state not confirmed (expected: {expected_state})")
            return True
        else:
            logger.error(f"Error controlling central heating: Status {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error controlling central heating: {e}")
        return False


def run_control():
    """Execute one temperature control cycle."""
    logger.info("=" * 60)
    logger.info("Electricity Price-Based Temperature Control System")
    logger.info("=" * 60)

    # Get base temperature
    logger.info("Fetching base temperature setpoint...")
    base_temperature = get_base_temperature()

    # Get current electricity price
    logger.info(f"Fetching current electricity price from {PRICE_SENSOR}...")
    current_price = get_current_price()

    # Get current temperature
    logger.info(f"Fetching current temperature from {TEMPERATURE_SENSOR}...")
    current_temperature = get_current_temperature()

    if current_price is not None and current_temperature is not None:
        logger.info(f"Current electricity price: {current_price} c/kWh")
        logger.info(f"Current temperature: {current_temperature}°C")
        
        # Calculate target temperature
        setpoint_temp, adjustment = get_setpoint_temperature(current_price, base_temperature)
        
        logger.info("Temperature Calculation:")
        logger.info(f"  Base temperature: {base_temperature}°C")
        logger.info(f"  Price adjustment: {adjustment:+.2f}°C")
        logger.info(f"  → Target setpoint: {setpoint_temp}°C")
        
        # Update setpoint in HA
        update_setpoint_in_ha(setpoint_temp)
        
        # Decision logic: heat if current temperature is below target setpoint
        should_heat = current_temperature < setpoint_temp
        temp_diff = setpoint_temp - current_temperature
        
        logger.info("Control Decision:")
        logger.info(f"  Current: {current_temperature}°C")
        logger.info(f"  Target:  {setpoint_temp}°C")
        logger.info(f"  Difference: {temp_diff:+.2f}°C")
        if should_heat:
            logger.info("  → HEAT ON (current < target)")
        else:
            logger.info("  → HEAT OFF (current ≥ target)")
        
        # Apply control
        logger.info("Applying room temperature control...")
        control_heating(should_heat)
        
        logger.info("=" * 60)
        logger.info("Room temperature control executed successfully!")
        logger.info("=" * 60)
        
        # Central heating control (if configured)
        if CENTRAL_HEATING_SHUTOFF_SWITCH:
            logger.info("")
            logger.info("=" * 60)
            logger.info("Central Heating Control")
            logger.info("=" * 60)
            
            # Get all daily prices for ranking
            logger.info("Fetching daily price data for ranking...")
            daily_prices = get_daily_prices()
            
            if daily_prices:
                logger.info(f"Retrieved {len(daily_prices)} quarter-hourly prices")
                logger.info(f"Price range: {min(daily_prices):.2f} - {max(daily_prices):.2f} c/kWh")
                logger.info(f"Configuration: Max {MAX_SHUTOFF_HOURS}h shutoff, Always-on threshold: {PRICE_ALWAYS_ON_THRESHOLD:.2f} c/kWh")
                
                # Determine if central heating should run
                should_run, reason = should_central_heating_run(current_price, daily_prices)
                
                # Log decision to Home Assistant for easy filtering
                log_heating_decision_to_ha(should_run, reason, current_price)
                
                logger.info("Central Heating Decision:")
                logger.info(f"  Current price: {current_price:.2f} c/kWh")
                logger.info(f"  Reason: {reason}")
                if should_run:
                    logger.info("  → CENTRAL HEATING RUNNING (control switch will be OFF)")
                else:
                    logger.info("  → CENTRAL HEATING BLOCKED (control switch will be ON - shutoff during expensive period)")
                
                # Apply central heating control
                logger.info("Applying central heating control...")
                control_central_heating(should_run)
                
                logger.info("=" * 60)
                logger.info("Central heating control executed successfully!")
                logger.info("=" * 60)
            else:
                logger.warning("Could not retrieve daily prices for central heating control")
                logger.info("=" * 60)
        
        # Ping healthcheck to indicate successful completion
        ping_healthcheck(success=True)
        
    else:
        if current_price is None:
            logger.error("Failed to get electricity price.")
        if current_temperature is None:
            logger.error("Failed to get current temperature.")
        logger.error("Aborting temperature control.")
        logger.info("=" * 60)
        
        # Ping healthcheck with failure status
        ping_healthcheck(success=False)


if __name__ == "__main__":
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz
    
    # Get timezone from environment or default to Europe/Helsinki
    tz = pytz.timezone(os.getenv("TZ", "Europe/Helsinki"))
    
    # Create scheduler
    scheduler = BlockingScheduler(timezone=tz)
    
    # Schedule to run at :00, :15, :30, :45 every hour
    scheduler.add_job(
        run_control,
        trigger=CronTrigger(minute='0,15,30,45', timezone=tz),
        id='temperature_control',
        name='Temperature Control',
        replace_existing=True
    )
    
    logger.info("Scheduler initialized. Will run at :00, :15, :30, :45 every hour.")
    logger.info(f"Timezone: {tz}")
    logger.info("Running initial control cycle now...")
    
    # Run once immediately at startup
    try:
        run_control()
    except Exception as e:
        logger.error(f"Error in initial control cycle: {e}", exc_info=True)
    
    # Start scheduler (blocks forever)
    logger.info("Starting scheduler... (this will block and keep the process running)")
    try:
        scheduler.start()
        logger.info("Scheduler stopped normally (should not reach here)")
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by signal.")
    except Exception as e:
        logger.error(f"Scheduler failed: {e}", exc_info=True)
        raise

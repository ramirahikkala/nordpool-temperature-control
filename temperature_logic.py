"""
Temperature Control Logic.

Contains the algorithms for:
- Calculating temperature adjustment based on electricity price
- Determining if central heating should run
"""
import logging
from datetime import datetime, timezone

from config import (
    TEMP_VARIATION,
    PRICE_LOW_THRESHOLD,
    MAX_SHUTOFF_HOURS,
    PRICE_ALWAYS_ON_THRESHOLD,
    CENTRAL_HEATING_SHUTOFF_SWITCH,
)
from heating_logger import log_heating_decision as log_decision_to_file

logger = logging.getLogger(__name__)


def calculate_temperature_adjustment(price):
    """
    Calculate temperature adjustment based on electricity price.
    
    Linear formula: adjustment = TEMP_VARIATION - (price * (TEMP_VARIATION / PRICE_LOW_THRESHOLD))
    - price = 0 c/kWh  → +TEMP_VARIATION°C (cheap/free)
    - price = PRICE_LOW_THRESHOLD c/kWh → 0°C (baseline)
    - price = 2*PRICE_LOW_THRESHOLD c/kWh → -TEMP_VARIATION°C (expensive)
    
    Clamped to ±TEMP_VARIATION range.
    
    Args:
        price: Current electricity price in c/kWh
    
    Returns:
        float: Temperature adjustment in °C (rounded to 2 decimals)
    """
    # Simple linear calculation
    adjustment = TEMP_VARIATION - (price * (TEMP_VARIATION / PRICE_LOW_THRESHOLD))
    
    # Clamp to bounds
    adjustment = max(-TEMP_VARIATION, min(TEMP_VARIATION, adjustment))
    return round(adjustment, 2)


def get_setpoint_temperature(price, base_temp):
    """Calculate the target setpoint temperature based on current price and base temperature.
    
    Args:
        price: Current electricity price in c/kWh
        base_temp: Base temperature setpoint in °C
    
    Returns:
        tuple: (setpoint: float, adjustment: float)
    """
    adjustment = calculate_temperature_adjustment(price)
    setpoint = base_temp + adjustment
    return round(setpoint, 2), adjustment


def should_central_heating_run(current_price, daily_prices):
    """Determine if central heating should be running based on price ranking.
    
    Logic:
    - If current price < PRICE_ALWAYS_ON_THRESHOLD: always return True (heating ON)
    - Otherwise: return False (heating OFF) only if current quarter is among the
      top MAX_SHUTOFF_HOURS*4 most expensive quarters of the day
    
    Args:
        current_price: Current electricity price (c/kWh)
        daily_prices: List of all prices for today (96 quarter-hourly values)
    
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


def log_heating_decision(should_run, reason, current_price):
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

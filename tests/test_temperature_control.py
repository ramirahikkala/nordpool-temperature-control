"""
Unit tests for electricity price-based temperature control.
Run with: pytest tests/ -v
"""

import pytest
import os

# Set dummy token for tests before importing modules
os.environ.setdefault("HA_API_TOKEN", "test_token_for_unit_tests")

from src.temperature_logic import (
    calculate_temperature_adjustment,
    get_setpoint_temperature,
    should_central_heating_run,
)
from src.config import (
    BASE_TEMPERATURE_FALLBACK,
    PRICE_LOW_THRESHOLD,
    PRICE_HIGH_THRESHOLD,
    TEMP_VARIATION,
    PRICE_ALWAYS_ON_THRESHOLD,
    MAX_SHUTOFF_HOURS
)

# Use fallback as base temperature for tests
BASE_TEMPERATURE = BASE_TEMPERATURE_FALLBACK


class TestTemperatureAdjustment:
    """Test temperature adjustment calculation."""
    
    def test_negative_price(self):
        """Test that negative prices are capped at maximum heating."""
        adjustment = calculate_temperature_adjustment(-5)
        assert adjustment == TEMP_VARIATION
        assert adjustment == 0.5
    
    def test_zero_price(self):
        """Test free electricity gives maximum heating adjustment."""
        adjustment = calculate_temperature_adjustment(0)
        assert adjustment == TEMP_VARIATION
        assert adjustment == 0.5
    
    def test_baseline_price(self):
        """Test that baseline price (10 c/kWh) gives no adjustment."""
        adjustment = calculate_temperature_adjustment(PRICE_LOW_THRESHOLD)
        assert adjustment == 0.0
    
    def test_mid_range_price(self):
        """Test price between baseline and high threshold."""
        adjustment = calculate_temperature_adjustment(15)
        assert adjustment == -0.25
    
    def test_high_threshold_price(self):
        """Test that high threshold price (20 c/kWh) gives maximum reduction."""
        adjustment = calculate_temperature_adjustment(PRICE_HIGH_THRESHOLD)
        assert adjustment == -TEMP_VARIATION
        assert adjustment == -0.5
    
    def test_extreme_high_price(self):
        """Test that extreme prices are capped at maximum reduction."""
        adjustment = calculate_temperature_adjustment(60)
        assert adjustment == -TEMP_VARIATION
        assert adjustment == -0.5
    
    def test_cheap_electricity_5_cents(self):
        """Test cheap electricity at 5 c/kWh."""
        adjustment = calculate_temperature_adjustment(5)
        assert adjustment == 0.25
    
    def test_adjustment_within_bounds(self):
        """Test that all adjustments stay within ±TEMP_VARIATION."""
        test_prices = [-10, -5, 0, 2, 5, 8, 10, 12, 15, 18, 20, 30, 50, 100]
        for price in test_prices:
            adjustment = calculate_temperature_adjustment(price)
            assert -TEMP_VARIATION <= adjustment <= TEMP_VARIATION, \
                f"Adjustment {adjustment} out of bounds for price {price}"


class TestSetpointTemperature:
    """Test setpoint temperature calculation."""
    
    def test_setpoint_at_zero_price(self):
        """Test setpoint at free electricity."""
        setpoint, adjustment = get_setpoint_temperature(0, BASE_TEMPERATURE)
        assert setpoint == BASE_TEMPERATURE + TEMP_VARIATION
        assert setpoint == 21.5
        assert adjustment == 0.5
    
    def test_setpoint_at_baseline(self):
        """Test setpoint at baseline price."""
        setpoint, adjustment = get_setpoint_temperature(10, BASE_TEMPERATURE)
        assert setpoint == BASE_TEMPERATURE
        assert setpoint == 21.0
        assert adjustment == 0.0
    
    def test_setpoint_at_high_price(self):
        """Test setpoint at expensive electricity."""
        setpoint, adjustment = get_setpoint_temperature(20, BASE_TEMPERATURE)
        assert setpoint == BASE_TEMPERATURE - TEMP_VARIATION
        assert setpoint == 20.5
        assert adjustment == -0.5
    
    def test_setpoint_returns_tuple(self):
        """Test that function returns both setpoint and adjustment."""
        result = get_setpoint_temperature(10, BASE_TEMPERATURE)
        assert isinstance(result, tuple)
        assert len(result) == 2
        setpoint, adjustment = result
        assert isinstance(setpoint, float)
        assert isinstance(adjustment, float)


class TestLinearFormula:
    """Test that the linear formula works correctly across the range."""
    
    def test_linear_progression_cheap_range(self):
        """Test linear progression in cheap price range (0-10 c/kWh)."""
        # At 0 c/kWh: +0.5°C
        adj_0 = calculate_temperature_adjustment(0)
        # At 5 c/kWh: +0.25°C
        adj_5 = calculate_temperature_adjustment(5)
        # At 10 c/kWh: 0°C
        adj_10 = calculate_temperature_adjustment(10)
        
        assert adj_0 > adj_5 > adj_10
        assert adj_0 == 0.5
        assert adj_5 == 0.25
        assert adj_10 == 0.0
    
    def test_linear_progression_expensive_range(self):
        """Test linear progression in expensive price range (10-20 c/kWh)."""
        # At 10 c/kWh: 0°C
        adj_10 = calculate_temperature_adjustment(10)
        # At 15 c/kWh: -0.25°C
        adj_15 = calculate_temperature_adjustment(15)
        # At 20 c/kWh: -0.5°C
        adj_20 = calculate_temperature_adjustment(20)
        
        assert adj_10 > adj_15 > adj_20
        assert adj_10 == 0.0
        assert adj_15 == -0.25
        assert adj_20 == -0.5
    
    def test_symmetry(self):
        """Test that adjustment is symmetric around baseline."""
        adj_0 = calculate_temperature_adjustment(0)
        adj_20 = calculate_temperature_adjustment(20)
        
        assert adj_0 == -adj_20
        assert abs(adj_0) == abs(adj_20)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_very_negative_price(self):
        """Test extreme negative price."""
        adjustment = calculate_temperature_adjustment(-100)
        assert adjustment == 0.5
    
    def test_very_high_price(self):
        """Test extreme high price."""
        adjustment = calculate_temperature_adjustment(1000)
        assert adjustment == -0.5
    
    def test_float_prices(self):
        """Test that float prices work correctly."""
        adjustment = calculate_temperature_adjustment(10.172)
        assert isinstance(adjustment, float)
        assert -0.5 <= adjustment <= 0.5
    
    def test_rounding(self):
        """Test that results are properly rounded to 2 decimals."""
        adjustment = calculate_temperature_adjustment(7.333)
        # Should have at most 2 decimal places
        assert round(adjustment, 2) == adjustment


class TestCentralHeatingControl:
    """Test central heating control logic with 15-minute granularity."""
    
    def test_cheap_price_always_on(self):
        """Test that cheap prices always allow heating to run."""
        # Create 96 sample prices (24 hours * 4 quarters)
        prices = [10.0] * 96
        
        # Price below threshold should return True
        should_run, reason = should_central_heating_run(5.0, prices)
        assert should_run is True
        assert "always on" in reason.lower() or "threshold" in reason.lower()
    
    def test_15_minute_granularity(self):
        """Test that the function works with 96 prices (15-minute resolution)."""
        # 96 prices = 24 hours at 15-minute intervals
        prices = [10.0 + i*0.1 for i in range(96)]  # Incrementing prices
        
        # Test with different prices
        should_run, reason = should_central_heating_run(15.0, prices)
        assert isinstance(should_run, bool)
        assert isinstance(reason, str)
    
    def test_top_expensive_quarters_shutoff(self):
        """Test that the top expensive quarters are shut off."""
        # Create prices where last 2 hours (8 quarters) are most expensive
        prices = [10.0] * 88 + [50.0] * 8  # Last 8 quarters are expensive
        
        # High price in expensive quarters should turn off heating
        should_run, reason = should_central_heating_run(50.0, prices)
        assert should_run is False
        assert "top" in reason.lower() or "expensive" in reason.lower()
    
    def test_low_price_in_expensive_range(self):
        """Test that low prices don't trigger shutoff even if within shutoff window."""
        # Create prices where last 2 hours are expensive
        prices = [50.0] * 88 + [60.0] * 8
        
        # Current price is 10 (cheap) - should not shut off even if it's rare
        should_run, reason = should_central_heating_run(10.0, prices)
        assert should_run is True
    
    def test_tied_prices_ranked_correctly(self):
        """Test handling of multiple prices at same level."""
        # Create prices with many tied values
        prices = [20.0] * 50 + [30.0] * 46  # 50 quarters at 20, 46 at 30
        
        # At the boundary, should be handled correctly
        should_run_20, _ = should_central_heating_run(20.0, prices)
        should_run_30, _ = should_central_heating_run(30.0, prices)
        
        # 30 is always more expensive, so different behavior
        assert isinstance(should_run_20, bool)
        assert isinstance(should_run_30, bool)
    
    def test_max_shutoff_hours_respected(self):
        """Test that maximum shutoff hours configuration is respected."""
        # Create a day with top MAX_SHUTOFF_HOURS being expensive
        expensive_quarters = int(MAX_SHUTOFF_HOURS * 4)
        prices = [10.0] * (96 - expensive_quarters) + [50.0] * expensive_quarters
        
        # Price at threshold should result in shutoff
        should_run, reason = should_central_heating_run(50.0, prices)
        assert should_run is False
        assert str(expensive_quarters) in reason or "top" in reason.lower()
    
    def test_no_prices_defaults_on(self):
        """Test that missing prices default to heating ON."""
        should_run, reason = should_central_heating_run(10.0, [])
        assert should_run is True
        assert "no" in reason.lower() or "available" in reason.lower()
    
    def test_result_format(self):
        """Test that function returns expected tuple format."""
        prices = [15.0] * 96
        result = should_central_heating_run(15.0, prices)
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        should_run, reason = result
        assert isinstance(should_run, bool)
        assert isinstance(reason, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

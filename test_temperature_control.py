"""
Unit tests for electricity price-based temperature control.
Run with: pytest test_temperature_control.py -v
"""

import pytest
import os

# Set dummy token for tests before importing main
os.environ.setdefault("HA_API_TOKEN", "test_token_for_unit_tests")

from main import (
    calculate_temperature_adjustment,
    get_setpoint_temperature,
    BASE_TEMPERATURE_FALLBACK,
    PRICE_LOW_THRESHOLD,
    PRICE_HIGH_THRESHOLD,
    TEMP_VARIATION
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

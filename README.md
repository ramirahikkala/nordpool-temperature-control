# Home Assistant Temperature Control

Electricity price-based temperature control system for Home Assistant.

## Features

- Monitors Nordpool electricity prices
- Adjusts temperature setpoint based on price (±0.5°C variation)
- Controls Shelly switch for heating
- Runs automatically every 15 minutes (when prices update)

## Configuration

### Create Input Number in Home Assistant (Optional)

To control the base temperature from the HA UI, add this to your `configuration.yaml`:

```yaml
input_number:
  heating_base_temperature:
    name: Heating Base Temperature
    min: 15
    max: 25
    step: 0.5
    unit_of_measurement: "°C"
    icon: mdi:thermometer
  
# `heating_base_temperature` is the only input required here. The calculated
# target setpoint (base + price adjustment) is published by this script to a
# sensor entity in Home Assistant (see `SETPOINT_OUTPUT` in the .env file).
```

**Note:** 
- `heating_base_temperature` is your desired base temperature (INPUT - you control this)
 - Calculated setpoint is published to the entity configured in `SETPOINT_OUTPUT` (OUTPUT - automatically updated by the script)

After adding, restart Home Assistant.

### Setup Environment Variables

Create a `.env` file (copy from `.env.example`):

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Home Assistant Configuration
HA_URL=https://ha.ketunmetsa.fi
HA_API_TOKEN=your_token_here

# Sensors and Entities
PRICE_SENSOR=sensor.nordpool_kwh_fi_eur_3_10_0255
SWITCH_ENTITY=switch.shelly1minig3_5432044efb74
TEMPERATURE_SENSOR=sensor.your_temperature_sensor  # Indoor temperature sensor
OUTDOOR_TEMP_SENSOR=sensor.your_outdoor_temp  # Optional outdoor temperature

# Shelly External Temperature (Optional)
# Send temperature updates to Shelly device for external temperature control
# Example: http://192.168.86.32/ext_t?temp=
SHELLY_TEMP_URL=  # Leave empty to disable

# Temperature Control Settings
BASE_TEMPERATURE=21.0  # Fallback if input_number not used
BASE_TEMPERATURE_INPUT=input_number.heating_base_temperature  # Optional
SETPOINT_OUTPUT=sensor.heating_target_setpoint  # Optional output sensor name (read-only)

PRICE_LOW_THRESHOLD=10.0
PRICE_HIGH_THRESHOLD=20.0
TEMP_VARIATION=0.5
```

**Note**: If `BASE_TEMPERATURE_INPUT` is set, the system will read the temperature from that entity in HA. If it's not set or fails to read, it will use the `BASE_TEMPERATURE` fallback value.

## Temperature Logic

- **Price ≤ 0 c/kWh**: +0.5°C (maximum heating)
- **Price = 10 c/kWh**: 0°C (baseline)
- **Price ≥ 20 c/kWh**: -0.5°C (minimum heating)
- Linear interpolation between these points

## Usage

### Run Locally

```bash
uv run main.py
```

### Run Tests

```bash
uv run pytest test_temperature_control.py -v
```

### Run with Docker Compose

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

The container will automatically run the control script every 15 minutes.

## Development

- `main.py` - Main temperature control logic
- `test_temperature_control.py` - Unit tests
- `Dockerfile` - Container image
- `docker-compose.yml` - Service configuration

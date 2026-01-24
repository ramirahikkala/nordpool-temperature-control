# Nordpool Temperature Control# Home Assistant Temperature Control



Electricity price-based temperature control for Home Assistant.Electricity price-based temperature control system for Home Assistant.



## Features## Features



- Adjusts room heater based on electricity price (±0.5°C from base temperature)- Monitors Nordpool electricity prices

- Blocks central heating during the most expensive hours- Adjusts temperature setpoint based on price (±0.5°C variation)

- Web dashboard with price charts and status- Controls Shelly switch for heating

- Sends temperature to Shelly device for external control- Runs automatically every 15 minutes (when prices update)



## Quick Start## Configuration



```bash### Create Input Number in Home Assistant (Optional)

# Copy and edit environment variables

cp .env.example .envTo control the base temperature from the HA UI, add this to your `configuration.yaml`:



# Run with uv```yaml

uv run main.pyinput_number:

  heating_base_temperature:

# Or run web dashboard    name: Heating Base Temperature

uv run python -m web.app    min: 15

```    max: 25

    step: 0.5

## Configuration    unit_of_measurement: "°C"

    icon: mdi:thermometer

Key environment variables in `.env`:  

# `heating_base_temperature` is the only input required here. The calculated

```bash# target setpoint (base + price adjustment) is published by this script to a

HA_URL=https://your-ha-instance# sensor entity in Home Assistant (see `SETPOINT_OUTPUT` in the .env file).

HA_API_TOKEN=your_token```



TEMPERATURE_SENSOR=sensor.indoor_temp**Note:** 

SWITCH_ENTITY=switch.room_heater- `heating_base_temperature` is your desired base temperature (INPUT - you control this)

CENTRAL_HEATING_SHUTOFF_SWITCH=switch.central_heating  # Optional - Calculated setpoint is published to the entity configured in `SETPOINT_OUTPUT` (OUTPUT - automatically updated by the script)



BASE_TEMPERATURE=21.0After adding, restart Home Assistant.

TEMP_VARIATION=0.5

```### Setup Environment Variables



## Project StructureCreate a `.env` file (copy from `.env.example`):



``````bash

├── main.py              # Entry point (scheduler)cp .env.example .env

├── src/```

│   ├── config.py        # Configuration

│   ├── ha_client.py     # Home Assistant APIEdit `.env` with your settings:

│   ├── temperature_logic.py

│   ├── control.py       # Main control loop```bash

│   └── background_tasks.py# Home Assistant Configuration

├── web/HA_URL=https://ha.ketunmetsa.fi

│   ├── app.py           # Flask dashboardHA_API_TOKEN=your_token_here

│   └── templates/

├── tests/# Sensors and Entities

└── data/PRICE_SENSOR=sensor.nordpool_kwh_fi_eur_3_10_0255

```SWITCH_ENTITY=switch.shelly1minig3_5432044efb74

TEMPERATURE_SENSOR=sensor.your_temperature_sensor  # Indoor temperature sensor

## DockerOUTDOOR_TEMP_SENSOR=sensor.your_outdoor_temp  # Optional outdoor temperature



```bash# Shelly External Temperature (Optional)

docker compose up -d# Send temperature updates to Shelly device for external temperature control

```# Example: http://192.168.86.32/ext_t?temp=

SHELLY_TEMP_URL=  # Leave empty to disable

## Temperature Logic

# Temperature Control Settings

| Price (c/kWh) | Adjustment |BASE_TEMPERATURE=21.0  # Fallback if input_number not used

|---------------|------------|BASE_TEMPERATURE_INPUT=input_number.heating_base_temperature  # Optional

| ≤ 0           | +0.5°C     |SETPOINT_OUTPUT=sensor.heating_target_setpoint  # Optional output sensor name (read-only)

| 10            | 0°C        |

| ≥ 20          | -0.5°C     |PRICE_LOW_THRESHOLD=10.0

PRICE_HIGH_THRESHOLD=20.0

Linear interpolation between these points.TEMP_VARIATION=0.5

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

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant configuration repository for a Swedish smart home. Primary focus areas:
- **Energy management**: Solar production monitoring (Fronius inverter), NordPool electricity pricing
- **EV charging**: Multi-car charging control via ChargeNode wallbox (Modbus TCP)
- **Climate**: IVT heat pump monitoring, room-based automation
- **Lighting**: ZigBee-based (Aqara devices), Tellstick RF, 9+ room zones

Running Home Assistant 2026.1.3 with MariaDB on Synology NAS for history storage.

## Configuration Architecture

**Entry point**: `configuration.yaml` - includes all other configs via `!include` directives

**Include patterns used**:
```yaml
!include filename.yaml              # Single file
!include_dir_named packages/        # Directory as dict (package names become keys)
!include_dir_list mqtt/             # Directory as list
!include_dir_merge_list templates/  # Merge lists from directory
!secret key_name                    # From secrets.yaml (git-ignored)
```

**Key configuration files**:
| File | Purpose |
|------|---------|
| `automations.yaml` | 100+ automation rules |
| `scripts.yaml` | Reusable automation sequences |
| `templates/` | Jinja2 template sensors (7 files: cars, prices, sun, weather, etc.) |
| `modbus.yaml` | ChargeNode EV charger TCP communication |
| `mqtt/teslamate.yaml` | TeslaMate vehicle data integration |
| `vars.yaml` | Persistent state variables (solar accumulation, car states) |
| `packages/` | Bundled component configs (currently: engineheater) |

**Custom components**:
- `custom_zha_quirks/` - ZigBee device quirks (Aqara H1 remote, Tuya TS0601 dimmer)
- `python_scripts/shellies_discovery.py` - Shelly device auto-discovery

## Key Integrations

**Communication protocols**:
- **Modbus TCP**: ChargeNode EV charger at `!secret modbus_chargenode_host`
- **MQTT**: TeslaMate data, Shelly devices, BYD vehicle telemetry
- **REST**: ChargeNode queue management (`rest.yaml`)
- **ZHA**: Primary ZigBee coordinator with OTA updates enabled

**Vehicles tracked**: 2 EVs (Delphine/BYD Dolphin, RYA)

**Hot tub (Spabadet)**: Price-aware thermostat with freeze protection (see details below)

**External services**: Google Assistant, Google Calendar, NordPool pricing, YR weather

## Template Patterns

Templates in `/templates/` use Jinja2 heavily. **Naming**: older template entities have a `template_` prefix (e.g. `sensor.template_spabadet_temperature`), but newer HA versions use the `unique_id` directly (e.g. `binary_sensor.spabadet_deadline_heating`). Don't add the prefix for new entities.

Common patterns:

```yaml
# State-based calculations
{{ states('sensor.power_meter') | float(0) }}

# Attribute access
{{ state_attr('sensor.name', 'attribute') }}

# Conditional logic with multiple states
{% if is_state('binary_sensor.car_charging', 'on') %}
```

Energy templates calculate: home power balance (excluding EV), solar production tracking, price-aware charging decisions.

## Hot Tub (Spabadet)

Controlled via 3 switched phases: `switch.spabadet_l2` (heater), `switch.spabadet_l3` (pump). Temperature from battery-powered sensor (`sensor.spabadet_temperatur`).

**Core logic** in `script.spabadet_pump_and_heater_v2` (scripts.yaml):
- **Heater ON** if: temp below `input_number.spabadet_lower_temp_limit`, OR price is cheap, OR deadline heating active — AND temp below target (`input_number.spabadet_target_temp_weekdays` / `input_number.spabadet_target_temp_weekends`)
- **Pump ON** if: outdoor temp < 0°C (freeze protection), water temp below limit, deadline heating active, or every 4h when pump ran < 7h/day

**Deadline heating** (`binary_sensor.spabadet_deadline_heating` in `templates/hottub.yaml`):
- Three modes: **pre-tomorrow** (Thu/Fri when tomorrow_valid), **same-day** (Fri/Sat before 16:00), **bath maintenance** (Fri/Sat 16:00–20:00)
- Pre-tomorrow: on Thu after ~13:00 (when NordPool tomorrow_valid), picks cheapest hours from today+tomorrow prices through Fri 16:00. Same on Fri evening for Sat.
- Same-day: picks cheapest hours from today's prices to reach target by 16:00
- Formula: `hours_needed = ceil((target + 1 - current + hours_left × 0.2) / 2.0)` (heating rate 2°C/h, cooling 0.2°C/h, +1°C buffer)
- Hard deadline: if hours_left <= hours_needed, always heats
- Bath maintenance (16:00–20:00): heats if below target regardless of price
- After 20:00: OFF (bath is over)

**Automation** (`Spabadet, pump and heater`): Triggers hourly, on temp changes, and on NordPool price changes. Calls the V2 script.

**Disabled automations** (superseded by deadline heating sensor):
- `Kontrollera spabadets värme och pump` — overlapped with V2 script
- `Värma spabadet med billigaste elpris på fredagar` — replaced by template sensor

**Alarm** (`Spabadet, larm om värmen`): Notifies on stale temp readings (2h+), temp below limit, or unexpected power draw.

**Manual override** (`script.spabadet_pause_control`): Toggled via `input_boolean.spabadet_manual` — disables automation, turns on pump+heater, tracks session cost via `var.spa_cost`.

**Load balancing**: EV charging script (`ladda_bilen_uppstart`) turns off spa heater during charging to free L2 capacity. `binary_sensor.l2_overcurrent` detects overload (L2 >= 20A with spa drawing current).

**Template sensors** in `templates/hottub.yaml`: energy (corrected kWh, monotonic counters), power, cost, per-phase current, temperature, pump runtime.

## Development Notes

- **Validation**: Home Assistant validates YAML on startup/reload
- **Testing**: Use Developer Tools in HA UI or trigger service calls
- **Secrets**: All credentials in `secrets.yaml` (git-ignored)
- **Language**: Swedish in UI labels and automation descriptions
- **Database**: 3-day history retention in external MariaDB

## Network Context

- Trusted proxy range: `172.30.33.0/24` (Docker/HA network)
- Tellstick Duo: `core-tellstick:50800-50801`
- ZigBee database: `/config/zigbee.db`

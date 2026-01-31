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

**External services**: Google Assistant, Google Calendar, NordPool pricing, YR weather

## Template Patterns

Templates in `/templates/` use Jinja2 heavily. Common patterns:

```yaml
# State-based calculations
{{ states('sensor.power_meter') | float(0) }}

# Attribute access
{{ state_attr('sensor.name', 'attribute') }}

# Conditional logic with multiple states
{% if is_state('binary_sensor.car_charging', 'on') %}
```

Energy templates calculate: home power balance (excluding EV), solar production tracking, price-aware charging decisions.

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

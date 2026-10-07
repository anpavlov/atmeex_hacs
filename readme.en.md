# Atmeex Cloud

[Русская версия](README.md)

A Home Assistant integration to control Airnanny A7 breathers through the Atmeex cloud service.

## Features

- Control operation modes: off, heating, ventilation
- 7 fan speeds: as a percentage (Fan) or as a number from 1 to 7 (Number)
- 3 damper positions: supply, mixed mode, recirculation
- Heating temperature control (10-30°C, 0.5°C step)
- Passive ventilation (damper open, fan off)
- Current readings: room temperature and humidity, CO₂, intake air temperature
- Humidifier: off or stage 1–3, "No water" sensor (on models with a humidifier)
- Auto mode and night mode
- Authorization via email + password, or via phone number with SMS one-time code

## Supported Devices

- Airnanny A7

## Installation

### Via HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=anpavlov&repository=atmeex_hacs)

### Manual

1. Copy the `custom_components/atmeex_cloud` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant


## Platforms

The integration creates entities of these types for each device (some only on models with a humidifier):

- **Climate** — full breather control: power, temperature, fan speed, damper mode
- **Switch** — power switch with automatic damper control, auto mode and night mode
- **Fan** — fan speed and power control WITHOUT damper control
- **Number** — fan speed as a number from 1 to 7
- **Select** — damper position (open/mixed/closed) and humidifier stage selection
- **Sensor** — current breather sensor readings
- **Binary sensor** — humidifier is out of water

### Climate

Main entity for breather control.

**HVAC Modes:**

- **Off** — turns off power and closes the damper
- **Heat** — supply air with heating to the set temperature
- **Fan Only** — ventilation without heating with open damper

**Fan Speed Control:**

7 preset speeds — from 1 to 7

**Preset Modes (damper positions):**

- **Supply** — damper open, air from outside
- **Mixed** — mixed mode
- **Recirculation** — damper closed, air from indoors

**Heating Temperature Control:**

- Range: 10-30°C
- Step: 0.5°C

### Switch

Power switch with automatic damper control.

- **On:** opens damper (outdoor air supply) and turns on fan
- **Off:** closes damper (recirculation) and turns off fan

Perfect for simple on/off control with fresh air supply in automations.

### Switch (Auto mode, Night mode)

Turn the breather's auto mode and night mode on and off, like the buttons with the same names in the Atmeex app. The modes exclude each other: turning one on turns the other off.

In auto mode the breather picks the fan speed itself, so a manual speed change (Number, Fan, fan mode in Climate) turns auto mode off.

### Fan

Entity for fan control without damper management.

- Turn fan on/off
- Speed control in percentage (0-100%) — converts to speeds 1 to 7
- **Important:** Does NOT change damper position when turned on/off

Use Fan when you want to control only the fan while keeping the current damper position.

### Number (Fan speed)

Fan speed as a number from 1 to 7, the same as the fan mode in Climate. It changes the speed only: a breather that is off stays off, auto mode turns off. The Fan entity with its percentage speed keeps working as before.

### Select (Damper)

Entity for independent damper position control.

- **Supply** — damper open
- **Mixed** — mixed mode
- **Recirculation** — damper closed

### Select (Humidifier)

Humidification stage: off, stage 1, 2 or 3. Created only for models with a humidifier — only they report room humidity.

### Sensor

Breather sensor readings, updated every 30 seconds:

- **Room temperature**, °C (also shown as current temperature in Climate)
- **Room humidity**, % (also shown as current humidity in Climate)
- **CO₂**, ppm
- **Intake air temperature**, °C

A sensor is created only if the breather reports that reading: room humidity exists only on models with a humidifier, CO₂ only on models with a CO₂ sensor (models without one report zero).

### Binary sensor (No water)

Turns on when the humidifier runs out of water. Created only for models with a humidifier.

## Operation Features

### Switch vs Fan — Key Difference

- **Switch** — controls power AND damper. When turned on, always provides outdoor air supply.
- **Fan** — controls ONLY the fan. Damper position remains unchanged.

### On/Off Behavior

- **Switch:** opens damper on turn on, closes on turn off
- **Fan:** does NOT touch the damper on either turn on or turn off
- **Climate:** HEAT/FAN_ONLY opens damper, closes on turn off

### Passive Ventilation

You can open the damper with the fan turned off. This allows natural ventilation without the noise of a running fan.

**Method 1 (via Climate):**
1. Turn off the climate entity
2. Enable "Supply" preset

**Method 2 (via Fan + Select):**
1. Turn off the fan via the Fan entity
2. Set the damper to "Supply" via the Select entity

**Method 3 (via Switch + Select):**
1. Turn off Switch (will close the damper)
2. Set damper to "Supply" via Select (will open damper without turning on fan)

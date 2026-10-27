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
- Local mode: breezers work with Home Assistant without the Atmeex cloud

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

## Local mode (no cloud)

Breezers keep a TCP connection to the Atmeex cloud (`ws.iot.atmeex.com`, port 3001) and exchange JSON messages with it. The integration can accept these connections itself: the breezers then work even when the cloud is down, and readings arrive as soon as a breezer sends them (usually every 5 seconds). Home Assistant can also relay the breezers' messages to the cloud and back, so the Atmeex app keeps working.

1. Turn on "Local server for breezers" in the integration options (**Settings → Devices & services → Atmeex Cloud → Configure**). Home Assistant starts listening on TCP port 3001. "Atmeex cloud connection through Home Assistant" is on by default.
2. Make the router redirect the breezers' connections to port 3001 to Home Assistant. Breezers and Home Assistant are usually on the same network, so hairpin NAT is needed too, otherwise the breezer gets the reply from the wrong address. Example for MikroTik (replace `<...>` with the addresses of the breezer and Home Assistant; add other breezers to the same list):

   ```
   /ip firewall address-list
   add list=atmeex-breezers address=<breezer IP>
   /ip firewall nat
   add chain=dstnat src-address-list=atmeex-breezers protocol=tcp dst-port=3001 action=dst-nat to-addresses=<Home Assistant IP> to-ports=3001 comment=atmeex-local
   add chain=srcnat src-address-list=atmeex-breezers dst-address=<Home Assistant IP> protocol=tcp dst-port=3001 action=masquerade comment=atmeex-local
   ```

   Don't add Home Assistant's own address to the list: its own cloud connections would come back to it. A breezer connects to Home Assistant the next time it reconnects (after a reboot or when its cloud connection drops).

Good to know:

- The integration takes the device list from the cloud and keeps a copy, so it has to reach the cloud successfully once. After that local mode works without it.
- With the cloud connection on, Home Assistant keeps a cloud connection for each connected breezer: the Atmeex app sees the readings and controls the breezer as before, and changes from the app and from Home Assistant reach each other through the breezer. When the cloud is down, the breezers keep working with Home Assistant, and once the cloud is back Home Assistant connects them to it on its own. Without the cloud connection, breezers connected to Home Assistant are offline in the app.
- Home Assistant becomes a link between the breezers and the cloud: while it is off or restarting, the breezers can't reach the cloud either. The router can lift the redirect while Home Assistant isn't ready for the breezers, so they connect to the cloud directly. Example for MikroTik (the rules from the example above are marked `comment=atmeex-local`): one check notices a frozen Home Assistant (the web UI doesn't answer), the other notices that the local server isn't listening, for example while Home Assistant is starting. The redirect is on only while both are fine:

  ```
  /tool netwatch
  add comment=atmeex-ha-web type=http-get host=<Home Assistant IP> port=8123 interval=30s timeout=10s down-script="/system script run atmeex-local-off" up-script="/system script run atmeex-local-on"
  add comment=atmeex-ha-local type=tcp-conn host=<Home Assistant IP> port=3001 interval=30s timeout=5s down-script="/system script run atmeex-local-off" up-script="/system script run atmeex-local-on"
  /system script
  add name=atmeex-local-off source="/ip firewall nat disable [find comment=atmeex-local]; /ip firewall connection remove [find protocol=tcp dst-port=3001]"
  add name=atmeex-local-on source=":if ([/tool netwatch get [find comment=atmeex-ha-web] status]=\"up\" && [/tool netwatch get [find comment=atmeex-ha-local] status]=\"up\") do={/ip firewall nat enable [find comment=atmeex-local]; /ip firewall connection remove [find protocol=tcp dst-port=3001]}"
  ```

  Dropping the connections makes the breezers reconnect right away instead of at the next break.
- To move the breezers back to the cloud directly, remove the router rules and turn the local server off.
- Commands go straight to the breezer; breezers not connected to Home Assistant are still controlled through the cloud.
- The server only accepts breezers from your account, but without a password: any device on the local network can pretend to be a breezer. Don't expose port 3001 to the internet.

## Tests

The tests run the integration in a real Home Assistant (`pytest-homeassistant-custom-component`) against a fake Atmeex cloud. Python 3.14 is required:

```sh
pip install -r requirements_test.txt
pytest
```

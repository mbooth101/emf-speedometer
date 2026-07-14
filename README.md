# Speedometer

Strap your Tildagon to your Hacky Racer, radio-controlled Henry Hoover, karaoke tuk-tuk, or anything else that needs a speedometer.

Written as a demo for my event-based GPS Hexpansion firmware concept, and therefore requires the presence of a GPS Hexpansion such as that made by [The Machine Shop](https://themachineshop.uk/products/gps-hexpansion/) initialised with the latest GPS Hexpansion firmware.

## Controls

* A/D buttons: Cycle through units (knots, mph, km/h, m/s)
* B/E buttons: Cycle through dial speed ranges (e.g show 0 to 10, 0 to 20, or 0 to 30 mph)
* F button: Suspend Speedometer and return to the Tildagon main menu.

## Install

**NOTE:** This app requires Tildagon OS v2.0.0 or newer!

This is due to making use of new Hexpansion utility functions to interact with EEPROM firmware code running on the GPS module.

### From App Store

Available from the app store: https://apps.badge.emfcamp.org/apps/00432041/

### Local Install

Cross compile with the `mpy-cross` tool and download to the badge with the `mpremote` tool:

```
cd emf-speedometer
mpy-cross app.py
mpremote fs cp app.mpy :/apps/mbooth101_emf_speedometer
```

## Firmware Install

If your GPS Hexpansion arrived uninitialised, or you need to manually re-flash the Hexpansion firmware for any reason, you can do so by inserting the GPS Hexpansion into port 2 of your Tildagon, and running the following commands:

```
cd emf-speedometer
mpremote mount EEPROM + run EEPROM/prepare_eeprom.py + cp EEPROM/gps.mpy :/hexpansion/app.mpy
```

Once complete, the GPS Hexpansion may be inserted into any port. The script is just hard-coded to port 2 for flashing the firmware.

## Demo

[speedo_demo.webm](https://github.com/user-attachments/assets/e3bb52ef-21a5-45c4-a1f6-146faa869056)

The 3D printed Tildagon case is by [Nightcaster](https://github.com/nightcaster), plans [available from Printables](https://www.printables.com/model/1643166-emf-tildagon-badge-case-emf-2024-badge).

## License

This repo is MIT licensed.

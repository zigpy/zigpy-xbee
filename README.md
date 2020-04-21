# zigpy-xbee

[![Build Status](https://travis-ci.org/zigpy/zigpy-xbee.svg?branch=master)](https://travis-ci.org/zigpy/zigpy-xbee)
[![Coverage](https://coveralls.io/repos/github/zigpy/zigpy-xbee/badge.svg?branch=master)](https://coveralls.io/github/zigpy/zigpy-xbee?branch=master)

[zigpy-xbee](https://github.com/zigpy/zigpy-xbee/) is a Python implementation for the [Zigpy](https://github.com/zigpy/) project to implement [XBee](https://en.wikipedia.org/wiki/XBee) based [Zigbee](https://www.zigbee.org) radio devices from Digi.

- https://github.com/zigpy/zigpy-xbee

Digi XBee is the brand name of a family of form factor compatible radio modules from Digi International. 

The XBee radios can all be used with the minimum number of connections — power (3.3 V), ground, data in and data out (UART), with other recommended lines being Reset and Sleep.[5] Additionally, most XBee families have some other flow control, input/output (I/O), analog-to-digital converter (A/D) and indicator lines built in.

- https://en.wikipedia.org/wiki/XBee

Zigbee Home Automation integration with **[zigpy](https://github.com/zigpy/zigpy/)** allows you to connect one of many off-the-shelf Zigbee adapters using one of the available Zigbee radio library modules compatible with zigpy to control Zigbee based devices, including this **[zigpy-xbee](https://github.com/zigpy/zigpy-xbee/)** library for Xbee based Zigbee radio modules. 

[zigpy](https://github.com/zigpy/zigpy/)** currently has support for controlling Zigbee device types such as binary sensors (e.g., motion and door sensors), sensors (e.g., temperature sensors), lightbulbs, switches, and fans. A working implementation of zigbe exist in **[Home Assistant](https://www.home-assistant.io)** (Python based open source home automation software) as part of its **[ZHA component](https://www.home-assistant.io/components/zha/)**

## Compatible hardware

zigpy works with separate radio libraries which can each interface with multiple USB and GPIO radio hardware adapters/modules over different native UART serial protocols. Such radio libraries includes **[zigpy-xbee](https://github.com/zigpy/zigpy-xbee)** (which communicates with XBee based Zigbee radios), **[bellows](https://github.com/zigpy/bellows)** (which communicates with EZSP/EmberZNet based radios), and as **[zigpy-deconz](https://github.com/zigpy/zigpy-deconz)** for deCONZ serial protocol (for communicating with ConBee and RaspBee USB and GPIO radios from Dresden-Elektronik). There are also an experimental radio library called **[zigpy-zigate](https://github.com/doudz/zigpy-zigate)** for communicating with ZiGate based radios.

### Known working XBee based Zigbee radio modules for Zigpy

These are XBee Zigbee based radios that have been tested with the [zigpy-xbee](https://github.com/zigpy/zigpy-xbee) library for zigpy

- Digi XBee Series 2C (S2C) modules
- Digi XBee Series 2 (S2) modules. Note: These will need to be manually flashed with the Zigbee Coordinator API firmware via XCTU.
- Digi XBee Series 3 (xbee3-24) modules

# Releases of zigpy-xbee via PyPI

New packages of tagged versions are also released via the "zigpy-xbee" project on PyPI
- https://pypi.org/project/zigpy-xbee/
  - https://pypi.org/project/zigpy-xbee/#history
  - https://pypi.org/project/zigpy-xbee/#files

Older packages of tagged versions are still available on the "zigpy-xbee-homeassistant" project on PyPI
  - https://pypi.org/project/zigpy-xbee-homeassistant/

# How to contribute

If you are looking to make a contribution to this project we suggest that you follow the steps in these guides:
- https://github.com/firstcontributions/first-contributions/blob/master/README.md
- https://github.com/firstcontributions/first-contributions/blob/master/github-desktop-tutorial.md

Some developers might also be interested in receiving donations in the form of hardware such as Zigbee modules or devices, and even if such donations are most often donated with no strings attached it could in many cases help the developers motivation and indirect improve the development of this project.

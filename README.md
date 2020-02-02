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

# Releases of zigpy-xbee-homeassistant via PyPI
Tagged versions of zigpy-xbee-homeassistant are also released via PyPI

- https://pypi.org/project/zigpy-xbee-homeassistant/
- https://pypi.org/project/zigpy-xbee-homeassistant/#history
- https://pypi.org/project/zigpy-xbee-homeassistant/#files

# How to contribute

If you are looking to make a contribution to this project we suggest that you follow the steps in these guides:
- https://github.com/firstcontributions/first-contributions/blob/master/README.md
- https://github.com/firstcontributions/first-contributions/blob/master/github-desktop-tutorial.md

Some developers might also be interested in receiving donations in the form of hardware such as Zigbee modules or devices, and even if such donations are most often donated with no strings attached it could in many cases help the developers motivation and indirect improve the development of this project.

## Related projects

### Zigpy
[Zvigpy](https://github.com/zigpy/zigpy)** is **[Zigbee protocol stack](https://en.wikipedia.org/wiki/Zigbee)** integration project to implement the **[Zigbee Home Automation](https://www.zigbee.org/)** standard as a Python 3 library. Zigbee Home Automation integration with zigpy allows you to connect one of many off-the-shelf Zigbee adapters using one of the available Zigbee radio library modules compatible with zigpy to control Zigbee based devices. There is currently support for controlling Zigbee device types such as binary sensors (e.g., motion and door sensors), sensors (e.g., temperature sensors), lightbulbs, switches, and fans. A working implementation of zigbe exist in **[Home Assistant](https://www.home-assistant.io)** (Python based open source home automation software) as part of its **[ZHA component](https://www.home-assistant.io/components/zha/)**

### ZHA Device Handlers
ZHA deviation handling in Home Assistant relies on on the third-party [ZHA Device Handlers](https://github.com/dmulcahey/zha-device-handlers) project. Zigbee devices that deviate from or do not fully conform to the standard specifications set by the [Zigbee Alliance](https://www.zigbee.org) may require the development of custom [ZHA Device Handlers](https://github.com/dmulcahey/zha-device-handlers) (ZHA custom quirks handler implementation) to for all their functions to work properly with the ZHA component in Home Assistant. These ZHA Device Handlers for Home Assistant can thus be used to parse custom messages to and from non-compliant Zigbee devices. The custom quirks implementations for zigpy implemented as ZHA Device Handlers for Home Assistant are a similar concept to that of [Hub-connected Device Handlers for the SmartThings Classics platform](https://docs.smartthings.com/en/latest/device-type-developers-guide/) as well as that of [Zigbee-Shepherd Converters as used by Zigbee2mqtt](https://www.zigbee2mqtt.io/how_tos/how_to_support_new_devices.html), meaning they are each virtual representations of a physical device that expose additional functionality that is not provided out-of-the-box by the existing integration between these platforms.

### ZHA Map
[zha-map](https://github.com/zha-ng/zha-map) project allow Home Assistant to build a ZHA network topology map.

### zha-network-visualization-card
[zha-network-visualization-card](https://github.com/dmulcahey/zha-network-visualization-card) is a custom Lovelace element for visualizing the ZHA Zigbee network in Home Assistant.

### ZHA Network Card
[zha-network-card](https://github.com/dmulcahey/zha-network-card) is a custom Lovelace card that displays ZHA network and device information in Home Assistant

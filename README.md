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

- [Digi XBee Series 3 (xbee3-24)](https://www.digi.com/products/embedded-systems/digi-xbee/rf-modules/2-4-ghz-rf-modules/xbee3-zigbee-3) and [Digi XBee Series S2C](https://www.digi.com/products/embedded-systems/digi-xbee/rf-modules/2-4-ghz-rf-modules/xbee-zigbee) modules
  - Note! While not a must, [it is recommend to upgrade XBee Series 3 and S2C to newest firmware firmware using XCTU](https://www.digi.com/resources/documentation/Digidocs/90002002/Default.htm#Tasks/t_load_zb_firmware.htm)
- [Digi XBee Series 2 (S2)](https://www.digi.com/support/productdetail?pid=3430) modules (Note! This first have to be [flashed with Zigbee Coordinator API firmware](https://www.digi.com/support/productdetail?pid=3430))

# Port configuration

- To configure __usb__ port path for your XBee serial device, just specify the TTY (serial com) port, example : `/dev/ttyACM0`

Note! Users can change UART baud rate of your Digi XBee using the Digi's XCTU configuration tool. Using XCTU tool 
enable the API communication mode -- `ATAP2`, set baudrate to 57600 -- `ATBD6`, save parameters.

# Testing new releases

Testing a new release of the zigpy-xbee library before it is released in Home Assistant.

If you are using Supervised Home Assistant (formerly known as the Hassio/Hass.io distro):
- Add https://github.com/home-assistant/hassio-addons-development as "add-on" repository
- Install "Custom deps deployment" addon
- Update config like: 
  ```
  pypi:
    - zigpy-xbee==0.12.0
  apk: []
  ```
  where 0.12.0 is the new version
- Start the addon

If you are instead using some custom python installation of Home Assistant then do this:
- Activate your python virtual env
- Update package with ``pip``
  ```
  pip install zigpy-xbee==0.12.0

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

"""Setup module for zigpy-xbee"""

from setuptools import find_packages, setup

import zigpy_xbee

setup(
    name="zigpy-xbee-homeassistant",
    version=zigpy_xbee.__version__,
    description="A library which communicates with XBee radios for zigpy",
    url="http://github.com/zigpy/zigpy-xbee",
    author="Russell Cloran",
    author_email="rcloran@gmail.com",
    license="GPL-3.0",
    packages=find_packages(exclude=["*.tests"]),
    install_requires=["pyserial-asyncio", "zigpy-homeassistant >= 0.10.0"],
    tests_require=["pytest"],
)

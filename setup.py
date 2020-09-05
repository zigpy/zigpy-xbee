"""Setup module for zigpy-xbee"""

import os

from setuptools import find_packages, setup

import zigpy_xbee

this_directory = os.path.join(os.path.abspath(os.path.dirname(__file__)))
with open(os.path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="zigpy-xbee",
    version=zigpy_xbee.__version__,
    description="A library which communicates with XBee radios for zigpy",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="http://github.com/zigpy/zigpy-xbee",
    author="Russell Cloran",
    author_email="rcloran@gmail.com",
    license="GPL-3.0",
    packages=find_packages(exclude=["*.tests"]),
    install_requires=["pyserial-asyncio", "zigpy>= 0.23.0"],
    tests_require=["pytest"],
)

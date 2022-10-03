"""Setup module for zigpy-xbee"""

import pathlib

from setuptools import find_packages, setup

import zigpy_xbee

setup(
    name="zigpy-xbee",
    version=zigpy_xbee.__version__,
    description="A library which communicates with XBee radios for zigpy",
    long_description=(pathlib.Path(__file__).parent / "README.md").read_text(),
    long_description_content_type="text/markdown",
    url="http://github.com/zigpy/zigpy-xbee",
    author="Russell Cloran",
    author_email="rcloran@gmail.com",
    license="GPL-3.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=["zigpy>=0.51.0"],
    tests_require=["pytest", "asynctest", "pytest-asyncio"],
)

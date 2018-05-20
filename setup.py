"""Setup module for zigbpy-xbee"""

from setuptools import find_packages, setup

setup(
    name="zigpy-xbee",
    version="0.1.1",
    description="A library which communicates with XBee radios for zigpy",
    url="http://github.com/zigpy/zigpy-xbee",
    author="Russell Cloran",
    author_email="rcloran@gmail.com",
    license="GPL-3.0",
    packages=find_packages(exclude=['*.tests']),
    install_requires=[
        'pyserial-asyncio',
        'zigpy',
    ],
    tests_require=[
        'pytest',
    ],
)

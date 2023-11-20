"""XBee module config."""

import voluptuous as vol
import zigpy.config

SCHEMA_DEVICE = zigpy.config.SCHEMA_DEVICE.extend(
    {vol.Optional(zigpy.config.CONF_DEVICE_BAUDRATE, default=57600): int}
)

CONFIG_SCHEMA = zigpy.config.CONFIG_SCHEMA.extend(
    {vol.Required(zigpy.config.CONF_DEVICE): zigpy.config.SCHEMA_DEVICE}
)

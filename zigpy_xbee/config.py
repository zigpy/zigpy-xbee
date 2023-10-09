"""XBee module config."""

import voluptuous as vol
from zigpy.config import (  # noqa: F401 pylint: disable=unused-import
    CONF_DATABASE,
    CONF_DEVICE,
    CONF_DEVICE_PATH,
    CONFIG_SCHEMA,
    SCHEMA_DEVICE,
    cv_boolean,
)

CONF_DEVICE_BAUDRATE = "baudrate"

SCHEMA_DEVICE = SCHEMA_DEVICE.extend(
    {vol.Optional(CONF_DEVICE_BAUDRATE, default=57600): int}
)

CONFIG_SCHEMA = CONFIG_SCHEMA.extend({vol.Required(CONF_DEVICE): SCHEMA_DEVICE})

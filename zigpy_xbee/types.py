"""Additional types for data parsing."""

import enum

import zigpy.types as t


class Bytes(bytes):
    """Serializable and deserializable bytes."""

    def serialize(self):
        """Serialize the class."""
        return self

    @classmethod
    def deserialize(cls, data):
        """Deserialize the data into the class."""
        return cls(data), b""


class ATCommand(Bytes):
    """XBee AT command name."""

    @classmethod
    def deserialize(cls, data):
        """Deserialize the data into the class."""
        return cls(data[:2]), data[2:]


class EUI64(t.EUI64):
    """EUI64 without prefix."""

    @classmethod
    def deserialize(cls, data):
        """Deserialize the data into the class."""
        r, data = super().deserialize(data)
        return cls(r[::-1]), data

    def serialize(self):
        """Serialize the class."""
        assert self._length == len(self)
        return super().serialize()[::-1]


class UndefinedEnumMeta(enum.EnumMeta):
    """Meta class for Enum that always has a value."""

    def __call__(cls, value=None, *args, **kwargs):
        """Return the member, default, or undefined value."""
        if value is None:
            # the 1st enum member is default
            return next(iter(cls))

        try:
            return super().__call__(value, *args, **kwargs)
        except ValueError as exc:
            try:
                return super().__call__(cls._UNDEFINED)
            except AttributeError:
                raise exc


class UndefinedEnum(enum.Enum, metaclass=UndefinedEnumMeta):
    """Enum that always has a value."""


class FrameId(t.uint8_t):
    """API frame ID."""


class NWK(t.uint16_t_be):
    """zigpy.types.NWK but big endian."""

    def __repr__(self):
        """Get printable representation."""
        return f"0x{self:04x}"

    def __str__(self):
        """Get string representation."""
        return f"0x{self:04x}"


class Relays(t.LVList, item_type=NWK, length_type=t.uint8_t):
    """List of Relays."""


UNKNOWN_IEEE = EUI64([t.uint8_t(0xFF) for i in range(0, 8)])
UNKNOWN_NWK = NWK(0xFFFE)


class TXStatus(t.uint8_t, UndefinedEnum):
    """TX Status frame."""

    SUCCESS = 0x00  # Standard

    # all retries are expired and no ACK is received.
    # Not returned for Broadcasts
    NO_ACK_RECEIVED = 0x01
    CCA_FAILURE = 0x02

    # Transmission was purged because a coordinator tried to send to an end
    # device, but it timed out waiting for a poll from the end device that
    # never occurred, this haapens when Coordinator times out of an indirect
    # transmission. Timeouse is defines ad 2.5 * 'SP' (Cyclic Sleep Period)
    # parameter value
    INDIRECT_TX_TIMEOUT = 0x03

    # invalid destination endpoint
    INVALID_DESTINATION_ENDPOINT = 0x15

    # not returned for Broadcasts
    NETWORK_ACK_FAILURE = 0x21

    # TX failed because end device was not joined to the network
    INDIRECT_TX_FAILURE = 0x22

    # Self addressed
    SELF_ADDRESSED = 0x23

    # Address not found
    ADDRESS_NOT_FOUND = 0x24

    # Route not found
    ROUTE_NOT_FOUND = 0x25

    # Broadcast source failed to hear a neighbor relay the message
    BROADCAST_RELAY_FAILURE = 0x26

    # Invalid binding table index
    INVALID_BINDING_IDX = 0x2B

    # Resource error lack of free buffers, timers, and so forth.
    NO_RESOURCES = 0x2C

    # Attempted broadcast with APS transmission
    BROADCAST_APS_TX_ATTEMPT = 0x2D

    # Attempted unicast with APS transmission, but EE=0
    UNICAST_APS_TX_ATTEMPT = 0x2E

    INTERNAL_ERROR = 0x31

    # Transmission failed due to resource depletion (for example, out of
    # buffers, especially for indirect messages from coordinator)
    NO_RESOURCES_2 = 0x32

    # The payload in the frame was larger than allowed
    PAYLOAD_TOO_LARGE = 0x74
    _UNDEFINED = 0x2C


class DiscoveryStatus(t.uint8_t, UndefinedEnum):
    """Discovery status of TX Status frame."""

    SUCCESS = 0x00
    ADDRESS_DISCOVERY = 0x01
    ROUTE_DISCOVERY = 0x02
    ADDRESS_AND_ROUTE = 0x03
    EXTENDED_TIMEOUT = 0x40
    _UNDEFINED = 0x00


class TXOptions(t.bitmap8):
    """TX Options for explicit transmit frame."""

    NONE = 0x00

    Disable_Retries_and_Route_Repair = 0x01
    Enable_APS_Encryption = 0x20
    Use_Extended_TX_Timeout = 0x40


class ModemStatus(t.uint8_t, UndefinedEnum):
    """Modem Status."""

    HARDWARE_RESET = 0x00
    WATCHDOG_TIMER_RESET = 0x01
    JOINED_NETWORK = 0x02
    DISASSOCIATED = 0x03
    CONFIGURATION_ERROR_SYNCHRONIZATION_LOST = 0x04
    COORDINATOR_REALIGNMENT = 0x05
    COORDINATOR_STARTED = 0x06
    NETWORK_SECURITY_KEY_UPDATED = 0x07
    NETWORK_WOKE_UP = 0x0B
    NETWORK_WENT_TO_SLEEP = 0x0C
    VOLTAGE_SUPPLY_LIMIT_EXCEEDED = 0x0D
    DEVICE_CLOUD_CONNECTED = 0x0E
    DEVICE_CLOUD_DISCONNECTED = 0x0F
    MODEM_KEY_ESTABLISHED = 0x10
    MODEM_CONFIGURATION_CHANGED_WHILE_JOIN_IN_PROGRESS = 0x11
    ACCESS_FAULT = 0x12
    FATAL_STACK_ERROR = 0x13
    PLKE_TABLE_INITIATED = 0x14
    PLKE_TABLE_SUCCESS = 0x15
    PLKE_TABLE_IS_FULL = 0x16
    PLKE_NOT_AUTHORIZED = 0x17
    PLKE_INVALID_TRUST_CENTER_REQUEST = 0x18
    PLKE_TRUST_CENTER_UPDATE_FAIL = 0x19
    PLKE_BAD_EUI_ADDRESS = 0x1A
    PLKE_LINK_KEY_REJECTED = 0x1B
    PLKE_UPDATE_OCCURED = 0x1C
    PLKE_LINK_KEY_TABLE_CLEAR = 0x1D
    ZIGBEE_FREQUENCY_AGILITY_HAS_REQUESTED_CHANNEL_CHANGE = 0x1E
    ZIGBEE_EXECUTE_ATFR_NO_JOINABLE_BEACON_RESPONSES = 0x1F
    ZIGBEE_TOKENS_SPACE_RECOVERED = 0x20
    ZIGBEE_TOKENS_SPACE_UNRECOVERABLE = 0x21
    ZIGBEE_TOKENS_SPACE_CORRUPTED = 0x22
    ZIGBEE_DUAL_MODE_METAFRAME_ERROR = 0x30
    BLE_CONNECT = 0x32
    BLE_DISCONNECT = 0x33
    NO_SECURE_SESSION_CONNECTION = 0x34
    CELL_COMPONENT_UPDATE_STARTED = 0x35
    CELL_COMPONENT_UPDATE_FAILED = 0x36
    CELL_COMPONENT_UPDATE_SUCCEDED = 0x37
    XBEE_FIRMWARE_UPDATE_STARTED = 0x38
    XBEE_FIRMWARE_UPDATE_FAILED = 0x39
    XBEE_WILL_RESET_TO_APPLY_FIRMWARE_UPDATE = 0x3A
    SECURE_SESSION_SUCCESSFULLY_ESTABLISHED = 0x3B
    SECURE_SESSION_ENDED = 0x3C
    SECURE_SESSION_AUTHENTICATION_FAILED = 0x3D
    PAN_ID_CONFLICT_DETECTED = 0x3E
    PAN_ID_UPDATED_DUE_TO_CONFLICT = 0x3F
    ROUTER_PAN_ID_CHANGED_BY_COORDINATOR_DUE_TO_CONFLICT = 0x40
    NETWORK_WATCHDOG_TIMEOUT_EXPIRED_THREE_TIMES = 0x42
    JOIN_WINDOW_OPENED = 0x43
    JOIN_WINDOW_CLOSED = 0x44
    NETWORK_SECURITY_KEY_ROTATION_INITIATED = 0x45
    STACK_RESET = 0x80
    FIB_BOOTLOADER_RESET = 0x81
    SEND_OR_JOIN_COMMAND_ISSUED_WITHOUT_CONNECTING_FROM_AP = 0x82
    ACCESS_POINT_NOT_FOUND = 0x83
    PSK_NOT_CONFIGURED = 0x84
    SSID_NOT_FOUND = 0x87
    FAILED_TO_JOIN_WITH_SECURITY_ENABLED = 0x88
    COER_LOCKUP_OR_CRYSTAL_FAILURE_RESET = 0x89
    INVALID_CHANNEL = 0x8A
    LOW_VOLTAGE_RESET = 0x8B
    FAILED_TO_JOIN_ACCESS_POINT = 0x8E

    UNKNOWN_MODEM_STATUS = 0xFF
    _UNDEFINED = 0xFF


class RegistrationStatus(t.uint8_t, UndefinedEnum):
    """Key Registration Status."""

    SUCCESS = 0x00
    KEY_TOO_LONG = 0x01
    TRANSIENT_KEY_TABLE_IS_FULL = 0x18
    ADDRESS_NOT_FOUND_IN_THE_KEY_TABLE = 0xB1
    KEY_IS_INVALID_OR_RESERVED = 0xB2
    INVALID_ADDRESS = 0xB3
    KEY_TABLE_IS_FULL = 0xB4
    SECURITY_DATA_IS_INVALID_INSTALL_CODE_CRC_FAILS = 0xBD

    UNKNOWN_MODEM_STATUS = 0xFF
    _UNDEFINED = 0xFF

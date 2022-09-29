import enum

import zigpy.types


def deserialize(data, schema):
    result = []
    for type_ in schema:
        value, data = type_.deserialize(data)
        result.append(value)
    return result, data


def serialize(data, schema):
    return b"".join(t(v).serialize() for t, v in zip(schema, data))


class Bytes(bytes):
    def serialize(self):
        return self

    @classmethod
    def deserialize(cls, data):
        return cls(data), b""


class ATCommand(Bytes):
    @classmethod
    def deserialize(cls, data):
        return cls(data[:2]), data[2:]


class int_t(int):
    _signed = True

    def serialize(self):
        return self.to_bytes(self._size, "big", signed=self._signed)

    @classmethod
    def deserialize(cls, data):
        # Work around https://bugs.python.org/issue23640
        r = cls(int.from_bytes(data[: cls._size], "big", signed=cls._signed))
        data = data[cls._size :]
        return r, data


class int8s(int_t):
    _size = 1


class int16s(int_t):
    _size = 2


class int24s(int_t):
    _size = 3


class int32s(int_t):
    _size = 4


class int40s(int_t):
    _size = 5


class int48s(int_t):
    _size = 6


class int56s(int_t):
    _size = 7


class int64s(int_t):
    _size = 8


class uint_t(int_t):
    _signed = False


class uint8_t(uint_t):
    _size = 1


class uint16_t(uint_t):
    _size = 2


class uint24_t(uint_t):
    _size = 3


class uint32_t(uint_t):
    _size = 4


class uint40_t(uint_t):
    _size = 5


class uint48_t(uint_t):
    _size = 6


class uint56_t(uint_t):
    _size = 7


class uint64_t(uint_t):
    _size = 8


class Bool(uint8_t, enum.Enum):
    # Boolean type with values true and false.

    false = 0x00  # An alias for zero, used for clarity.
    true = 0x01  # An alias for one, used for clarity.


class EUI64(zigpy.types.EUI64):
    @classmethod
    def deserialize(cls, data):
        r, data = super().deserialize(data)
        return cls(r[::-1]), data

    def serialize(self):
        assert self._length == len(self)
        return super().serialize()[::-1]


class UndefinedEnumMeta(enum.EnumMeta):
    def __call__(cls, value=None, *args, **kwargs):
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
    pass


class FrameId(uint8_t):
    pass


class NWK(uint16_t):
    def __repr__(self):
        return "0x{:04x}".format(self)

    def __str__(self):
        return "0x{:04x}".format(self)


class Relays(zigpy.types.LVList, item_type=NWK, length_type=uint8_t):
    """List of Relays."""


UNKNOWN_IEEE = EUI64([uint8_t(0xFF) for i in range(0, 8)])
UNKNOWN_NWK = NWK(0xFFFE)


class TXStatus(uint8_t, UndefinedEnum):
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


class DiscoveryStatus(uint8_t, UndefinedEnum):
    """Discovery status of TX Status frame."""

    SUCCESS = 0x00
    ADDRESS_DISCOVERY = 0x01
    ROUTE_DISCOVERY = 0x02
    ADDRESS_AND_ROUTE = 0x03
    EXTENDED_TIMEOUT = 0x40
    _UNDEFINED = 0x00


class TXOptions(zigpy.types.bitmap8):
    NONE = 0x00

    Disable_Retries_and_Route_Repair = 0x01
    Enable_APS_Encryption = 0x20
    Use_Extended_TX_Timeout = 0x40

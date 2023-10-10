"""Tests for types module."""

import pytest
import zigpy.types as t

import zigpy_xbee.types as xbee_t


def test_bytes_serialize():
    """Test Bytes.serialize()."""
    data = 0x89AB.to_bytes(4, "big")
    result = xbee_t.Bytes(data).serialize()
    assert result == data


def test_bytes_deserialize():
    """Test Bytes.deserialize()."""
    data, rest = xbee_t.Bytes.deserialize(0x89AB.to_bytes(3, "big"))
    assert data == b"\x00\x89\xAB"
    assert rest == b""


def test_atcommand():
    """Test ATCommand class."""
    cmd = b"AI"
    data = 0x06.to_bytes(4, "big")
    r_cmd, r_data = xbee_t.ATCommand.deserialize(cmd + data)

    assert r_cmd == cmd
    assert r_data == data


def test_undefined_enum_undefined_value():
    """Test UndefinedEnum class."""

    class undEnum(t.uint8_t, xbee_t.UndefinedEnum):
        OK = 0
        ERROR = 2
        UNDEFINED_VALUE = 0xFF
        _UNDEFINED = 0xFF

    i = undEnum(0)
    assert i == 0
    assert i.name == "OK"

    i = undEnum(2)
    assert i == 2
    assert i.name == "ERROR"

    i = undEnum(0xEE)
    assert i.name == "UNDEFINED_VALUE"

    i = undEnum()
    assert i is undEnum.OK


def test_undefined_enum_undefinede():
    """Test UndefinedEnum undefined member."""

    class undEnum(t.uint8_t, xbee_t.UndefinedEnum):
        OK = 0
        ERROR = 2
        UNDEFINED_VALUE = 0xFF

    with pytest.raises(ValueError):
        undEnum(0xEE)


def test_nwk():
    """Test NWK class."""
    nwk = xbee_t.NWK(0x1234)

    assert str(nwk) == "0x1234"
    assert repr(nwk) == "0x1234"


def test_eui64():
    """Test EUI64 class."""
    extra = b"\xBE\xEF"
    data = b"01234567"

    result, rest = xbee_t.EUI64.deserialize(data + extra)

    assert rest == extra
    assert result == xbee_t.EUI64((0x37, 0x36, 0x35, 0x34, 0x33, 0x32, 0x31, 0x30))

    data = xbee_t.EUI64([t.uint8_t(i) for i in range(0x30, 0x38)])
    result = data.serialize()

    assert result == b"76543210"

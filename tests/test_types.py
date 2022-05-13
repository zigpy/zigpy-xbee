import pytest

from zigpy_xbee import types as t


def test_deserialize():
    extra = b"\xBE\xEF"
    data = b"\xff\xff\xfe01234567"
    schema = (t.uint8_t, t.int16s, t.EUI64)
    result, rest = t.deserialize(data + extra, schema)

    assert rest == extra
    assert result[0] == 0xFF
    assert result[1] == -2
    assert result[2] == t.EUI64((0x37, 0x36, 0x35, 0x34, 0x33, 0x32, 0x31, 0x30))


def test_serialize():
    data = [0xFF, -2, t.EUI64([t.uint8_t(i) for i in range(0x30, 0x38)])]
    schema = (t.uint8_t, t.int16s, t.EUI64)
    result = t.serialize(data, schema)

    assert result == b"\xff\xff\xfe76543210"


def test_bytes_serialize():
    data = 0x89AB.to_bytes(4, "big")
    result = t.Bytes(data).serialize()
    assert result == data


def test_bytes_deserialize():
    data, rest = t.Bytes.deserialize(0x89AB.to_bytes(3, "big"))
    assert data == b"\x00\x89\xAB"
    assert rest == b""


def test_atcommand():
    cmd = "AI".encode("ascii")
    data = 0x06.to_bytes(4, "big")
    r_cmd, r_data = t.ATCommand.deserialize(cmd + data)

    assert r_cmd == cmd
    assert r_data == data


def test_undefined_enum_undefined_value():
    class undEnum(t.uint8_t, t.UndefinedEnum):
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
    class undEnum(t.uint8_t, t.UndefinedEnum):
        OK = 0
        ERROR = 2
        UNDEFINED_VALUE = 0xFF

    with pytest.raises(ValueError):
        undEnum(0xEE)


def test_nwk():
    nwk = t.NWK(0x1234)

    assert str(nwk) == "0x1234"
    assert repr(nwk) == "0x1234"

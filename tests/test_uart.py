import asyncio
from unittest import mock

import pytest
import serial_asyncio

from zigpy_xbee import uart
import zigpy_xbee.config

DEVICE_CONFIG = zigpy_xbee.config.SCHEMA_DEVICE(
    {zigpy_xbee.config.CONF_DEVICE_PATH: "/dev/null"}
)


@pytest.fixture
def gw():
    gw = uart.Gateway(mock.MagicMock())
    gw._transport = mock.MagicMock()
    gw._transport.serial.BAUDRATES = serial_asyncio.serial.Serial.BAUDRATES
    return gw


def test_baudrate(gw):
    gw.baudrate
    gw.baudrate = 19200
    assert gw._transport.serial.baudrate == 19200


def test_baudrate_fail(gw):
    with pytest.raises(ValueError):
        gw.baudrate = 3333


async def test_connect(monkeypatch):
    api = mock.MagicMock()

    async def mock_conn(loop, protocol_factory, **kwargs):
        protocol = protocol_factory()
        loop.call_soon(protocol.connection_made, None)
        return None, protocol

    monkeypatch.setattr(serial_asyncio, "create_serial_connection", mock_conn)

    await uart.connect(DEVICE_CONFIG, api)


def test_command_mode_rsp(gw):
    data = b"OK"
    gw.command_mode_rsp(data)
    assert gw._api.handle_command_mode_rsp.call_count == 1
    assert gw._api.handle_command_mode_rsp.call_args[0][0] == "OK"


def test_command_mode_send(gw):
    data = b"ATAP2\x0D"
    gw.command_mode_send(data)
    assert gw._transport.write.call_count == 1
    assert gw._transport.write.called_once_with(data)


def test_close(gw):
    gw.close()
    assert gw._transport.close.call_count == 1


def test_data_received_chunk_frame(gw):
    data = b"~\x00\r\x88\rID\x00\x00\x00\x00\x00\x00\x00\x00\x00\xdd"
    gw.frame_received = mock.MagicMock()
    gw.data_received(data[:3])
    assert gw.frame_received.call_count == 0
    gw.data_received(data[3:])
    assert gw.frame_received.call_count == 1
    assert gw.frame_received.call_args[0][0] == data[3:-1]


def test_data_received_full_frame(gw):
    data = b"~\x00\r\x88\rID\x00\x00\x00\x00\x00\x00\x00\x00\x00\xdd"
    gw.frame_received = mock.MagicMock()
    gw.data_received(data)
    assert gw.frame_received.call_count == 1
    assert gw.frame_received.call_args[0][0] == data[3:-1]


def test_data_received_incomplete_frame(gw):
    data = b"~\x00\x07\x8b\x0e\xff\xfd"
    gw.frame_received = mock.MagicMock()
    gw.data_received(data)
    assert gw.frame_received.call_count == 0


def test_data_received_at_response_non_cmd_mode(gw):
    data = b"OK\x0D"
    gw.frame_received = mock.MagicMock()
    gw.command_mode_rsp = mock.MagicMock()

    gw.data_received(data)
    assert gw.command_mode_rsp.call_count == 0


def test_data_received_at_response_in_cmd_mode(gw):
    data = b"OK\x0D"
    gw.frame_received = mock.MagicMock()
    gw.command_mode_rsp = mock.MagicMock()

    gw.command_mode_send(b"")
    gw.data_received(data)
    assert gw.command_mode_rsp.call_count == 1
    assert gw.command_mode_rsp.call_args[0][0] == b"OK"

    gw.reset_command_mode()
    gw.data_received(data)
    assert gw.command_mode_rsp.call_count == 1


def test_extract(gw):
    gw._buffer = b"\x7E\x00\x02\x23\x7D\x31\xCBextra"
    frame = gw._extract_frame()
    assert frame == b"\x23\x11"
    assert gw._buffer == b"extra"


def test_extract_wrong_checksum(gw):
    gw._buffer = b"\x7E\x00\x02\x23\x7D\x31\xCEextra"
    frame = gw._extract_frame()
    assert frame is None
    assert gw._buffer == b"extra"


def test_extract_checksum_none(gw):
    data = b"\x7E\x00\x02\x23\x7D\x31"
    gw._buffer = data
    gw._checksum = lambda x: None
    frame = gw._extract_frame()
    assert frame is None
    assert gw._buffer == data


def test_extract_frame_len_none(gw):
    data = b"\x7E"
    gw._buffer = data
    frame = gw._extract_frame()
    assert frame is None
    assert gw._buffer == data


def test_extract_frame_no_start(gw):
    data = b"\x00\x02\x23\x7D\x31"
    gw._buffer = data
    frame = gw._extract_frame()
    assert frame is None
    assert gw._buffer == data


def test_frame_received(gw):
    data = b"frame"
    gw.frame_received(data)
    assert gw._api.frame_received.call_count == 1
    assert gw._api.frame_received.call_args[0][0] == data


def test_send(gw):
    gw.send(b"\x23\x11")
    assert gw._transport.write.call_count == 1
    data = b"\x7E\x00\x02\x23\x7D\x31\xCB"
    assert gw._transport.write.called_once_with(data)


def test_escape(gw):
    data = b"".join(
        [
            a.to_bytes(1, "big") + b.to_bytes(1, "big")
            for a, b in zip(gw.RESERVED, b"\x22\x33\x44\x55")
        ]
    )
    escaped = gw._escape(data)
    assert len(data) < len(escaped)
    chk = [c for c in escaped if c in gw.RESERVED]
    assert len(chk) == len(gw.RESERVED)  # 4 chars to escape, thus 4 escape chars
    assert escaped == b'}^"}]3}1D}3U'


def test_unescape(gw):
    extra = b"\xaa\xbb\xcc\xff"
    escaped = b'}^"}]3}1D}3U'
    chk = b"".join(
        [
            a.to_bytes(1, "big") + b.to_bytes(1, "big")
            for a, b in zip(gw.RESERVED, b"\x22\x33\x44\x55")
        ]
    )
    unescaped, rest = gw._get_unescaped(escaped + extra, 8)
    assert len(escaped) > len(unescaped)
    assert rest == extra
    assert unescaped == chk


def test_unescape_underflow(gw):
    escaped = b'}^"}'
    unescaped, rest = gw._get_unescaped(escaped, 3)
    assert unescaped is None
    assert rest is None


def test_connection_lost_exc(gw):
    gw._connected_future = asyncio.Future()

    gw.connection_lost(ValueError())

    conn_lost = gw._api.connection_lost
    assert conn_lost.call_count == 1
    assert isinstance(conn_lost.call_args[0][0], Exception)
    assert gw._connected_future.done()
    assert gw._connected_future.exception()


def test_connection_closed(gw):
    gw._connected_future = asyncio.Future()
    gw.connection_lost(None)

    assert gw._api.connection_lost.call_count == 0
    assert gw._connected_future.done()
    assert gw._connected_future.result() is True

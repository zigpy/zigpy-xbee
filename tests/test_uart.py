from unittest import mock

import pytest
import serial_asyncio

from zigpy_xbee import uart


@pytest.mark.asyncio
async def test_connect_uart(monkeypatch):
    api = mock.MagicMock()
    portmock = mock.MagicMock()

    async def mock_conn(loop, protocol_factory, **kwargs):
        protocol = protocol_factory()
        loop.call_soon(protocol.connection_made, None)
        return None, protocol
    monkeypatch.setattr(serial_asyncio, 'create_serial_connection', mock_conn)

    await uart.connect(portmock, 57600, api)


@pytest.fixture
def gw():
    gw = uart.Gateway(mock.MagicMock())
    gw._transport = mock.MagicMock()
    gw._transport.serial.BAUDRATES = serial_asyncio.serial.Serial.BAUDRATES
    return gw


@pytest.mark.asyncio
async def test_connect(monkeypatch):
    api = mock.MagicMock()
    portmock = mock.MagicMock()

    async def mock_conn(loop, protocol_factory, **kwargs):
        protocol = protocol_factory()
        loop.call_soon(protocol.connection_made, None)
        return None, protocol
    monkeypatch.setattr(serial_asyncio, 'create_serial_connection', mock_conn)

    await uart.connect(portmock, 57600, api)


def test_close(gw):
    gw.close()
    assert gw._transport.close.call_count == 1


def test_data_received_chunk_frame(gw):
    data = b'~\x00\x07\x8b\x0e\xff\xfd\x00$\x02D'
    gw.frame_received = mock.MagicMock()
    gw.data_received(data[:-4])
    assert gw.frame_received.call_count == 0
    gw.data_received(data[-4:])
    assert gw.frame_received.call_count == 1
    assert gw.frame_received.call_args[0][0] == data[3:-1]


def test_data_received_full_frame(gw):
    data = b'~\x00\x07\x8b\x0e\xff\xfd\x00$\x02D'
    gw.frame_received = mock.MagicMock()
    gw.data_received(data)
    assert gw.frame_received.call_count == 1
    assert gw.frame_received.call_args[0][0] == data[3:-1]


def test_data_received_incomplete_frame(gw):
    data = b'~\x00\x07\x8b\x0e\xff\xfd'
    gw.frame_received = mock.MagicMock()
    gw.data_received(data)
    assert gw.frame_received.call_count == 0


def test_extract(gw):
    gw._buffer = b'\x7E\x00\x02\x23\x7D\x31\xCBextra'
    frame = gw._extract_frame()
    assert frame == b'\x23\x11'
    assert gw._buffer == b'extra'


def test_extract_wrong_checksum(gw):
    gw._buffer = b'\x7E\x00\x02\x23\x7D\x31\xCEextra'
    frame = gw._extract_frame()
    assert frame is None
    assert gw._buffer == b'extra'


def test_extract_checksum_none(gw):
    data = b'\x7E\x00\x02\x23\x7D\x31'
    gw._buffer = data
    gw._checksum = lambda x: None
    frame = gw._extract_frame()
    assert frame is None
    assert gw._buffer == data


def test_extract_frame_len_none(gw):
    data = b'\x7E'
    gw._buffer = data
    frame = gw._extract_frame()
    assert frame is None
    assert gw._buffer == data


def test_extract_frame_no_start(gw):
    data = b'\x00\x02\x23\x7D\x31'
    gw._buffer = data
    frame = gw._extract_frame()
    assert frame is None
    assert gw._buffer == data


def test_frame_received(gw):
    data = b'frame'
    gw.frame_received(data)
    assert gw._api.frame_received.call_count == 1
    assert gw._api.frame_received.call_args[0][0] == data


def test_send(gw):
    gw.send(b'\x23\x11')
    assert gw._transport.write.call_count == 1
    data = b'\x7E\x00\x02\x23\x7D\x31\xCB'
    assert gw._transport.write.called_once_with(data)

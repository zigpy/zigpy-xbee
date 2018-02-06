from unittest import mock

from zigpy_xbee.uart import Gateway


def test_extract():
    gateway = Gateway(mock.MagicMock())
    gateway._buffer = b'\x7E\x00\x02\x23\x7D\x31\xCBextra'
    frame = gateway._extract_frame()
    assert frame == b'\x23\x11'
    assert gateway._buffer == b'extra'


def test_send():
    gateway = Gateway(mock.MagicMock())
    gateway._transport = mock.MagicMock()
    gateway.send(b'\x23\x11')
    assert gateway._transport.write.call_count == 1
    data = b'\x7E\x00\x02\x23\x7D\x31\xCB'
    assert gateway._transport.write.called_once_with(data)

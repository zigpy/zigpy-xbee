import asyncio
from unittest import mock

import pytest

from zigpy_xbee import api as xbee_api
from zigpy_xbee import types as t
from zigpy_xbee import uart


@pytest.fixture
def api():
    api = xbee_api.XBee()
    api._uart = mock.MagicMock()
    return api


@pytest.mark.asyncio
async def test_connect(monkeypatch):
    api = xbee_api.XBee()
    dev = mock.MagicMock()
    monkeypatch.setattr(
        uart, 'connect',
        mock.MagicMock(side_effect=asyncio.coroutine(mock.MagicMock())))
    await api.connect(dev, 115200)


def test_close(api):
    api._uart.close = mock.MagicMock()
    api.close()
    assert api._uart.close.call_count == 1


def test_commands():
    import string
    anum = string.ascii_letters + string.digits + '_'

    for cmd_name, cmd_opts in xbee_api.COMMANDS.items():
        assert isinstance(cmd_name, str) is True
        assert all([c in anum for c in cmd_name]), cmd_name
        assert len(cmd_opts) == 3
        cmd_id, schema, reply = cmd_opts
        assert isinstance(cmd_id, int) is True
        assert isinstance(schema, tuple) is True
        assert reply is None or isinstance(reply, int)


@pytest.mark.asyncio
async def test_command(api):
    def mock_api_frame(name, *args):
        c = xbee_api.COMMANDS[name]
        return mock.sentinel.api_frame_data, c[2]
    api._api_frame = mock.MagicMock(side_effect=mock_api_frame)
    api._uart.send = mock.MagicMock()

    for cmd_name, cmd_opts in xbee_api.COMMANDS.items():
        cmd_id, schema, expect_reply = cmd_opts
        ret = api._command(cmd_name, mock.sentinel.cmd_data)
        if expect_reply:
            assert asyncio.isfuture(ret) is True
            ret.cancel()
        else:
            assert ret is None
        assert api._api_frame.call_count == 1
        assert api._api_frame.call_args[0][0] == cmd_name
        assert api._api_frame.call_args[0][1] == mock.sentinel.cmd_data
        assert api._uart.send.call_count == 1
        assert api._uart.send.call_args[0][0] == mock.sentinel.api_frame_data
        api._api_frame.reset_mock()
        api._uart.send.reset_mock()


def test_seq_command(api):
    api._command = mock.MagicMock()
    api._seq = mock.sentinel.seq
    api._seq_command(mock.sentinel.cmd_name, mock.sentinel.args)
    assert api._command.call_count == 1
    assert api._command.call_args[0][0] == mock.sentinel.cmd_name
    assert api._command.call_args[0][1] == mock.sentinel.seq
    assert api._command.call_args[0][2] == mock.sentinel.args


def test_at_command(api, monkeypatch):
    monkeypatch.setattr(t, 'serialize', mock.MagicMock(return_value=mock.sentinel.serialize))
    api._command = mock.MagicMock()
    api._seq = mock.sentinel.seq

    for at_cmd in xbee_api.AT_COMMANDS:
        api._at_command(at_cmd, mock.sentinel.args)
        assert t.serialize.call_count == 1
        assert api._command.call_count == 1
        assert api._command.call_args[0][0] == 'at'
        assert api._command.call_args[0][1] == mock.sentinel.seq
        assert api._command.call_args[0][2] == at_cmd.encode('ascii')
        assert api._command.call_args[0][3] == mock.sentinel.serialize
        t.serialize.reset_mock()
        api._command.reset_mock()


def test_api_frame(api):
    ieee = t.EUI64([t.uint8_t(a) for a in range(0, 8)])
    for cmd_name, cmd_opts in xbee_api.COMMANDS.items():
        cmd_id, schema, repl = cmd_opts
        if schema:
            args = [ieee if isinstance(a(), t.EUI64) else a() for a in schema]
            frame, repl = api._api_frame(cmd_name, *args)
        else:
            frame, repl = api._api_frame(cmd_name)


def test_frame_received(api, monkeypatch):
    monkeypatch.setattr(t, 'deserialize', mock.MagicMock(
        return_value=(mock.sentinel.deserialize_data, b'')))
    my_handler = mock.MagicMock()

    for cmd, cmd_opts in xbee_api.COMMANDS.items():
        cmd_id = cmd_opts[0]
        payload = b'\x01\x02\x03\x04'
        data = cmd_id.to_bytes(1, 'big') + payload
        setattr(api, '_handle_{}'.format(cmd), my_handler)
        api.frame_received(data)
        assert t.deserialize.call_count == 1
        assert t.deserialize.call_args[0][0] == payload
        assert my_handler.call_count == 1
        assert my_handler.call_args[0][0] == mock.sentinel.deserialize_data
        t.deserialize.reset_mock()
        my_handler.reset_mock()


def _handle_at_response(api, tsn, status, at_response=b''):
    data = (tsn, 'AI'.encode('ascii'), status, at_response)
    response = asyncio.Future()
    api._awaiting[tsn] = (response, )
    api._handle_at_response(data)
    return response


def test_handle_at_response_none(api):
    tsn = 123
    fut = _handle_at_response(api, tsn, 0)
    assert fut.done() is True
    assert fut.result() is None
    assert fut.exception() is None


def test_handle_at_response_data(api):
    tsn = 123
    status, response = 0, 0x23
    fut = _handle_at_response(api, tsn, status, [response])
    assert fut.done() is True
    assert fut.result() == response
    assert fut.exception() is None


def test_handle_at_response_error(api):
    tsn = 123
    status, response = 1, 0x23
    fut = _handle_at_response(api, tsn, status, [response])
    assert fut.done() is True
    assert fut.exception() is not None


def test_handle_modem_status(api):
    s = mock.sentinel
    data = [s.modem_status, s.extra_1, s.extra_2, s.extra_3]
    api._app = mock.MagicMock()
    api._app.handle_modem_status = mock.MagicMock()
    api._handle_modem_status(data)
    assert api._app.handle_modem_status.call_count == 1
    assert api._app.handle_modem_status.call_args[0][0] == mock.sentinel.modem_status


def test_handle_explicit_rx_indicator(api):
    data = b'\x00\x01\x02\x03\x04\x05\x06\x07'
    api._app = mock.MagicMock()
    api._app.handle_rx = mock.MagicMock()
    api._handle_explicit_rx_indicator(data)
    assert api._app.handle_rx.call_count == 1


def test_handle_tx_status(api):
    api._handle_tx_status(b'\x01\x02\x03\x04')

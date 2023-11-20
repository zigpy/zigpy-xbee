"""Tests for API."""

import asyncio

import pytest
import serial
import zigpy.config
import zigpy.exceptions
import zigpy.types as t

from zigpy_xbee import api as xbee_api, types as xbee_t, uart
from zigpy_xbee.exceptions import ATCommandError, ATCommandException, InvalidCommand
from zigpy_xbee.zigbee.application import ControllerApplication

import tests.async_mock as mock

DEVICE_CONFIG = zigpy.config.SCHEMA_DEVICE(
    {
        zigpy.config.CONF_DEVICE_PATH: "/dev/null",
        zigpy.config.CONF_DEVICE_BAUDRATE: 57600,
    }
)


@pytest.fixture
def api():
    """Sample XBee API fixture."""
    api = xbee_api.XBee(DEVICE_CONFIG)
    api._uart = mock.MagicMock()
    return api


async def test_connect(monkeypatch):
    """Test connect."""
    api = xbee_api.XBee(DEVICE_CONFIG)
    monkeypatch.setattr(uart, "connect", mock.AsyncMock())
    await api.connect()


def test_close(api):
    """Test connection close."""
    uart = api._uart
    api.close()

    assert api._uart is None
    assert uart.close.call_count == 1


def test_commands():
    """Test command requests and command responses description."""
    import string

    anum = string.ascii_letters + string.digits + "_"
    commands = {**xbee_api.COMMAND_REQUESTS, **xbee_api.COMMAND_RESPONSES}

    for cmd_name, cmd_opts in commands.items():
        assert isinstance(cmd_name, str) is True
        assert all(c in anum for c in cmd_name), cmd_name
        assert len(cmd_opts) == 3
        cmd_id, schema, reply = cmd_opts
        assert isinstance(cmd_id, int) is True
        assert isinstance(schema, tuple) is True
        assert reply is None or isinstance(reply, int)


async def test_command(api):
    """Test AT commands."""

    def mock_api_frame(name, *args):
        c = xbee_api.COMMAND_REQUESTS[name]
        return mock.sentinel.api_frame_data, c[2]

    api._api_frame = mock.MagicMock(side_effect=mock_api_frame)
    api._uart.send = mock.MagicMock()

    for cmd_name, cmd_opts in xbee_api.COMMAND_REQUESTS.items():
        cmd_id, schema, expect_reply = cmd_opts
        ret = api._command(cmd_name, mock.sentinel.cmd_data)
        if expect_reply:
            assert asyncio.isfuture(ret) is True
            ret.cancel()
        else:
            assert ret is None
        assert api._api_frame.call_count == 1
        assert api._api_frame.call_args[0][0] == cmd_name
        assert api._api_frame.call_args[0][1] == api._seq - 1
        assert api._api_frame.call_args[0][2] == mock.sentinel.cmd_data
        assert api._uart.send.call_count == 1
        assert api._uart.send.call_args[0][0] == mock.sentinel.api_frame_data
        api._api_frame.reset_mock()
        api._uart.send.reset_mock()

        ret = api._command(cmd_name, mock.sentinel.cmd_data, mask_frame_id=True)
        assert ret is None
        assert api._api_frame.call_count == 1
        assert api._api_frame.call_args[0][0] == cmd_name
        assert api._api_frame.call_args[0][1] == 0
        assert api._api_frame.call_args[0][2] == mock.sentinel.cmd_data
        assert api._uart.send.call_count == 1
        assert api._uart.send.call_args[0][0] == mock.sentinel.api_frame_data
        api._api_frame.reset_mock()
        api._uart.send.reset_mock()


async def test_command_not_connected(api):
    """Test AT command while disconnected to the device."""
    api._uart = None

    def mock_api_frame(name, *args):
        return mock.sentinel.api_frame_data, api._seq

    api._api_frame = mock.MagicMock(side_effect=mock_api_frame)

    for cmd, _cmd_opts in xbee_api.COMMAND_REQUESTS.items():
        with pytest.raises(zigpy.exceptions.APIException):
            await api._command(cmd, mock.sentinel.cmd_data)
        assert api._api_frame.call_count == 0
        api._api_frame.reset_mock()


async def _test_at_or_queued_at_command(api, cmd, monkeypatch, do_reply=True):
    monkeypatch.setattr(
        t, "serialize", mock.MagicMock(return_value=mock.sentinel.serialize)
    )
    """Call api._at_command() or api._queued_at() with every possible command."""

    def mock_command(name, *args):
        rsp = xbee_api.COMMAND_REQUESTS[name][2]
        ret = None
        if rsp:
            ret = asyncio.Future()
            if do_reply:
                ret.set_result(mock.sentinel.at_result)
        return ret

    api._command = mock.MagicMock(side_effect=mock_command)
    api._seq = mock.sentinel.seq

    for at_cmd in xbee_api.AT_COMMANDS:
        res = await cmd(at_cmd, mock.sentinel.args)
        assert t.serialize.call_count == 1
        assert api._command.call_count == 1
        assert api._command.call_args[0][0] in ("at", "queued_at")
        assert api._command.call_args[0][1] == at_cmd.encode("ascii")
        assert api._command.call_args[0][2] == mock.sentinel.serialize
        assert res == mock.sentinel.at_result
        t.serialize.reset_mock()
        api._command.reset_mock()


async def test_at_command(api, monkeypatch):
    """Test api._at_command."""
    await _test_at_or_queued_at_command(api, api._at_command, monkeypatch)


async def test_at_command_no_response(api, monkeypatch):
    """Test api._at_command with no response."""
    with pytest.raises(asyncio.TimeoutError):
        await _test_at_or_queued_at_command(
            api, api._at_command, monkeypatch, do_reply=False
        )


async def test_queued_at_command(api, monkeypatch):
    """Test api._queued_at."""
    await _test_at_or_queued_at_command(api, api._queued_at, monkeypatch)


async def _test_remote_at_command(api, monkeypatch, do_reply=True):
    monkeypatch.setattr(
        t, "serialize", mock.MagicMock(return_value=mock.sentinel.serialize)
    )
    """Call api._remote_at_command()."""

    def mock_command(name, *args):
        rsp = xbee_api.COMMAND_REQUESTS[name][2]
        ret = None
        if rsp:
            ret = asyncio.Future()
            if do_reply:
                ret.set_result(mock.sentinel.at_result)
        return ret

    api._command = mock.MagicMock(side_effect=mock_command)
    api._seq = mock.sentinel.seq

    for at_cmd in xbee_api.AT_COMMANDS:
        res = await api._remote_at_command(
            mock.sentinel.ieee,
            mock.sentinel.nwk,
            mock.sentinel.opts,
            at_cmd,
            mock.sentinel.args,
        )
        assert t.serialize.call_count == 1
        assert api._command.call_count == 1
        assert api._command.call_args[0][0] == "remote_at"
        assert api._command.call_args[0][1] == mock.sentinel.ieee
        assert api._command.call_args[0][2] == mock.sentinel.nwk
        assert api._command.call_args[0][3] == mock.sentinel.opts
        assert api._command.call_args[0][4] == at_cmd.encode("ascii")
        assert api._command.call_args[0][5] == mock.sentinel.serialize
        assert res == mock.sentinel.at_result
        t.serialize.reset_mock()
        api._command.reset_mock()


async def test_remote_at_cmd(api, monkeypatch):
    """Test remote AT command."""
    await _test_remote_at_command(api, monkeypatch)


async def test_remote_at_cmd_no_rsp(api, monkeypatch):
    """Test remote AT command with no response."""
    monkeypatch.setattr(xbee_api, "REMOTE_AT_COMMAND_TIMEOUT", 0.1)
    with pytest.raises(asyncio.TimeoutError):
        await _test_remote_at_command(api, monkeypatch, do_reply=False)


def test_api_frame(api):
    """Test api._api_frame."""
    ieee = t.EUI64([t.uint8_t(a) for a in range(0, 8)])
    for cmd_name, cmd_opts in xbee_api.COMMAND_REQUESTS.items():
        cmd_id, schema, repl = cmd_opts
        if schema:
            args = [ieee if issubclass(a, t.EUI64) else a() for a in schema]
            frame, repl = api._api_frame(cmd_name, *args)
        else:
            frame, repl = api._api_frame(cmd_name)


def test_frame_received(api, monkeypatch):
    """Test api.frame_received()."""
    monkeypatch.setattr(
        t,
        "deserialize",
        mock.MagicMock(
            return_value=(
                [
                    mock.sentinel.arg_0,
                    mock.sentinel.arg_1,
                    mock.sentinel.arg_2,
                    mock.sentinel.arg_3,
                    mock.sentinel.arg_4,
                    mock.sentinel.arg_5,
                    mock.sentinel.arg_6,
                    mock.sentinel.arg_7,
                    mock.sentinel.arg_8,
                ],
                b"",
            )
        ),
    )
    my_handler = mock.MagicMock()

    for cmd, cmd_opts in xbee_api.COMMAND_RESPONSES.items():
        cmd_id = cmd_opts[0]
        payload = b"\x01\x02\x03\x04"
        data = cmd_id.to_bytes(1, "big") + payload
        setattr(api, f"_handle_{cmd}", my_handler)
        api.frame_received(data)
        assert t.deserialize.call_count == 1
        assert t.deserialize.call_args[0][0] == payload
        assert my_handler.call_count == 1
        assert my_handler.call_args[0][0] == mock.sentinel.arg_0
        assert my_handler.call_args[0][1] == mock.sentinel.arg_1
        assert my_handler.call_args[0][2] == mock.sentinel.arg_2
        assert my_handler.call_args[0][3] == mock.sentinel.arg_3
        t.deserialize.reset_mock()
        my_handler.reset_mock()


def test_frame_received_no_handler(api, monkeypatch):
    """Test frame received with no handler defined."""
    monkeypatch.setattr(
        t, "deserialize", mock.MagicMock(return_value=(b"deserialized data", b""))
    )
    my_handler = mock.MagicMock()
    cmd = "no_handler"
    cmd_id = 0x00
    xbee_api.COMMAND_RESPONSES[cmd] = (cmd_id, (), None)
    api._commands_by_id[cmd_id] = cmd

    cmd_opts = xbee_api.COMMAND_RESPONSES[cmd]
    cmd_id = cmd_opts[0]
    payload = b"\x01\x02\x03\x04"
    data = cmd_id.to_bytes(1, "big") + payload
    api.frame_received(data)
    assert t.deserialize.call_count == 1
    assert t.deserialize.call_args[0][0] == payload
    assert my_handler.call_count == 0


def _handle_at_response(api, tsn, status, at_response=b""):
    """Call api._handle_at_response."""
    data = (tsn, b"AI", status, at_response)
    response = asyncio.Future()
    api._awaiting[tsn] = (response,)
    api._handle_at_response(*data)
    return response


def test_handle_at_response_none(api):
    """Test AT successful response with no value."""
    tsn = 123
    fut = _handle_at_response(api, tsn, 0)
    assert fut.done() is True
    assert fut.result() is None
    assert fut.exception() is None


def test_handle_at_response_data(api):
    """Test AT successful response with data."""
    tsn = 123
    status, response = 0, 0x23
    fut = _handle_at_response(api, tsn, status, [response])
    assert fut.done() is True
    assert fut.result() == response
    assert fut.exception() is None


def test_handle_at_response_error(api):
    """Test AT unsuccessful response."""
    tsn = 123
    status, response = 1, 0x23
    fut = _handle_at_response(api, tsn, status, [response])
    assert fut.done() is True
    assert isinstance(fut.exception(), ATCommandError)


def test_handle_at_response_invalid_command(api):
    """Test invalid AT command response."""
    tsn = 123
    status, response = 2, 0x23
    fut = _handle_at_response(api, tsn, status, [response])
    assert fut.done() is True
    assert isinstance(fut.exception(), InvalidCommand)


def test_handle_at_response_undef_error(api):
    """Test AT unsuccessful response with undefined error."""
    tsn = 123
    status, response = 0xEE, 0x23
    fut = _handle_at_response(api, tsn, status, [response])
    assert fut.done() is True
    assert isinstance(fut.exception(), ATCommandException)


def test_handle_remote_at_rsp(api):
    """Test handling the response."""
    api._handle_at_response = mock.MagicMock()
    s = mock.sentinel
    api._handle_remote_at_response(s.frame_id, s.ieee, s.nwk, s.cmd, s.status, s.data)
    assert api._handle_at_response.call_count == 1
    assert api._handle_at_response.call_args[0][0] == s.frame_id
    assert api._handle_at_response.call_args[0][1] == s.cmd
    assert api._handle_at_response.call_args[0][2] == s.status
    assert api._handle_at_response.call_args[0][3] == s.data


def _send_modem_event(api, event):
    """Call api._handle_modem_status()."""
    api._app = mock.MagicMock(spec=ControllerApplication)
    api._handle_modem_status(event)
    assert api._app.handle_modem_status.call_count == 1
    assert api._app.handle_modem_status.call_args[0][0] == event


def test_handle_modem_status(api):
    """Test api._handle_modem_status()."""
    api._running.clear()
    api._reset.set()
    _send_modem_event(api, xbee_t.ModemStatus.COORDINATOR_STARTED)
    assert api.is_running is True
    assert api.reset_event.is_set() is True

    api._running.set()
    api._reset.set()
    _send_modem_event(api, xbee_t.ModemStatus.DISASSOCIATED)
    assert api.is_running is False
    assert api.reset_event.is_set() is True

    api._running.set()
    api._reset.clear()
    _send_modem_event(api, xbee_t.ModemStatus.HARDWARE_RESET)
    assert api.is_running is False
    assert api.reset_event.is_set() is True


def test_handle_explicit_rx_indicator(api):
    """Test receiving explicit_rx_indicator frame."""
    s = mock.sentinel
    data = [
        s.src_ieee,
        s.src_nwk,
        s.src_ep,
        s.dst_ep,
        s.cluster_id,
        s.profile,
        s.opts,
        b"abcdef",
    ]
    api._app = mock.MagicMock()
    api._app.handle_rx = mock.MagicMock()
    api._handle_explicit_rx_indicator(*data)
    assert api._app.handle_rx.call_count == 1


def _handle_tx_status(api, status, wrong_frame_id=False):
    """Call api._handle_tx_status."""
    status = xbee_t.TXStatus(status)
    frame_id = 0x12
    send_fut = mock.MagicMock(spec=asyncio.Future)
    api._awaiting[frame_id] = (send_fut,)
    s = mock.sentinel
    if wrong_frame_id:
        frame_id += 1
    api._handle_tx_status(
        frame_id, s.dst_nwk, s.retries, status, xbee_t.DiscoveryStatus()
    )
    return send_fut


def test_handle_tx_status_success(api):
    """Test handling successful TX Status."""
    fut = _handle_tx_status(api, xbee_t.TXStatus.SUCCESS)
    assert len(api._awaiting) == 0
    assert fut.set_result.call_count == 1
    assert fut.set_exception.call_count == 0


def test_handle_tx_status_except(api):
    """Test exceptional TXStatus."""
    fut = _handle_tx_status(api, xbee_t.TXStatus.ADDRESS_NOT_FOUND)
    assert len(api._awaiting) == 0
    assert fut.set_result.call_count == 0
    assert fut.set_exception.call_count == 1


def test_handle_tx_status_unexpected(api):
    """Test TX status reply on unexpected frame."""
    fut = _handle_tx_status(api, 1, wrong_frame_id=True)
    assert len(api._awaiting) == 1
    assert fut.set_result.call_count == 0
    assert fut.set_exception.call_count == 0


def test_handle_tx_status_duplicate(api):
    """Test TX status duplicate reply."""
    status = xbee_t.TXStatus.SUCCESS
    frame_id = 0x12
    send_fut = mock.MagicMock(spec=asyncio.Future)
    send_fut.set_result.side_effect = asyncio.InvalidStateError
    api._awaiting[frame_id] = (send_fut,)
    s = mock.sentinel
    api._handle_tx_status(frame_id, s.dst_nwk, s.retries, status, s.disc)
    assert len(api._awaiting) == 0
    assert send_fut.set_result.call_count == 1
    assert send_fut.set_exception.call_count == 0


def test_handle_registration_status(api):
    """Test device registration status."""
    frame_id = 0x12
    status = xbee_t.RegistrationStatus.SUCCESS
    fut = asyncio.Future()
    api._awaiting[frame_id] = (fut,)
    api._handle_registration_status(frame_id, status)
    assert fut.done() is True
    assert fut.result() == xbee_t.RegistrationStatus.SUCCESS
    assert fut.exception() is None

    frame_id = 0x13
    status = xbee_t.RegistrationStatus.KEY_TABLE_IS_FULL
    fut = asyncio.Future()
    api._awaiting[frame_id] = (fut,)
    api._handle_registration_status(frame_id, status)
    assert fut.done() is True
    with pytest.raises(RuntimeError, match="Registration Status: KEY_TABLE_IS_FULL"):
        fut.result()


async def test_command_mode_at_cmd(api):
    """Test AT in command mode."""
    command = "+++"

    def cmd_mode_send(cmd):
        api._cmd_mode_future.set_result(True)

    api._uart.command_mode_send = cmd_mode_send

    result = await api.command_mode_at_cmd(command)
    assert result


async def test_command_mode_at_cmd_timeout(api):
    """Test AT in command mode with timeout."""
    command = "+++"

    api._uart.command_mode_send = mock.MagicMock()

    result = await api.command_mode_at_cmd(command)
    assert result is None


def test_handle_command_mode_rsp(api):
    """Test command mode response."""
    api._cmd_mode_future = None
    data = "OK"
    api.handle_command_mode_rsp(data)

    api._cmd_mode_future = asyncio.Future()
    api.handle_command_mode_rsp(data)
    assert api._cmd_mode_future.done()
    assert api._cmd_mode_future.result() is True

    api._cmd_mode_future = asyncio.Future()
    api.handle_command_mode_rsp("ERROR")
    assert api._cmd_mode_future.done()
    assert api._cmd_mode_future.result() is False

    data = "Hello"
    api._cmd_mode_future = asyncio.Future()
    api.handle_command_mode_rsp(data)
    assert api._cmd_mode_future.done()
    assert api._cmd_mode_future.result() == data


async def test_enter_at_command_mode(api):
    """Test switching to command mode."""
    api.command_mode_at_cmd = mock.AsyncMock(return_value=mock.sentinel.at_response)

    res = await api.enter_at_command_mode()
    assert res == mock.sentinel.at_response


async def test_api_mode_at_commands(api):
    """Test AT in API mode."""
    api.command_mode_at_cmd = mock.AsyncMock(return_value=mock.sentinel.api_mode)

    res = await api.api_mode_at_commands(57600)
    assert res is True

    async def mock_at_cmd(cmd):
        if cmd == "ATWR\r":
            return False
        return True

    api.command_mode_at_cmd = mock_at_cmd
    res = await api.api_mode_at_commands(57600)
    assert res is None


async def test_init_api_mode(api, monkeypatch):
    """Test init the API mode."""
    monkeypatch.setattr(api._uart, "baudrate", 57600)
    api.enter_at_command_mode = mock.AsyncMock(return_value=True)

    res = await api.init_api_mode()
    assert res is None
    assert api.enter_at_command_mode.call_count == 1

    api.enter_at_command_mode = mock.AsyncMock(return_value=False)

    res = await api.init_api_mode()
    assert res is False
    assert api.enter_at_command_mode.call_count == 10

    async def enter_at_mode():
        if api._uart.baudrate == 9600:
            return True
        return False

    api._uart.baudrate = 57600
    api.enter_at_command_mode = mock.MagicMock(side_effect=enter_at_mode)
    api.api_mode_at_commands = mock.AsyncMock(return_value=True)

    res = await api.init_api_mode()
    assert res is True
    assert api.enter_at_command_mode.call_count == 5


def test_set_application(api):
    """Test setting the application."""
    api.set_application(mock.sentinel.app)
    assert api._app == mock.sentinel.app


def test_handle_route_record_indicator(api):
    """Test api._handle_route_record_indicator()."""
    s = mock.sentinel
    api._handle_route_record_indicator(s.ieee, s.src, s.rx_opts, s.hops)


def test_handle_many_to_one_rri(api):
    """Test api._handle_many_to_one_rri()."""
    ieee = t.EUI64([t.uint8_t(a) for a in range(0, 8)])
    nwk = 0x1234
    api._handle_many_to_one_rri(ieee, nwk, 0)


@mock.patch.object(xbee_api.XBee, "_at_command", new_callable=mock.AsyncMock)
@mock.patch.object(uart, "connect", return_value=mock.MagicMock())
async def test_probe_success(mock_connect, mock_at_cmd):
    """Test device probing."""

    res = await xbee_api.XBee.probe(DEVICE_CONFIG)
    assert res is True
    assert mock_connect.call_count == 1
    assert mock_connect.await_count == 1
    assert mock_connect.call_args[0][0] == DEVICE_CONFIG
    assert mock_at_cmd.call_count == 1
    assert mock_connect.return_value.close.call_count == 1


@mock.patch.object(xbee_api.XBee, "init_api_mode", return_value=True)
@mock.patch.object(xbee_api.XBee, "_at_command", side_effect=asyncio.TimeoutError)
@mock.patch.object(uart, "connect", return_value=mock.MagicMock())
async def test_probe_success_api_mode(mock_connect, mock_at_cmd, mock_api_mode):
    """Test device probing."""

    res = await xbee_api.XBee.probe(DEVICE_CONFIG)
    assert res is True
    assert mock_connect.call_count == 1
    assert mock_connect.await_count == 1
    assert mock_connect.call_args[0][0] == DEVICE_CONFIG
    assert mock_at_cmd.call_count == 1
    assert mock_api_mode.call_count == 1
    assert mock_connect.return_value.close.call_count == 1


@mock.patch.object(xbee_api.XBee, "init_api_mode")
@mock.patch.object(xbee_api.XBee, "_at_command", side_effect=asyncio.TimeoutError)
@mock.patch.object(uart, "connect", return_value=mock.MagicMock())
@pytest.mark.parametrize(
    "exception",
    (asyncio.TimeoutError, serial.SerialException, zigpy.exceptions.APIException),
)
async def test_probe_fail(mock_connect, mock_at_cmd, mock_api_mode, exception):
    """Test device probing fails."""

    mock_api_mode.side_effect = exception
    mock_api_mode.reset_mock()
    mock_at_cmd.reset_mock()
    mock_connect.reset_mock()
    res = await xbee_api.XBee.probe(DEVICE_CONFIG)
    assert res is False
    assert mock_connect.call_count == 1
    assert mock_connect.await_count == 1
    assert mock_connect.call_args[0][0] == DEVICE_CONFIG
    assert mock_at_cmd.call_count == 1
    assert mock_api_mode.call_count == 1
    assert mock_connect.return_value.close.call_count == 1


@mock.patch.object(xbee_api.XBee, "init_api_mode", return_value=False)
@mock.patch.object(xbee_api.XBee, "_at_command", side_effect=asyncio.TimeoutError)
@mock.patch.object(uart, "connect", return_value=mock.MagicMock())
async def test_probe_fail_api_mode(mock_connect, mock_at_cmd, mock_api_mode):
    """Test device probing fails."""

    mock_api_mode.reset_mock()
    mock_at_cmd.reset_mock()
    mock_connect.reset_mock()
    res = await xbee_api.XBee.probe(DEVICE_CONFIG)
    assert res is False
    assert mock_connect.call_count == 1
    assert mock_connect.await_count == 1
    assert mock_connect.call_args[0][0] == DEVICE_CONFIG
    assert mock_at_cmd.call_count == 1
    assert mock_api_mode.call_count == 1
    assert mock_connect.return_value.close.call_count == 1


@mock.patch.object(xbee_api.XBee, "connect", return_value=mock.MagicMock())
async def test_xbee_new(conn_mck):
    """Test new class method."""
    api = await xbee_api.XBee.new(mock.sentinel.application, DEVICE_CONFIG)
    assert isinstance(api, xbee_api.XBee)
    assert conn_mck.call_count == 1
    assert conn_mck.await_count == 1


@mock.patch.object(xbee_api.XBee, "connect", return_value=mock.MagicMock())
async def test_connection_lost(conn_mck):
    """Test `connection_lost` propagataion."""
    api = await xbee_api.XBee.new(mock.sentinel.application, DEVICE_CONFIG)
    await api.connect()

    app = api._app = mock.MagicMock()

    err = RuntimeError()
    api.connection_lost(err)

    app.connection_lost.assert_called_once_with(err)

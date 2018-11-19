import asyncio
from unittest import mock

import pytest

from zigpy.types import EUI64
from zigpy_xbee.api import XBee
from zigpy_xbee.zigbee.application import ControllerApplication


@pytest.fixture
def app(database_file=None):
    return ControllerApplication(XBee(), database_file=database_file)


def test_modem_status(app):
    assert 0x00 in app._api.MODEM_STATUS
    app.handle_modem_status(0x00)
    # assert that the test below actually checks a value that is not in MODEM_STATUS
    assert 0xff not in app._api.MODEM_STATUS
    app.handle_modem_status(0xff)


def _test_rx(app, device, deserialized):
    app.get_device = mock.MagicMock(return_value=device)
    app.deserialize = mock.MagicMock(return_value=deserialized)

    app.handle_rx(
        b'\x01\x02\x03\x04\x05\x06\x07\x08',
        mock.sentinel.src_nwk,
        mock.sentinel.src_ep,
        mock.sentinel.dst_ep,
        mock.sentinel.cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        b'',
    )

    assert app.deserialize.call_count == 1


def test_rx(app):
    device = mock.MagicMock()
    app.handle_message = mock.MagicMock()
    _test_rx(app, device, (1, 2, False, []))
    assert app.handle_message.call_count == 1
    assert app.handle_message.call_args == ((
        device,
        False,
        mock.sentinel.profile_id,
        mock.sentinel.cluster_id,
        mock.sentinel.src_ep,
        mock.sentinel.dst_ep,
        1,
        2,
        [],
    ), )


def test_rx_nwk_0000(app):
    app._handle_reply = mock.MagicMock()
    app.handle_message = mock.MagicMock()
    app.handle_rx(
        b'\x01\x02\x03\x04\x05\x06\x07\x08',
        0x0000,
        mock.sentinel.src_ep,
        mock.sentinel.dst_ep,
        mock.sentinel.cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        b''
    )
    assert app.handle_message.call_count == 0
    assert app._handle_reply.call_count == 0


def test_rx_reply(app):
    app._handle_reply = mock.MagicMock()
    _test_rx(app, mock.MagicMock(), (1, 2, True, []))
    assert app._handle_reply.call_count == 1


def test_rx_failed_deserialize(app, caplog):
    app._handle_reply = mock.MagicMock()
    app.handle_message = mock.MagicMock()
    app.get_device = mock.MagicMock(return_value=mock.sentinel.device)
    app.deserialize = mock.MagicMock(side_effect=ValueError)

    app.handle_rx(
        range(8),
        mock.sentinel.src_nwk,
        mock.sentinel.src_ep,
        mock.sentinel.dst_ep,
        mock.sentinel.cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        b'',
    )

    assert any(record.levelname == 'ERROR' for record in caplog.records)

    assert app._handle_reply.call_count == 0
    assert app.handle_message.call_count == 0


@pytest.mark.asyncio
async def test_form_network(app):
    async def mock_at_command(cmd, *args):
        if cmd == 'MY':
            return mock.sentinel.ncp_nwk
        return None

    app._api._at_command = mock.MagicMock(spec=XBee._at_command,
                                          side_effect=mock_at_command)
    await app.form_network()
    assert app._api._at_command.call_count > 8
    assert app._nwk == mock.sentinel.ncp_nwk


async def _test_startup(app, ai_status=0xff, auto_form=False):
    ai_tries = 5

    async def _at_command_mock(cmd, *args):
        nonlocal ai_tries
        ai_tries -= 1
        return {
            'SH': 0x01020304,
            'SL': 0x05060708,
            'MY': 0xfffe if ai_status else 0x0000,
            'AI': ai_status if ai_tries < 0 else 0xff
        }.get(cmd, None)

    app._api._at_command = mock.MagicMock(spec=XBee._at_command,
                                          side_effect=_at_command_mock)
    app.form_network = mock.MagicMock(
        side_effect=asyncio.coroutine(mock.MagicMock()))

    await app.startup(auto_form=auto_form)
    return app


@pytest.mark.asyncio
async def test_startup_ai(app):
    auto_form = True
    await _test_startup(app, 0x00, auto_form)
    assert app._nwk == 0x0000
    assert app._ieee == EUI64(range(1, 9))
    assert app.form_network.call_count == 0

    auto_form = False
    await _test_startup(app, 0x00, auto_form)
    assert app._nwk == 0x0000
    assert app._ieee == EUI64(range(1, 9))
    assert app.form_network.call_count == 0

    auto_form = True
    await _test_startup(app, 0x06, auto_form)
    assert app._nwk == 0xfffe
    assert app._ieee == EUI64(range(1, 9))
    assert app.form_network.call_count == 1

    auto_form = False
    await _test_startup(app, 0x06, auto_form)
    assert app._nwk == 0xfffe
    assert app._ieee == EUI64(range(1, 9))
    assert app.form_network.call_count == 0


@pytest.mark.asyncio
async def test_permit(app):
    app._api._at_command = mock.MagicMock(
        side_effect=asyncio.coroutine(mock.MagicMock()))
    time_s = 30
    await app.permit(time_s)
    assert app._api._at_command.call_count == 3
    assert app._api._at_command.call_args_list[0][0][1] == time_s


async def _test_request(app, do_reply=True, expect_reply=True, **kwargs):
    seq = 123
    nwk = 0x2345
    app._devices_by_nwk[nwk] = 0x22334455

    def _mock_seq_command(cmdname, ieee, nwk, src_ep, dst_ep, cluster,
                          profile, radius, options, data):
        if expect_reply:
            if do_reply:
                app._pending[seq].set_result(mock.sentinel.reply_result)

    app._api._seq_command = mock.MagicMock(side_effect=_mock_seq_command)
    return await app.request(nwk, 0x0260, 1, 2, 3, seq, [4, 5, 6], expect_reply=expect_reply, **kwargs)


@pytest.mark.asyncio
async def test_request_with_reply(app):
    assert await _test_request(app, True, True) == mock.sentinel.reply_result


@pytest.mark.asyncio
async def test_request_expect_no_reply(app):
    assert await _test_request(app, False, False, tries=2, timeout=0.1) is None


@pytest.mark.asyncio
async def test_request_no_reply(app):
    with pytest.raises(asyncio.TimeoutError):
        await _test_request(app, False, True, tries=2, timeout=0.1)


def _handle_reply(app, tsn):
    app.handle_message = mock.MagicMock()
    return app._handle_reply(
        mock.sentinel.device,
        mock.sentinel.profile,
        mock.sentinel.cluster,
        mock.sentinel.src_ep,
        mock.sentinel.dst_ep,
        tsn,
        mock.sentinel.command_id,
        mock.sentinel.args
    )


def test_handle_reply(app):
    tsn = 123
    fut = asyncio.Future()
    app._pending[tsn] = fut
    _handle_reply(app, tsn)

    assert app.handle_message.call_count == 0
    assert fut.result() == mock.sentinel.args


def test_handle_reply_dup(app):
    tsn = 123
    fut = asyncio.Future()
    app._pending[tsn] = fut
    fut.set_result(mock.sentinel.reply_result)
    _handle_reply(app, tsn)
    assert app.handle_message.call_count == 0


def test_handle_reply_unexpected(app):
    tsn = 123
    _handle_reply(app, tsn)
    assert app.handle_message.call_count == 1
    assert app.handle_message.call_args[0][0] == mock.sentinel.device
    assert app.handle_message.call_args[0][1] is True
    assert app.handle_message.call_args[0][2] == mock.sentinel.profile
    assert app.handle_message.call_args[0][3] == mock.sentinel.cluster
    assert app.handle_message.call_args[0][4] == mock.sentinel.src_ep
    assert app.handle_message.call_args[0][5] == mock.sentinel.dst_ep
    assert app.handle_message.call_args[0][6] == tsn
    assert app.handle_message.call_args[0][7] == mock.sentinel.command_id
    assert app.handle_message.call_args[0][8] == mock.sentinel.args

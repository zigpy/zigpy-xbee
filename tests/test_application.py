import asyncio
from unittest import mock

import pytest

from zigpy.types import EUI64, uint16_t
from zigpy_xbee.api import ModemStatus, XBee
from zigpy_xbee.zigbee.application import ControllerApplication


@pytest.fixture
def app(database_file=None):
    return ControllerApplication(XBee(), database_file=database_file)


def test_modem_status(app):
    assert 0x00 in ModemStatus.__members__.values()
    app.handle_modem_status(ModemStatus(0x00))
    assert 0xEE not in ModemStatus.__members__.values()
    app.handle_modem_status(ModemStatus(0xEE))


def _test_rx(app, device, nwk, deserialized,
             dst_ep=mock.sentinel.dst_ep,
             cluster_id=mock.sentinel.cluster_id,
             data=b''):
    app.get_device = mock.MagicMock(return_value=device)
    app.deserialize = mock.MagicMock(return_value=deserialized)

    app.handle_rx(
        b'\x01\x02\x03\x04\x05\x06\x07\x08',
        nwk,
        mock.sentinel.src_ep,
        dst_ep,
        cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        data,
    )

    assert app.deserialize.call_count == 1


def _test_rx_ieee_generic(app, device, nwk, deserialized,
                          dst_ep=mock.sentinel.dst_ep,
                          cluster_id=mock.sentinel.cluster_id,
                          data=b''):
    app.get_device = mock.MagicMock(return_value=device)
    app.deserialize = mock.MagicMock(return_value=deserialized)

    app.handle_rx(
        b'\xff\xff\xff\xff\xff\xff\xff\xff',
        nwk,
        mock.sentinel.src_ep,
        dst_ep,
        cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        data,
    )

    assert app.deserialize.call_count == 1


def test_rx(app):
    device = mock.MagicMock()
    app.handle_message = mock.MagicMock()
    _test_rx(app, device, mock.sentinel.src_nwk, (1, 2, False, []))
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


def test_rx_unknown_device(app):
    app._handle_reply = mock.MagicMock()
    app.handle_message = mock.MagicMock()
    app.handle_join = mock.MagicMock()
    app.get_device = mock.MagicMock(side_effect=KeyError)
    app.handle_rx(
        b'\x01\x02\x03\x04\x05\x06\x07\x08',
        0x1234,
        mock.sentinel.src_ep,
        mock.sentinel.dst_ep,
        mock.sentinel.cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        b''
    )
    assert app.handle_join.call_count == 0
    assert app.get_device.call_count == 1
    assert app.handle_message.call_count == 0
    assert app._handle_reply.call_count == 0


def test_rx_reply(app):
    app._handle_reply = mock.MagicMock()
    _test_rx(app, mock.MagicMock(), mock.sentinel.src_nwk, (1, 2, True, []))
    assert app._handle_reply.call_count == 1


def test_rx_failed_deserialize(app, caplog):
    from zigpy.device import Status as DeviceStatus

    app._handle_reply = mock.MagicMock()
    app.handle_message = mock.MagicMock()
    nwk = 0x1234
    ieee, _ = EUI64.deserialize(b'\x01\x02\x03\x04\x05\x06\x07\x08')
    device = app.add_device(ieee, nwk)
    device.status = DeviceStatus.ENDPOINTS_INIT
    app.get_device = mock.MagicMock(return_value=device)
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


@pytest.fixture
def device(app):
    def _device(new=False, zdo_init=False, nwk=uint16_t(0x1234)):
        from zigpy.device import Device, Status as DeviceStatus

        ieee, _ = EUI64.deserialize(b'\x08\x07\x06\x05\x04\x03\x02\x01')
        dev = Device(app, ieee, nwk)
        if new:
            dev.status = DeviceStatus.NEW
        elif zdo_init:
            dev.status = DeviceStatus.ZDO_INIT
        else:
            dev.status = DeviceStatus.ENDPOINTS_INIT
        return dev
    return _device


def _device_join(app, dev, data):
    app.handle_message = mock.MagicMock()
    app.handle_join = mock.MagicMock()

    deserialized = (1, 2, False, [])
    dst_ep = 0
    cluster_id = 0x0013

    _test_rx(app, dev, dev.nwk, deserialized, dst_ep, cluster_id, data)
    assert app.handle_join.call_count == 1
    assert app.handle_message.call_count == 1


def test_device_join_new(app, device):
    dev = device()
    data = b'\xee' + dev.nwk.serialize() + dev.ieee.serialize()

    _device_join(app, dev, data)


def test_device_join_inconsistent_nwk(app, device):
    dev = device()
    data = b'\xee' + b'\x01\x02' + dev.ieee.serialize()

    _device_join(app, dev, data)


def test_device_join_inconsistent_ieee(app, device):
    dev = device()
    data = b'\xee' + dev.nwk.serialize() + b'\x01\x02\x03\x04\x05\x06\x07\x08'

    _device_join(app, dev, data)


def _device_status_new(app, dev):
    app.handle_join = mock.MagicMock()
    app.handle_message = mock.MagicMock()
    app.handle_reply = mock.MagicMock()
    app.get_device = mock.MagicMock(return_value=dev)
    app.deserialize = mock.MagicMock()

    app.handle_rx(
        b'\x01\x02\x03\x04\x05\x06\x07\x08',
        dev.nwk,
        mock.sentinel.src_ep,
        mock.sentinel.dst_ep,
        mock.sentinel.cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        b'',
    )

    assert app.deserialize.call_count == 0
    assert app.handle_join.call_count == 0
    assert app.handle_message.call_count == 0
    assert app.handle_reply.call_count == 0


def test_handle_rx_device_status_new(app, device):
    dev = device(new=True)
    _device_status_new(app, dev)


def test_handle_rx_device_status_zdo(app, device):
    dev = device(zdo_init=True)
    _device_status_new(app, dev)


@pytest.mark.asyncio
async def test_broadcast(app):
    (profile, cluster, src_ep, dst_ep, grpid, radius, tsn, data) = (
        0x260, 1, 2, 3, 0x0100, 0x06, 210, b'\x02\x01\x00'
    )

    app._api._seq_command = mock.MagicMock(
        side_effect=asyncio.coroutine(mock.MagicMock())
    )

    await app.broadcast(
        profile, cluster, src_ep, dst_ep, grpid, radius, tsn, data)
    assert app._api._seq_command.call_count == 1
    assert app._api._seq_command.call_args[0][0] == 'tx_explicit'
    assert app._api._seq_command.call_args[0][3] == src_ep
    assert app._api._seq_command.call_args[0][4] == dst_ep
    assert app._api._seq_command.call_args[0][9] == data


@pytest.mark.asyncio
async def test_get_association_state(app):
    ai_results = (0xff, 0xff, 0xff, 0xff, mock.sentinel.ai)
    app._api._at_command = mock.MagicMock(
        spec=XBee._at_command, side_effect=asyncio.coroutine(mock.MagicMock(
            side_effect=ai_results
        )))
    ai = await app._get_association_state()
    assert app._api._at_command.call_count == len(ai_results)
    assert ai is mock.sentinel.ai


@pytest.mark.asyncio
async def test_form_network(app):
    legacy_module = False

    async def mock_at_command(cmd, *args):
        if cmd == 'MY':
            return 0x0000
        elif cmd == 'WR':
            app._api.coordinator_started_event.set()
        elif cmd == 'CE' and legacy_module:
            raise RuntimeError
        return None

    app._api._at_command = mock.MagicMock(spec=XBee._at_command,
                                          side_effect=mock_at_command)
    app._api._queued_at = mock.MagicMock(spec=XBee._at_command,
                                         side_effect=mock_at_command)
    app._get_association_state = mock.MagicMock(
        spec=ControllerApplication._get_association_state,
        side_effect=asyncio.coroutine(mock.MagicMock(return_value=0x00))
    )

    await app.form_network()
    assert app._api._at_command.call_count >= 1
    assert app._api._queued_at.call_count >= 7
    assert app._nwk == 0x0000

    app._api._at_command.reset_mock()
    app._api._queued_at.reset_mock()
    legacy_module = True
    await app.form_network()
    assert app._api._at_command.call_count >= 1
    assert app._api._queued_at.call_count >= 7
    assert app._nwk == 0x0000


async def _test_startup(app, ai_status=0xff, auto_form=False, api_mode=True,
                        api_config_succeeds=True, ee=1, eo=2, zs=2,
                        legacy_module=False):
    ai_tries = 5
    app._nwk = mock.sentinel.nwk

    async def _at_command_mock(cmd, *args):
        nonlocal ai_tries
        if not api_mode:
            raise asyncio.TimeoutError
        if cmd == 'CE' and legacy_module:
            raise RuntimeError

        ai_tries -= 1 if cmd == 'AI' else 0
        return {
            'AI': ai_status if ai_tries < 0 else 0xff,
            'CE': 1 if ai_status == 0 else 0,
            'EO': eo,
            'EE': ee,
            'ID': mock.sentinel.at_id,
            'MY': 0xfffe if ai_status else 0x0000,
            'NJ': mock.sentinel.at_nj,
            'OI': mock.sentinel.at_oi,
            'OP': mock.sentinel.at_op,
            'SH': 0x01020304,
            'SL': 0x05060708,
            'ZS': zs,
        }.get(cmd, None)

    app._api._at_command = mock.MagicMock(spec=XBee._at_command,
                                          side_effect=_at_command_mock)

    async def init_api_mode_mock():
        nonlocal api_mode
        api_mode = api_config_succeeds
        return api_config_succeeds

    app._api.init_api_mode = mock.MagicMock(side_effect=init_api_mode_mock)
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

    auto_form = True
    await _test_startup(app, 0x00, auto_form, zs=1)
    assert app._nwk == 0x0000
    assert app._ieee == EUI64(range(1, 9))
    assert app.form_network.call_count == 1

    auto_form = False
    await _test_startup(app, 0x06, auto_form, legacy_module=True)
    assert app._nwk == 0xfffe
    assert app._ieee == EUI64(range(1, 9))
    assert app.form_network.call_count == 0

    auto_form = True
    await _test_startup(app, 0x00, auto_form, zs=1, legacy_module=True)
    assert app._nwk == 0x0000
    assert app._ieee == EUI64(range(1, 9))
    assert app.form_network.call_count == 1


@pytest.mark.asyncio
async def test_startup_no_api_mode(app):
    auto_form = True
    await _test_startup(app, 0x00, auto_form, api_mode=False)
    assert app._nwk == 0x0000
    assert app._ieee == EUI64(range(1, 9))
    assert app.form_network.call_count == 0
    assert app._api.init_api_mode.call_count == 1
    assert app._api._at_command.call_count >= 16


@pytest.mark.asyncio
async def test_startup_api_mode_config_fails(app):
    auto_form = True
    await _test_startup(app, 0x00, auto_form,
                        api_mode=False, api_config_succeeds=False)
    assert app._nwk == mock.sentinel.nwk
    assert app._ieee is None
    assert app.form_network.call_count == 0
    assert app._api.init_api_mode.call_count == 1
    assert app._api._at_command.call_count == 1


@pytest.mark.asyncio
async def test_permit(app):
    app._api._at_command = mock.MagicMock(
        side_effect=asyncio.coroutine(mock.MagicMock()))
    time_s = 30
    await app.permit_ncp(time_s)
    assert app._api._at_command.call_count == 3
    assert app._api._at_command.call_args_list[0][0][1] == time_s


async def _test_request(app, do_reply=True, expect_reply=True, **kwargs):
    seq = 123
    nwk = 0x2345
    ieee = EUI64(b'\x01\x02\x03\x04\x05\x06\x07\x08')
    app.add_device(ieee, nwk)

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


@pytest.mark.asyncio
async def test_force_remove(app):
    await app.force_remove(mock.sentinel.device)


@pytest.mark.asyncio
async def test_shutdown(app):
    app._api.close = mock.MagicMock()
    await app.shutdown()
    assert app._api.close.call_count == 1

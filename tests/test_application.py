import asyncio

import pytest
from zigpy import types as t
import zigpy.exceptions
from zigpy.zdo.types import ZDOCmd

from zigpy_xbee.api import ModemStatus, XBee
import zigpy_xbee.config as config
import zigpy_xbee.types as xbee_t
from zigpy_xbee.zigbee import application

import tests.async_mock as mock

APP_CONFIG = {
    config.CONF_DEVICE: {
        config.CONF_DEVICE_PATH: "/dev/null",
        config.CONF_DEVICE_BAUDRATE: 115200,
    },
    config.CONF_DATABASE: None,
}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(application, "TIMEOUT_TX_STATUS", 0.1)
    monkeypatch.setattr(application, "TIMEOUT_REPLY", 0.1)
    monkeypatch.setattr(application, "TIMEOUT_REPLY_EXTENDED", 0.1)
    app = application.ControllerApplication(APP_CONFIG)
    api = XBee(APP_CONFIG[config.CONF_DEVICE])
    monkeypatch.setattr(api, "_command", mock.AsyncMock())
    app._api = api

    app.state.node_info.nwk = 0x0000
    app.state.node_info.ieee = t.EUI64.convert("aa:bb:cc:dd:ee:ff:00:11")
    return app


def test_modem_status(app):
    assert 0x00 in ModemStatus.__members__.values()
    app.handle_modem_status(ModemStatus(0x00))
    assert 0xEE not in ModemStatus.__members__.values()
    app.handle_modem_status(ModemStatus(0xEE))


def _test_rx(
    app,
    device,
    nwk,
    dst_ep=mock.sentinel.dst_ep,
    cluster_id=mock.sentinel.cluster_id,
    data=mock.sentinel.data,
):
    app.get_device = mock.MagicMock(return_value=device)

    app.handle_rx(
        b"\x01\x02\x03\x04\x05\x06\x07\x08",
        nwk,
        mock.sentinel.src_ep,
        dst_ep,
        cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        data,
    )


def test_rx(app):
    device = mock.MagicMock()
    app.handle_message = mock.MagicMock()
    _test_rx(app, device, mock.sentinel.src_nwk, data=mock.sentinel.message)
    assert app.handle_message.call_count == 1
    assert app.handle_message.call_args == (
        (
            device,
            mock.sentinel.profile_id,
            mock.sentinel.cluster_id,
            mock.sentinel.src_ep,
            mock.sentinel.dst_ep,
            mock.sentinel.message,
        ),
    )


def test_rx_nwk_0000(app):
    app._handle_reply = mock.MagicMock()
    app.handle_message = mock.MagicMock()
    app.get_device = mock.MagicMock()
    app.handle_rx(
        b"\x01\x02\x03\x04\x05\x06\x07\x08",
        0x0000,
        mock.sentinel.src_ep,
        mock.sentinel.dst_ep,
        mock.sentinel.cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        b"",
    )
    assert app.handle_message.call_count == 1
    assert app.get_device.call_count == 2


def test_rx_unknown_device(app, device):
    """Unknown NWK, but existing device."""
    app.handle_message = mock.MagicMock()
    app.handle_join = mock.MagicMock()
    dev = device(nwk=0x1234)
    app.devices[dev.ieee] = dev

    num_before_rx = len(app.devices)
    app.handle_rx(
        b"\x08\x07\x06\x05\x04\x03\x02\x01",
        0x3334,
        mock.sentinel.src_ep,
        mock.sentinel.dst_ep,
        mock.sentinel.cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        b"",
    )
    assert app.handle_join.call_count == 1
    assert app.handle_message.call_count == 1
    assert len(app.devices) == num_before_rx


def test_rx_unknown_device_ieee(app):
    """Unknown NWK, and unknown IEEE."""
    app.handle_message = mock.MagicMock()
    app.handle_join = mock.MagicMock()
    app.get_device = mock.MagicMock(side_effect=KeyError)
    app.handle_rx(
        b"\xff\xff\xff\xff\xff\xff\xff\xff",
        0x3334,
        mock.sentinel.src_ep,
        mock.sentinel.dst_ep,
        mock.sentinel.cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rxopts,
        b"",
    )
    assert app.handle_join.call_count == 0
    assert app.get_device.call_count == 2
    assert app.handle_message.call_count == 0


@pytest.fixture
def device(app):
    def _device(new=False, zdo_init=False, nwk=t.uint16_t(0x1234)):
        from zigpy.device import Device, Status as DeviceStatus

        ieee, _ = t.EUI64.deserialize(b"\x08\x07\x06\x05\x04\x03\x02\x01")
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

    dst_ep = 0
    cluster_id = 0x0013

    _test_rx(app, dev, dev.nwk, dst_ep, cluster_id, data)
    assert app.handle_join.call_count == 1
    assert app.handle_message.call_count == 1


def test_device_join_new(app, device):
    dev = device()
    data = b"\xee" + dev.nwk.serialize() + dev.ieee.serialize()

    _device_join(app, dev, data)


def test_device_join_inconsistent_nwk(app, device):
    dev = device()
    data = b"\xee" + b"\x01\x02" + dev.ieee.serialize()

    _device_join(app, dev, data)


def test_device_join_inconsistent_ieee(app, device):
    dev = device()
    data = b"\xee" + dev.nwk.serialize() + b"\x01\x02\x03\x04\x05\x06\x07\x08"

    _device_join(app, dev, data)


async def test_broadcast(app):
    (profile, cluster, src_ep, dst_ep, grpid, radius, tsn, data) = (
        0x260,
        1,
        2,
        3,
        0x0100,
        0x06,
        210,
        b"\x02\x01\x00",
    )

    app._api._command.return_value = xbee_t.TXStatus.SUCCESS

    r = await app.broadcast(profile, cluster, src_ep, dst_ep, grpid, radius, tsn, data)
    assert r[0] == xbee_t.TXStatus.SUCCESS
    assert app._api._command.call_count == 1
    assert app._api._command.call_args[0][0] == "tx_explicit"
    assert app._api._command.call_args[0][3] == src_ep
    assert app._api._command.call_args[0][4] == dst_ep
    assert app._api._command.call_args[0][9] == data

    app._api._command.return_value = xbee_t.TXStatus.ADDRESS_NOT_FOUND
    r = await app.broadcast(profile, cluster, src_ep, dst_ep, grpid, radius, tsn, data)
    assert r[0] != xbee_t.TXStatus.SUCCESS

    app._api._command.side_effect = asyncio.TimeoutError
    r = await app.broadcast(profile, cluster, src_ep, dst_ep, grpid, radius, tsn, data)
    assert r[0] != xbee_t.TXStatus.SUCCESS


async def test_get_association_state(app):
    ai_results = (0xFF, 0xFF, 0xFF, 0xFF, mock.sentinel.ai)
    app._api._at_command = mock.AsyncMock(
        spec=XBee._at_command,
        side_effect=ai_results,
    )
    ai = await app._get_association_state()
    assert app._api._at_command.call_count == len(ai_results)
    assert ai is mock.sentinel.ai


async def test_form_network(app):
    legacy_module = False

    async def mock_at_command(cmd, *args):
        if cmd == "MY":
            return 0x0000
        elif cmd == "WR":
            app._api.coordinator_started_event.set()
        elif cmd == "CE" and legacy_module:
            raise RuntimeError
        return None

    app._api._at_command = mock.MagicMock(
        spec=XBee._at_command, side_effect=mock_at_command
    )
    app._api._queued_at = mock.MagicMock(
        spec=XBee._at_command, side_effect=mock_at_command
    )
    app._get_association_state = mock.AsyncMock(
        spec=application.ControllerApplication._get_association_state,
        return_value=0x00,
    )

    app.write_network_info = mock.MagicMock(wraps=app.write_network_info)

    await app.form_network()
    assert app._api._at_command.call_count >= 1
    assert app._api._queued_at.call_count >= 7

    network_info = app.write_network_info.mock_calls[0][2]["network_info"]

    app._api._queued_at.assert_any_call("SC", 1 << (network_info.channel - 11))
    app._api._queued_at.assert_any_call("KY", b"ZigBeeAlliance09")

    app._api._at_command.reset_mock()
    app._api._queued_at.reset_mock()
    legacy_module = True
    await app.form_network()
    assert app._api._at_command.call_count >= 1
    assert app._api._queued_at.call_count >= 7

    network_info = app.write_network_info.mock_calls[0][2]["network_info"]

    app._api._queued_at.assert_any_call("SC", 1 << (network_info.channel - 11))
    app._api._queued_at.assert_any_call("KY", b"ZigBeeAlliance09")


async def _test_start_network(
    app,
    ai_status=0xFF,
    api_mode=True,
    api_config_succeeds=True,
    ee=1,
    eo=2,
    zs=2,
    legacy_module=False,
):
    ai_tries = 5
    app.state.node_info.nwk = mock.sentinel.nwk

    def _at_command_mock(cmd, *args):
        nonlocal ai_tries
        if not api_mode:
            raise asyncio.TimeoutError
        if cmd == "CE" and legacy_module:
            raise RuntimeError

        ai_tries -= 1 if cmd == "AI" else 0
        return {
            "AI": ai_status if ai_tries < 0 else 0xFF,
            "CE": 1 if ai_status == 0 else 0,
            "EO": eo,
            "EE": ee,
            "ID": 0x25DCF87E03EA5906,
            "MY": 0xFFFE if ai_status else 0x0000,
            "NJ": mock.sentinel.at_nj,
            "OI": 0xDD94,
            "OP": mock.sentinel.at_op,
            "SH": 0x08070605,
            "SL": 0x04030201,
            "ZS": zs,
        }.get(cmd, None)

    def init_api_mode_mock():
        nonlocal api_mode
        api_mode = api_config_succeeds
        return api_config_succeeds

    with mock.patch("zigpy_xbee.api.XBee") as XBee_mock:
        api_mock = mock.MagicMock()
        api_mock._at_command = mock.AsyncMock(side_effect=_at_command_mock)
        api_mock.init_api_mode = mock.AsyncMock(side_effect=init_api_mode_mock)

        XBee_mock.new = mock.AsyncMock(return_value=api_mock)

        await app.connect()

    app.form_network = mock.AsyncMock()
    await app.load_network_info()
    await app.start_network()
    return app


async def test_start_network(app):
    await _test_start_network(app, ai_status=0x00)
    assert app.state.node_info.nwk == 0x0000
    assert app.state.node_info.ieee == t.EUI64(range(1, 9))
    assert app.state.network_info.pan_id == 0xDD94
    assert app.state.network_info.extended_pan_id == t.ExtendedPanId.convert(
        "25:dc:f8:7e:03:ea:59:06"
    )

    await _test_start_network(app, ai_status=0x00)
    assert app.state.node_info.nwk == 0x0000
    assert app.state.node_info.ieee == t.EUI64(range(1, 9))
    assert app.form_network.call_count == 0

    with pytest.raises(zigpy.exceptions.NetworkNotFormed):
        await _test_start_network(app, ai_status=0x06)

    with pytest.raises(zigpy.exceptions.NetworkNotFormed):
        await _test_start_network(app, ai_status=0x00, zs=1)

    with pytest.raises(zigpy.exceptions.NetworkNotFormed):
        await _test_start_network(app, ai_status=0x06, legacy_module=True)

    with pytest.raises(zigpy.exceptions.NetworkNotFormed):
        await _test_start_network(app, ai_status=0x00, zs=1, legacy_module=True)


async def test_start_network_no_api_mode(app):
    await _test_start_network(app, ai_status=0x00, api_mode=False)
    assert app.state.node_info.nwk == 0x0000
    assert app.state.node_info.ieee == t.EUI64(range(1, 9))
    assert app._api.init_api_mode.call_count == 1
    assert app._api._at_command.call_count >= 16


async def test_start_network_api_mode_config_fails(app):
    with pytest.raises(zigpy.exceptions.ControllerException):
        await _test_start_network(
            app, ai_status=0x00, api_mode=False, api_config_succeeds=False
        )

    assert app._api.init_api_mode.call_count == 1
    assert app._api._at_command.call_count == 1


async def test_permit(app):
    app._api._at_command = mock.AsyncMock()
    time_s = 30
    await app.permit_ncp(time_s)
    assert app._api._at_command.call_count == 2
    assert app._api._at_command.call_args_list[0][0][1] == time_s


async def _test_request(
    app,
    expect_reply=True,
    send_success=True,
    send_timeout=False,
    is_end_device=True,
    node_desc=True,
    **kwargs
):
    seq = 123
    nwk = 0x2345
    ieee = t.EUI64(b"\x01\x02\x03\x04\x05\x06\x07\x08")
    dev = app.add_device(ieee, nwk)

    if node_desc:
        dev.node_desc = mock.MagicMock()
        dev.node_desc.is_end_device = is_end_device
    else:
        dev.node_desc = None

    def _mock_command(
        cmdname, ieee, nwk, src_ep, dst_ep, cluster, profile, radius, options, data
    ):
        send_fut = asyncio.Future()
        if not send_timeout:
            if send_success:
                send_fut.set_result(xbee_t.TXStatus.SUCCESS)
            else:
                send_fut.set_result(xbee_t.TXStatus.ADDRESS_NOT_FOUND)
        return send_fut

    app._api._command = mock.MagicMock(side_effect=_mock_command)
    return await app.request(
        dev,
        0x0260,
        1,
        2,
        3,
        seq,
        b"\xaa\x55\xbe\xef",
        expect_reply=expect_reply,
        **kwargs
    )


async def test_request_with_reply(app):
    r = await _test_request(app, expect_reply=True, send_success=True)
    assert r[0] == 0


async def test_request_without_node_desc(app):
    r = await _test_request(app, expect_reply=True, send_success=True, node_desc=False)
    assert r[0] == 0


async def test_request_send_timeout(app):
    r = await _test_request(app, send_timeout=True)
    assert r[0] != 0


async def test_request_send_fail(app):
    r = await _test_request(app, send_success=False)
    assert r[0] != 0


async def test_request_extended_timeout(app):
    is_end_device = False
    r = await _test_request(app, True, True, is_end_device=is_end_device)
    assert r[0] == xbee_t.TXStatus.SUCCESS
    assert app._api._command.call_count == 1
    assert app._api._command.call_args[0][8] & 0x40 == 0x00
    app._api._command.reset_mock()

    r = await _test_request(app, True, True, node_desc=False)
    assert r[0] == xbee_t.TXStatus.SUCCESS
    assert app._api._command.call_count == 1
    assert app._api._command.call_args[0][8] & 0x40 == 0x40
    app._api._command.reset_mock()

    is_end_device = True
    r = await _test_request(app, True, True, is_end_device=is_end_device)
    assert r[0] == xbee_t.TXStatus.SUCCESS
    assert app._api._command.call_count == 1
    assert app._api._command.call_args[0][8] & 0x40 == 0x40
    app._api._command.reset_mock()


async def test_force_remove(app):
    await app.force_remove(mock.sentinel.device)


async def test_shutdown(app):
    app._api.close = mock.MagicMock()
    await app.shutdown()
    assert app._api.close.call_count == 1


def test_remote_at_cmd(app, device):
    dev = device()
    app.get_device = mock.MagicMock(return_value=dev)
    app._api = mock.MagicMock(spec=XBee)
    s = mock.sentinel
    app.remote_at_command(s.nwk, s.cmd, s.data, apply_changes=True, encryption=True)
    assert app._api._remote_at_command.call_count == 1
    assert app._api._remote_at_command.call_args[0][0] is dev.ieee
    assert app._api._remote_at_command.call_args[0][1] == s.nwk
    assert app._api._remote_at_command.call_args[0][2] == 0x12
    assert app._api._remote_at_command.call_args[0][3] == s.cmd
    assert app._api._remote_at_command.call_args[0][4] == s.data


@pytest.fixture
def ieee():
    return t.EUI64.deserialize(b"\x00\x01\x02\x03\x04\x05\x06\x07")[0]


@pytest.fixture
def nwk():
    return t.uint16_t(0x0100)


def test_rx_device_annce(app, ieee, nwk):
    dst_ep = 0
    cluster_id = ZDOCmd.Device_annce
    device = mock.MagicMock()
    device.status = device.Status.NEW
    app.get_device = mock.MagicMock(return_value=device)
    app.handle_join = mock.MagicMock()
    app.handle_message = mock.MagicMock()

    data = t.uint8_t(0xAA).serialize()
    data += nwk.serialize()
    data += ieee.serialize()
    data += t.uint8_t(0x8E).serialize()

    app.handle_rx(
        ieee,
        nwk,
        mock.sentinel.src_ep,
        dst_ep,
        cluster_id,
        mock.sentinel.profile_id,
        mock.sentinel.rx_opt,
        data,
    )

    assert app.handle_message.call_count == 1
    assert app.handle_join.call_count == 1
    assert app.handle_join.call_args[0][0] == nwk
    assert app.handle_join.call_args[0][1] == ieee
    assert app.handle_join.call_args[0][2] == 0


async def _test_mrequest(app, send_success=True, send_timeout=False, **kwargs):
    seq = 123
    group_id = 0x2345

    def _mock_command(
        cmdname, ieee, nwk, src_ep, dst_ep, cluster, profile, radius, options, data
    ):
        send_fut = asyncio.Future()
        if not send_timeout:
            if send_success:
                send_fut.set_result(xbee_t.TXStatus.SUCCESS)
            else:
                send_fut.set_result(xbee_t.TXStatus.ADDRESS_NOT_FOUND)
        return send_fut

    app._api._command = mock.MagicMock(side_effect=_mock_command)
    return await app.mrequest(group_id, 0x0260, 1, 2, seq, b"\xaa\x55\xbe\xef")


async def test_mrequest_with_reply(app):
    r = await _test_mrequest(app, send_success=True)
    assert r[0] == 0


async def test_mrequest_send_timeout(app):
    r = await _test_mrequest(app, send_timeout=True)
    assert r[0] != 0


async def test_mrequest_send_fail(app):
    r = await _test_mrequest(app, send_success=False)
    assert r[0] != 0

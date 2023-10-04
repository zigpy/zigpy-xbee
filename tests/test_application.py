import asyncio

import pytest
import zigpy.exceptions
import zigpy.state
import zigpy.types as t
import zigpy.zdo.types as zdo_t

from zigpy_xbee.api import XBee
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
def node_info():
    return zigpy.state.NodeInfo(
        nwk=t.NWK(0x0000),
        ieee=t.EUI64.convert("00:12:4b:00:1c:a1:b8:46"),
        logical_type=zdo_t.LogicalType.Coordinator,
    )


@pytest.fixture
def network_info(node_info):
    return zigpy.state.NetworkInfo(
        extended_pan_id=t.ExtendedPanId.convert("bd:27:0b:38:37:95:dc:87"),
        pan_id=t.PanId(0x9BB0),
        nwk_update_id=18,
        nwk_manager_id=t.NWK(0x0000),
        channel=t.uint8_t(15),
        channel_mask=t.Channels.ALL_CHANNELS,
        security_level=t.uint8_t(5),
        network_key=zigpy.state.Key(
            key=t.KeyData.convert("2ccade06b3090c310315b3d574d3c85a"),
            seq=108,
            tx_counter=118785,
        ),
        tc_link_key=zigpy.state.Key(
            key=t.KeyData(b"ZigBeeAlliance09"),
            partner_ieee=node_info.ieee,
            tx_counter=8712428,
        ),
        key_table=[],
        children=[],
        nwk_addresses={},
        source="zigpy-xbee@0.0.0",
    )


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
    assert 0x00 in xbee_t.ModemStatus.__members__.values()
    app.handle_modem_status(xbee_t.ModemStatus(0x00))
    assert 0xEE not in xbee_t.ModemStatus.__members__.values()
    app.handle_modem_status(xbee_t.ModemStatus(0xEE))


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

    with pytest.raises(zigpy.exceptions.DeliveryError):
        r = await app.broadcast(
            profile, cluster, src_ep, dst_ep, grpid, radius, tsn, data
        )

    app._api._command.side_effect = asyncio.TimeoutError

    with pytest.raises(zigpy.exceptions.DeliveryError):
        r = await app.broadcast(
            profile, cluster, src_ep, dst_ep, grpid, radius, tsn, data
        )


async def test_get_association_state(app):
    ai_results = (0xFF, 0xFF, 0xFF, 0xFF, mock.sentinel.ai)
    app._api._at_command = mock.AsyncMock(
        spec=XBee._at_command,
        side_effect=ai_results,
    )
    ai = await app._get_association_state()
    assert app._api._at_command.call_count == len(ai_results)
    assert ai is mock.sentinel.ai


@pytest.mark.parametrize("legacy_module", (False, True))
async def test_write_network_info(app, node_info, network_info, legacy_module):
    def _mock_queued_at(name, *args):
        if legacy_module and name == "CE":
            raise RuntimeError("Legacy module")
        return "OK"

    app._api._queued_at = mock.AsyncMock(
        spec=XBee._queued_at, side_effect=_mock_queued_at
    )
    app._api._at_command = mock.AsyncMock(spec=XBee._at_command)
    app._api._running = mock.AsyncMock(spec=app._api._running)

    app._get_association_state = mock.AsyncMock(
        spec=application.ControllerApplication._get_association_state,
        return_value=0x00,
    )

    await app.write_network_info(network_info=network_info, node_info=node_info)

    app._api._queued_at.assert_any_call("SC", 1 << (network_info.channel - 11))
    app._api._queued_at.assert_any_call("KY", b"ZigBeeAlliance09")
    app._api._queued_at.assert_any_call("NK", network_info.network_key.key.serialize())
    app._api._queued_at.assert_any_call("ID", 0xBD270B383795DC87)


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
    app.state.node_info = zigpy.state.NodeInfo()

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


async def test_permit_with_key(app):
    app._api._command = mock.AsyncMock(return_value=xbee_t.TXStatus.SUCCESS)
    app._api._at_command = mock.AsyncMock(return_value="OK")
    node = t.EUI64(b"\x01\x02\x03\x04\x05\x06\x07\x08")
    code = b"\xC9\xA7\xD2\x44\x1A\x71\x16\x95\xCD\x62\x17\x0D\x33\x28\xEA\x2B\x42\x3D"
    time_s = 500
    await app.permit_with_key(node=node, code=code, time_s=time_s)
    app._api._at_command.assert_called_once_with("KT", time_s)
    app._api._command.assert_called_once_with(
        "register_joining_device", node, 0xFFFE, 1, code
    )


async def test_permit_with_link_key(app):
    app._api._command = mock.AsyncMock(return_value=xbee_t.TXStatus.SUCCESS)
    app._api._at_command = mock.AsyncMock(return_value="OK")
    node = t.EUI64(b"\x01\x02\x03\x04\x05\x06\x07\x08")
    link_key = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0A\x0B\x0C\x0D\x0E\x0F"
    time_s = 500
    await app.permit_with_link_key(node=node, link_key=link_key, time_s=time_s)
    app._api._at_command.assert_called_once_with("KT", time_s)
    app._api._command.assert_called_once_with(
        "register_joining_device", node, 0xFFFE, 0, link_key
    )


async def _test_request(
    app, expect_reply=True, send_success=True, send_timeout=False, **kwargs
):
    seq = 123
    nwk = 0x2345
    ieee = t.EUI64(b"\x01\x02\x03\x04\x05\x06\x07\x08")
    dev = app.add_device(ieee, nwk)

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
        **kwargs,
    )


async def test_request_with_ieee(app):
    r = await _test_request(app, use_ieee=True, send_success=True)
    assert r[0] == 0


async def test_request_with_reply(app):
    r = await _test_request(app, expect_reply=True, send_success=True)
    assert r[0] == 0


async def test_request_send_timeout(app):
    with pytest.raises(zigpy.exceptions.DeliveryError):
        await _test_request(app, send_timeout=True)


async def test_request_send_fail(app):
    with pytest.raises(zigpy.exceptions.DeliveryError):
        await _test_request(app, send_success=False)


async def test_request_unknown_device(app):
    dev = zigpy.device.Device(
        application=app, ieee=xbee_t.UNKNOWN_IEEE, nwk=xbee_t.UNKNOWN_NWK
    )
    with pytest.raises(
        zigpy.exceptions.DeliveryError,
        match="Cannot send a packet to a device without a known IEEE address",
    ):
        await app.request(
            dev,
            0x0260,
            1,
            2,
            3,
            123,
            b"\xaa\x55\xbe\xef",
        )


async def test_request_extended_timeout(app):
    r = await _test_request(app, True, True, extended_timeout=False)
    assert r[0] == xbee_t.TXStatus.SUCCESS
    assert app._api._command.call_count == 1
    assert app._api._command.call_args[0][8] & 0x40 == 0x00
    app._api._command.reset_mock()

    r = await _test_request(app, True, True, extended_timeout=True)
    assert r[0] == xbee_t.TXStatus.SUCCESS
    assert app._api._command.call_count == 1
    assert app._api._command.call_args[0][8] & 0x40 == 0x40
    app._api._command.reset_mock()


async def test_force_remove(app):
    await app.force_remove(mock.sentinel.device)


async def test_shutdown(app):
    mack_close = mock.MagicMock()
    app._api.close = mack_close
    await app.shutdown()
    assert app._api is None
    assert mack_close.call_count == 1


async def test_remote_at_cmd(app, device):
    dev = device()
    app.get_device = mock.MagicMock(return_value=dev)
    app._api = mock.MagicMock(spec=XBee)
    s = mock.sentinel
    await app.remote_at_command(
        s.nwk, s.cmd, s.data, apply_changes=True, encryption=True
    )
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
    cluster_id = zdo_t.ZDOCmd.Device_annce
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
    with pytest.raises(zigpy.exceptions.DeliveryError):
        await _test_mrequest(app, send_timeout=True)


async def test_mrequest_send_fail(app):
    with pytest.raises(zigpy.exceptions.DeliveryError):
        await _test_mrequest(app, send_success=False)


async def test_reset_network_info(app):
    async def mock_at_command(cmd, *args):
        if cmd == "NR":
            return 0x00

        return None

    app._api._at_command = mock.MagicMock(
        spec=XBee._at_command, side_effect=mock_at_command
    )

    await app.reset_network_info()

    app._api._at_command.assert_called_once_with("NR", 0)


async def test_move_network_to_channel(app):
    app._api._queued_at = mock.AsyncMock(spec=XBee._at_command)
    await app._move_network_to_channel(26, new_nwk_update_id=1)

    assert len(app._api._queued_at.mock_calls) == 1
    app._api._queued_at.assert_any_call("SC", 1 << (26 - 11))


async def test_energy_scan(app):
    rssi = b"\x0A\x0F\x14\x19\x1E\x23\x28\x2D\x32\x37\x3C\x41\x46\x4B\x50\x55"
    app._api._at_command = mock.AsyncMock(spec=XBee._at_command, return_value=rssi)
    time_s = 3
    count = 3
    energy = await app.energy_scan(
        channels=[x for x in range(11, 27)], duration_exp=time_s, count=count
    )
    assert app._api._at_command.mock_calls == [mock.call("ED", time_s)] * count
    assert {k: round(v, 3) for k, v in energy.items()} == {
        11: 254.032,
        12: 253.153,
        13: 251.486,
        14: 248.352,
        15: 242.562,
        16: 232.193,
        17: 214.619,
        18: 187.443,
        19: 150.853,
        20: 109.797,
        21: 72.172,
        22: 43.571,
        23: 24.769,
        24: 13.56,
        25: 7.264,
        26: 3.844,
    }

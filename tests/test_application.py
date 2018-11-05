import asyncio
from unittest import mock

import pytest

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

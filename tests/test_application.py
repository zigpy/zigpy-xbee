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

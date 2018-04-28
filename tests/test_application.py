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

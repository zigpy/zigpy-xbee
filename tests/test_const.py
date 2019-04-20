import zigpy_xbee.const


def test_version():
    assert isinstance(zigpy_xbee.const.__short_version__, str)
    assert isinstance(zigpy_xbee.const.__version__, str)

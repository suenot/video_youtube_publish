from channel import normalize_handle, channel_id_from_url


def test_normalize_handle_adds_at():
    assert normalize_handle("marketmaker-cc") == "@marketmaker-cc"


def test_normalize_handle_from_url():
    assert normalize_handle("https://youtube.com/@marketmaker-cc") == "@marketmaker-cc"


def test_channel_id_from_url():
    u = "https://studio.youtube.com/channel/UCbPEVsO_M-axL0mylsoTADw/videos"
    assert channel_id_from_url(u) == "UCbPEVsO_M-axL0mylsoTADw"


def test_channel_id_from_url_none():
    assert channel_id_from_url("https://studio.youtube.com/") is None

from burn_subs.ffmpeg import build_subtitles_filter


def test_build_subtitles_filter_escapes_basic_chars() -> None:
    vf = build_subtitles_filter("/tmp/a:b'c.mkv", 2)
    assert "stream_index=2" in vf
    assert "filename='" in vf
    assert "\\:" in vf  # colon escaped
    assert "\\'" in vf  # quote escaped


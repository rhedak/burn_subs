from unittest.mock import patch, MagicMock
import subprocess

from burn_subs.ffmpeg import build_subtitles_filter, get_subtitle_codec, probe_streams


def test_build_subtitles_filter_escapes_basic_chars() -> None:
    vf = build_subtitles_filter("/tmp/a:b'c.mkv", 2)
    assert "stream_index=2" in vf
    assert "filename='" in vf
    assert "\\:" in vf  # colon escaped
    assert "\\'" in vf  # quote escaped


# --- get_subtitle_codec ---

def _make_run_result(stdout: str) -> MagicMock:
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.returncode = 0
    return result


def test_get_subtitle_codec_stream_specifier_uses_s_prefix() -> None:
    """ffprobe must use 's:N' not '0:s:N' — the file-index prefix breaks ffprobe 8.x."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs):
        calls.append(args)
        return _make_run_result("ass")

    with patch("burn_subs.ffmpeg._run", side_effect=fake_run):
        get_subtitle_codec(ffprobe_bin="ffprobe", input_file="test.mkv", stream_index=2)

    for cmd in calls:
        sel_idx = cmd.index("-select_streams")
        specifier = cmd[sel_idx + 1]
        assert specifier == "s:2", f"Expected 's:2', got '{specifier}' (must not use '0:s:2')"


def test_get_subtitle_codec_returns_detected_value() -> None:
    with patch("burn_subs.ffmpeg._run", return_value=_make_run_result("ass")):
        assert get_subtitle_codec(ffprobe_bin="ffprobe", input_file="f.mkv", stream_index=0) == "ass"


def test_get_subtitle_codec_falls_back_to_unknown() -> None:
    with patch("burn_subs.ffmpeg._run", return_value=_make_run_result("")):
        assert get_subtitle_codec(ffprobe_bin="ffprobe", input_file="f.mkv", stream_index=0) == "unknown"


# --- probe_streams ---

_FFPROBE_JSON = """{
    "streams": [
        {"index": 0, "codec_type": "video"},
        {"index": 1, "codec_type": "audio", "tags": {"language": "jpn", "title": ""}},
        {"index": 2, "codec_type": "subtitle", "tags": {"language": "eng", "title": "English subs"}},
        {"index": 3, "codec_type": "attachment", "tags": {}}
    ]
}"""


def test_probe_streams_uses_show_streams_flag() -> None:
    """-show_streams must be used; the old -show_entries subsection syntax silenced subtitle streams."""
    captured: list[list[str]] = []

    def fake_run(args: list[str], **kwargs):
        captured.append(args)
        r = MagicMock(spec=subprocess.CompletedProcess)
        r.returncode = 0
        r.stdout = _FFPROBE_JSON
        return r

    with patch("burn_subs.ffmpeg._run", side_effect=fake_run):
        probe_streams(ffprobe_bin="ffprobe", input_file="test.mkv")

    assert captured, "ffprobe was not called"
    cmd = captured[0]
    assert "-show_streams" in cmd, "-show_streams flag must be present"
    assert not any("show_entries" in arg for arg in cmd), "-show_entries must not be used"


def test_probe_streams_parses_subtitle_stream() -> None:
    def fake_run(args, **kwargs):
        r = MagicMock(spec=subprocess.CompletedProcess)
        r.returncode = 0
        r.stdout = _FFPROBE_JSON
        return r

    with patch("burn_subs.ffmpeg._run", side_effect=fake_run):
        streams = probe_streams(ffprobe_bin="ffprobe", input_file="test.mkv")

    subtitle_streams = [s for s in streams if s.codec_type == "subtitle"]
    assert len(subtitle_streams) == 1
    s = subtitle_streams[0]
    assert s.language == "eng"
    assert s.title == "English subs"



def test_probe_streams_returns_empty_on_ffprobe_error() -> None:
    def fake_run(args, **kwargs):
        r = MagicMock(spec=subprocess.CompletedProcess)
        r.returncode = 1
        r.stdout = ""
        return r

    with patch("burn_subs.ffmpeg._run", side_effect=fake_run):
        assert probe_streams(ffprobe_bin="ffprobe", input_file="test.mkv") == []

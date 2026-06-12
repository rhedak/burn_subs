from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, call

import pytest

from burn_subs.core import BurnOptions, ConvertResult, burn_subtitles, convert_files
from burn_subs.ffmpeg import FFmpegBinaries

FAKE_BINS = FFmpegBinaries(ffmpeg="ffmpeg", ffprobe="ffprobe")


@pytest.fixture()
def src(tmp_path: Path) -> str:
    f = tmp_path / "video.mkv"
    f.write_bytes(b"fake")
    return str(f)


@pytest.fixture()
def dst(tmp_path: Path) -> str:
    return str(tmp_path / "_out" / "video.mp4")


# ---------------------------------------------------------------------------
# No-op / skip paths
# ---------------------------------------------------------------------------

def test_noop_when_no_subs_and_no_height(tmp_path: Path) -> None:
    """.mp4 input with no work to do is a true no-op."""
    src = tmp_path / "video.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "_out" / "video.mp4"
    opts = BurnOptions(subtitle_stream_index=None, target_height=None)
    result = burn_subtitles(str(src), str(dst), options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "none"


def test_transcode_when_not_mp4_and_no_subs(src: str, dst: str) -> None:
    """.mkv input with no subs should transcode to MP4 (not no-op)."""
    opts = BurnOptions(subtitle_stream_index=None, target_height=None)
    with patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "transcode"
    cmd = mock_run.call_args[0][0]
    # Should map video and audio, no subtitles filter
    map_targets = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-map"]
    assert "0:v:0" in map_targets
    assert "-filter_complex" not in cmd
    assert "-vf" not in cmd


def test_skips_existing_output(tmp_path: Path, src: str) -> None:
    out = tmp_path / "video.mp4"
    out.write_bytes(b"existing")
    opts = BurnOptions(overwrite=False)
    result = burn_subtitles(src, str(out), options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "none"


def test_overwrite_flag_does_not_skip_existing(tmp_path: Path, src: str) -> None:
    out = tmp_path / "video.mp4"
    out.write_bytes(b"existing")
    opts = BurnOptions(overwrite=True)
    with patch("burn_subs.core.get_subtitle_codec", return_value="ass"), \
         patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg"):
        result = burn_subtitles(src, str(out), options=opts, binaries=FAKE_BINS)
    assert result.ok


# ---------------------------------------------------------------------------
# Scale-only path
# ---------------------------------------------------------------------------

def test_scale_only_no_subs(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=None, target_height=720)
    with patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "scale"
    cmd = mock_run.call_args[0][0]
    assert "scale=-2:720" in " ".join(cmd)


# ---------------------------------------------------------------------------
# Text subtitle paths
# ---------------------------------------------------------------------------

def test_text_subtitle_uses_vf(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=0)
    with patch("burn_subs.core.get_subtitle_codec", return_value="ass"), \
         patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "text"
    assert result.detected_codec == "ass"
    cmd = mock_run.call_args[0][0]
    assert "-vf" in cmd


def test_text_subtitle_with_scale(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=0, target_height=480)
    with patch("burn_subs.core.get_subtitle_codec", return_value="ass"), \
         patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    cmd = mock_run.call_args[0][0]
    vf = cmd[cmd.index("-vf") + 1]
    assert "subtitles=" in vf
    assert "scale=-2:480" in vf


def test_missing_libass_returns_error(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=0)
    with patch("burn_subs.core.get_subtitle_codec", return_value="ass"), \
         patch("burn_subs.core.check_subtitles_filter", return_value=False):
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert not result.ok
    assert result.error is not None
    assert "libass" in result.error


# ---------------------------------------------------------------------------
# PGS / overlay paths
# ---------------------------------------------------------------------------

def test_pgs_uses_overlay_filter(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=0)
    with patch("burn_subs.core.get_subtitle_codec", return_value="hdmv_pgs_subtitle"), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "overlay"
    assert result.detected_codec == "hdmv_pgs_subtitle"
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "overlay" in fc
    assert "-map" in cmd
    assert "[v]" in cmd


def test_pgs_with_scale_chains_in_filter_complex(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=0, target_height=720)
    with patch("burn_subs.core.get_subtitle_codec", return_value="hdmv_pgs_subtitle"), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "overlay" in fc
    assert "scale=-2:720" in fc


def test_pgs_with_scale_does_not_produce_double_video_map(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=0, target_height=720)
    with patch("burn_subs.core.get_subtitle_codec", return_value="hdmv_pgs_subtitle"), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    cmd = mock_run.call_args[0][0]
    # -map 0:v:0 must not appear as a standalone mapping alongside -map [v]
    map_targets = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-map"]
    assert "0:v:0" not in map_targets


# ---------------------------------------------------------------------------
# Unknown codec fallback
# ---------------------------------------------------------------------------

def test_unknown_codec_tries_text_first(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=0)
    with patch("burn_subs.core.get_subtitle_codec", return_value="unknown"), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "text"
    cmd = mock_run.call_args[0][0]
    assert "-vf" in cmd


def test_unknown_codec_falls_back_to_overlay(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=0)
    error = subprocess.CalledProcessError(1, [], output="text filter failed")
    with patch("burn_subs.core.get_subtitle_codec", return_value="unknown"), \
         patch("burn_subs.core._run_ffmpeg", side_effect=[error, None]) as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "overlay"
    assert mock_run.call_count == 2
    overlay_cmd = mock_run.call_args_list[1][0][0]
    assert "-filter_complex" in overlay_cmd


# ---------------------------------------------------------------------------
# External subtitle file paths
# ---------------------------------------------------------------------------

def test_external_text_subtitle_uses_vf(tmp_path: Path, src: str, dst: str) -> None:
    """External .srt file should use -vf with subtitles= filter."""
    sub_file = tmp_path / "sub.srt"
    sub_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    opts = BurnOptions(
        subtitle_stream_index=None,
        external_subtitle_file=str(sub_file),
    )
    with patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "text"
    cmd = mock_run.call_args[0][0]
    vf = cmd[cmd.index("-vf") + 1]
    assert "subtitles=" in vf


def test_external_pgs_subtitle_uses_overlay_with_second_input(tmp_path: Path, src: str, dst: str) -> None:
    """External .sup file should use -filter_complex overlay with a second -i."""
    sub_file = tmp_path / "sub.sup"
    sub_file.write_bytes(b"fake pgs")
    opts = BurnOptions(
        subtitle_stream_index=None,
        external_subtitle_file=str(sub_file),
    )
    with patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "overlay"
    cmd = mock_run.call_args[0][0]
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "overlay" in fc
    assert "[1:s:0]" in fc


def test_external_subtitle_with_scale(tmp_path: Path, src: str, dst: str) -> None:
    """External sub + target_height chains scale into the filter."""
    sub_file = tmp_path / "sub.srt"
    sub_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    opts = BurnOptions(
        subtitle_stream_index=None,
        external_subtitle_file=str(sub_file),
        target_height=480,
    )
    with patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    cmd = mock_run.call_args[0][0]
    vf = cmd[cmd.index("-vf") + 1]
    assert "subtitles=" in vf
    assert "scale=-2:480" in vf


def test_external_subtitle_not_found_returns_error(src: str, dst: str) -> None:
    """Non-existent external sub file should give error."""
    opts = BurnOptions(
        subtitle_stream_index=None,
        external_subtitle_file="/nonexistent/sub.srt",
    )
    result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert not result.ok
    assert "not found" in (result.error or "").lower()


def test_external_subtitle_missing_libass_returns_error(tmp_path: Path, src: str, dst: str) -> None:
    """External text sub with no libass should error."""
    sub_file = tmp_path / "sub.srt"
    sub_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    opts = BurnOptions(
        subtitle_stream_index=None,
        external_subtitle_file=str(sub_file),
    )
    with patch("burn_subs.core.check_subtitles_filter", return_value=False):
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert not result.ok
    assert "libass" in (result.error or "")


def test_external_subtitle_unknown_extension_falls_back_to_overlay(tmp_path: Path, src: str, dst: str) -> None:
    """Unknown external sub extension should try text, then fallback to overlay."""
    sub_file = tmp_path / "sub.xyz"
    sub_file.write_bytes(b"data")
    opts = BurnOptions(
        subtitle_stream_index=None,
        external_subtitle_file=str(sub_file),
    )
    error = subprocess.CalledProcessError(1, [], output="filter failed")
    with patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg", side_effect=[error, None]) as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method == "overlay"
    assert mock_run.call_count == 2
    overlay_cmd = mock_run.call_args_list[1][0][0]
    assert "-filter_complex" in overlay_cmd


def test_external_subtitle_prevents_noop(src: str, dst: str, tmp_path: Path) -> None:
    """Setting external_subtitle_file should prevent the no-op early return."""
    sub_file = tmp_path / "sub.srt"
    sub_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    opts = BurnOptions(
        subtitle_stream_index=None,
        target_height=None,
        external_subtitle_file=str(sub_file),
    )
    with patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert result.ok
    assert result.method != "none"
    assert mock_run.called


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_ffmpeg_failure_returns_error_result(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=0)
    err = subprocess.CalledProcessError(1, [], output="fatal: codec not found")
    with patch("burn_subs.core.get_subtitle_codec", return_value="ass"), \
         patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg", side_effect=err):
        result = burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS)
    assert not result.ok
    assert result.error is not None
    assert "fatal: codec not found" in result.error


def test_log_callback_receives_output(src: str, dst: str) -> None:
    opts = BurnOptions(subtitle_stream_index=0)
    log: list[str] = []
    with patch("burn_subs.core.get_subtitle_codec", return_value="ass"), \
         patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg"):
        burn_subtitles(src, dst, options=opts, binaries=FAKE_BINS, log_callback=log.append)
    assert any("Processing" in line for line in log)


# ---------------------------------------------------------------------------
# convert_files batch wrapper
# ---------------------------------------------------------------------------

def test_convert_files_output_paths(tmp_path: Path) -> None:
    f1 = tmp_path / "a.mkv"
    f2 = tmp_path / "b.mkv"
    f1.write_bytes(b"x")
    f2.write_bytes(b"y")
    out_dir = str(tmp_path / "_out")

    with patch("burn_subs.core.get_subtitle_codec", return_value="ass"), \
         patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg"):
        results = convert_files([str(f1), str(f2)], output_dir=out_dir, binaries=FAKE_BINS)

    assert len(results) == 2
    assert all(r.ok for r in results)
    assert results[0].output_file == str(Path(out_dir) / "a.mp4")
    assert results[1].output_file == str(Path(out_dir) / "b.mp4")


def test_convert_files_collects_failures(tmp_path: Path) -> None:
    f = tmp_path / "a.mkv"
    f.write_bytes(b"x")
    err = subprocess.CalledProcessError(1, [], output="boom")

    with patch("burn_subs.core.get_subtitle_codec", return_value="ass"), \
         patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg", side_effect=err):
        results = convert_files([str(f)], output_dir=str(tmp_path / "_out"), binaries=FAKE_BINS)

    assert len(results) == 1
    assert not results[0].ok


def test_convert_files_external_subs_passed_through(tmp_path: Path) -> None:
    """convert_files should apply per-file external subs via external_subs dict."""
    f1 = tmp_path / "a.mkv"
    f1.write_bytes(b"x")
    sub1 = tmp_path / "a.srt"
    sub1.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")

    with patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        results = convert_files(
            [str(f1)],
            output_dir=str(tmp_path / "_out"),
            binaries=FAKE_BINS,
            external_subs={str(f1): str(sub1)},
        )
    assert len(results) == 1
    assert results[0].ok
    assert results[0].method == "text"
    cmd = mock_run.call_args[0][0]
    assert "-vf" in cmd


def test_convert_files_external_subs_none_falls_back_to_embedded(tmp_path: Path) -> None:
    """When external_subs maps a file to None, fall back to embedded subtitle."""
    f = tmp_path / "a.mkv"
    f.write_bytes(b"x")

    with patch("burn_subs.core.get_subtitle_codec", return_value="ass"), \
         patch("burn_subs.core.check_subtitles_filter", return_value=True), \
         patch("burn_subs.core._run_ffmpeg") as mock_run:
        results = convert_files(
            [str(f)],
            output_dir=str(tmp_path / "_out"),
            binaries=FAKE_BINS,
            external_subs={str(f): None},
        )
    assert len(results) == 1
    assert results[0].ok
    assert results[0].method == "text"
    cmd = mock_run.call_args[0][0]
    assert "-vf" in cmd

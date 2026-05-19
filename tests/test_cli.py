from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from burn_subs.cli import build_parser, main
from burn_subs.core import BurnOptions, ConvertResult


def _ok(input_file: str = "a.mkv", output_file: str = "_out/a.mp4") -> ConvertResult:
    return ConvertResult(input_file=input_file, output_file=output_file, ok=True, method="text")


def _fail(input_file: str = "a.mkv", output_file: str = "_out/a.mp4") -> ConvertResult:
    return ConvertResult(input_file=input_file, output_file=output_file, ok=False, error="oops")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_parser_defaults() -> None:
    args = build_parser().parse_args(["input.mkv"])
    assert args.output_dir == "_out"
    assert args.audio_index == 0
    assert args.subtitle_index == 0
    assert not args.no_subs
    assert not args.overwrite
    assert args.height is None


def test_parser_height_flag() -> None:
    args = build_parser().parse_args(["input.mkv", "--height", "720"])
    assert args.height == 720


def test_parser_no_subs_flag() -> None:
    args = build_parser().parse_args(["input.mkv", "--no-subs"])
    assert args.no_subs


# ---------------------------------------------------------------------------
# main() exit codes
# ---------------------------------------------------------------------------

def test_main_returns_2_when_no_files_found() -> None:
    with patch("burn_subs.cli._expand_inputs", return_value=[]):
        rc = main(["*.mkv"])
    assert rc == 2


def test_main_returns_0_on_all_success(tmp_path: Path) -> None:
    f = tmp_path / "video.mkv"
    f.write_bytes(b"x")
    with patch("burn_subs.cli.convert_files", return_value=[_ok(str(f))]):
        rc = main([str(f), "-o", str(tmp_path / "_out")])
    assert rc == 0


def test_main_returns_1_on_any_failure(tmp_path: Path) -> None:
    f = tmp_path / "video.mkv"
    f.write_bytes(b"x")
    with patch("burn_subs.cli.convert_files", return_value=[_fail(str(f))]):
        rc = main([str(f), "-o", str(tmp_path / "_out")])
    assert rc == 1


# ---------------------------------------------------------------------------
# Option wiring
# ---------------------------------------------------------------------------

def test_no_subs_sets_subtitle_index_none(tmp_path: Path) -> None:
    f = tmp_path / "video.mkv"
    f.write_bytes(b"x")
    captured: list[BurnOptions] = []

    def fake_convert(files, *, output_dir, options, binaries=None, log_callback=None):
        captured.append(options)
        return [_ok(str(f))]

    with patch("burn_subs.cli.convert_files", side_effect=fake_convert):
        main([str(f), "--no-subs"])

    assert captured[0].subtitle_stream_index is None


def test_height_flag_wired_to_target_height(tmp_path: Path) -> None:
    f = tmp_path / "video.mkv"
    f.write_bytes(b"x")
    captured: list[BurnOptions] = []

    def fake_convert(files, *, output_dir, options, binaries=None, log_callback=None):
        captured.append(options)
        return [_ok(str(f))]

    with patch("burn_subs.cli.convert_files", side_effect=fake_convert):
        main([str(f), "--height", "360"])

    assert captured[0].target_height == 360


def test_audio_and_subtitle_index_wired(tmp_path: Path) -> None:
    f = tmp_path / "video.mkv"
    f.write_bytes(b"x")
    captured: list[BurnOptions] = []

    def fake_convert(files, *, output_dir, options, binaries=None, log_callback=None):
        captured.append(options)
        return [_ok(str(f))]

    with patch("burn_subs.cli.convert_files", side_effect=fake_convert):
        main([str(f), "--audio-index", "2", "--subtitle-index", "1"])

    assert captured[0].audio_index == 2
    assert captured[0].subtitle_stream_index == 1

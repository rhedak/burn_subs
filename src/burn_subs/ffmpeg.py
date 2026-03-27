from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


class FFmpegNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True)
class FFmpegBinaries:
    ffmpeg: str
    ffprobe: str


def resolve_binaries(
    ffmpeg: Optional[str] = None,
    ffprobe: Optional[str] = None,
) -> FFmpegBinaries:
    """
    Resolve ffmpeg/ffprobe paths.
    Defaults to resolving from PATH.
    """
    ffmpeg_path = ffmpeg or shutil.which("ffmpeg")
    ffprobe_path = ffprobe or shutil.which("ffprobe")

    if not ffmpeg_path:
        raise FFmpegNotFoundError("ffmpeg not found on PATH")
    if not ffprobe_path:
        raise FFmpegNotFoundError("ffprobe not found on PATH")

    return FFmpegBinaries(ffmpeg=os.fspath(ffmpeg_path), ffprobe=os.fspath(ffprobe_path))


def _run(
    args: list[str],
    *,
    timeout_s: Optional[float] = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=check,
    )


def get_subtitle_codec(
    *,
    ffprobe_bin: str,
    input_file: str,
    stream_index: int,
    timeout_s: float = 15.0,
) -> str:
    """Robust codec detection for PGS + text subtitles."""
    try:
        cmd1 = [
            ffprobe_bin,
            "-v",
            "quiet",
            "-probesize",
            "100M",
            "-analyzeduration",
            "200M",
            "-select_streams",
            f"0:s:{stream_index}",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            input_file,
        ]
        result1 = _run(cmd1, timeout_s=timeout_s, check=False)
        codec = (result1.stdout or "").strip()
        if codec:
            return codec

        cmd2 = [
            ffprobe_bin,
            "-v",
            "quiet",
            "-probesize",
            "100M",
            "-analyzeduration",
            "200M",
            "-select_streams",
            f"0:s:{stream_index}",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            input_file,
        ]
        result2 = _run(cmd2, timeout_s=timeout_s, check=False)
        return ((result2.stdout or "").strip()) or "unknown"
    except Exception:
        return "unknown"


def build_subtitles_filter(input_path: str, stream_index: int) -> str:
    """
    Build an ffmpeg subtitles filter string.
    Uses explicit option names for ffmpeg filter parser reliability.
    """
    safe = input_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return f"subtitles=filename='{safe}':stream_index={stream_index}"


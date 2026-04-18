from __future__ import annotations

import os
import shutil
import subprocess
import json
from dataclasses import dataclass
from typing import Optional


class FFmpegNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True)
class FFmpegBinaries:
    ffmpeg: str
    ffprobe: str


@dataclass(frozen=True)
class StreamInfo:
    index: int
    codec_type: str
    language: str
    title: str


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
            f"s:{stream_index}",
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
            f"s:{stream_index}",
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


def probe_streams(*, ffprobe_bin: str, input_file: str, timeout_s: float = 30.0) -> list[StreamInfo]:
    """
    Probe stream metadata for UI dropdown population.
    Increased probing for reliable subtitle detection in MKV files.
    """
    cmd = [
        ffprobe_bin,
        "-v", "quiet",
        "-probesize", "2000M",           # Much larger
        "-analyzeduration", "2000M",     # Much larger
        "-print_format", "json",
        "-show_entries", "stream=index,codec_type:stream_tags=language,title",
        input_file,
    ]
    try:
        result = _run(cmd, timeout_s=timeout_s, check=False)
        if result.returncode != 0:
            print(f"ffprobe returned error code {result.returncode}")
            return []

        payload = json.loads(result.stdout or "{}")
        raw_streams = payload.get("streams", [])
        out: list[StreamInfo] = []

        for s in raw_streams:
            tags = s.get("tags", {}) or {}
            try:
                idx = int(s.get("index", -1))
                if idx < 0:
                    continue
                ctype = str(s.get("codec_type", "unknown"))
                lang = str(tags.get("language", "unknown")).strip() or "unknown"
                title = str(tags.get("title", "")).strip()
                out.append(StreamInfo(index=idx, codec_type=ctype, language=lang, title=title))
            except Exception:
                continue

        return out
    except Exception as e:
        print(f"Probe error: {e}")
        return []


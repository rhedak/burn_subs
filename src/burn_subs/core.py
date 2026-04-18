from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Callable

from .ffmpeg import FFmpegBinaries, build_subtitles_filter, get_subtitle_codec, resolve_binaries


@dataclass(frozen=True)
class BurnOptions:
    subtitle_stream_index: Optional[int] = 0
    audio_index: int = 0
    overwrite: bool = False
    video_codec: str = "mpeg4"
    video_quality: str = "3"
    audio_codec: str = "aac"
    audio_bitrate: str = "160k"


@dataclass(frozen=True)
class ConvertResult:
    input_file: str
    output_file: str
    ok: bool
    method: Optional[str] = None
    detected_codec: Optional[str] = None
    error: Optional[str] = None


def _run_ffmpeg(command: list[str], log_callback: Optional[Callable[[str], None]] = None) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    if log_callback and process.stdout:
        for line in process.stdout:
            log_callback(line)

    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)


def burn_subtitles(
    input_file: str,
    output_file: str,
    *,
    options: BurnOptions = BurnOptions(),
    binaries: Optional[FFmpegBinaries] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> ConvertResult:
    """
    Burn subtitles into video and transcode to MP4.
    """
    if log_callback:
        log_callback(f"Processing: {input_file}\n")
        log_callback(f"Output: {output_file}\n")

    if options.subtitle_stream_index is None:
        if log_callback:
            log_callback("No subtitles selected → no-op\n")
        return ConvertResult(
            input_file=input_file,
            output_file=output_file,
            ok=True,
            method="none",
        )

    bins = binaries or resolve_binaries()

    in_path = Path(input_file)
    out_path = Path(output_file)

    if out_path.exists() and not options.overwrite:
        if log_callback:
            log_callback("Output file already exists → skipping\n")
        return ConvertResult(
            input_file=input_file,
            output_file=output_file,
            ok=True,
            method="none",
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    base_dir = in_path.parent if str(in_path.parent) else Path(".")
    suffix = in_path.suffix
    clean_input: Optional[Path] = None

    try:
        with tempfile.NamedTemporaryFile(dir=base_dir, suffix=suffix, delete=False) as tmp:
            clean_input = Path(tmp.name)
        clean_input.write_bytes(in_path.read_bytes())

        if log_callback:
            log_callback("Created temporary clean input file\n")

        codec = get_subtitle_codec(
            ffprobe_bin=bins.ffprobe,
            input_file=os.fspath(clean_input),
            stream_index=int(options.subtitle_stream_index),
        )
        codec_lower = codec.lower()
        is_pgs = ("pgs" in codec_lower) or (codec_lower == "hdmv_pgs_subtitle")

        if log_callback:
            log_callback(f"Detected subtitle codec: {codec} {'(PGS)' if is_pgs else '(text)'}\n")

        # ==================== FIXED BASE COMMAND ====================
        # We now map BOTH video and audio here, then override video mapping when using filters
        base_command = [
            bins.ffmpeg,
            "-y" if options.overwrite else "-n",
            "-probesize", "100M",
            "-analyzeduration", "200M",
            "-i", os.fspath(clean_input),
            "-map", "0:v:0",                                   # Map video (will be overridden for filters)
            "-map", f"0:a:{options.audio_index}",              # Map selected audio
        ]

        encode_args = [
            "-c:v", options.video_codec,
            "-q:v", options.video_quality,
            "-c:a", options.audio_codec,
            "-b:a", options.audio_bitrate,
            "-movflags", "+faststart",
            os.fspath(out_path),
        ]

        def run_with(extra_args: list[str], method_name: str) -> None:
            full_command = base_command + extra_args + encode_args
            if log_callback:
                log_callback(f"\n--- Running ffmpeg ({method_name}) ---\n")
                log_callback("$ " + " ".join(full_command) + "\n\n")
            _run_ffmpeg(full_command, log_callback=log_callback)

        # ==================== PGS SUBTITLES ====================
        if is_pgs:
            run_with(
                [
                    "-filter_complex", f"[0:v:0][0:s:{options.subtitle_stream_index}]overlay[v]",
                    "-map", "[v]",                                 # Use the filtered video instead
                ],
                method_name="overlay (PGS)"
            )
            if log_callback:
                log_callback("Successfully burned PGS subtitles using overlay filter.\n")
            return ConvertResult(
                input_file=input_file,
                output_file=output_file,
                ok=True,
                method="overlay",
                detected_codec=codec
            )

        # ==================== TEXT SUBTITLES ====================
        if codec != "unknown":
            vf = build_subtitles_filter(os.fspath(clean_input), int(options.subtitle_stream_index))
            run_with(["-vf", vf], method_name="text subtitles filter")
            if log_callback:
                log_callback("Successfully burned text subtitles.\n")
            return ConvertResult(
                input_file=input_file,
                output_file=output_file,
                ok=True,
                method="text",
                detected_codec=codec
            )

        # Unknown codec fallback
        if log_callback:
            log_callback("Unknown subtitle codec. Trying text filter first...\n")

        vf = build_subtitles_filter(os.fspath(clean_input), int(options.subtitle_stream_index))
        try:
            run_with(["-vf", vf], method_name="text subtitles filter (fallback)")
            if log_callback:
                log_callback("Successfully burned using text filter.\n")
            return ConvertResult(
                input_file=input_file,
                output_file=output_file,
                ok=True,
                method="text",
                detected_codec=codec
            )
        except subprocess.CalledProcessError:
            if log_callback:
                log_callback("Text filter failed → falling back to overlay...\n")
            run_with(
                [
                    "-filter_complex", f"[0:v:0][0:s:{options.subtitle_stream_index}]overlay[v]",
                    "-map", "[v]",
                ],
                method_name="overlay (fallback)"
            )
            if log_callback:
                log_callback("Successfully burned using overlay filter (fallback).\n")
            return ConvertResult(
                input_file=input_file,
                output_file=output_file,
                ok=True,
                method="overlay",
                detected_codec=codec
            )

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or str(e)
        if log_callback:
            log_callback(f"\nERROR: ffmpeg failed!\n{error_msg}\n")
        return ConvertResult(input_file=input_file, output_file=output_file, ok=False, error=error_msg)
    except Exception as e:
        if log_callback:
            log_callback(f"\nUnexpected error: {e}\n")
        return ConvertResult(input_file=input_file, output_file=output_file, ok=False, error=str(e))
    finally:
        if clean_input and clean_input.exists():
            try:
                clean_input.unlink()
                if log_callback:
                    log_callback("Cleaned up temporary file.\n")
            except Exception:
                pass


def convert_files(
    files: Iterable[str],
    *,
    output_dir: str = "_out",
    options: BurnOptions = BurnOptions(),
    binaries: Optional[FFmpegBinaries] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> list[ConvertResult]:
    out_dir = Path(output_dir)
    results: list[ConvertResult] = []
    for f in files:
        in_path = Path(f)
        out_file = out_dir / (in_path.stem + ".mp4")
        results.append(
            burn_subtitles(
                os.fspath(in_path),
                os.fspath(out_file),
                options=options,
                binaries=binaries,
                log_callback=log_callback,
            )
        )
    return results
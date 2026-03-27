from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .ffmpeg import FFmpegBinaries, build_subtitles_filter, get_subtitle_codec, resolve_binaries


@dataclass(frozen=True)
class BurnOptions:
    subtitle_stream_index: Optional[int] = 0
    audio_index: int = 0
    overwrite: bool = False
    video_codec: str = "mpeg4"
    video_quality: str = "3"  # ffmpeg -q:v value
    audio_codec: str = "aac"
    audio_bitrate: str = "160k"


@dataclass(frozen=True)
class ConvertResult:
    input_file: str
    output_file: str
    ok: bool
    method: Optional[str] = None  # "text", "overlay", "none"
    detected_codec: Optional[str] = None
    error: Optional[str] = None


def _run_ffmpeg(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def burn_subtitles(
    input_file: str,
    output_file: str,
    *,
    options: BurnOptions = BurnOptions(),
    binaries: Optional[FFmpegBinaries] = None,
    log_fallback_errors: bool = True,
) -> ConvertResult:
    """
    Burn subtitles into video and transcode to MP4.

    - If subtitle_stream_index is None, no conversion is performed (treated as a no-op).
    - Subtitle method selection:
      - PGS/bitmap: overlay
      - Text: subtitles filter
      - Unknown: try text first, then fall back to overlay
    """
    if options.subtitle_stream_index is None:
        return ConvertResult(
            input_file=input_file,
            output_file=output_file,
            ok=True,
            method="none",
            detected_codec=None,
        )

    bins = binaries or resolve_binaries()

    in_path = Path(input_file)
    out_path = Path(output_file)

    if out_path.exists() and not options.overwrite:
        return ConvertResult(
            input_file=input_file,
            output_file=output_file,
            ok=True,
            method="none",
            detected_codec=None,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Create a clean temp copy of the input filename (avoids escaping issues in the subtitles filter).
    base_dir = in_path.parent if str(in_path.parent) else Path(".")
    suffix = in_path.suffix
    clean_input: Optional[Path] = None

    try:
        with tempfile.NamedTemporaryFile(dir=base_dir, suffix=suffix, delete=False) as tmp:
            clean_input = Path(tmp.name)

        # Copy rather than rename: safer and avoids altering the user's originals.
        clean_input.write_bytes(in_path.read_bytes())

        codec = get_subtitle_codec(
            ffprobe_bin=bins.ffprobe,
            input_file=os.fspath(clean_input),
            stream_index=int(options.subtitle_stream_index),
        )
        codec_lower = codec.lower()
        is_pgs = ("pgs" in codec_lower) or (codec_lower == "hdmv_pgs_subtitle")

        base_command = [
            bins.ffmpeg,
            "-y" if options.overwrite else "-n",
            "-probesize",
            "100M",
            "-analyzeduration",
            "200M",
            "-i",
            os.fspath(clean_input),
            "-map",
            "0:v:0",
            "-map",
            f"0:a:{options.audio_index}",
        ]

        encode_args = [
            "-c:v",
            options.video_codec,
            "-q:v",
            options.video_quality,
            "-c:a",
            options.audio_codec,
            "-b:a",
            options.audio_bitrate,
            "-movflags",
            "+faststart",
            os.fspath(out_path),
        ]

        def run_with(extra_args: list[str]) -> None:
            _run_ffmpeg(base_command + extra_args + encode_args)

        if is_pgs:
            run_with(
                [
                    "-filter_complex",
                    f"[0:v:0][0:s:{options.subtitle_stream_index}]overlay[v]",
                    "-map",
                    "[v]",
                ]
            )
            return ConvertResult(
                input_file=input_file,
                output_file=output_file,
                ok=True,
                method="overlay",
                detected_codec=codec,
            )

        if codec != "unknown":
            vf = build_subtitles_filter(os.fspath(clean_input), int(options.subtitle_stream_index))
            run_with(["-vf", vf])
            return ConvertResult(
                input_file=input_file,
                output_file=output_file,
                ok=True,
                method="text",
                detected_codec=codec,
            )

        # Unknown: try text first, then fall back to overlay.
        vf = build_subtitles_filter(os.fspath(clean_input), int(options.subtitle_stream_index))
        try:
            run_with(["-vf", vf])
            return ConvertResult(
                input_file=input_file,
                output_file=output_file,
                ok=True,
                method="text",
                detected_codec=codec,
            )
        except subprocess.CalledProcessError as text_err:
            if log_fallback_errors:
                try:
                    log_file = base_dir / "subtitle_fallback_errors.log"
                    text_stderr = (text_err.stderr or "").strip() or "(no stderr)"
                    with log_file.open("a", encoding="utf-8") as fh:
                        fh.write("\n" + "=" * 80 + "\n")
                        fh.write(f"input={input_file}\n")
                        fh.write(f"output={output_file}\n")
                        fh.write(f"subtitle_stream_index={options.subtitle_stream_index}\n")
                        fh.write(f"audio_index={options.audio_index}\n")
                        fh.write(f"detected_codec={codec}\n")
                        fh.write("first_attempt=text_subtitles_filter\n")
                        fh.write("stderr:\n")
                        fh.write(text_stderr + "\n")
                except Exception:
                    pass

            run_with(
                [
                    "-filter_complex",
                    f"[0:v:0][0:s:{options.subtitle_stream_index}]overlay[v]",
                    "-map",
                    "[v]",
                ]
            )
            return ConvertResult(
                input_file=input_file,
                output_file=output_file,
                ok=True,
                method="overlay",
                detected_codec=codec,
            )

    except subprocess.CalledProcessError as e:
        return ConvertResult(
            input_file=input_file,
            output_file=output_file,
            ok=False,
            method=None,
            detected_codec=None,
            error=(e.stderr or str(e)),
        )
    except Exception as e:
        return ConvertResult(
            input_file=input_file,
            output_file=output_file,
            ok=False,
            method=None,
            detected_codec=None,
            error=str(e),
        )
    finally:
        if clean_input and clean_input.exists():
            try:
                clean_input.unlink()
            except Exception:
                pass


def convert_files(
    files: Iterable[str],
    *,
    output_dir: str = "_out",
    options: BurnOptions = BurnOptions(),
    binaries: Optional[FFmpegBinaries] = None,
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
            )
        )
    return results


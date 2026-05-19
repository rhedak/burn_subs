from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

from .core import BurnOptions, convert_files


def _expand_inputs(inputs: list[str]) -> list[str]:
    files: list[str] = []
    for item in inputs:
        matches = glob.glob(item)
        if matches:
            files.extend(matches)
        else:
            files.append(item)
    # keep order but remove duplicates
    seen: set[str] = set()
    out: list[str] = []
    for f in files:
        p = os.fspath(Path(f))
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="burn-subs", description="Burn subtitle streams into video using ffmpeg.")
    p.add_argument("inputs", nargs="+", help="Input files and/or glob patterns (e.g. *.mkv)")
    p.add_argument("-o", "--output-dir", default="_out", help="Output directory (default: %(default)s)")
    p.add_argument("--audio-index", type=int, default=0, help="Audio stream index (default: %(default)s)")
    p.add_argument("--subtitle-index", type=int, default=0, help="Subtitle stream index (default: %(default)s)")
    p.add_argument("--no-subs", action="store_true", help="Do not burn subtitles (no-op conversion)")
    p.add_argument("--overwrite", action="store_true", help="Overwrite output files if they exist")
    p.add_argument("--height", type=int, default=None, metavar="PX",
                   help="Scale output to this height in pixels (e.g. 720 for 720p). Width is set automatically to preserve aspect ratio. Default: keep original resolution.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    files = _expand_inputs(args.inputs)
    if not files:
        print("No input files found.", file=sys.stderr)
        return 2

    options = BurnOptions(
        subtitle_stream_index=None if args.no_subs else args.subtitle_index,
        audio_index=args.audio_index,
        overwrite=args.overwrite,
        target_height=args.height,
    )

    results = convert_files(files, output_dir=args.output_dir, options=options)
    ok = sum(1 for r in results if r.ok)
    fail = len(results) - ok

    for r in results:
        status = "OK" if r.ok else "FAIL"
        extra = ""
        if r.ok and r.method:
            extra = f" ({r.method})"
        if not r.ok and r.error:
            extra = f" ({r.error.strip().splitlines()[-1]})"
        print(f"{status}: {r.input_file} -> {r.output_file}{extra}")

    if fail:
        print(f"\nDone with failures. ok={ok} fail={fail}", file=sys.stderr)
        return 1
    print(f"\nDone. ok={ok} fail={fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


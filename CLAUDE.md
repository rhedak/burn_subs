# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Create venv and install locally (editable)
uv venv && uv pip install -e .

# Run all tests
uv run pytest

# Run a single test
pytest tests/test_ffmpeg_helpers.py::test_build_subtitles_filter_escapes_basic_chars

# Run CLI
burn-subs input.mkv -o _out
burn-subs "*.mkv" -o _out --audio-index 0 --subtitle-index 0

# Run GUI
burn-subs-gui
```

No linter is configured. No build step is required for development.

## Requirements

- `ffmpeg` and `ffprobe` on `PATH`, compiled with libass (required for the `subtitles` filter). On macOS: `brew install ffmpeg-full` (the standard `ffmpeg` bottle omits libass).

## Architecture

The package lives in `src/burn_subs/` with four modules:

- **`ffmpeg.py`** — low-level ffmpeg/ffprobe wrappers: `resolve_binaries`, `probe_streams`, `get_subtitle_codec`, `build_subtitles_filter`. No business logic, just subprocess calls and data types (`FFmpegBinaries`, `StreamInfo`).
- **`core.py`** — main processing logic. `burn_subtitles()` drives the conversion: copies the input to a temp file (to avoid path/special-char issues with ffmpeg's subtitle filter), probes the subtitle codec, then applies either an overlay filter (PGS/bitmap) or a `subtitles=` video filter (text). Falls back from text to overlay for unknown codecs. `convert_files()` is the batch wrapper used by both CLI and GUI.
- **`cli.py`** — `argparse`-based entry point. Expands glob patterns, builds `BurnOptions`, calls `convert_files`.
- **`gui.py`** — Tkinter GUI (`burn-subs-gui`). Lets users pick files, select audio/subtitle streams via dropdowns (populated via `probe_streams`), and run batch conversion with a live log view.

### Key design points

- `BurnOptions` (frozen dataclass in `core.py`) is the single config object passed through all layers — add new encoding options there.
- The temp-file copy in `burn_subtitles` is intentional: ffmpeg's `subtitles=` filter has issues with paths containing colons or special characters, so the file is copied to a temp name in the same directory before processing.
- Output is always MP4 (`mpeg4` video + `aac` audio). Changing the container requires updating both `core.py` encode args and the `.mp4` stem logic in `convert_files`.
- `log_callback: Callable[[str], None]` threads through `core.py` → `_run_ffmpeg` so both CLI (stdout print) and GUI (text widget append) can display live ffmpeg output.

# burn-subs

Burn subtitle streams into a video using `ffmpeg`.

Includes:
- **CLI**: `burn-subs`
- **Desktop GUI (Tkinter)**: `burn-subs-gui` (batch-convert multiple files)

## Requirements

- Python **3.10+**
- `ffmpeg` and `ffprobe` available on your `PATH`, compiled with **libass** (required for burning text/ASS subtitles)
  - macOS (Homebrew): `brew install ffmpeg-full` *(the standard `ffmpeg` bottle omits libass)*

## Install (local)

```bash
uv venv  # first time only
source .venv/bin/activate
uv pip install -e .
```

## CLI usage

Convert one file:

```bash
burn-subs input.mkv -o _out
```

Convert many files (glob):

```bash
burn-subs "*.mkv" -o _out --audio-index 0 --subtitle-index 0
```

Overwrite outputs:

```bash
burn-subs "*.mkv" -o _out --overwrite
```

## GUI usage

```bash
burn-subs-gui
```

Then use **Add files…** to select multiple inputs, pick an output directory, and run the batch.

## Notes

- Output is currently MP4 with video transcoded to `mpeg4` and audio to `aac`.
- Subtitle strategy:
  - **PGS/bitmap** subtitles: overlay
  - **Text** subtitles: `subtitles` filter
  - **Unknown** codec: try text first, then fall back to overlay (and log details to `subtitle_fallback_errors.log` in the input directory).

## Future PyPI deployment (plan)

When you’re ready to publish:

1. Build distributions:

```bash
python -m pip install -U build twine
python -m build
```

2. Upload to TestPyPI first:

```bash
python -m twine upload --repository testpypi dist/*
```

3. Verify install from TestPyPI in a clean venv.

4. Upload to PyPI:

```bash
python -m twine upload dist/*
```

For automation later, add a GitHub Actions workflow that runs tests/builds on tag and uploads using PyPI trusted publishing.

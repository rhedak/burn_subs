"""burn-subs: burn subtitle streams into video using ffmpeg."""

from .core import BurnOptions, ConvertResult, convert_files, burn_subtitles

__all__ = [
    "BurnOptions",
    "ConvertResult",
    "convert_files",
    "burn_subtitles",
]


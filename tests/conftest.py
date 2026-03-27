import sys
from pathlib import Path


def pytest_configure() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    sys.path.insert(0, str(src))


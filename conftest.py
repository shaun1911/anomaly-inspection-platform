"""Make ``aip`` importable from a fresh clone without installing."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "aip" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

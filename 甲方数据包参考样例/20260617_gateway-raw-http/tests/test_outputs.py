"""Harbor verifier entry — delegates to workspace acceptance suite."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SOURCE_DIR = Path(os.environ.get("SOURCE_DIR", "/app/source"))
ACCEPTANCE = SOURCE_DIR / "tests" / "acceptance"

if __name__ == "__main__":
    env = {**os.environ, "PYTHONPATH": f"{SOURCE_DIR}:{os.environ.get('PYTHONPATH', '')}"}
    raise SystemExit(
        subprocess.call(
            [sys.executable, "-m", "pytest", str(ACCEPTANCE), "-q"],
            env=env,
        )
    )

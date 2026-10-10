"""Start the dashboard without typing the Streamlit command.

Usage:  python run_streamlit.py

Any extra arguments are passed straight to Streamlit, for example:
    python run_streamlit.py --server.port 8502
"""

import subprocess
import sys
from pathlib import Path

APP_FILE = Path(__file__).resolve().parent / "app.py"


def main() -> int:
    command = [sys.executable, "-m", "streamlit", "run", str(APP_FILE), *sys.argv[1:]]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())

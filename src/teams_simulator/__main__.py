"""Entry point for ``python -m teams_simulator``.

Launches the Tkinter UI. For headless / scripted use, prefer
``python -m teams_simulator.cli``.
"""

from __future__ import annotations

import sys

from .ui import main as ui_main


def main() -> int:
    return ui_main()


if __name__ == "__main__":
    sys.exit(main())

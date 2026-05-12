"""Entry point for ``python -m teams_simulator``.

Launches the Tkinter UI. For headless / scripted use, prefer
``python -m teams_simulator.cli``.
"""

from __future__ import annotations

import sys

from .logsetup import install_crash_handler, write_startup_error


def main() -> int:
    # Hard-crash dump (segfaults, fatal threads) BEFORE we touch Tk.
    install_crash_handler("ui")
    try:
        from .ui import main as ui_main
        return ui_main()
    except BaseException as exc:
        # Last-resort dump - even when launched via pythonw (no console)
        # the user still finds a file on the Desktop.
        path = write_startup_error("ui", exc)
        # Re-raise so the standard tracker still sees it.
        if isinstance(exc, SystemExit):
            raise
        sys.stderr.write(f"\nTeams Simulator failed to start. See: {path}\n")
        raise


if __name__ == "__main__":
    sys.exit(main())

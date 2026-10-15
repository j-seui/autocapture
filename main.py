"""Run with Python or the packaged Windows executable."""
from __future__ import annotations

import sys


def main() -> None:
    from autocapture.win32 import enable_dpi_awareness
    enable_dpi_awareness()
    if "--self-test" in sys.argv:
        from autocapture.selftest import self_test
        index = sys.argv.index("--self-test")
        self_test(sys.argv[index + 1] if len(sys.argv) > index + 1 else "self-test-output")
        return
    from autocapture.app import App
    App().mainloop()


if __name__ == "__main__":
    main()

"""Entry point for a packaged build.

`branch/app.py` cannot be the entry script itself: it uses relative imports
(`from .profile import Profile`), which need the module to be part of its
package. Run directly -- which is exactly what PyInstaller's bootloader does --
Python has no parent package for it and the build dies on the first import with
"attempted relative import with no known parent package".

Running from source is unaffected, because `python -m branch.app` imports the
package properly. So this file exists only for the build, and the build is the
one place the failure appears.
"""
from __future__ import annotations

import sys

from branch.app import main

if __name__ == "__main__":
    sys.exit(main())

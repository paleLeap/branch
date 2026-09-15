"""Where Branch's bundled files live, running from source or from a build.

THE PROBLEM THIS SOLVES

Five modules used to resolve their data with `Path(__file__).parent.parent`,
which is correct when the program runs from a checkout and **wrong the moment it
is frozen**. PyInstaller unpacks bundled data into a temporary directory and
points `sys._MEIPASS` at it; `__file__` then refers to a module inside the
bundle, and the walk up to "the repo root" lands somewhere that does not exist.

The failure is not an import error, which would at least be obvious. It is
`load_cities()` returning an empty tuple: no city list, so the location field
never suggests anything, "nearest major city" never fires, Craigslist cannot
pick an area, and no trade profile loads -- a program that starts, looks right,
and finds nothing. Exactly the class of silent failure this project keeps having
to design out.

So there is one answer to "where are the files", and it is here.
"""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True inside a PyInstaller build."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def root() -> Path:
    """The directory holding `data/` and `profiles/`.

    Frozen, that is PyInstaller's unpack directory. From source it is the
    project root -- the parent of the `branch` package.
    """
    if is_frozen():
        return Path(sys._MEIPASS)                      # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def data(*parts: str) -> Path:
    return root().joinpath("data", *parts)


def profiles() -> Path:
    return root() / "profiles"


def package(*parts: str) -> Path:
    """A file shipped *inside* the package, like ui/theme.json.

    Frozen, the package's own files land under the unpack root in the same
    layout, so this is the same walk either way -- but going through here keeps
    every path question in one module.
    """
    if is_frozen():
        return Path(sys._MEIPASS).joinpath("branch", *parts)   # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.joinpath(*parts)

"""Entry point.

    python -m branch.app

The look lives in ui/theme.json, not here. Change a value and restart; ui_scale
resizes the whole window on its own.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from . import resources
from .profile import Profile
from .runner import ScanRunner
from .ui import MainWindow
from .ui.theme import Theme

ROOT = resources.root()


def _browser_loads() -> int:
    import importlib
    importlib.import_module("PySide6.QtWebEngineCore")
    importlib.import_module("PySide6.QtWebEngineWidgets")
    importlib.import_module("branch.ui.browser")
    return 1


def check(out=None) -> int:
    """Verify a build has everything it needs, and say so. `Branch --check`.

    A packaged build that is missing its data does not crash -- it starts, looks
    right, and finds nothing, because every one of these loads returns an empty
    list on failure. That is unfalsifiable from the outside, so this makes it
    falsifiable: it is the one command to run on a machine where "it opened but
    there were no trades in the dropdown".
    """
    from . import resources
    from .places import load_cities
    from .profile import Profile
    from .sources.craigslist import load_areas

    write = (out or sys.stdout).write
    checks = [
        ("cities", lambda: len(load_cities()), 1000),
        ("craigslist areas", lambda: len(load_areas()), 100),
        ("trade profiles", lambda: len(Profile.load_all(resources.profiles())), 1),
        ("theme", lambda: len(Theme.load().values), 1),
        # The browser IS the product for Facebook, FB Groups and Craigslist, and
        # QtWebEngine is the piece most likely to be missing from a build: it is
        # imported lazily, so PyInstaller cannot see it without being told. An
        # import is enough -- starting Chromium here would cost seconds and a
        # window. Bundling failures show up at import.
        ("browser", _browser_loads, 1),
    ]
    bad = 0
    write(f"Branch, {'packaged build' if resources.is_frozen() else 'from source'}\n")
    write(f"resources: {resources.root()}\n")
    for name, load, least in checks:
        try:
            count = load()
        except Exception as error:                       # a build problem, not a bug
            count, error_text = 0, f" ({type(error).__name__}: {error})"
        else:
            error_text = ""
        ok = count >= least
        bad += 0 if ok else 1
        write(f"  {'ok  ' if ok else 'FAIL'} {name}: {count}{error_text}\n")
    write("everything the program needs is present\n" if not bad
          else f"{bad} missing -- this build is incomplete\n")
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    if "--check" in (argv if argv is not None else sys.argv):
        return check()

    # Qt 6 handles per-monitor DPI correctly on its own; PassThrough keeps
    # fractional scales (125%, 150%) exact instead of rounding them to whole
    # numbers, which is what makes a window look wrong on a 1440p monitor.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    # WM_CLASS instance comes from argv[0] on X11, which would otherwise be
    # "app.py". Name it like the rest of the family so picom.conf can target it
    # with a per-window rule later; with no rule it takes the global defaults,
    # which is what we want -- corner-radius 10, blur, shadow.
    args = list(argv if argv is not None else sys.argv)
    args[0] = "pale-branch"
    app = QApplication(args)
    app.setApplicationName("Branch")
    app.setDesktopFileName("pale-branch")

    # Ubuntu Sans is the family font. Never name a weight inside the family --
    # fontconfig substitutes silently if the exact face is missing.
    theme = Theme.load()
    family = str(theme.font_family).split(",")[0].strip().strip('"')
    font = QFont(family, int(theme.font_size))
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)

    try:
        profiles = Profile.load_all(ROOT / "profiles")
    except Exception as exc:                      # a bad hand-edited YAML must not be fatal
        print(f"warning: could not load profiles: {exc}", file=sys.stderr)
        profiles = {}
    # Show the human name, hand the engine the slug.
    trade_slugs = {p.name: slug for slug, p in profiles.items()}
    trade_prompts = {p.name: p.prompts() for p in profiles.values()}
    trades = sorted(trade_slugs)

    window = MainWindow(trades=trades, theme=theme, trade_slugs=trade_slugs,
                        trade_prompts=trade_prompts)

    runner = ScanRunner(ROOT, profiles, parent=window)
    window.scan_requested.connect(runner.run)
    window.exclusion_requested.connect(runner.exclude)
    runner.finished.connect(window.show_result)
    runner.started.connect(window.scan_started)

    # Sources that need a logged-in browser are driven by the window, not the
    # worker thread, and their posts are folded into the next scan.
    def _start_browsing(query: dict) -> None:
        targets = runner.interactive_targets(query)
        window.set_browse_queue(runner.browse_queues(query))
        window.browse(targets)

    window.scan_requested.connect(_start_browsing)
    window.browser_harvested.connect(runner.rescan)

    # Tell the window what each source can actually do: run now, run once the
    # user has signed in, or not at all. The window shows all three differently.
    window.set_source_states(runner.source_states())

    def _sign_in(service: str, url: str) -> None:
        """Open the service's own sign-in page, visibly, and nothing else.

        No harvesting: this is the one time the browser is opened for the user
        rather than for a scan. Branch never sees the password -- it is typed
        into the service's own form, in the user's own session.
        """
        window.open_login(service, url)

    def _refresh_states() -> None:
        window.set_source_states(runner.source_states())

    window.login_requested.connect(_sign_in)
    window.login_finished.connect(_refresh_states)

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

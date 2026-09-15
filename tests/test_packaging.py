"""The build, checked from the outside.

    python -m unittest discover -s tests

None of this needs PyInstaller installed. It asserts the things that make a
packaged build work, all of which fail *silently* when they are wrong: a bundle
missing its data starts, looks right, and finds nothing.
"""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from branch import resources                                      # noqa: E402


class TestResourcePaths(unittest.TestCase):
    """Every bundled file is found through one module, so freezing changes one
    answer rather than five."""

    def test_nothing_walks_up_from___file___to_find_data(self):
        """The bug this prevents: `Path(__file__).parent.parent / "data"` is
        right from a checkout and wrong inside a build, where PyInstaller
        unpacks to a temporary directory."""
        offenders = []
        for path in sorted((ROOT / "branch").rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "__file__" not in line or line.lstrip().startswith("#"):
                    continue
                if path.name == "resources.py":
                    continue            # the one module allowed to ask
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "these must go through branch.resources")

    def test_the_bundled_files_are_all_reachable(self):
        self.assertTrue(resources.data("cities.csv.gz").exists())
        self.assertTrue(resources.data("craigslist_areas.csv.gz").exists())
        self.assertTrue(resources.profiles().is_dir())
        self.assertTrue(resources.package("ui", "theme.json").exists())

    def test_it_knows_it_is_not_frozen(self):
        self.assertFalse(resources.is_frozen())


class TestSelfCheck(unittest.TestCase):
    """`Branch --check`: the one command to run when someone says "it opened
    but there was nothing in it"."""

    def test_it_passes_from_source(self):
        from branch.app import check
        out = io.StringIO()
        self.assertEqual(check(out), 0, out.getvalue())
        self.assertIn("everything the program needs is present", out.getvalue())

    def test_it_reports_every_thing_a_build_can_lose(self):
        from branch.app import check
        out = io.StringIO()
        check(out)
        for name in ("cities", "craigslist areas", "trade profiles", "theme", "browser"):
            self.assertIn(name, out.getvalue())

    def test_main_honours_the_flag_without_opening_a_window(self):
        source = (ROOT / "branch" / "app.py").read_text(encoding="utf-8")
        body = source.split("def main(")[1].split("\n    #")[0]
        self.assertIn("--check", body)
        self.assertLess(body.index("--check"), body.index("QApplication")
                        if "QApplication" in body else len(body))


class TestSpec(unittest.TestCase):
    """The spec file, read as text -- PyInstaller need not be installed."""

    @classmethod
    def setUpClass(cls):
        cls.spec = (ROOT / "branch.spec").read_text(encoding="utf-8")

    def test_the_spec_is_checked_in(self):
        """`.gitignore` ships with `*.spec` in it by habit, which would drop the
        one file that says how to build this."""
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("*.spec", ignore)

    def test_every_silently_lost_file_is_bundled(self):
        for needed in ("cities.csv.gz", "craigslist_areas.csv.gz",
                       "theme.json", "profiles", "NOTICE"):
            with self.subTest(file=needed):
                self.assertIn(needed, self.spec)

    def test_the_lazily_imported_browser_is_declared(self):
        """It is imported inside a function so a user who never touches Facebook
        does not load Chromium -- which also hides it from PyInstaller."""
        for module in ("PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
                       "branch.ui.browser"):
            with self.subTest(module=module):
                self.assertIn(module, self.spec)

    def test_the_entry_point_is_not_the_relative_importing_module(self):
        """branch/app.py as the entry dies on its first relative import: the
        bootloader runs it with no parent package. Found by building it."""
        self.assertIn("run_branch.py", self.spec)
        self.assertTrue((ROOT / "run_branch.py").exists())
        self.assertNotIn('"branch" / "app.py"', self.spec)

    def test_upx_is_off(self):
        """UPX corrupts Qt's DLLs; a compressed WebEngine does not start."""
        self.assertNotIn("upx=True", self.spec)

    def test_it_is_a_windowed_build(self):
        """console=True flashes a terminal up behind the window on Windows."""
        self.assertIn("console=False", self.spec)


class TestWindowsPaths(unittest.TestCase):
    """Windows is the target platform; these are the places it differs."""

    def test_settings_go_to_appdata_on_windows(self):
        from branch import locate
        real = sys.platform
        try:
            sys.platform = "win32"
            self.assertIn("branch", str(locate.cache_path()).lower())
        finally:
            sys.platform = real

    def test_no_posix_only_paths_are_hardcoded(self):
        for path in sorted((ROOT / "branch").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for bad in ('"/home/', "'/home/", '"/tmp/', "'/tmp/", '"/usr/'):
                with self.subTest(module=path.name, pattern=bad):
                    self.assertNotIn(bad, text)

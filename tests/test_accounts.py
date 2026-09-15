"""What Branch remembers about sign-ins, and what it must never remember.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from branch import accounts                                       # noqa: E402


class TestAccounts(unittest.TestCase):

    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "accounts.json"

    def test_unknown_service_is_not_connected(self):
        """The honest answer to "have you seen this signed in?" before anything
        has run is no -- and no is also the safe one, because guessing yes turns
        into a scan that silently returns nothing."""
        self.assertFalse(accounts.connected("facebook", self.path))
        self.assertEqual(accounts.connected_services(self.path), set())

    def test_a_sign_in_is_remembered(self):
        accounts.mark("Facebook", True, self.path)
        self.assertTrue(accounts.connected("facebook", self.path))
        self.assertEqual(accounts.connected_services(self.path), {"facebook"})

    def test_signing_out_is_remembered_too(self):
        accounts.mark("Facebook", True, self.path)
        accounts.mark("Facebook", False, self.path)
        self.assertFalse(accounts.connected("facebook", self.path))

    def test_services_do_not_collide(self):
        accounts.mark("Facebook", True, self.path)
        accounts.mark("X", False, self.path)
        self.assertTrue(accounts.connected("facebook", self.path))
        self.assertFalse(accounts.connected("x", self.path))

    def test_a_corrupt_file_reads_as_unknown(self):
        """A half-written settings file must not stop the program starting."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ not json", encoding="utf-8")
        self.assertFalse(accounts.connected("facebook", self.path))
        accounts.mark("facebook", True, self.path)         # and recovers
        self.assertTrue(accounts.connected("facebook", self.path))

    def test_it_stores_a_flag_and_a_time_and_nothing_else(self):
        """The hard one. Branch may remember *that* a service is signed in. It
        may never hold anything that could identify or impersonate the user --
        no password, no cookie, no token, no username, no id."""
        accounts.mark("Facebook", True, self.path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"facebook"})
        self.assertEqual(set(data["facebook"]), {"connected", "at"})
        self.assertIsInstance(data["facebook"]["connected"], bool)
        self.assertIsInstance(data["facebook"]["at"], float)

    def test_nothing_in_the_module_reaches_for_a_credential(self):
        """Checked in the source, not just in the output, so a later change that
        starts storing a session token fails here rather than in the wild."""
        source = (ROOT / "branch" / "accounts.py").read_text(encoding="utf-8").lower()
        code = "\n".join(line for line in source.splitlines()
                         if not line.strip().startswith("#"))
        # The docstring names these to say they are excluded; the code must not.
        code = code.split('"""')[-1]
        for banned in ("password", "cookie", "token", "session", "credential",
                       "username", "user_id"):
            self.assertNotIn(banned, code, f"accounts.py touches {banned!r}")


if __name__ == "__main__":
    unittest.main()

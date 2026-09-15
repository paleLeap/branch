"""Which services the user has signed in to, in Branch's own browser.

WHY THIS FILE EXISTS

Facebook and X only return anything to a signed-in session, and Branch's browser
keeps its **own** session -- being signed in to Facebook in Chrome does nothing
here. That surprised the user once already, and the symptom was a scan that
looked like it worked and found nothing. The window therefore has to be able to
say "this needs a sign-in" *before* a scan runs, and offer the page that fixes it.

Knowing that means remembering one bit per service.

WHAT IS STORED, AND WHAT IS NOT

A service name, whether the last attempt saw a signed-in session, and when. That
is the whole file:

    {"facebook": {"connected": true, "at": 1789200000.0}}

**Never a password, a cookie, a token, a username or an id.** Branch does not see
the password -- it is typed into Facebook's own page in their own form -- and this
module has no way to reach the session even if it wanted to. The README allows
persisting "the user's own settings, queries, connected accounts"; this is the
connected-accounts half and nothing more.

Reading the browser's cookie jar would answer the same question without a file,
and it was the first design. It is rejected on purpose: that jar is the user's
live session, it is not ours to open, and a flag we wrote ourselves cannot leak
anything we did not already know.

UNKNOWN MEANS NOT CONNECTED. A service Branch has never seen signed in is
reported as needing a sign-in, because the honest answer is "I do not know" and
the cost of guessing wrong the optimistic way is a silent empty scan.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .locate import cache_path


def accounts_path() -> Path:
    """Beside location.json, in the user's own config directory."""
    return cache_path().parent / "accounts.json"


def _read(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or accounts_path()).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}          # absent, unreadable or corrupt all mean "unknown"


def connected(service: str, path: Path | None = None) -> bool:
    """Has Branch's browser seen a signed-in session for this service?"""
    entry = _read(path).get((service or "").lower())
    return bool(entry.get("connected")) if isinstance(entry, dict) else False


def connected_services(path: Path | None = None) -> set[str]:
    data = _read(path)
    return {k for k, v in data.items() if isinstance(v, dict) and v.get("connected")}


def mark(service: str, is_connected: bool, path: Path | None = None) -> None:
    """Record what the browser just learned. Best effort: a config directory
    that cannot be written is not a reason to fail a scan."""
    service = (service or "").lower()
    if not service:
        return
    target = path or accounts_path()
    data = _read(target)
    data[service] = {"connected": bool(is_connected), "at": time.time()}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass

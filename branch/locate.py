"""Work out roughly where the program is being launched, so the location field
can fill itself in with the nearest major city.

PRIVACY, stated plainly because it is the one place Branch touches a third party
that is not a search source: resolving an approximate position from an IP address
means sending a request to a geolocation service, which sees the user's IP. So:

  - It happens **once** and the answer is cached on disk. No repeat lookups.
  - It is skipped entirely if the cache is warm, if BRANCH_NO_GEOIP is set, or if
    the user has typed their own location.
  - It fails silently and the field simply starts empty. Nothing depends on it.
  - No coordinates leave the machine; the lookup only returns them.

The city dataset itself is bundled and offline (see places.py) -- only the initial
"where am I" step touches the network, and the user can skip it and type a city.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Only fields needed; asking for less is the polite call and a smaller response.
GEOIP_URL = "http://ip-api.com/json/?fields=status,city,regionName,lat,lon"
TIMEOUT_SECONDS = 3.0


def cache_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "branch" / "location.json"


@dataclass(frozen=True)
class Fix:
    lat: float
    lon: float
    source: str        # "cache" | "geoip"


def read_cache(path: Path | None = None) -> Fix | None:
    target = path or cache_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return Fix(float(data["lat"]), float(data["lon"]), "cache")
    except Exception:
        return None


def write_cache(fix: Fix, path: Path | None = None) -> None:
    target = path or cache_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"lat": fix.lat, "lon": fix.lon}), encoding="utf-8")
    except OSError:
        pass          # a read-only home is not a reason to fail


def lookup_geoip(url: str = GEOIP_URL, timeout: float = TIMEOUT_SECONDS) -> Fix | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") not in (None, "success"):
            return None
        return Fix(float(data["lat"]), float(data["lon"]), "geoip")
    except Exception:
        return None   # offline, blocked, rate-limited, malformed -- all the same here


def detect(use_network: bool = True, path: Path | None = None) -> Fix | None:
    """Cached fix if there is one, otherwise one network lookup, otherwise nothing."""
    cached = read_cache(path)
    if cached is not None:
        return cached
    if not use_network or os.environ.get("BRANCH_NO_GEOIP"):
        return None
    fix = lookup_geoip()
    if fix is not None:
        write_cache(fix, path)
    return fix

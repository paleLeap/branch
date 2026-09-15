"""Joins the window to the sources and the engine.

Network work happens on a worker thread. A scan can take several seconds and can
hang on a blocked network; the window must stay responsive throughout, and the
user must be able to change their mind and re-run.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .engine import scan
from .models import ScanResult
from .profile import Profile
from .sources.base import Query
from .sources.registry import build as build_sources

SINCE_HOURS = {
    "Last hour": 1.0, "Last 6 hours": 6.0, "Last 24 hours": 24.0,
    "Last 3 days": 72.0, "Last week": 168.0, "Last month": 720.0,
}


def _radius_miles(label: str) -> float:
    match = re.search(r"\d+", label or "")
    return float(match.group()) if match else 25.0


class ScanRunner(QObject):
    """Runs a scan and hands the result back on the UI thread."""

    finished = Signal(object)
    started = Signal()

    def __init__(self, root: Path, profiles: dict[str, Profile], parent=None) -> None:
        super().__init__(parent)
        self.root = root
        self.profiles = profiles
        self.sources = build_sources()
        self.last_query: dict | None = None
        self._running = False

    # -- entry points --------------------------------------------------------

    def run(self, query: dict) -> None:
        self.last_query = query
        if self._running:
            return          # one scan at a time; the button stays live for re-runs
        profile = self._profile(query)
        if profile is None:
            self.finished.emit(ScanResult(unavailable={"trade": "choose a trade first"}))
            return
        self._running = True
        self.started.emit()
        threading.Thread(target=self._work, args=(query, profile), daemon=True).start()

    def exclude(self, phrase: str) -> None:
        """Tuning from the results list: exclude a phrase and re-run at once."""
        if self.last_query is None:
            return
        profile = self._profile(self.last_query)
        if profile is not None and profile.add_exclusion(phrase):
            self.run(self.last_query)

    def availability(self) -> dict[str, str | None]:
        return {key: source.available() for key, source in self.sources.items()}

    def source_states(self) -> dict:
        """What the window should show for every source, in one pass.

        The connected-account flags are read here rather than in the adapters so
        an adapter stays a thing that knows how to search one site, and nothing
        about where this install keeps its settings.
        """
        from . import accounts
        signed_in = accounts.connected_services()
        return {key: source.state(signed_in) for key, source in self.sources.items()}

    def interactive_targets(self, query: dict) -> list[tuple[str, str, str]]:
        """(key, url, label) for each chosen source that needs a browser."""
        profile = self._profile(query)
        if profile is None:
            return []
        request = self._request(query, profile)
        out = []
        for key in query.get("sources") or []:
            source = self.sources.get(key)
            if source is not None and getattr(source, "interactive", False):
                out.append((key, source.url(request), source.label))
        return out

    def browse_queues(self, query: dict) -> dict[str, list[tuple[str, str]]]:
        """Every search each interactive source wants to work through."""
        profile = self._profile(query)
        if profile is None:
            return {}
        request = self._request(query, profile)
        queues = {}
        for key in query.get("sources") or []:
            source = self.sources.get(key)
            if source is None or not getattr(source, "interactive", False):
                continue
            urls = getattr(source, "urls", None)
            if urls is not None:
                queues[key] = urls(request)
        return queues

    def rescan(self, extra_items: list) -> None:
        """Re-run the last scan with posts harvested from a browser folded in."""
        if self.last_query is None:
            return
        profile = self._profile(self.last_query)
        if profile is None:
            return
        self._extra = list(extra_items)
        self.run(self.last_query)

    # -- work ----------------------------------------------------------------

    def _profile(self, query: dict) -> Profile | None:
        slug = query.get("trade_slug")
        return self.profiles.get(slug) if slug else None

    def _work(self, query: dict, profile: Profile) -> None:
        try:
            self.finished.emit(self._collect(query, profile))
        except Exception as exc:                      # never kill the UI thread
            self.finished.emit(ScanResult(unavailable={"scan": f"failed: {exc}"}))
        finally:
            self._running = False

    def _request(self, query: dict, profile: Profile) -> Query:
        return Query(
            trade=profile.trade,
            narrow=query.get("narrow", ""),
            location=query.get("location", ""),
            coordinates=query.get("coordinates"),
            radius_miles=_radius_miles(query.get("radius", "")),
            since_hours=SINCE_HOURS.get(query.get("since", ""), 24.0),
            terms=profile.prompts(8),
            forums=profile.forums,
            ask=(profile.ask_phrases(1) or [""])[0],
            asks=profile.ask_phrases(10),
        )

    def _collect(self, query: dict, profile: Profile) -> ScanResult:
        chosen = list(query.get("sources") or [])
        request = self._request(query, profile)

        items, unavailable, notes = [], {}, []
        for key in chosen:
            source = self.sources.get(key)
            if source is None:
                unavailable[key] = "unknown source"
                continue
            if getattr(source, "interactive", False):
                # Needs the user and a browser; the window drives it separately.
                continue
            fetched = source.fetch(request)
            items.extend(fetched.items)
            unavailable.update(fetched.unavailable)
            for note in fetched.notes:
                notes.append(f"{source.label}: {note}")
            # A source with no geography must say so rather than let the radius
            # setting imply one was honoured.
            if fetched.items and not source.geographic:
                notes.append(f"{source.label}: not filtered by location")

        for key in self.sources:
            if key not in chosen and key not in unavailable:
                unavailable.setdefault(key, "not selected")
        unavailable = {k: v for k, v in unavailable.items()
                       if v != "not selected" or k in chosen}

        items.extend(getattr(self, "_extra", []))
        self._extra = []
        result = scan(items, profile,
                      narrow=query.get("narrow") or None,
                      unavailable=unavailable)
        if notes:
            result.unavailable.setdefault("_notes", "  ·  ".join(notes))
        return result

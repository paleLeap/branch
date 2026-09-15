"""Load fixture items from JSON.

Fixtures are how Branch is developed and tested without a network, a browser or a
platform account. A source adapter is just something else that produces Items.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Item


def load_items(path: str | Path, now: datetime | None = None) -> list[Item]:
    now = now or datetime.now(timezone.utc)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items: list[Item] = []
    for raw in data["items"]:
        if "posted_at" in raw:
            posted = datetime.fromisoformat(raw["posted_at"])
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
        else:
            posted = now - timedelta(hours=float(raw.get("age_hours", 0)))
        items.append(Item(
            id=raw["id"], text=raw.get("text", ""), url=raw.get("url", ""),
            venue=raw["venue"], posted_at=posted, author=raw.get("author"),
            title=raw.get("title"),
            extra={k: v for k, v in raw.items()
                   if k in ("expect", "why")},
        ))
    return items

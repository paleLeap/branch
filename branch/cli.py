"""Command-line runner. The GUI will call the same engine; this exists so the
engine can be exercised and tuned before any window exists.

    python -m branch.cli --trade motorcycle-repair
    python -m branch.cli --trade plumbing --show-discarded
    python -m branch.cli --all
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from . import resources
from .engine import scan
from .fixtures import load_items
from .profile import Profile

ROOT = resources.root()
BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"


def run(profile: Profile, items, now, show_discarded: bool) -> None:
    result = scan(items, profile, now=now)
    print(f"\n{BOLD}{profile.name}{RESET}  ({profile.trade})")
    print(f"  scanned {result.scanned} items across {len(result.venues)} venues "
          f"-> {len(result.leads)} leads")
    if result.unavailable:
        for venue, why in result.unavailable.items():
            print(f"  {DIM}not scanned: {venue} -- {why}{RESET}")

    for i, lead in enumerate(result.leads, 1):
        it = lead.item
        print(f"\n  {BOLD}{i}. [{lead.score:5.2f}]{RESET} {it.title or it.text[:60]}")
        print(f"     {DIM}{it.venue} | {it.author} | {lead.explanation.age_hours:.0f}h ago | {it.url}{RESET}")
        body = " ".join((it.text or "").split())
        print(f"     {body[:150]}{'...' if len(body) > 150 else ''}")
        for line in lead.explanation.lines():
            print(f"     {DIM}{line}{RESET}")

    if show_discarded and result.discarded:
        print(f"\n  {DIM}-- discarded ({len(result.discarded)}) --{RESET}")
        for d in result.discarded:
            print(f"     {DIM}{d.item.id:4} [{d.stage:9}] {d.reason}{RESET}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="branch", description="Branch -- local demand radar")
    ap.add_argument("--trade", help="trade profile to run")
    ap.add_argument("--all", action="store_true", help="run every profile")
    ap.add_argument("--profiles", default=str(ROOT / "profiles"))
    ap.add_argument("--fixtures", default=str(ROOT / "fixtures" / "mixed_venue.json"))
    ap.add_argument("--show-discarded", action="store_true")
    args = ap.parse_args(argv)

    profiles = Profile.load_all(args.profiles)
    if not profiles:
        print(f"no profiles found in {args.profiles}")
        return 1

    now = datetime.now(timezone.utc)
    items = load_items(args.fixtures, now=now)

    if args.all:
        chosen = list(profiles.values())
    elif args.trade:
        if args.trade not in profiles:
            print(f"unknown trade {args.trade!r}. available: {', '.join(sorted(profiles))}")
            return 1
        chosen = [profiles[args.trade]]
    else:
        print("available trades: " + ", ".join(sorted(profiles)))
        print("run with --trade <name> or --all")
        return 0

    for prof in chosen:
        for w in prof.validate():
            print(f"  warning [{prof.trade}]: {w}")
        run(prof, items, now, args.show_discarded)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Branch -- a local demand radar.

Deterministic. No AI at runtime. See docs/CLASSIFICATION.md.
"""
from .engine import scan
from .models import Discarded, Item, Lead, ScanResult
from .profile import Profile

__all__ = ["scan", "Profile", "Item", "Lead", "Discarded", "ScanResult"]
__version__ = "0.1.0"

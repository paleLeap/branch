"""An embedded browser that harvests what you are looking at.

WHY THIS EXISTS AND WHAT SHAPE IT TAKES

Facebook returns HTTP 400 to a logged-out client and its robots.txt disallows
everything, so the only way to see Marketplace or a local group is to be signed
in. This window is that: the user's own session, in a browser they drive.

It is **attended**. It opens when asked, does its work while the user is watching,
and stops. It does not run in the background, does not run on a schedule, and does
not run while the user is away. That is a deliberate limit, and the reason is
practical rather than legal: bulk, machine-speed collection is what automation
detection looks for, and the account it would cost is the user's own.

Scrolling is paced like a person reading -- a step every second and a half or so,
with a cap. It reaches the same posts as a fast scroll and does not look like a
crawler doing it.

WHAT IS KEPT

The browser stores the user's **own** login session, so they do not sign in every
time -- the same thing any browser does, in their own config directory. Nothing
about the posts it reads is written anywhere: harvested posts live in memory,
go through the engine, and are gone when the scan is replaced.

Branch never sees or handles a password. The user types it into Facebook's own
page, in this window, exactly as they would in Chrome.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..locate import cache_path
from ..models import Item
from .theme import Size, Theme, stylesheet

#: Which sign-in each venue needs. Three of these are one Facebook account:
#: the window says "Sign in to Facebook" once rather than three times.
VENUE_SERVICE = {
    "facebook": "Facebook",
    "groups": "Facebook",
    "marketplace": "Facebook",
    "x": "X",
}

#: Paced like a person reading, not like a crawler. See the module docstring.
#: The interval is jittered around this: a metronome is its own signature.
SCROLL_INTERVAL_MS = 1500
SCROLL_JITTER_MS = 900
#: How long to let lazily-loaded posts arrive before reading the page again.
LOAD_WAIT_MS = 1800
SETTLE_MS = 2500

#: Paging stops at whichever of these comes first. The stale counter is the one
#: that normally fires, and it is the honest one: it means the feed stopped
#: producing anything new, rather than an arbitrary limit being hit.
MAX_SCROLLS = 60
MAX_SECONDS = 240
STALE_ROUNDS = 4

#: Craigslist stamps a posting "9/14" and nothing else -- no year, no clock.
_MONTH_DAY = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")

_RELATIVE = re.compile(
    r"(?:(\d+)\s*(min|minute|hr|hour|h|d|day|w|week)s?\s*ago)"
    r"|(just now|just listed)|(yesterday)",
    re.I)


def parse_relative_time(text: str, now: datetime) -> datetime | None:
    """Turn "3 days ago" or "5 hrs" into a real time.

    Facebook shows relative times and no absolute ones. Without a timestamp the
    recency half of scoring is meaningless, so anything unparseable is reported
    as unknown rather than quietly treated as new.
    """
    match = _RELATIVE.search(text or "")
    if not match:
        return _month_day(text or "", now)
    if match.group(3):
        return now
    if match.group(4):
        return now - timedelta(days=1)
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith(("min",)):
        return now - timedelta(minutes=amount)
    if unit.startswith(("h", "hr", "hour")):
        return now - timedelta(hours=amount)
    if unit.startswith(("d", "day")):
        return now - timedelta(days=amount)
    if unit.startswith(("w", "week")):
        return now - timedelta(weeks=amount)
    return None


def _month_day(text: str, now: datetime) -> datetime | None:
    """Turn craigslist's "9/14" into a real date.

    No year is given, so the year is inferred: a date more than a week ahead of
    today is last year's, which is what happens every January. Anything that
    does not parse stays unknown rather than being treated as new -- a lead's
    age is half its score, and guessing "today" would promote stale postings.
    """
    match = _MONTH_DAY.search(text)
    if not match:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    for year in (now.year, now.year - 1):
        try:
            when = datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
        if when <= now + timedelta(days=7):
            return when
    return None


# Collects the groups a discovery page found, so they can be read in turn.
#
# A public group's feed is readable WITHOUT joining, and unlike search results it
# carries real /groups/<id>/posts/<id>/ permalinks -- so leads from here can
# actually be opened. That makes "find the local groups, then read them" the best
# shaped route into Facebook that Branch has.
GROUP_LINKS_JS = r"""
(() => {
  const ids = new Set();
  document.querySelectorAll('a[href*="/groups/"]').forEach(a => {
    const m = a.href.match(/facebook\.com\/groups\/([0-9]{6,}|[A-Za-z0-9._-]{4,})\/?(\?|$)/);
    if (m) ids.add(m[1]);
  });
  return JSON.stringify([...ids].slice(0, 12));
})()
"""


# Scrolls whatever actually scrolls.
#
# Facebook does not scroll the document: document.body.scrollHeight equals
# window.innerHeight, and the feed is an inner element with its own overflow.
# Scrolling the window alone therefore loaded nothing past the first screenful,
# which is why the first version came back with four posts however long it ran.
#
# Reports whether anything moved, so paging can tell "the feed is finished" apart
# from "we are scrolling the wrong element" -- those look identical otherwise.
SCROLL_JS = r"""
(() => {
  const feed = document.querySelector('[role="feed"]');
  const before = document.body.scrollHeight;
  let moved = false;

  // Facebook's feed is virtualised: only what is near the viewport exists in the
  // DOM, and setting scrollTop on a container does not make it load the next
  // batch. Bringing the LAST rendered item into view does -- that is the signal
  // the virtualiser is waiting for. This is why arithmetic scrolling stalled at
  // one screenful however long it ran.
  if (feed && feed.lastElementChild) {
    feed.lastElementChild.scrollIntoView({block: 'end'});
    moved = true;
  }

  const step = Math.round(window.innerHeight * 0.8);
  const y = window.scrollY;
  window.scrollBy(0, step);
  if (window.scrollY !== y) moved = true;

  for (let el = feed; el; el = el.parentElement) {
    if (el.scrollHeight > el.clientHeight + 40) {
      const was = el.scrollTop;
      el.scrollTop = Math.min(el.scrollTop + step, el.scrollHeight);
      if (el.scrollTop !== was) moved = true;
      break;
    }
  }

  return JSON.stringify({
    moved: moved,
    docHeight: document.body.scrollHeight,
    grew: document.body.scrollHeight > before,
    rendered: feed ? feed.children.length : 0,
  });
})()
"""


# Reads the page the user is looking at.
#
# Three strategies, most specific first. Facebook's own shapes are tried first,
# but a generic fallback matters: the specific selectors are the part most likely
# to break -- Facebook changes them without notice -- and a browser that silently
# returns nothing is worse than one that returns roughly the right blocks. The
# fallback also makes the address bar useful, because the user can steer to any
# site and still collect from it.
EXTRACT_JS = r"""
(() => {
  const seen = new Set(), out = [];
  const push = (text, url, how) => {
    text = (text || '')
      // Lazy-loading placeholders render the word "Facebook" dozens of times.
      // Strip it before truncating, or the filler eats the real post.
      .replace(/(?:Facebook\s*){2,}/g, ' ')
      // Post chrome that carries no information about what the person wants.
      .replace(/\bShared post\b/g, ' ')
      .replace(/\s+·\s+(Join|Follow|Like|Comment|Share)\b/g, ' ')
      .replace(/\s+/g, ' ').trim();
    if (!text || text.length < 25 || !url) return false;
    // Keep the query, minus Facebook's tracking noise. Stripping it wholesale
    // was the bug behind "Open" landing on the wrong page: a search result's
    // permalink is /stories/<id>/<token>/?view_single, and without view_single
    // that same URL opens the Stories viewer instead of the post.
    let clean = url;
    try {
      const u = new URL(url);
      [...u.searchParams.keys()].forEach(k => {
        if (k.startsWith('__') || k === 'ref' || k === 'refid') u.searchParams.delete(k);
      });
      clean = u.toString();
    } catch (e) { clean = url.split('?')[0]; }

    const key = clean + '|' + text.slice(0, 40);
    if (seen.has(key)) return false;
    seen.add(key);
    out.push({text: text.slice(0, 1200), url: clean, how: how});
    return true;
  };

  // 1. Marketplace listings.
  document.querySelectorAll('a[href*="/marketplace/item/"]').forEach(a => {
    const box = a.closest('[data-testid], div');
    push((box && box.innerText) || a.innerText, a.href, 'marketplace');
  });

  // 2. Feed, group and search results. Two shapes: the news feed and group
  // feeds use role="article"; SEARCH results do not -- they are aria-posinset
  // children of a role="feed", which is why post search returned nothing while
  // groups search returned ten.
  // Pick the anchor that points at the POST, not at wherever it was posted.
  //
  // A plain querySelector list returns whatever comes first in the DOM, and in a
  // group post that is the group's own name link -- so every "Open" went to the
  // group page instead of the post. Score the candidates and take the best.
  // Search results do NOT carry /posts/ permalinks -- checked live, not one of
  // 24 results had one. What they do carry is a /stories/<id>/<token>/ link,
  // which is the post itself. Rank that top; a bare group or profile link is the
  // container, not the post, and was what every "Open" used to land on.
  const linkScore = href => {
    if (!href) return -1;
    if (/\/status\/\d+/.test(href)) return 6;
    if (/\/stories\/\d+\/[^/]+/.test(href)) return 6;
    if (/\/groups\/[^/]+\/(posts|permalink)\//.test(href)) return 5;
    if (/\/posts\/|\/permalink\/|story_fbid=/.test(href)) return 4;
    if (/\/videos\/\d|\/photo\/\?|\/photo\/\d/.test(href)) return 2;
    if (/\/groups\/[^/]+\/?$/.test(href)) return 0;     // the group itself
    if (/facebook\.com\/[^/]+\/?$/.test(href)) return 0; // someone's profile
    return 1;
  };
  const postLink = el => {
    let best = null, bestScore = 0;
    el.querySelectorAll('a[href]').forEach(a => {
      const score = linkScore(a.href);
      if (score > bestScore) { bestScore = score; best = a; }
    });
    return best;
  };
  document.querySelectorAll('[role="article"]').forEach(el => {
    const a = postLink(el);
    push(el.innerText, a ? a.href : location.href, 'article');
  });
  document.querySelectorAll('[role="feed"] > div, [aria-posinset]').forEach(el => {
    if (el.querySelector('[role="article"]')) return;      // already taken above
    const a = postLink(el);
    push(el.innerText, a ? a.href : location.href, 'search');
  });

  // 3. X posts. The permalink is the timestamp anchor, /<user>/status/<id>.
  document.querySelectorAll('article[data-testid="tweet"], article[role="article"]')
    .forEach(el => {
      const a = el.querySelector('a[href*="/status/"]');
      push(el.innerText, a ? a.href : location.href, 'tweet');
    });

  // 4. Craigslist search results. Server-rendered HTML has the titles but no
  // links and no dates -- those arrive when the page's own JS populates
  // .cl-search-result, which takes a few seconds. Each card then carries a
  // data-pid, a real permalink, and a .meta whose first token is the date.
  document.querySelectorAll('.cl-search-result, .cl-static-search-result')
    .forEach(el => {
      const a = el.querySelector('a[href*="/view/"], a.posting-title, a.cl-app-anchor[href]');
      const title = (el.getAttribute('title') || '').trim();
      const meta = (el.querySelector('.meta') || {}).textContent || '';
      // Title first: craigslist's card text is title + price + place, and the
      // title is the part that says what the person actually wants.
      push([title, meta].join(' '), a ? a.href : location.href, 'craigslist');
    });

  // 5. Anything else: a block of real text with a link in or near it.
  if (out.length === 0) {
    const junk = /^(home|menu|log ?in|sign ?up|vote|reply|share|more|next|prev)/i;
    document.querySelectorAll('li, article, tr, [class*="post"], [class*="item"]')
      .forEach(el => {
        if (el.querySelector('li, article')) return;      // keep the leaf, not the list
        if (el.closest('nav, header, footer')) return;    // site chrome, not content
        const text = (el.innerText || '').trim();
        if (text.length < 60 || junk.test(text)) return;
        const a = el.querySelector('a[href]');
        if (a && a.href) push(text, a.href, 'generic');
      });
  }
  return JSON.stringify(out);
})()
"""


class HarvestBrowser(QWidget):
    """A browser window that reads what is on screen and hands back posts."""

    harvested = Signal(list)          # list[Item]
    progress = Signal(str)
    #: (service, connected) -- what this window just learned about a sign-in.
    #: Only ever a service name and a yes or no; see accounts.py.
    signed_in = Signal(str, bool)

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.theme = theme
        self._items: dict[str, Item] = {}
        self._strategies: set[str] = set()
        self._scrolls = 0
        self._stale = 0
        self._last_count = 0

        self._finished = False
        self._started_at = 0.0
        self._after_extract = None
        self._queue: list[tuple[str, str]] = []
        self._all_items: dict[str, Item] = {}
        self._not_found = 0
        self._cycle = 0
        self._expanding = False
        # Set while the window is open purely so the user can sign in. Nothing
        # is read, scrolled or collected in this mode.
        self._logging_in = ""
        # Set BRANCH_SHOW_BROWSER=1 to watch it work.
        self._always_visible = os.environ.get("BRANCH_SHOW_BROWSER") == "1"
        self._venue = "facebook"
        self.setWindowTitle("Branch - browsing")
        self.setStyleSheet(stylesheet(theme))
        self.resize(theme.s(900), theme.s(700))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # A persistent profile so the user's own login survives a restart. This
        # is their session, in their config directory -- nothing about anyone
        # whose post is read is stored.
        store = cache_path().parent / "browser"
        store.mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile("branch", self)
        self.profile.setPersistentStoragePath(str(store))
        self.profile.setCachePath(str(store / "cache"))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

        # Qt's default user agent announces "QtWebEngine/6.10.2", and X refuses
        # to run its login flow for an embedded browser -- the sign-in simply
        # will not proceed. This is the same Chromium underneath; the string is
        # what differs. Kept in step with the real engine version rather than
        # invented, so it does not drift into a lie about what this is.
        default = self.profile.httpUserAgent()
        chrome = "Chrome/134.0.0.0"
        for part in default.split():
            if part.startswith("Chrome/"):
                chrome = part
        self.profile.setHttpUserAgent(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) {chrome} Safari/537.36")

        self.view = QWebEngineView(self)
        self.view.setPage(self._new_page())
        # An address bar, because the URL Branch guesses can be wrong -- Facebook
        # moves its search paths and Marketplace city slugs are inconsistent. When
        # the guess misses, the user steers to the right page themselves and
        # presses Collect. Without this the window is a dead end on a 404.
        nav = QHBoxLayout()
        nav.setContentsMargins(theme.s(Size.pad), theme.s(6), theme.s(Size.pad), 0)
        nav.setSpacing(theme.s(6))
        self.back = QPushButton("<")
        self.back.setObjectName("go")
        self.back.setCursor(Qt.PointingHandCursor)
        self.back.clicked.connect(self.view.back)
        nav.addWidget(self.back, 0)

        self.address = QLineEdit()
        self.address.setObjectName("query")
        self.address.setFixedHeight(theme.s(Size.query_h))
        self.address.returnPressed.connect(self._go_to_address)
        nav.addWidget(self.address, 1)

        self.reload_page = QPushButton("Reload")
        self.reload_page.setObjectName("go")
        self.reload_page.setCursor(Qt.PointingHandCursor)
        self.reload_page.clicked.connect(self.view.reload)
        nav.addWidget(self.reload_page, 0)
        layout.addLayout(nav, 0)
        self.view.urlChanged.connect(lambda u: self.address.setText(u.toString()))
        layout.addWidget(self.view, 1)

        bar = QHBoxLayout()
        bar.setContentsMargins(theme.s(Size.pad), theme.s(6), theme.s(Size.pad), theme.s(6))
        self.status = QLabel("")
        self.status.setObjectName("fieldLabel")
        self.status.setWordWrap(True)
        bar.addWidget(self.status, 1)

        self.skip = QPushButton("Skip this search")
        self.skip.setObjectName("go")
        self.skip.setCursor(Qt.PointingHandCursor)
        self.skip.setToolTip("Move on to the next search and keep what this one found")
        self.skip.clicked.connect(lambda: (self.hide(), self._skip_to_next("skipped")))
        bar.addWidget(self.skip, 0)

        self.collect_now = QPushButton("Collect what's on screen")
        self.collect_now.setObjectName("go")
        self.collect_now.setCursor(Qt.PointingHandCursor)
        self.collect_now.clicked.connect(self._extract)
        bar.addWidget(self.collect_now, 0)

        self.finish = QPushButton("Stop scanning")
        self.finish.setObjectName("go")
        self.finish.setCursor(Qt.PointingHandCursor)
        self.finish.setToolTip("End the whole scan now and show what was found")
        self.finish.clicked.connect(self._finish)
        bar.addWidget(self.finish, 0)
        layout.addLayout(bar, 0)


    def _new_page(self):
        from PySide6.QtWebEngineCore import QWebEnginePage
        return QWebEnginePage(self.profile, self)

    # -- driving -------------------------------------------------------------

    def harvest_all(self, targets: list[tuple[str, str]], venue: str) -> None:
        """Work through several searches, accumulating across all of them.

        Scrolling deeper does not help once a feed is exhausted -- measured, a
        Facebook post search returns about four results and the page simply stops
        growing. Depth therefore comes from asking more than one question:
        "need a plumber", "plumber recommendation", "looking for a plumber". The
        queue is paced exactly like the scrolling is, and results accumulate
        because items are keyed by URL.
        """
        self._queue = [(u, l, bool(rest and rest[0] == "discover"))
                       for u, l, *rest in targets[1:]]
        self._all_items = {}
        self._cycle += 1
        first_url, first_label, *rest = targets[0]
        self.harvest(first_url, venue, first_label, keep=True,
                     expand=bool(rest and rest[0] == "discover"))

    MAX_GROUPS = 5

    def harvest(self, url: str, venue: str, label: str, keep: bool = False,
                expand: bool = False) -> None:
        """Open `url` and read it, scrolling at a human pace.

        The window stays **hidden** unless it needs the user. Verified to cost
        nothing: a hidden view with a real size loads, lazy-renders and extracts
        exactly as a visible one does -- 29 posts and 3 leads either way.

        It shows itself the moment it needs a person: a login page, a "Not Found",
        or a page that will not load. Those are the only situations where a human
        can help, and hiding them would leave a scan silently stuck.
        """
        self._expanding = expand
        self._logging_in = ""
        try:
            self.view.loadFinished.disconnect(self._login_loaded)
        except (RuntimeError, TypeError):
            pass
        if not keep:
            self._queue = []
            self._all_items = {}
        self._items.clear()
        self._scrolls = 0
        self._stale = 0
        self._last_count = 0

        self._finished = False
        self._venue = venue
        self._say(f"Opening {label}. Sign in if asked -- Branch never sees your password.")
        self.view.loadFinished.connect(self._loaded, Qt.UniqueConnection)
        self.view.load(QUrl(url))
        if self._always_visible:
            self.reveal("")

    def open_login(self, service: str, url: str) -> None:
        """Show the service's own sign-in page. Read nothing, collect nothing.

        This is the only time the browser opens for the user rather than for a
        scan, and it is deliberately inert: no scrolling, no extraction, no
        queue. The user signs in on the service's own form, in their own
        session. **Branch never sees the password**, here or anywhere.
        """
        self._logging_in = service
        self._queue = []
        self._items.clear()
        self._finished = True             # nothing is in flight to finish
        try:
            self.view.loadFinished.disconnect(self._loaded)
        except (RuntimeError, TypeError):
            pass                          # not connected; nothing to undo
        self.view.loadFinished.connect(self._login_loaded, Qt.UniqueConnection)
        self.view.load(QUrl(url))
        self.reveal(f"Sign in to {service} here. Branch never sees your password "
                    "-- this is their own page. Close this window when you are done.")

    def _login_loaded(self, ok: bool) -> None:
        """Did the sign-in take?

        Both services bounce a signed-in visitor off /login to their own home
        page, so the URL answers this on its own most of the time. The page text
        is the second opinion, for the case where they serve the form in place.
        """
        if not self._logging_in or not ok:
            return
        url = self.view.url().toString().lower()
        if "login" in url or "signin" in url or "sign_in" in url:
            self.signed_in.emit(self._logging_in, False)
            return
        self.view.page().runJavaScript(
            "document.body ? document.body.innerText.slice(0, 200) : ''",
            self._login_checked)

    def _login_checked(self, sample: str | None) -> None:
        if not self._logging_in:
            return
        text = (sample or "").strip().lower()
        walled = any(m in text for m in
                     ("log into facebook", "log in to facebook",
                      "join or log into", "sign in to x", "sign in to twitter"))
        self.signed_in.emit(self._logging_in, not walled)
        if not walled:
            self._say(f"Signed in to {self._logging_in}. You can close this "
                      "window and press Go.")

    def _go_to_address(self) -> None:
        url = self.address.text().strip()
        if url and "://" not in url:
            url = "https://" + url
        if url:
            self.view.load(QUrl(url))

    def reveal(self, why: str) -> None:
        """Bring the window up, because something needs a person."""
        if why:
            self._say(why)
        self.show()
        self.raise_()
        self.activateWindow()

    def _loaded(self, ok: bool) -> None:
        if not ok:
            self.reveal("That page could not be loaded. Edit the address above "
                        "and press Enter, then use Collect.")
            return
        # A wrong guess lands on Facebook's bare 404. Say what to do about it
        # rather than scrolling an error page for twenty seconds.
        self.view.page().runJavaScript(
            "document.body ? document.body.innerText.slice(0, 200) : ''",
            self._after_load)

    def _after_load(self, sample: str | None) -> None:
        text = (sample or "").strip().lower()

        # This window has its own profile and its own session. Being signed in to
        # Facebook in Chrome does nothing here, and the symptom is confusing:
        # Marketplace still returns results (it serves them to anyone) while
        # search and groups return a bare "Not Found", which reads like a broken
        # URL rather than a missing login.
        if "log into facebook" in text or "join or log into" in text \
                or "log in to facebook" in text:
            # Record it, so the window can say so *before* the next scan instead
            # of the user finding out by watching one come back empty.
            service = VENUE_SERVICE.get(self._venue)
            if service:
                self.signed_in.emit(service, False)
            self.reveal("You are not signed in to Facebook in THIS window -- it "
                        "has its own browser session. Sign in here once and Branch "
                        "will remember it, then press Collect.")
            return

        if text.startswith("not found") or "page isn" in text or "isn't available" in text:
            # Interrupting a ten-search scan for one bad page is the wrong trade:
            # while signed in this is usually transient. Skip it, and only ask for
            # help once it has happened twice in a row.
            self._not_found += 1
            if self._not_found < 2 and self._queue:
                self._all_items.update(self._items)
                self._skip_to_next("Facebook did not recognise that search")
                return
            self.reveal("Facebook returned 'Not Found' twice. This window may not "
                        "be signed in -- open facebook.com above, sign in, then "
                        "press Collect.")
            return
        # A gated page that rendered is proof of a working session -- the only
        # positive evidence there is, short of reading the cookie jar, which is
        # the user's and not ours to open.
        service = VENUE_SERVICE.get(self._venue)
        if service:
            self.signed_in.emit(service, True)
        self._not_found = 0
        self._say("Reading the page...")
        QTimer.singleShot(SETTLE_MS, self._begin_scrolling)

    def _begin_scrolling(self) -> None:
        self._started_at = time.monotonic()
        self._stale = 0
        self._extract(then=self._schedule_next)

    def _expand_groups(self, raw: str | None, why: str) -> None:
        """Queue the discovered groups' feeds ahead of anything else."""
        try:
            ids = json.loads(raw or "[]")
        except (TypeError, ValueError):
            ids = []
        found = [(f"https://www.facebook.com/groups/{gid}/", f"group {gid}", False)
                 for gid in ids[:self.MAX_GROUPS]]
        if not found:
            self._say("No groups found for that trade and area.")
            self._skip_to_next(why)
            return
        self._queue = found + self._queue
        self._say(f"Found {len(found)} local groups. Reading them...")
        url, label, expand = self._queue.pop(0)
        self._advance(url, label, f"{len(found)} groups found", expand)

    def _advance(self, url: str, label: str, why: str, expand: bool = False) -> None:
        """Move to the next search, ignoring any advance already in flight.

        Two paths can advance the queue -- a search reaching its own stop
        condition, and the user closing the window -- and when both fired, two
        searches ran at the same time.
        """
        self._cycle += 1
        cycle = self._cycle
        self._say(f"{len(self._all_items)} posts so far ({why}). Next: {label}...")
        QTimer.singleShot(
            SCROLL_INTERVAL_MS * 2 + random.randint(0, SCROLL_JITTER_MS),
            lambda u=url, l=label, c=cycle, e=expand: (
                self.harvest(u, self._venue, l, keep=True, expand=e)
                if c == self._cycle and not self._finished else None))

    def _schedule_next(self) -> None:
        """One page per cycle: scroll, wait for it to load, read, decide."""
        stop = self._stop_reason()
        if stop is not None:
            self._all_items.update(self._items)
            if self._expanding:
                # This page was a list of groups, not of posts. Turn it into the
                # group feeds to read next, then carry on normally.
                self._expanding = False
                self.view.page().runJavaScript(
                    GROUP_LINKS_JS, lambda raw, s=stop: self._expand_groups(raw, s))
                return
            if self._queue and not self._finished:
                url, label, expand = self._queue.pop(0)
                # Paced like everything else: a fresh search immediately after the
                # last one finishes is the part that would look automated.
                self._advance(url, label, stop, expand)
                return
            self._say(f"Read {len(self._all_items)} posts over {self._scrolls} "
                      f"pages ({stop}).")
            self._finished = True
            self.harvested.emit(list(self._all_items.values()))
            return
        wait = SCROLL_INTERVAL_MS + random.randint(-SCROLL_JITTER_MS // 2,
                                                   SCROLL_JITTER_MS // 2)
        QTimer.singleShot(max(600, wait), self._page)

    def _stop_reason(self) -> str | None:
        if self._finished:
            return "stopped"
        if self._stale >= STALE_ROUNDS:
            return "no new posts"
        if self._scrolls >= MAX_SCROLLS:
            return "page limit"
        if time.monotonic() - self._started_at > MAX_SECONDS:
            return "time limit"
        return None

    def _page(self) -> None:
        self._scrolls += 1
        self.view.page().runJavaScript(SCROLL_JS, self._scrolled)

    def _scrolled(self, raw: str | None) -> None:
        try:
            info = json.loads(raw or "{}")
        except (TypeError, ValueError):
            info = {}
        self._rendered = info.get("rendered", 0)
        self._last_scroll_info = info
        # Let the lazily-loaded posts arrive before reading the page again.
        QTimer.singleShot(LOAD_WAIT_MS,
                          lambda: self._extract(then=self._schedule_next))

    def _extract(self, then=None) -> None:
        self._after_extract = then
        self.view.page().runJavaScript(EXTRACT_JS, self._collect)

    def _collect(self, raw: str | None) -> None:
        try:
            found = json.loads(raw or "[]")
        except (TypeError, ValueError):
            found = []
        now = datetime.now(timezone.utc)
        self._strategies = {e.get("how") for e in found if e.get("how")}
        for entry in found:
            url = entry.get("url", "")
            text = entry.get("text", "")
            if not url or url in self._items:
                continue
            when = parse_relative_time(text, now)
            self._items[url] = Item(
                id=f"{self._venue}:{url}", text=text, title=None, url=url,
                venue=self._venue, posted_at=when or now,
                extra={"time_known": when is not None, "link": link_kind(url)},
            )
        before, self._last_count = self._last_count, len(self._items)
        self._stale = 0 if self._last_count != before else self._stale + 1

        if not self._items:
            self._say("Nothing readable found on this page yet -- scroll down, or "
                      "navigate to a page of posts and press Collect.")
        else:
            how = ", ".join(sorted(self._strategies)) or "page"
            total = len(self._all_items) + self._last_count
            self._say(f"Read {total} posts over {self._scrolls} pages ({how})...")

        then, self._after_extract = self._after_extract, None
        if then is not None:
            then()

    def _finish(self) -> None:
        self._finished = True
        self._queue = []
        self._all_items.update(self._items)
        self.harvested.emit(list(self._all_items.values()))
        self.hide()

    def _say(self, message: str) -> None:
        self.status.setText(message)
        self.progress.emit(message)

    def closeEvent(self, event) -> None:
        """Closing the window means "I have dealt with this one", not "stop".

        It used to end the whole scan: he closed the window that appeared for one
        search and the remaining nine were thrown away with it. Only Stop scanning
        button stops everything now.

        Closing a *sign-in* window is different again: nothing was being read, so
        there is nothing to hand back. Emitting an empty harvest here would look
        like a finished scan and re-run the last one.
        """
        if self._logging_in:
            self._logging_in = ""
            try:
                self.view.loadFinished.disconnect(self._login_loaded)
            except (RuntimeError, TypeError):
                pass
            self.hide()
            event.accept()
            return
        self._all_items.update(self._items)
        if self._queue and not self._finished:
            event.accept()
            self.hide()
            self._skip_to_next("you closed the window")
            return
        self._finished = True
        self.harvested.emit(list(self._all_items.values()))
        super().closeEvent(event)

    def _skip_to_next(self, why: str) -> None:
        """Abandon the current search, keep what it found, carry on."""
        if not self._queue:
            self._say(f"Read {len(self._all_items)} posts ({why}).")
            self._finished = True
            self.harvested.emit(list(self._all_items.values()))
            return
        url, label, expand = self._queue.pop(0)
        self._advance(url, label, why, expand)


def link_kind(url: str) -> str:
    """What the extracted link actually points at.

    Facebook search results for GROUP posts carry no post permalink at all --
    checked live: the only anchors on the card are the group, the author and the
    search itself, because the real navigation is a JS click handler with no href.
    So "Open" cannot always reach the post, and the card says which it is rather
    than pretending. Browsing a group directly does give real permalinks, which is
    one more reason joining the local groups is worth doing.
    """
    if re.search(r"/groups/[^/]+/(posts|permalink)/", url):
        return "post"
    if re.search(r"/posts/|/permalink/|story_fbid=", url):
        return "post"
    if re.search(r"/stories/\d+/[^/]+", url):
        return "story"
    if re.search(r"/status/\d+", url):
        return "post"
    if re.search(r"/marketplace/item/", url):
        return "listing"
    if re.search(r"/groups/[^/]+/?$", url):
        return "group"
    if re.search(r"facebook\.com/[^/]+/?$", url):
        return "profile"
    return "page"

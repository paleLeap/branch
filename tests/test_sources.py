"""Source adapters. Network-touching tests are marked and skipped by default:
set BRANCH_LIVE=1 to run them.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from branch.profile import Profile                            # noqa: E402
from branch.sources.base import Fetched, Query, Source        # noqa: E402
from branch.sources.hackernews import HackerNews, _strip_html  # noqa: E402
from branch.sources.reddit import Reddit, subreddits_for       # noqa: E402
from branch.sources.registry import NotBuilt, build            # noqa: E402

LIVE = os.environ.get("BRANCH_LIVE") == "1"


class TestRegistry(unittest.TestCase):
    def test_every_source_reports_its_state(self):
        for key, source in build().items():
            reason = source.available()
            self.assertTrue(reason is None or isinstance(reason, str), key)
            self.assertEqual(source.key, key)

    def test_unbuilt_sources_say_so_rather_than_vanishing(self):
        """A toggle with nothing behind it must explain itself, not silently
        return no results -- that is indistinguishable from finding nothing.

        Nothing in the window is unbuilt today -- Reviews was the last one and
        it was built on 2026-09-16 -- so this pins the behaviour on the class
        rather than on whichever source happens to be waiting next.
        """
        for source in build().values():
            if isinstance(source, NotBuilt):
                with self.subTest(source=source.key):
                    self.assertTrue(source.available())
                    self.assertTrue(source.short_reason)
        stub = NotBuilt("later", "Later", "not built yet", "not built")
        self.assertIn("not built", stub.available())

    def test_unbuilt_fetch_returns_a_reason_and_never_raises(self):
        fetched = NotBuilt("later", "Later", "not built yet", "not built").fetch(
            Query(trade="t"))
        self.assertEqual(fetched.items, [])
        self.assertIn("later", fetched.unavailable)

    def test_youtube_is_gone_rather_than_listed_as_unbuilt(self):
        """Dropped on purpose: nobody goes to YouTube to ask for a plumber, and
        a toggle that will never be built is a promise the window cannot keep."""
        self.assertNotIn("youtube", build())

    def test_craigslist_is_built_rather_than_excluded(self):
        """It was excluded for two reasons and only one of them was true. Their
        terms do forbid automation; robots.txt does NOT disallow /search, and
        they publish posting sitemaps. It is read in the attended browser, which
        is the posture already agreed for Facebook."""
        source = build()["craigslist"]
        self.assertNotIsInstance(source, NotBuilt)
        self.assertTrue(source.interactive)
        self.assertTrue(source.geographic)
        self.assertEqual(source.login_service, "")     # no account needed


class TestHackerNews(unittest.TestCase):
    def setUp(self):
        self.source = HackerNews()

    def test_needs_no_credentials(self):
        self.assertIsNone(self.source.available())

    def test_declares_that_it_has_no_geography(self):
        """The radius setting must not imply a filter that was never applied."""
        self.assertFalse(self.source.geographic)

    def test_no_terms_is_reported_not_raised(self):
        fetched = self.source.fetch(Query(trade="t", terms=[]))
        self.assertEqual(fetched.items, [])
        self.assertIn("hackernews", fetched.unavailable)

    def test_html_is_stripped_from_comment_bodies(self):
        self.assertEqual(_strip_html("<p>a &amp; b<i>c</i>"), "a & b c".replace(" c", "c"))

    @unittest.skipUnless(LIVE, "set BRANCH_LIVE=1 for network tests")
    def test_live_fetch_returns_real_posts(self):
        fetched = self.source.fetch(
            Query(trade="it-support", terms=["backup", "ransomware"], since_hours=336))
        self.assertFalse(fetched.unavailable)
        self.assertGreater(len(fetched.items), 0)
        for item in fetched.items:
            self.assertTrue(item.url.startswith("https://news.ycombinator.com/"))
            self.assertEqual(item.venue, "hackernews")
            self.assertLess(item.age_hours(), 400)


class TestReddit(unittest.TestCase):
    def test_reports_missing_credentials_plainly(self):
        source = Reddit()
        reason = source.available()
        if reason is not None:
            self.assertIn("reddit.com/prefs/apps", reason)

    @unittest.skipUnless(LIVE, "hits the network and paces itself; BRANCH_LIVE=1")
    def test_fetch_without_credentials_does_not_raise(self):
        """It returns real posts without credentials, via the public feeds."""
        fetched = Reddit().fetch(Query(trade="t", location="Dallas, TX", terms=["x"]))
        self.assertIsInstance(fetched, Fetched)

    def test_reddit_reads_more_than_the_newest_posts(self):
        """The new-posts feed caps at 100 across every town -- a few hours of a
        busy metro. Comments are a hundred more, and are where "anyone know a
        good plumber?" usually lives, since it is a reply more often than a post."""
        source = (ROOT / "branch" / "sources" / "reddit.py").read_text(encoding="utf-8")
        self.assertIn("/comments/.rss", source)
        self.assertIn("search.rss", source)

    def test_reddit_spaces_its_requests(self):
        """Anonymous reads allow about one a minute, measured."""
        self.assertGreaterEqual(Reddit.SPACING_SECONDS, 15)

    def test_subreddit_guessing(self):
        """Locality is in the container: read r/Dallas, not the site for "Dallas"."""
        self.assertIn("Dallas", subreddits_for("Dallas, TX"))
        self.assertIn("FortWorth", subreddits_for("Fort Worth, TX"))
        self.assertEqual(subreddits_for(""), [])
        self.assertEqual(subreddits_for(", TX"), [])

    def test_radius_becomes_a_list_of_local_subreddits(self):
        """A multireddit fetches them all in ONE request, which is what makes the
        radius usable at roughly one anonymous request per minute."""
        from branch.sources.reddit import subreddits_in_radius
        query = Query(trade="t", location="Dallas, TX",
                      coordinates=(32.7831, -96.8067), radius_miles=50)
        subs = subreddits_in_radius(query)
        self.assertGreater(len(subs), 3)
        self.assertEqual(subs[0], "Dallas")
        self.assertIn("FortWorth", subs)

    def test_a_tighter_radius_reads_fewer_places(self):
        from branch.sources.reddit import subreddits_in_radius
        def at(miles):
            return subreddits_in_radius(Query(
                trade="t", location="Dallas, TX",
                coordinates=(32.7831, -96.8067), radius_miles=miles), limit=20)
        self.assertLess(len(at(10)), len(at(60)))

    def test_works_with_no_credentials_at_all(self):
        """/r/x/new.json is 403 to anonymous clients but /r/x/new.rss is not."""
        self.assertIsNone(Reddit().available())
        self.assertEqual(Reddit().mode(), "feed" if not os.environ.get(
            "BRANCH_REDDIT_CLIENT_ID") else "search")

    @unittest.skipUnless(LIVE, "set BRANCH_LIVE=1 for network tests")
    def test_live_reads_real_local_posts(self):
        import time
        source = Reddit()
        query = Query(trade="plumbing", location="Dallas, TX",
                      coordinates=(32.7831, -96.8067), radius_miles=50,
                      since_hours=720)
        for _ in range(6):
            fetched = source.fetch(query)
            if fetched.items:
                break
            time.sleep(30)
        self.assertGreater(len(fetched.items), 0)
        self.assertTrue(all(i.venue.startswith("reddit:r/") for i in fetched.items))
        self.assertGreater(len({i.venue for i in fetched.items}), 1)


class TestContract(unittest.TestCase):
    """Rules every adapter obeys, checked against all of them at once."""

    def test_no_adapter_raises_on_a_hopeless_query(self):
        for key, source in build().items():
            with self.subTest(source=key):
                fetched = source.fetch(Query(trade="", terms=[]))
                self.assertIsInstance(fetched, Fetched)

    def test_every_adapter_declares_a_cost(self):
        for key, source in build().items():
            with self.subTest(source=key):
                self.assertIsInstance(source.cost_per_scan, float)
                self.assertGreaterEqual(source.cost_per_scan, 0.0)


class TestWritesNothing(unittest.TestCase):
    """Branch reads. It does not keep what it reads.

    The only files Branch ever writes are the user's *own* things: the
    approximate location it worked out once, and the tuning they typed. Nothing
    about a person whose post was scanned is persisted anywhere, ever.
    """

    def test_a_scan_creates_no_files(self):
        import tempfile
        from branch.engine import scan
        from branch.profile import Profile
        from branch.sources.registry import build

        watched = Path(tempfile.mkdtemp())
        before = set(watched.rglob("*"))

        profile = Profile.load(ROOT / "profiles" / "plumbing.yaml")
        items = []
        for source in build().values():
            items.extend(source.fetch(Query(trade="plumbing", terms=[])).items)
        scan(items, profile)

        self.assertEqual(set(watched.rglob("*")), before)

    @staticmethod
    def _writes_in(path: Path) -> list[str]:
        """Calls that could put bytes on disk.

        Done with the AST rather than by searching for "open(", which a first
        attempt did -- and which matches urlopen(), so it flagged every adapter
        that fetches anything.
        """
        import ast
        # "replace" is deliberately absent: str.replace collides with
        # Path.replace, and text munging is everywhere in this codebase.
        writers = {"write", "write_text", "write_bytes", "writelines",
                   "mkdir", "touch", "dump", "unlink", "rename"}
        found: list[str] = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in writers:
                found.append(func.attr)
            elif isinstance(func, ast.Name) and func.id == "open":
                mode = next((a.value for a in node.args[1:2]
                             if isinstance(a, ast.Constant)), "r")
                if any(m in str(mode) for m in ("w", "a", "x", "+")):
                    found.append("open(write)")
        return found

    def test_feed_cache_never_touches_the_filesystem(self):
        """The cache exists to avoid asking a server twice in a minute. It must
        not become a copy of other people's posts sitting on disk."""
        self.assertEqual(self._writes_in(ROOT / "branch" / "sources" / "feeds.py"), [])

    def test_no_adapter_writes_to_disk(self):
        for name in ("hackernews.py", "reddit.py", "custom.py", "registry.py", "base.py"):
            with self.subTest(module=name):
                self.assertEqual(
                    self._writes_in(ROOT / "branch" / "sources" / name), [])

    def test_the_engine_writes_nothing_either(self):
        for name in ("engine.py", "models.py", "text.py", "runner.py"):
            with self.subTest(module=name):
                self.assertEqual(self._writes_in(ROOT / "branch" / name), [])


class TestCustomFeeds(unittest.TestCase):
    def test_parses_a_feed_list(self):
        import tempfile
        from branch.sources import custom
        path = Path(tempfile.mkdtemp()) / "feeds.txt"
        path.write_text(
            "# a comment\n"
            "\n"
            "https://example.invalid/a.rss\n"
            "My Forum = https://forum.invalid/latest.rss\n"
            "not-a-url\n", encoding="utf-8")
        original = custom.config_path
        custom.config_path = lambda: path
        try:
            feeds = custom.configured_feeds()
        finally:
            custom.config_path = original
        self.assertEqual(feeds, [("example.invalid", "https://example.invalid/a.rss"),
                                 ("My Forum", "https://forum.invalid/latest.rss")])

    def test_says_where_to_put_feeds_when_empty(self):
        from branch.sources.custom import CustomFeeds
        reason = CustomFeeds().available()
        if reason is not None:
            self.assertIn("feeds.txt", reason)


class TestFeedParsing(unittest.TestCase):
    def test_reads_atom(self):
        from branch.sources.feeds import parse
        xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
               '<title>T</title><content>&lt;p&gt;body&lt;/p&gt;</content>'
               '<link href="https://x.invalid/1"/><id>abc</id>'
               '<published>2026-09-15T01:00:00+00:00</published>'
               '<author><name>/u/someone</name></author></entry></feed>')
        entries = parse(xml)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].title, "T")
        self.assertEqual(entries[0].body, "body")
        self.assertEqual(entries[0].author, "/u/someone")

    def test_reads_rss(self):
        from branch.sources.feeds import parse
        xml = ('<rss><channel><item><title>T</title>'
               '<description>body</description><link>https://x.invalid/1</link>'
               '<pubDate>Mon, 15 Sep 2026 01:00:00 +0000</pubDate>'
               '</item></channel></rss>')
        entries = parse(xml)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].url, "https://x.invalid/1")

    def test_malformed_feed_yields_nothing_rather_than_raising(self):
        from branch.sources.feeds import parse
        self.assertEqual(parse("<not xml"), [])
        self.assertEqual(parse(""), [])

    def test_entries_without_a_date_are_dropped(self):
        """Recency scoring is meaningless without one."""
        from branch.sources.feeds import parse
        xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
               '<title>T</title><link href="https://x.invalid/1"/></entry></feed>')
        self.assertEqual(parse(xml), [])


class TestNewSources(unittest.TestCase):
    """Lemmy, Mastodon and Discourse. All open, none of them geographic."""

    def test_all_three_need_no_credentials(self):
        from branch.sources.lemmy import Lemmy
        from branch.sources.mastodon import Mastodon
        self.assertIsNone(Lemmy().available())
        self.assertIsNone(Mastodon().available())

    def test_none_of_them_claim_to_be_geographic(self):
        """The radius control must not imply a filter none of these apply."""
        from branch.sources.discourse import Discourse
        from branch.sources.lemmy import Lemmy
        from branch.sources.mastodon import Mastodon
        for source in (Lemmy(), Mastodon(), Discourse()):
            self.assertFalse(source.geographic, source.key)

    def test_mastodon_turns_phrases_into_tags(self):
        from branch.sources.mastodon import _tag
        self.assertEqual(_tag("water heater"), "waterheater")
        self.assertEqual(_tag("won't start"), "wontstart")

    def test_discourse_is_driven_by_the_trade_profile(self):
        """Which forums matter is a per-trade question, so the profile answers it."""
        profile = Profile.load(ROOT / "profiles" / "it-support.yaml")
        self.assertTrue(profile.forums)
        self.assertTrue(all(f.startswith("http") for f in profile.forums))

    def test_profile_ignores_junk_forum_entries(self):
        profile = Profile.from_dict({"trade": "t", "forums": ["nonsense", 42,
                                                              "https://ok.invalid/"]})
        self.assertEqual(profile.forums, ["https://ok.invalid"])

    def test_discourse_orders_by_recency(self):
        """Discourse ranks by relevance by default, which returns mostly old
        threads -- almost all outside any useful time window."""
        source = (ROOT / "branch" / "sources" / "discourse.py").read_text(encoding="utf-8")
        self.assertIn("order:latest", source)

    def test_discourse_without_forums_says_where_to_put_them(self):
        from branch.sources.discourse import Discourse
        fetched = Discourse().fetch(Query(trade="t", terms=["x"], forums=[]))
        self.assertEqual(fetched.items, [])
        self.assertIn("forums", " ".join(fetched.unavailable.values()))

    @unittest.skipUnless(LIVE, "set BRANCH_LIVE=1 for network tests")
    def test_live_all_open_sources_return_something_or_say_why(self):
        from branch.sources.registry import build
        profile = Profile.load(ROOT / "profiles" / "it-support.yaml")
        query = Query(trade="it-support", terms=profile.prompts(3),
                      forums=profile.forums, location="Dallas, TX",
                      coordinates=(32.7831, -96.8067), since_hours=720)
        for key in ("hackernews", "lemmy", "mastodon", "forums"):
            with self.subTest(source=key):
                fetched = build()[key].fetch(query)
                self.assertTrue(fetched.items or fetched.unavailable,
                                f"{key} returned nothing and gave no reason")


class TestFacebook(unittest.TestCase):
    """Marketplace and post search, through the user's own browser."""

    def setUp(self):
        from branch.sources.facebook import FacebookPosts, Marketplace
        self.marketplace = Marketplace()
        self.posts = FacebookPosts()
        self.query = Query(trade="motorcycle-repair", location="Fort Worth, TX",
                           radius_miles=25, terms=["carburetor"])

    def test_they_are_interactive_not_fetched(self):
        """They need a logged-in browser, which lives on the UI thread."""
        self.assertTrue(self.marketplace.interactive)
        self.assertTrue(self.posts.interactive)

    def test_fetch_says_why_rather_than_returning_silence(self):
        fetched = self.marketplace.fetch(self.query)
        self.assertEqual(fetched.items, [])
        self.assertIn("browser", " ".join(fetched.unavailable.values()))

    def test_the_runner_skips_them_instead_of_calling_fetch(self):
        """The account is patched in. Without that this test asks whether the
        machine running it happens to be signed in to Facebook -- it passed
        here and failed on the Windows runner for exactly that reason."""
        from unittest import mock
        from branch.profile import Profile
        from branch.runner import ScanRunner
        runner = ScanRunner(ROOT, {"plumbing": Profile.load(ROOT / "profiles" / "plumbing.yaml")})
        query = {"trade_slug": "plumbing", "location": "Dallas, TX", "narrow": "",
                 "coordinates": (32.78, -96.80), "radius": "25 miles",
                 "since": "Last hour", "sources": ["marketplace"]}
        with mock.patch.object(ScanRunner, "_signed_in",
                               staticmethod(lambda: {"facebook"})):
            result = runner._collect(query, runner.profiles["plumbing"])
        self.assertNotIn("marketplace", result.unavailable)

    def test_without_the_account_it_says_so_rather_than_opening_a_browser(self):
        from unittest import mock
        from branch.profile import Profile
        from branch.runner import ScanRunner
        runner = ScanRunner(ROOT, {"plumbing": Profile.load(ROOT / "profiles" / "plumbing.yaml")})
        query = {"trade_slug": "plumbing", "location": "Dallas, TX", "narrow": "",
                 "coordinates": (32.78, -96.80), "radius": "25 miles",
                 "since": "Last hour", "sources": ["marketplace"]}
        with mock.patch.object(ScanRunner, "_signed_in", staticmethod(lambda: set())):
            result = runner._collect(query, runner.profiles["plumbing"])
        self.assertIn("sign in to Facebook", result.unavailable["marketplace"])

    def test_marketplace_carries_the_radius(self):
        from branch.sources.facebook import marketplace_url
        url = marketplace_url(self.query)
        self.assertIn("/marketplace/fortworth/", url)
        self.assertIn("radius_km=40", url)             # 25 miles
        self.assertIn("creation_time_descend", url)    # newest first

    def test_marketplace_is_the_only_wired_source_with_a_real_radius(self):
        from branch.sources.registry import build
        geographic = [k for k, s in build().items() if s.geographic]
        self.assertIn("marketplace", geographic)

    def test_city_slug(self):
        from branch.sources.facebook import city_slug
        self.assertEqual(city_slug("Fort Worth, TX"), "fortworth")
        self.assertEqual(city_slug(""), "")

    def test_post_search_asks_the_way_a_customer_would(self):
        """Correction to an earlier conclusion: /search/ paths are NOT dead.
        Signed out every Facebook path returns "Not Found"; signed in, search
        works. The 404 was a missing session, not a missing endpoint.

        The query is how customers ask -- "need a plumber Dallas" -- not the
        trade's vocabulary, which finds people *discussing* the subject."""
        from branch.sources.facebook import posts_url
        url = posts_url(Query(trade="plumbing", location="Dallas, TX",
                              ask="need a plumber"))
        self.assertIn("/search/posts", url)
        self.assertIn("need+a+plumber", url)
        self.assertIn("Dallas", url)

    def test_every_profile_names_its_own_ask(self):
        """The fallback phrases are trade-agnostic on purpose ("any
        recommendations"), so searching one finds recommendations for
        everything."""
        from branch.profile import Profile
        for slug, prof in Profile.load_all(ROOT / "profiles").items():
            with self.subTest(trade=slug):
                self.assertTrue(prof.ask_terms, slug)
                self.assertNotIn("any recommendation", prof.ask_phrases(1)[0])

    def test_skeleton_filler_is_stripped_before_truncation(self):
        """Lazy-loading placeholders render "Facebook" dozens of times -- 297 of
        the 1200 characters we keep, in the run that found this."""
        from branch.ui.browser import EXTRACT_JS
        self.assertIn("(?:Facebook", EXTRACT_JS)

    def test_search_results_are_extracted_too(self):
        """Search results are aria-posinset children of a role="feed", not
        role="article" -- which is why post search returned nothing at first."""
        from branch.ui.browser import EXTRACT_JS
        self.assertIn("aria-posinset", EXTRACT_JS)
        self.assertIn("'search'", EXTRACT_JS)

    def test_browser_detects_a_signed_out_session(self):
        """This window has its own profile; being signed in elsewhere does
        nothing, and the symptom reads like a broken URL."""
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        self.assertIn("log into facebook", source)
        self.assertIn("its own browser session", source)

    def test_post_search_does_not_claim_geography(self):
        """It filters on *tagged* location; most posts carry no tag."""
        self.assertFalse(self.posts.geographic)

    def test_interactive_targets_are_offered_to_the_window(self):
        from unittest import mock
        from branch.profile import Profile
        from branch.runner import ScanRunner
        runner = ScanRunner(ROOT, {"plumbing": Profile.load(ROOT / "profiles" / "plumbing.yaml")})
        with mock.patch.object(ScanRunner, "_signed_in",
                               staticmethod(lambda: {"facebook"})):
            targets = runner.interactive_targets({
                "trade_slug": "plumbing", "location": "Dallas, TX", "narrow": "",
                "coordinates": (32.78, -96.80), "radius": "25 miles",
                "since": "Last week", "sources": ["marketplace", "reddit"]})
        self.assertEqual([t[0] for t in targets], ["marketplace"])
        self.assertTrue(targets[0][1].startswith("https://www.facebook.com/marketplace/"))


class TestHarvestBrowserRules(unittest.TestCase):
    """The browser is attended, paced and capped. Those are the safeguards that
    keep it from costing the user their own account, so they are pinned here."""

    def setUp(self):
        self.source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")

    def test_scrolling_is_paced_not_fast(self):
        import re as _re
        interval = int(_re.search(r"SCROLL_INTERVAL_MS = (\d+)", self.source).group(1))
        self.assertGreaterEqual(interval, 1000)

    def test_scrolling_is_capped(self):
        import re as _re
        self.assertTrue(_re.search(r"MAX_SCROLLS = \d+", self.source))

    def test_it_never_handles_a_password(self):
        for forbidden in ("password", "setHtml(", "login", "credentials"):
            self.assertNotIn(f"{forbidden}=", self.source.lower())

    def test_relative_times_are_parsed_or_reported_unknown(self):
        from datetime import datetime, timezone
        from branch.ui.browser import parse_relative_time
        now = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
        self.assertEqual(parse_relative_time("just now", now), now)
        self.assertEqual((now - parse_relative_time("3 days ago", now)).days, 3)
        self.assertEqual((now - parse_relative_time("5 hrs ago", now)).seconds // 3600, 5)
        # Unparseable must be None, not silently "now" -- recency scoring depends
        # on it, and a fake timestamp would rank an old listing as fresh.
        self.assertIsNone(parse_relative_time("no time here", now))

    def test_extraction_js_is_a_raw_string(self):
        """It contains \\s, which Python reads as an invalid escape in a normal
        string -- a SyntaxWarning today and an error in a future version."""
        from branch.ui.browser import EXTRACT_JS
        self.assertIn(r"\s+", EXTRACT_JS)

    def test_extraction_has_a_generic_fallback(self):
        """The Facebook-specific selectors are the part most likely to break.
        Returning nothing silently would be worse than returning rough blocks."""
        from branch.ui.browser import EXTRACT_JS
        self.assertIn("'generic'", EXTRACT_JS)
        self.assertIn("'marketplace'", EXTRACT_JS)
        self.assertIn("'article'", EXTRACT_JS)

    def test_paging_works_through_several_searches(self):
        """One Facebook search returns about four results and then stops growing
        -- measured live. Depth comes from asking more than one question."""
        from branch.profile import Profile
        from branch.sources.facebook import posts_urls
        prof = Profile.load(ROOT / "profiles" / "plumbing.yaml")
        urls = posts_urls(Query(trade="plumbing", location="Dallas, TX",
                                asks=prof.ask_phrases(3)))
        self.assertEqual(len(urls), 3)
        self.assertEqual(len({u for u, _l in urls}), 3)
        for url, label in urls:
            self.assertIn("/search/posts", url)
            self.assertIn("Dallas", url)

    def test_paging_stops_when_the_feed_stops_growing(self):
        """Not on an arbitrary limit: the stale counter is the honest signal."""
        from branch.ui import browser
        self.assertGreaterEqual(browser.MAX_SCROLLS, 30)
        self.assertGreaterEqual(browser.STALE_ROUNDS, 2)
        self.assertGreater(browser.MAX_SECONDS, 60)

    def test_scrolling_uses_scroll_into_view_for_the_virtualised_feed(self):
        """Setting scrollTop does not make a virtualised feed load the next
        batch; bringing the last rendered item into view does."""
        from branch.ui.browser import SCROLL_JS
        self.assertIn("scrollIntoView", SCROLL_JS)

    def test_scroll_pacing_is_jittered(self):
        """A scroll every 1500ms exactly is its own signature."""
        from branch.ui import browser
        self.assertGreater(browser.SCROLL_JITTER_MS, 0)

    def test_link_kind_names_what_the_url_points_at(self):
        """Facebook search results for group posts carry no post permalink at
        all -- only the group, the author and the search. "Open" therefore has to
        say where it is actually going."""
        from branch.ui.browser import link_kind
        self.assertEqual(link_kind("https://www.facebook.com/groups/1/posts/2/"), "post")
        self.assertEqual(link_kind("https://www.facebook.com/groups/1494427604106723/"), "group")
        self.assertEqual(link_kind("https://www.facebook.com/marketplace/item/9/"), "listing")
        self.assertEqual(link_kind("https://www.facebook.com/derrick.butts.50"), "profile")

    def test_tracking_params_are_stripped_but_others_kept(self):
        """Stripping the whole query broke the one permalink form search does
        offer: /stories/<id>/<token>/?view_single loses the post without it."""
        from branch.ui.browser import EXTRACT_JS
        self.assertIn("__", EXTRACT_JS)
        self.assertIn("searchParams", EXTRACT_JS)

    def test_browser_is_hidden_unless_it_needs_the_user(self):
        """Verified to cost nothing: a hidden view with a real size loads,
        lazy-renders and extracts exactly as a visible one does."""
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        harvest = source.split("def harvest(self,")[1].split("def ")[0]
        self.assertNotIn("self.show()", harvest)
        self.assertIn("_always_visible", harvest)

    def test_it_reveals_itself_when_sign_in_is_needed(self):
        """A login page, a Not Found or a failed load are the only moments a
        person can help. Hiding those would leave a scan silently stuck."""
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        after_load = source.split("def _after_load")[1].split("\n    def ")[0]
        self.assertGreaterEqual(after_load.count("self.reveal("), 2)
        loaded = source.split("def _loaded")[1].split("\n    def ")[0]
        self.assertIn("self.reveal(", loaded)

    def test_it_can_be_watched_on_request(self):
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        self.assertIn("BRANCH_SHOW_BROWSER", source)

    def test_closing_the_window_skips_one_search_not_the_scan(self):
        """It used to end everything: closing the window that appeared for one
        search threw away the nine still queued."""
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        close = source.split("def closeEvent")[1].split("\n    def ")[0]
        self.assertIn("_skip_to_next", close)
        self.assertIn("self._queue", close)

    def test_only_stop_scanning_ends_the_scan(self):
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        self.assertIn("Stop scanning", source)
        self.assertIn("Skip this search", source)
        finish = source.split("def _finish")[1].split("\n    def ")[0]
        self.assertIn("self._finished = True", finish)

    def test_one_not_found_is_skipped_rather_than_interrupting(self):
        """Interrupting a ten-search scan for one bad page is the wrong trade;
        while signed in a Not Found is usually transient."""
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        after = source.split("def _after_load")[1].split("\n    def ")[0]
        self.assertIn("_not_found", after)
        self.assertIn("_skip_to_next", after)

    def test_a_finished_scan_emits_by_itself(self):
        """Until now only Stop scanning or closing the window emitted anything,
        so a scan that ran cleanly to the end of its queue just sat there."""
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        schedule = source.split("def _schedule_next")[1].split("\n    def ")[0]
        self.assertIn("self.harvested.emit", schedule)

    def test_queue_advances_are_guarded_against_each_other(self):
        """A search reaching its stop condition and the user closing the window
        both advance the queue; when both fired, two searches ran at once."""
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        advance = source.split("def _advance")[1].split("\n    def ")[0]
        self.assertIn("self._cycle += 1", advance)
        self.assertIn("c == self._cycle", advance)


class TestX(unittest.TestCase):
    """X through the browser, not the API."""

    def setUp(self):
        from branch.sources.x import X
        self.source = X()
        self.query = Query(trade="plumbing", location="Dallas, TX",
                           radius_miles=25, asks=["need a plumber"])

    def test_the_api_price_does_not_apply(self):
        """$0.005/post is the API's price. The browser is not the API."""
        self.assertEqual(self.source.cost_per_scan, 0.0)

    def test_it_is_attended_like_facebook(self):
        self.assertTrue(self.source.interactive)

    def test_it_does_not_use_retired_geo_operators(self):
        """I claimed near:/within: gave X a real radius. Tested signed in, they
        return an explicit "No results" for every query -- including ones that
        return results without them. They do not narrow a search, they empty it,
        so leaving them in would have made every X scan silently return nothing."""
        self.assertFalse(self.source.geographic)
        url = self.source.url(self.query)
        self.assertNotIn("near%3A", url)
        self.assertNotIn("within%3A", url)
        self.assertIn("Dallas", url)

    def test_it_sorts_by_newest_not_by_popularity(self):
        """The default ranking surfaces popular old posts, and a month-old lead
        has already hired someone."""
        self.assertIn("f=live", self.source.url(self.query))

    def test_one_url_per_phrasing(self):
        from branch.sources.x import search_urls
        urls = search_urls(Query(trade="t", location="Dallas, TX", radius_miles=10,
                                 asks=["a", "b", "c"]))
        self.assertEqual(len(urls), 3)

    def test_a_status_link_is_recognised_as_a_post(self):
        from branch.ui.browser import link_kind
        self.assertEqual(link_kind("https://x.com/someone/status/1234567890"), "post")

    def test_the_extractor_knows_what_a_tweet_looks_like(self):
        from branch.ui.browser import EXTRACT_JS
        self.assertIn('data-testid="tweet"', EXTRACT_JS)
        self.assertIn("'tweet'", EXTRACT_JS)

    def test_the_browser_does_not_announce_itself_as_embedded(self):
        """Qt's default user agent says "QtWebEngine/6.10.2" and X refuses to run
        its login flow for an embedded browser. Same Chromium underneath; only
        the string differs."""
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        self.assertIn("setHttpUserAgent", source)
        self.assertNotIn('"QtWebEngine', source.split("setHttpUserAgent")[1][:400])

    def test_the_user_agent_tracks_the_real_engine_version(self):
        """Taken from the engine's own string rather than invented, so it does
        not drift into claiming a Chrome that is not underneath."""
        source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")
        self.assertIn('part.startswith("Chrome/")', source)


class TestFacebookGroups(unittest.TestCase):
    """Find the local groups, then read them."""

    def setUp(self):
        from branch.sources.facebook import FacebookGroups
        self.source = FacebookGroups()
        self.query = Query(trade="plumbing", location="Dallas, TX")

    def test_a_public_group_needs_no_joining(self):
        """Checked live: a public group's feed renders without membership, and
        unlike search results it carries real /posts/ permalinks."""
        self.assertTrue(self.source.interactive)
        self.assertTrue(self.source.geographic)

    def test_it_discovers_groups_rather_than_needing_them_configured(self):
        targets = self.source.urls(self.query)
        self.assertGreaterEqual(len(targets), 2)
        for url, label, kind in targets:
            self.assertEqual(kind, "discover")
            self.assertIn("/search/groups", url)

    def test_it_looks_for_customers_not_only_for_trades(self):
        """"<city> <trade>" alone finds contractor groups -- the supply side. A
        live run returned five of them and zero leads."""
        from branch.sources.facebook import group_discovery_urls
        joined = " ".join(group_discovery_urls(self.query))
        self.assertIn("homeowners", joined)
        self.assertIn("recommendations", joined)

    def test_group_links_are_collected_from_a_discovery_page(self):
        from branch.ui.browser import GROUP_LINKS_JS
        self.assertIn("/groups/", GROUP_LINKS_JS)

    def test_discovery_is_capped(self):
        from branch.ui.browser import HarvestBrowser
        self.assertLessEqual(HarvestBrowser.MAX_GROUPS, 8)

    def test_a_group_post_link_is_a_real_post(self):
        from branch.ui.browser import link_kind
        self.assertEqual(
            link_kind("https://www.facebook.com/groups/123/posts/456/"), "post")


class TestSourceStates(unittest.TestCase):
    """What the window is told about each source, and why it matters.

    Three answers, not two. "Needs a sign-in" is the one state the user can
    actually do something about, and collapsing it into "unavailable" would hide
    the fix -- which is what happened before this existed: Facebook looked ready,
    scanned, and came back empty because the browser's own session was logged out.
    """

    @staticmethod
    def _states(connected=frozenset()):
        from branch.sources.registry import build
        return {k: s.state(set(connected)) for k, s in build().items()}

    def test_the_sources_that_need_nothing_are_ready(self):
        # Marketplace left this list when it started asking for the Facebook
        # account every other Facebook surface asks for.
        states = self._states()
        for key in ("reddit", "craigslist"):
            with self.subTest(source=key):
                self.assertEqual(states[key].state, "ready")
                self.assertTrue(states[key].selectable)

    def test_unbuilt_and_excluded_sources_are_unavailable_with_a_reason(self):
        states = self._states()
        # Reviews used to be here. It runs now -- API with a key, Branch's own
        # browser on Google Maps without one -- so My feeds carries the rule.
        for key in ("feeds",):
            with self.subTest(source=key):
                self.assertEqual(states[key].state, "unavailable")
                self.assertFalse(states[key].selectable)
                self.assertTrue(states[key].reason, "no reason given")
                self.assertTrue(states[key].short, "no short label given")

    def test_every_unavailable_source_has_a_short_label_that_fits(self):
        """The full sentence is longer than the column is wide, so a short one
        goes on the face of it. Long enough to mean something, short enough to
        sit next to the name."""
        for key, state in self._states().items():
            if state.state == "unavailable":
                with self.subTest(source=key):
                    self.assertLessEqual(len(state.short), 16)
                    self.assertNotEqual(state.short, "unavailable",
                                        f"{key} never declared a short_reason")

    def test_facebook_and_x_ask_for_a_sign_in_and_say_where(self):
        states = self._states()
        for key, service in (("facebook", "Facebook"), ("groups", "Facebook"),
                             ("x", "X")):
            with self.subTest(source=key):
                self.assertEqual(states[key].state, "login")
                self.assertEqual(states[key].service, service)
                self.assertTrue(states[key].login_url.startswith("https://"))
                # Still tickable: ticking it is how the user reaches the sign-in.
                self.assertTrue(states[key].selectable)

    def test_marketplace_asks_for_the_account_it_needs(self):
        """It used to claim a logged-out visitor got results. Whether or not
        that still holds, it was the one Facebook surface showing a tick to
        somebody with no account -- telling him he was set up when he was not,
        which is worse than sending him to a sign-in he did not strictly need."""
        self.assertEqual(self._states()["marketplace"].state, "login")
        self.assertEqual(self._states(connected={"facebook"})["marketplace"].state,
                         "ready")

    def test_a_signed_in_service_stops_asking(self):
        states = self._states(connected={"facebook"})
        self.assertEqual(states["facebook"].state, "ready")
        self.assertEqual(states["groups"].state, "ready")
        self.assertEqual(states["x"].state, "login")   # a different account

    def test_the_runner_reports_a_state_for_every_source(self):
        from branch.profile import Profile
        from branch.runner import ScanRunner
        from branch.sources.registry import build
        runner = ScanRunner(ROOT, Profile.load_all(ROOT / "profiles"))
        states = runner.source_states()
        self.assertEqual(set(states), set(build()))


class TestSignInBrowsing(unittest.TestCase):
    """The browser's side of sign-in, checked in the source.

    These are source-level assertions for the same reason the other browser
    tests are: driving a real QtWebEngine session in a test would mean logging
    in to Facebook, which is exactly what no test may ever do.
    """

    @staticmethod
    def _source() -> str:
        return (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")

    def test_the_sign_in_window_collects_nothing(self):
        """It is opened for the user, not for a scan. Anything else would be
        harvesting a page the user opened to type a password into."""
        body = self._source().split("def open_login")[1].split("\n    def ")[0]
        self.assertNotIn("_begin_scrolling", body)
        self.assertNotIn("_extract", body)
        self.assertIn("self._queue = []", body)

    def test_closing_a_sign_in_window_does_not_look_like_a_finished_scan(self):
        """Emitting an empty harvest here re-runs the last scan, which is a
        confusing thing to have happen after signing in."""
        close = self._source().split("def closeEvent")[1].split("\n    def ")[0]
        self.assertIn("self._logging_in", close)
        head = close.split("self._all_items.update")[0]
        self.assertIn("return", head)

    def test_a_login_wall_during_a_scan_is_recorded(self):
        """The window must be able to say "sign in" before the next scan rather
        than after another empty one."""
        after_load = self._source().split("def _after_load")[1].split("\n    def ")[0]
        self.assertIn("signed_in.emit", after_load)

    def test_the_sign_in_watcher_is_detached_by_bookkeeping_not_by_exception(self):
        """PySide6 does not raise when a disconnect finds nothing attached -- it
        emits a RuntimeWarning and returns False. The try/except around it
        caught nothing, and the warning reached the user's log."""
        source = self._source()
        self.assertIn("_login_hooked", source)
        unhook = source.split("def _unhook_login")[1].split("\n    def ")[0]
        self.assertIn("if not self._login_hooked", unhook)

    def test_the_browser_never_reads_the_password_field(self):
        """The user types their password into the service's own form. Branch is
        the window around it and nothing else -- it does not fill that field, it
        does not read it back, and it does not go looking for it."""
        source = self._source().lower()
        for banned in ("type=password", "type='password'", 'type="password"',
                       "autofill", "document.cookie", "localstorage.getitem"):
            self.assertNotIn(banned, source, f"browser.py touches {banned!r}")


class TestCraigslist(unittest.TestCase):
    """Area picking and URL building. No network: the area table is bundled."""

    def setUp(self):
        from branch.sources import craigslist
        self.cl = craigslist
        self.areas = craigslist.load_areas()

    def test_the_area_table_is_bundled_and_covers_north_america(self):
        self.assertGreater(len(self.areas), 400)
        slugs = {a.slug for a in self.areas}
        for expected in ("dallas", "sfbay", "newyork", "chicago", "toronto",
                         "miami", "stlouis", "vancouver"):
            self.assertIn(expected, slugs)

    def test_every_area_has_real_coordinates(self):
        for area in self.areas:
            with self.subTest(area=area.slug):
                self.assertTrue(-180 <= area.lon <= 180)
                self.assertTrue(-90 <= area.lat <= 90)
                self.assertNotEqual((area.lat, area.lon), (0.0, 0.0))

    def test_the_nearest_area_is_the_one_a_person_would_name(self):
        """From Forney, Texas the answer is Dallas -- the same judgement the
        location field makes, and for the same reason."""
        self.assertEqual(self.cl.nearest_area(32.75, -96.47, self.areas).slug, "dallas")
        self.assertEqual(self.cl.nearest_area(37.77, -122.41, self.areas).slug, "sfbay")
        self.assertEqual(self.cl.nearest_area(43.70, -79.39, self.areas).slug, "toronto")

    def test_a_trade_reads_the_categories_its_customers_post_in(self):
        self.assertEqual(self.cl.categories_for("moving"), ("lbg", "ggg"))
        self.assertEqual(self.cl.categories_for("IT Support"), ("cpg", "ggg"))
        self.assertEqual(self.cl.categories_for("wedding-photography"), ("crg", "evg", "ggg"))

    def test_an_unrecognised_trade_reads_every_gig_rather_than_none(self):
        """Silently narrowing a trade we have no opinion about would be the
        quiet kind of failure this program keeps having to design out."""
        self.assertEqual(self.cl.categories_for("aardvark grooming"), ("ggg",))

    def test_it_never_reads_the_services_offered_board(self):
        """`bbb` is tradesmen advertising -- the competition. Reading it would
        fill the results with exactly what the profiles exclude."""
        self.assertNotIn("bbb", self.cl.CATEGORIES)
        urls = self.cl.search_urls(Query(trade="plumbing", location="Dallas, TX",
                                         coordinates=(32.78, -96.80)))
        for url, _ in urls:
            self.assertNotIn("cat=bbb", url)

    def test_urls_are_area_scoped(self):
        urls = self.cl.search_urls(Query(trade="moving", location="Dallas, TX",
                                         coordinates=(32.78, -96.80)))
        self.assertTrue(urls)
        for url, label in urls:
            self.assertIn("/search/area/dallas", url)
            self.assertIn("Dallas, TX", label)

    def test_a_typed_narrowing_becomes_one_extra_search_not_a_filter(self):
        """Craigslist's own search is weak; narrowing all six category pages to
        nothing is the likelier failure than missing one keyword search."""
        plain = self.cl.search_urls(Query(trade="moving", coordinates=(32.78, -96.80)))
        narrowed = self.cl.search_urls(Query(trade="moving", coordinates=(32.78, -96.80),
                                             narrow="need a mover"))
        self.assertEqual(len(narrowed), len(plain) + 1)
        self.assertIn("query=need+a+mover", narrowed[-1][0])

    def test_no_location_means_no_searches_rather_than_a_wrong_city(self):
        self.assertEqual(self.cl.search_urls(Query(trade="moving")), [])

    def test_it_needs_no_account(self):
        from branch.sources.craigslist import Craigslist
        self.assertEqual(Craigslist().login_service, "")
        self.assertIsNone(Craigslist().available())

    def test_it_says_so_if_the_bundled_table_is_missing(self):
        from pathlib import Path
        from branch.sources.craigslist import Craigslist
        source = Craigslist()
        original = self.cl.AREAS_PATH
        try:
            self.cl.AREAS_PATH = Path("/nonexistent/craigslist_areas.csv.gz")
            self.assertIn("missing", source.available() or "")
        finally:
            self.cl.AREAS_PATH = original


class TestCraigslistDates(unittest.TestCase):
    """Craigslist stamps "9/14" and nothing else."""

    def setUp(self):
        from branch.ui.browser import parse_relative_time
        self.parse = parse_relative_time
        self.now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

    def test_a_month_day_stamp_is_read(self):
        self.assertEqual(self.parse("9/14 $30/HR", self.now).date().isoformat(),
                         "2026-09-14")

    def test_a_date_ahead_of_today_is_last_year(self):
        """Every January, a posting stamped 12/28 is from December just gone."""
        self.assertEqual(self.parse("12/28 winter job", self.now).year, 2025)

    def test_relative_times_still_win(self):
        self.assertEqual(self.parse("3 days ago", self.now),
                         self.now - timedelta(days=3))

    def test_an_unreadable_stamp_stays_unknown(self):
        """Not "now". A lead's age is half its score, and guessing today would
        promote a stale posting to the top of the list."""
        self.assertIsNone(self.parse("no date at all here", self.now))
        self.assertIsNone(self.parse("99/99", self.now))


class TestForumsAvailability(unittest.TestCase):
    """Forums reported itself broken while shipping working forums."""

    def test_a_profile_that_names_forums_makes_the_source_available(self):
        from branch.sources.discourse import Discourse, profile_sites
        self.assertTrue(profile_sites(), "no bundled profile names a forum")
        self.assertIsNone(Discourse().available())

    def test_the_reason_names_both_ways_to_fix_it(self):
        """If it ever is unavailable, the message has to say what to do about
        it -- both the profile and the config file."""
        from branch.sources import discourse
        original = discourse.profile_sites
        try:
            discourse.profile_sites = lambda root=None: []
            reason = discourse.Discourse().available() or ""
            self.assertIn("profile", reason)
            self.assertIn("forums.txt", reason)
        finally:
            discourse.profile_sites = original

    def test_a_broken_profile_directory_does_not_hide_the_source(self):
        from pathlib import Path
        from branch.sources.discourse import profile_sites
        self.assertEqual(profile_sites(Path("/nonexistent/profiles")), [])


class TestATickMeansSignedIn(unittest.TestCase):
    """Reported from a friend's machine, v0.2.2: Facebook, Marketplace and FB
    Groups all showed ticks and he had never signed in to anything.

    Two causes. The browser counted any page that rendered as proof of a
    session, so one consent screen or redirect marked him connected for good.
    And Marketplace claimed to need no account at all.
    """

    def setUp(self):
        self.source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")

    def test_a_page_that_rendered_is_no_longer_called_a_session(self):
        self.assertNotIn("is proof of a working session", self.source)

    def test_the_session_cookie_is_what_counts(self):
        from branch.ui import browser
        self.assertIn("c_user", browser.HarvestBrowser.SESSION_COOKIES)
        self.assertIn("auth_token", browser.HarvestBrowser.SESSION_COOKIES)

    def test_only_the_cookies_name_is_read_never_its_value(self):
        """The value is the credential. Presence is the whole question."""
        block = self.source.split("def _service_for_cookie")[1].split("def _cookie_seen")[0]
        self.assertIn("cookie.name()", block)
        self.assertNotIn("cookie.value()", block)

    def test_a_profile_with_no_session_says_so(self):
        """Otherwise a wrongly-recorded tick is never contradicted and stays
        forever -- which is what happened to him."""
        self.assertIn("_report_missing_sessions", self.source)
        self.assertIn("loadAllCookies", self.source)

    def test_every_facebook_surface_asks_for_the_same_account(self):
        from branch.sources.registry import build
        sources = build()
        for key in ("facebook", "groups", "marketplace"):
            with self.subTest(source=key):
                self.assertEqual(sources[key].login_service, "Facebook")

    def test_nothing_claims_ready_for_an_account_it_has_not_seen(self):
        from branch.sources.registry import build
        for key, source in build().items():
            with self.subTest(source=key):
                if source.login_service:
                    self.assertEqual(source.state(set()).state, "login",
                                     f"{key} ticks without the account it needs")


class TestTheBrowserStaysOutOfTheWay(unittest.TestCase):
    """Reported from a friend's machine: "it continues to open the window used
    to search Facebook on their actual desktop".

    He was signed in to nothing, so every Facebook search in the queue hit a
    login wall, and the browser raised itself on top of his desktop for each
    one -- ten times for ten searches, and no posts at the end of it.
    """

    def setUp(self):
        self.source = (ROOT / "branch" / "ui" / "browser.py").read_text(encoding="utf-8")

    def test_a_source_with_no_session_is_never_opened(self):
        from branch.profile import Profile
        from branch.runner import ScanRunner
        from unittest import mock
        runner = ScanRunner(ROOT, Profile.load_all(ROOT / "profiles"))
        query = {"trade_slug": "plumbing", "location": "Dallas, TX",
                 "coordinates": (32.78, -96.8), "radius": "25 miles",
                 "since": "Last week", "sources": ["facebook", "groups", "craigslist"]}
        with mock.patch.object(ScanRunner, "_signed_in", staticmethod(lambda: set())):
            opened = [key for key, _u, _l in runner.interactive_targets(query)]
        self.assertNotIn("facebook", opened)
        self.assertNotIn("groups", opened)
        self.assertIn("craigslist", opened, "a source needing no account still runs")

    def test_it_is_opened_once_the_account_is_there(self):
        from branch.profile import Profile
        from branch.runner import ScanRunner
        from unittest import mock
        runner = ScanRunner(ROOT, Profile.load_all(ROOT / "profiles"))
        query = {"trade_slug": "plumbing", "location": "Dallas, TX",
                 "coordinates": (32.78, -96.8), "radius": "25 miles",
                 "since": "Last week", "sources": ["facebook"]}
        with mock.patch.object(ScanRunner, "_signed_in",
                               staticmethod(lambda: {"facebook"})):
            opened = [key for key, _u, _l in runner.interactive_targets(query)]
        self.assertEqual(opened, ["facebook"])

    def test_a_skipped_source_says_why(self):
        """Silent omission is a bug: a scan that did not search Facebook must
        not look like one that searched and found nothing."""
        from branch.profile import Profile
        from branch.runner import ScanRunner
        from unittest import mock
        profiles = Profile.load_all(ROOT / "profiles")
        runner = ScanRunner(ROOT, profiles)
        query = {"trade_slug": "plumbing", "location": "Dallas, TX",
                 "coordinates": (32.78, -96.8), "radius": "25 miles",
                 "since": "Last week", "sources": ["facebook"]}
        with mock.patch.object(ScanRunner, "_signed_in", staticmethod(lambda: set())):
            result = runner._collect(query, profiles["plumbing"])
        self.assertIn("sign in to Facebook", result.unavailable["facebook"])

    def test_the_window_comes_up_once_not_once_per_page(self):
        self.assertIn("if self._revealed and not again:", self.source)

    def test_a_sign_in_the_user_asked_for_always_comes_up(self):
        login = self.source.split("def open_login")[1].split("def ")[0]
        self.assertIn("again=True", login)

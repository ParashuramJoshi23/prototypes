"""Polite HTTP fetching: shared session, retries, rate limiting, robots.txt.

Two ways to fetch a page:
  - Client.get(url)        -> static HTML via requests (fast, default)
  - Client.render(url)     -> JS-rendered HTML via Playwright (opt-in, --render)

robots.txt is honored by default. A scraper hitting someone else's site should
identify itself and back off; this does both.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "upliance-recipe-scraper/0.1 (personal/educational prototype; "
    "+https://github.com/parashuramjoshi23/prototypes)"
)


class Client:
    def __init__(
        self,
        delay: float = 1.0,
        timeout: float = 20.0,
        respect_robots: bool = True,
        render: bool = False,
    ):
        self.delay = delay
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.render_enabled = render
        self._last_request = 0.0
        self._robots: dict[str, RobotFileParser] = {}
        self._browser = None  # lazily created Playwright browser

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        retry = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    # -- politeness ---------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def allowed(self, url: str) -> bool:
        """Check url against the host's robots.txt (cached per host)."""
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots.get(root)
        if rp is None:
            rp = RobotFileParser()
            rp.set_url(f"{root}/robots.txt")
            try:
                rp.read()
            except Exception:
                # If robots.txt is unreachable, fail open but stay polite.
                rp = None
            # Cache even a None-ish result by storing a permissive parser.
            if rp is None:
                rp = RobotFileParser()
                rp.parse([])
            self._robots[root] = rp
        return rp.can_fetch(USER_AGENT, url)

    # -- fetching -----------------------------------------------------------

    def get(self, url: str) -> str | None:
        """Fetch static HTML. Returns None if disallowed or on hard failure."""
        if not self.allowed(url):
            return None
        self._throttle()
        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code == 200:
            return resp.text
        resp.raise_for_status()
        return None

    def render(self, url: str) -> str | None:
        """Fetch JS-rendered HTML via Playwright. Requires `--render` + install."""
        if not self.allowed(url):
            return None
        self._throttle()
        page = self._page()
        page.goto(url, wait_until="networkidle", timeout=int(self.timeout * 1000))
        return page.content()

    def fetch(self, url: str) -> str | None:
        """Render if enabled, else static GET."""
        return self.render(url) if self.render_enabled else self.get(url)

    def _page(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._context = self._browser.new_context(user_agent=USER_AGENT)
        return self._context.new_page()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._pw.stop()
            self._browser = None
        self.session.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

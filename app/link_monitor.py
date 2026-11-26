"""Live website & livestream link monitor for Cymatics.fm.

Continuously polls the tracked website URL in the background, extracts every
available link (free downloads, giveaway pages, plugins, sample packs,
livestream embeds/links), and notifies the UI immediately when new links unlock.
"""

from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests


FREE_KEYWORDS = (
    "free",
    "giveaway",
    "livestream",
    "vault",
    "bonus",
    "unlock",
    "download",
    "drop",
    "plugin",
    "beta",
    "gift",
)

STREAM_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "twitch.tv",
    "vimeo.com",
    "kick.com",
)


@dataclass
class TrackedLink:
    url: str
    label: str
    category: str  # "FREE / DROP", "LIVESTREAM", "PRODUCT", "PAGE", "SCREEN"
    first_seen: str
    is_new: bool = True


class _LinkExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: List[Tuple[str, str]] = []
        self._current_href: Optional[str] = None
        self._current_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_map = dict(attrs)
        if tag == "a" and attr_map.get("href"):
            self._current_href = attr_map["href"]
            self._current_text = []
        elif tag == "iframe" and attr_map.get("src"):
            src = urljoin(self.base_url, attr_map["src"] or "")
            if src.startswith(("http://", "https://")):
                self.links.append((src, "Embedded Stream / Frame"))

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            txt = data.strip()
            if txt:
                self._current_text.append(txt)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_href is not None:
            raw_href = self._current_href.strip()
            label = " ".join(self._current_text).strip()
            self._current_href = None
            self._current_text = []
            if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:", "tel:")):
                return
            full_url = urljoin(self.base_url, raw_href)
            if full_url.startswith(("http://", "https://")):
                self.links.append((full_url, label or full_url))


def categorize_link(url: str, label: str) -> str:
    combined = f"{url} {label}".lower()
    host = urlparse(url).netloc.lower()
    if any(sd in host for sd in STREAM_DOMAINS) or "livestream" in combined or "watch?v=" in combined:
        return "LIVESTREAM"
    if any(k in combined for k in FREE_KEYWORDS):
        return "FREE / DROP"
    if "/products/" in url.lower() or "/collections/" in url.lower():
        return "PRODUCT"
    return "PAGE"


def extract_links_from_html(html_text: str, base_url: str) -> List[Tuple[str, str, str]]:
    """Return deduplicated (url, label, category) tuples from an HTML page."""
    parser = _LinkExtractor(base_url)
    parser.feed(html_text)
    seen = set()
    results: List[Tuple[str, str, str]] = []
    for url, label in parser.links:
        clean_url = url.split("#")[0].rstrip("/")
        if not clean_url or clean_url in seen:
            continue
        seen.add(clean_url)
        cat = categorize_link(clean_url, label)
        short_label = label if len(label) <= 64 else label[:61] + "..."
        results.append((clean_url, short_label, cat))
    return results


class LiveWebsiteLinkMonitor:
    """Background poller that tracks all live links on the target website."""

    def __init__(
        self,
        on_links_updated: Callable[[List[TrackedLink], List[TrackedLink]], None],
        on_log: Callable[[str], None],
    ) -> None:
        self.on_links_updated = on_links_updated
        self.on_log = on_log
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._known: Dict[str, TrackedLink] = {}
        self._target_url: str = "https://cymatics.fm/"
        self._interval_sec: float = 8.0
        self._initial_scan_done = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def start(self, target_url: str, interval_sec: float = 8.0) -> None:
        if self.is_running:
            self._target_url = target_url
            self._interval_sec = max(3.0, float(interval_sec))
            return
        self._target_url = target_url
        self._interval_sec = max(3.0, float(interval_sec))
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="LiveLinkMonitor", daemon=True)
        self._thread.start()
        self.on_log(f"[LINKS] Started live website & stream link tracker on {self._target_url}")

    def stop(self) -> None:
        self._stop_event.set()

    def add_screen_urls(self, urls: List[str]) -> List[TrackedLink]:
        """Register URLs spotted visually by the AI on the livestream screen/chat."""
        added: List[TrackedLink] = []
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        for raw in urls:
            clean = raw.strip().rstrip("/")
            if not clean or clean in self._known:
                continue
            item = TrackedLink(
                url=clean,
                label=f"Spotted on Screen: {clean}",
                category=categorize_link(clean, "screen drop"),
                first_seen=ts,
                is_new=True,
            )
            self._known[clean] = item
            added.append(item)
        if added:
            self.on_links_updated(self.get_all_links(), added)
        return added

    def get_all_links(self) -> List[TrackedLink]:
        priority = {"FREE / DROP": 0, "LIVESTREAM": 1, "PRODUCT": 2, "PAGE": 3}
        items = list(self._known.values())
        items.sort(key=lambda x: (0 if x.is_new else 1, priority.get(x.category, 9), x.url))
        return items

    def scan_once(self) -> Tuple[List[TrackedLink], List[TrackedLink]]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(self._target_url, headers=headers, timeout=15.0)
        resp.raise_for_status()
        extracted = extract_links_from_html(resp.text, resp.url or self._target_url)

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        newly_found: List[TrackedLink] = []
        for url, label, cat in extracted:
            if url not in self._known:
                item = TrackedLink(
                    url=url,
                    label=label,
                    category=cat,
                    first_seen=ts,
                    is_new=self._initial_scan_done,
                )
                self._known[url] = item
                if self._initial_scan_done:
                    newly_found.append(item)
            else:
                self._known[url].is_new = False

        self._initial_scan_done = True
        all_links = self.get_all_links()
        self.on_links_updated(all_links, newly_found)
        return all_links, newly_found

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                all_links, new_links = self.scan_once()
                if new_links:
                    self.on_log(
                        f"[NEW LIVE LINKS] {len(new_links)} new link(s) detected on {self._target_url}! "
                        f"First: {new_links[0].url}"
                    )
                elif len(all_links) > 0 and self._initial_scan_done:
                    pass
            except Exception as exc:
                self.on_log(f"[LINK MONITOR] Poll warning: {exc}")
            self._stop_event.wait(self._interval_sec)

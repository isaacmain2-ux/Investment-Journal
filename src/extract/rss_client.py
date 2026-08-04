"""
FT RSS client: fetch one feed and parse it to a tidy list of headline dicts.

Design mirrors fred_client / yf_client:
  * The single network call lives in `_http_get`, so tests mock it and the whole
    module runs offline. Nothing else here touches the network.
  * Parsing uses only the standard library (`xml.etree`). FT serves clean RSS 2.0,
    so no third-party feed library is needed - which also keeps the parser fully
    testable offline. It handles RSS 2.0 `<item>` and Atom `<entry>`, missing
    fields, HTML entities, and both RFC-822 (RSS) and ISO-8601 (Atom) dates.
    (If you ever prefer feedparser's extra tolerance, swap the body of
    `_parse_feed` for `feedparser.parse(content)` and re-map its fields - the
    rest of the module is unaffected.)
  * Conditional GET: pass a feed's stored ETag / Last-Modified and an unchanged
    feed returns a cheap 304, so nothing is re-parsed.
  * Each feed yields a FeedResult (ok | not_modified | empty | error). One bad
    or unreachable feed never crashes a multi-feed run - the outcome is in the
    returned object, never an exception.

A parsed item is a dict:
    {item_id, guid, title, summary, link, published_at}   (published_at: UTC datetime | None)
"""
from __future__ import annotations

import hashlib
import html
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import requests

DEFAULT_UA = "InvestmentJournal/1.0 (personal research)"
_TIMEOUT = 30
_MIN_INTERVAL = 1.0            # be a polite client: >= 1s between requests
_last_call = [0.0]

# XML namespaces we may meet in FT feeds
_ATOM = "{http://www.w3.org/2005/Atom}"
_DC = "{http://purl.org/dc/elements/1.1/}"


class FeedResult:
    """The outcome of fetching one feed."""

    def __init__(self, name: str, items: list[dict] | None = None,
                 status: str = "ok", error: str | None = None,
                 etag: str | None = None, last_modified: str | None = None,
                 http_status: int | None = None, raw: bytes | None = None):
        self.name = name
        self.items = items if items is not None else []
        self.status = status            # "ok" | "not_modified" | "empty" | "error"
        self.error = error
        self.etag = etag
        self.last_modified = last_modified
        self.http_status = http_status
        self.raw = raw                  # the exact bytes returned (for landing raw)

    @property
    def n_items(self) -> int:
        return len(self.items)

    def __repr__(self) -> str:
        return f"FeedResult({self.name}, status={self.status}, n_items={self.n_items})"


def _throttle() -> None:
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def _http_get(url: str, etag: str | None = None, last_modified: str | None = None,
              user_agent: str = DEFAULT_UA) -> requests.Response:
    """The ONLY network call in this module. Mock this in tests.
    Sends conditional-GET headers so an unchanged feed can answer 304."""
    headers = {"User-Agent": user_agent, "Accept": "application/rss+xml, application/xml, text/xml"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return requests.get(url, headers=headers, timeout=_TIMEOUT)


def _parse_datetime(raw: str | None):
    """Parse an RSS (RFC-822) or Atom (ISO-8601) date to a UTC datetime, or None."""
    if not raw:
        return None
    raw = raw.strip()
    # RFC-822, e.g. "Wed, 07 Jan 2026 09:58:19 GMT"
    try:
        dt = parsedate_to_datetime(raw)
        if dt is not None:
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    # ISO-8601, e.g. "2026-01-07T09:58:19Z"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _clean(text: str | None) -> str | None:
    """Decode HTML entities and trim. (Tag stripping is left to the gold model.)"""
    if text is None:
        return None
    return html.unescape(text).strip() or None


def _item_id(guid: str | None, link: str | None) -> str | None:
    """Stable id for de-duplication: the guid if present, else a hash of the link."""
    if guid:
        return guid.strip()
    if link:
        return "link:" + hashlib.sha1(link.strip().encode("utf-8")).hexdigest()
    return None


def _norm(guid, title, link, summary, published_raw) -> dict:
    return {
        "item_id": _item_id(guid, link),
        "guid": (guid or "").strip() or None,
        "title": _clean(title),
        "summary": _clean(summary),
        "link": (link or "").strip() or None,
        "published_at": _parse_datetime(published_raw),
    }


def _parse_feed(content: bytes | str) -> list[dict]:
    """Parse RSS 2.0 or Atom bytes into a list of normalised item dicts.
    Raises ValueError on unparseable XML (the caller turns that into an error result)."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValueError(f"XML parse error: {e}") from e

    items: list[dict] = []

    # --- RSS 2.0: <channel><item>... ---
    rss_items = root.findall(".//item")
    if rss_items:
        for it in rss_items:
            guid = it.findtext("guid")
            title = it.findtext("title")
            link = it.findtext("link")
            summary = it.findtext("description")
            published = it.findtext("pubDate") or it.findtext(_DC + "date")
            row = _norm(guid, title, link, summary, published)
            if row["item_id"]:
                items.append(row)
        return items

    # --- Atom: <feed><entry>... ---
    for en in root.findall(_ATOM + "entry"):
        guid = en.findtext(_ATOM + "id")
        title = en.findtext(_ATOM + "title")
        # prefer the alternate link's href
        link = None
        for ln in en.findall(_ATOM + "link"):
            if ln.get("rel", "alternate") == "alternate":
                link = ln.get("href")
                break
        if link is None:
            first = en.find(_ATOM + "link")
            link = first.get("href") if first is not None else None
        summary = en.findtext(_ATOM + "summary") or en.findtext(_ATOM + "content")
        published = en.findtext(_ATOM + "published") or en.findtext(_ATOM + "updated")
        row = _norm(guid, title, link, summary, published)
        if row["item_id"]:
            items.append(row)
    return items


def fetch_feed(name: str, url: str, etag: str | None = None,
               last_modified: str | None = None, user_agent: str = DEFAULT_UA,
               retries: int = 3) -> FeedResult:
    """Fetch and parse one feed. Never raises - the outcome is in the FeedResult.
    Pass the feed's stored etag/last_modified to enable a cheap 304 when unchanged."""
    for attempt in range(1, retries + 1):
        _throttle()
        try:
            resp = _http_get(url, etag=etag, last_modified=last_modified, user_agent=user_agent)
        except requests.RequestException as e:
            if attempt == retries:
                return FeedResult(name, status="error", error=f"network: {e}")
            time.sleep(2 * attempt)
            continue

        code = resp.status_code
        if code == 304:
            return FeedResult(name, status="not_modified", http_status=304,
                              etag=etag, last_modified=last_modified)
        if code == 200:
            new_etag = resp.headers.get("ETag")
            new_lastmod = resp.headers.get("Last-Modified")
            try:
                items = _parse_feed(resp.content)
            except ValueError as e:
                return FeedResult(name, status="error", error=str(e), http_status=200)
            status = "ok" if items else "empty"
            return FeedResult(name, items=items, status=status, http_status=200,
                              etag=new_etag, last_modified=new_lastmod, raw=resp.content)
        if code == 429 or 500 <= code < 600:
            if attempt == retries:
                return FeedResult(name, status="error", http_status=code,
                                  error=f"http {code} after {retries} attempts")
            time.sleep(2 * attempt)
            continue
        return FeedResult(name, status="error", http_status=code, error=f"http {code}")

    return FeedResult(name, status="error", error="exhausted retries")


def fetch_feeds(feeds: list[dict], caches: dict | None = None,
                user_agent: str = DEFAULT_UA) -> dict[str, FeedResult]:
    """Fetch many feeds (as dicts with name/url), returning {name: FeedResult}.
    `caches` maps feed name -> {'etag':..., 'last_modified':...} for conditional GET."""
    caches = caches or {}
    out: dict[str, FeedResult] = {}
    for fd in feeds:
        c = caches.get(fd["name"], {})
        out[fd["name"]] = fetch_feed(fd["name"], fd["url"],
                                     etag=c.get("etag"), last_modified=c.get("last_modified"),
                                     user_agent=user_agent)
    return out

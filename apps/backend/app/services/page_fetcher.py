"""
app/services/page_fetcher.py — Sync HTTP fetch + HTML extraction.

WHY SYNC (not async)?
The agents that call this are LangGraph nodes — synchronous functions.
Using async here would require asyncio.run() wrapping which complicates
error handling. Sync httpx.Client matches the existing pattern.

WHY MODULE-LEVEL DICT CACHE (not Redis)?
The Redis cache is async-only in this codebase. To avoid async/sync mixing,
we use a simple in-process TTL dict. Page fetches are uncommon enough that
this is acceptable. Production deployments would replace this with a sync
Redis client or memcached.
"""

import ipaddress
import logging
import socket
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 8000
MAX_REDIRECTS = 5
USER_AGENT = (
    "SupplierMind-Research/1.0 "
    "(academic project; contact: thesis@gisma.de)"
)
CACHE_TTL_SECONDS = 86400  # 24 hours

# Module-level in-memory cache: {url: (text, expiry_timestamp)}
_PAGE_CACHE: dict[str, tuple[str, float]] = {}


def _cache_get(url: str) -> str | None:
    entry = _PAGE_CACHE.get(url)
    if entry is None:
        return None
    text, expiry = entry
    if time.time() > expiry:
        del _PAGE_CACHE[url]
        return None
    return text


def _cache_set(url: str, text: str) -> None:
    # Cap cache size to prevent memory growth
    if len(_PAGE_CACHE) > 500:
        _PAGE_CACHE.clear()
    _PAGE_CACHE[url] = (text, time.time() + CACHE_TTL_SECONDS)


def _is_url_allowed(url: str) -> bool:
    """
    SSRF guard: URLs come from external search results, so only allow
    http(s) targets that resolve exclusively to public addresses. Rejects
    loopback, private, link-local (cloud metadata 169.254.169.254), and
    other non-global ranges via the stdlib.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def _fetch_raw(url: str, timeout_seconds: float | None = None) -> str | None:
    """Sync HTTP GET with timeout and proper headers.

    Redirects are followed manually so every hop is re-validated against the
    SSRF guard — auto-follow would let a public URL bounce us to an internal
    or metadata address.
    """
    try:
        with httpx.Client(
            timeout=max(0.1, float(timeout_seconds or 15.0)),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                if not _is_url_allowed(url):
                    logger.debug("[fetcher] Blocked non-public URL: %s", url)
                    return None
                response = client.get(url)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    url = str(httpx.URL(url).join(location))
                    continue
                if response.status_code != 200:
                    logger.debug(
                        "[fetcher] Non-200 for %s: %d", url, response.status_code
                    )
                    return None
                return response.text
            logger.debug("[fetcher] Too many redirects for %s", url)
            return None
    except Exception as e:
        logger.debug("[fetcher] Failed for %s: %s", url, e)
        return None


def _extract_text(html: str) -> str:
    """Extract clean text from HTML, removing scripts/styles/navigation."""
    try:
        soup = BeautifulSoup(html, "lxml")

        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()

        main = soup.find("main") or soup.find("article") or soup.body
        if main is None:
            return ""

        text = main.get_text(separator=" ", strip=True)
        text = " ".join(text.split())
        return text[:MAX_CONTENT_CHARS]
    except Exception as e:
        logger.debug("[fetcher] HTML parse failed: %s", e)
        return ""


def fetch_page_content(url: str, timeout_seconds: float | None = None) -> str | None:
    """
    Fetch and extract clean text from a webpage.
    Synchronous — safe to call from agent nodes.

    Returns up to MAX_CONTENT_CHARS of clean text, or None on failure.
    """
    if not url or not url.startswith(("http://", "https://")):
        return None

    # Check cache
    cached = _cache_get(url)
    if cached is not None:
        logger.debug("[fetcher] Cache hit: %s", url)
        return cached

    # Fetch
    html = _fetch_raw(url, timeout_seconds=timeout_seconds)
    if not html:
        return None

    text = _extract_text(html)
    if not text or len(text) < 200:
        logger.debug(
            "[fetcher] Insufficient text from %s (%d chars)", url, len(text)
        )
        return None

    _cache_set(url, text)
    return text

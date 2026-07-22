"""SSRF guard — page_fetcher must refuse non-public targets.

URLs come from external search results; a result redirecting to the cloud
metadata endpoint (169.254.169.254) must never be fetched.
"""

from app.services.page_fetcher import _fetch_raw, _is_url_allowed


def test_private_and_metadata_urls_rejected():
    assert not _is_url_allowed("http://169.254.169.254/latest/meta-data/")
    assert not _is_url_allowed("http://127.0.0.1:8000/admin")
    assert not _is_url_allowed("http://10.0.0.5/")
    assert not _is_url_allowed("http://192.168.1.1/")
    assert not _is_url_allowed("ftp://example.com/file")
    assert not _is_url_allowed("file:///etc/passwd")


def test_fetch_raw_blocks_private_ip_without_network():
    # Literal IPs resolve locally (no DNS), so this is fast and offline.
    assert _fetch_raw("http://169.254.169.254/latest/meta-data/") is None
    assert _fetch_raw("http://127.0.0.1:1/") is None

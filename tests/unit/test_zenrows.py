"""Unit tests for the ZenRows proxy session shim.

Pure tests only — exercise param-building and key redaction with no network,
matching the repo's no-HTTP-mocking convention. Pins the SincSports invariant
that JS rendering stays OFF by default.
"""

from __future__ import annotations

from src.scrapers._zenrows import ZenRowsSession, _redact


def _session(**kwargs) -> ZenRowsSession:
    # api_key passed explicitly so tests never depend on the environment.
    return ZenRowsSession(api_key="testkey123", **kwargs)


class TestBuildParams:
    def test_js_render_omitted_by_default(self):
        """SincSports invariant: js_render must NOT be sent unless explicitly enabled."""
        params = _session(premium_proxy=True)._build_params("https://example.com")
        assert "js_render" not in params
        assert params["url"] == "https://example.com"
        assert params["apikey"] == "testkey123"

    def test_js_render_included_when_enabled(self):
        params = _session(js_render=True, premium_proxy=True)._build_params("https://example.com")
        assert params["js_render"] == "true"

    def test_premium_proxy_sends_country(self):
        params = _session(premium_proxy=True)._build_params("https://example.com")
        assert params["premium_proxy"] == "true"
        assert params["proxy_country"] == "us"

    def test_no_premium_proxy_omits_country(self):
        params = _session(premium_proxy=False)._build_params("https://example.com")
        assert "premium_proxy" not in params
        assert "proxy_country" not in params

    def test_original_status_on_by_default(self):
        """original_status=true surfaces target-side 403/404 blocks to raise_for_status()."""
        params = _session(premium_proxy=True)._build_params("https://example.com")
        assert params["original_status"] == "true"


class TestRedact:
    def test_replaces_secret(self):
        url = "https://api.zenrows.com/v1/?apikey=testkey123&url=x"
        redacted = _redact(url, "testkey123")
        assert "testkey123" not in redacted
        assert "REDACTED" in redacted

    def test_none_inputs_are_safe(self):
        assert _redact(None, "k") is None
        assert _redact("text", None) == "text"

"""Tests pour utils/http_utils.py.

Couvre :
  - create_session_with_retries : création et configuration de la session
  - fetch_and_extract_text : récupération HTML + extraction texte, cas d'erreur
  - extract_top_n_largest_images : OG image, Twitter Card, balises img, cascade
"""

import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_response(html: str = "", status_code: int = 200):
    """Crée un mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = html.encode("utf-8")
    resp.text = html
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import requests
        err = requests.exceptions.HTTPError(response=resp)
        resp.raise_for_status.side_effect = err
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# create_session_with_retries
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateSessionWithRetries:
    def setup_method(self):
        from utils.http_utils import create_session_with_retries
        self.fn = create_session_with_retries

    def test_returns_requests_session(self):
        import requests
        session = self.fn()
        assert isinstance(session, requests.Session)

    def test_has_http_adapter(self):
        session = self.fn()
        assert "http://" in session.adapters

    def test_has_https_adapter(self):
        session = self.fn()
        assert "https://" in session.adapters

    def test_custom_retries_applied(self):
        session = self.fn(total_retries=7)
        adapter = session.adapters["https://"]
        assert adapter.max_retries.total == 7

    def test_custom_backoff_factor(self):
        session = self.fn(backoff_factor=1.5)
        adapter = session.adapters["https://"]
        assert adapter.max_retries.backoff_factor == 1.5

    def test_default_status_forcelist(self):
        session = self.fn()
        adapter = session.adapters["https://"]
        assert 429 in adapter.max_retries.status_forcelist
        assert 500 in adapter.max_retries.status_forcelist
        assert 503 in adapter.max_retries.status_forcelist


# ─────────────────────────────────────────────────────────────────────────────
# fetch_and_extract_text
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchAndExtractText:
    def setup_method(self):
        from utils.http_utils import fetch_and_extract_text
        self.fn = fetch_and_extract_text

    def test_successful_fetch_returns_text(self):
        html = "<html><body><p>Bonjour le monde</p></body></html>"
        with patch("utils.http_utils.requests.get", return_value=_make_response(html)):
            result = self.fn("https://example.com")
        assert "Bonjour" in result
        assert "le monde" in result

    def test_empty_url_returns_error(self):
        result = self.fn("")
        assert "Erreur" in result or result == ""

    def test_none_url_returns_error(self):
        result = self.fn(None)
        assert "Erreur" in result

    def test_url_without_protocol_returns_error(self):
        result = self.fn("example.com/page")
        assert "Erreur" in result

    def test_http_error_returns_error_string(self):
        with patch("utils.http_utils.requests.get", return_value=_make_response("", 404)):
            result = self.fn("https://example.com/404")
        assert "Erreur" in result or "404" in result

    def test_timeout_returns_error_string(self):
        import requests as req
        with patch("utils.http_utils.requests.get", side_effect=req.exceptions.Timeout()):
            result = self.fn("https://example.com", max_retries=1)
        assert "Erreur" in result or "Timeout" in result.title() or "timeout" in result.lower()

    def test_connection_error_returns_error_string(self):
        import requests as req
        with patch("utils.http_utils.requests.get", side_effect=req.exceptions.ConnectionError()):
            result = self.fn("https://example.com", max_retries=1)
        assert "Erreur" in result or "connexion" in result.lower()

    def test_strips_script_and_style_tags(self):
        html = ("<html><head><style>body{color:red}</style></head>"
                "<body><script>alert(1)</script><p>Texte utile</p></body></html>")
        with patch("utils.http_utils.requests.get", return_value=_make_response(html)):
            result = self.fn("https://example.com")
        assert "Texte utile" in result

    def test_returns_string_type(self):
        with patch("utils.http_utils.requests.get", return_value=_make_response("<p>ok</p>")):
            result = self.fn("https://example.com")
        assert isinstance(result, str)

    def test_timeout_retries_requested_times(self):
        import requests as req
        mock_get = MagicMock(side_effect=req.exceptions.Timeout())
        with patch("utils.http_utils.requests.get", mock_get), \
             patch("utils.http_utils.time.sleep"):  # éviter les délais en test
            self.fn("https://example.com", max_retries=3)
        assert mock_get.call_count == 3


# ─────────────────────────────────────────────────────────────────────────────
# extract_top_n_largest_images
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractTopNLargestImages:
    def setup_method(self):
        from utils.http_utils import extract_top_n_largest_images
        self.fn = extract_top_n_largest_images

    def _html_with_og(self, img_url: str = "https://img.example.com/photo.jpg") -> str:
        return f"""
        <html><head>
        <meta property="og:image" content="{img_url}">
        <meta property="og:image:width" content="1200">
        <meta property="og:image:height" content="630">
        <meta property="og:title" content="Test Article">
        </head><body></body></html>
        """

    def _html_with_twitter(self, img_url: str = "https://img.example.com/twitter.jpg") -> str:
        return f"""
        <html><head>
        <meta name="twitter:image" content="{img_url}">
        </head><body></body></html>
        """

    def _html_with_img_tags(self) -> str:
        return """
        <html><body>
        <img src="https://cdn.example.com/big.jpg" width="800" height="600" alt="Big image">
        <img src="https://cdn.example.com/small.jpg" width="200" height="100" alt="Small">
        <img src="https://cdn.example.com/medium.jpg" width="600" height="400" alt="Medium">
        </body></html>
        """

    def test_extracts_og_image(self):
        with patch("utils.http_utils.requests.get",
                   return_value=_make_response(self._html_with_og())):
            result = self.fn("https://example.com")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["url"] == "https://img.example.com/photo.jpg"

    def test_og_image_has_correct_dimensions(self):
        with patch("utils.http_utils.requests.get",
                   return_value=_make_response(self._html_with_og())):
            result = self.fn("https://example.com")
        assert result[0]["width"] == 1200
        assert result[0]["height"] == 630
        assert result[0]["area"] == 1200 * 630

    def test_twitter_card_fallback(self):
        """Quand pas de OG image, utilise Twitter Card."""
        with patch("utils.http_utils.requests.get",
                   return_value=_make_response(self._html_with_twitter())):
            result = self.fn("https://example.com")
        assert isinstance(result, list)
        assert any("twitter.jpg" in r["url"] for r in result)

    def test_img_tags_extracted(self):
        """Les balises <img> avec width explicite sont extraites."""
        with patch("utils.http_utils.requests.get",
                   return_value=_make_response(self._html_with_img_tags())):
            result = self.fn("https://example.com", n=3, min_width=500)
        urls = [r["url"] for r in result]
        # big.jpg (800px) et medium.jpg (600px) passent le filtre ≥ 500px
        assert any("big.jpg" in u for u in urls)
        assert not any("small.jpg" in u for u in urls)

    def test_min_width_filter(self):
        html = """
        <html><head>
        <meta property="og:image" content="https://img.example.com/og.jpg">
        </head><body>
        <img src="https://cdn.example.com/large.jpg" width="1000" height="800">
        <img src="https://cdn.example.com/tiny.jpg" width="100" height="100">
        </body></html>
        """
        with patch("utils.http_utils.requests.get",
                   return_value=_make_response(html)):
            result = self.fn("https://example.com", n=5, min_width=600)
        urls = [r["url"] for r in result]
        assert not any("tiny.jpg" in u for u in urls)

    def test_returns_at_most_n_images(self):
        html = """
        <html><body>
        <img src="https://i.example.com/a.jpg" width="800" height="600">
        <img src="https://i.example.com/b.jpg" width="700" height="500">
        <img src="https://i.example.com/c.jpg" width="600" height="400">
        <img src="https://i.example.com/d.jpg" width="550" height="350">
        </body></html>
        """
        with patch("utils.http_utils.requests.get", return_value=_make_response(html)):
            result = self.fn("https://example.com", n=2, min_width=500)
        assert len(result) <= 2

    def test_deduplicates_same_url(self):
        img_url = "https://img.example.com/photo.jpg"
        # OG + Twitter même URL
        html = f"""
        <html><head>
        <meta property="og:image" content="{img_url}">
        <meta name="twitter:image" content="{img_url}">
        </head><body></body></html>
        """
        with patch("utils.http_utils.requests.get", return_value=_make_response(html)):
            result = self.fn("https://example.com", n=5)
        urls = [r["url"] for r in result]
        assert urls.count(img_url) == 1

    def test_returns_empty_or_error_on_failure(self):
        """En cas d'erreur réseau, retourne soit une liste vide soit un dict {error}."""
        import requests as req
        with patch("utils.http_utils.requests.get",
                   side_effect=req.exceptions.ConnectionError()):
            result = self.fn("https://example.com")
        # La fonction peut retourner une liste vide ou un dict {error} selon impl.
        assert result == [] or (isinstance(result, dict) and "error" in result)

    def test_result_dict_has_required_keys(self):
        with patch("utils.http_utils.requests.get",
                   return_value=_make_response(self._html_with_og())):
            result = self.fn("https://example.com")
        for item in result:
            assert "url" in item
            assert "width" in item
            assert "height" in item
            assert "area" in item

    def test_og_title_is_not_used_as_alt_by_default(self):
        html = """
        <html><head>
        <meta property="og:image" content="https://img.example.com/photo.jpg">
        <meta property="og:title" content="Titre Article">
        </head><body></body></html>
        """
        with patch("utils.http_utils.requests.get", return_value=_make_response(html)):
            result = self.fn("https://example.com")
        assert result[0]["title"] == "Titre Article"
        assert result[0]["alt"] == ""

    def test_og_image_alt_is_preserved(self):
        html = """
        <html><head>
        <meta property="og:image" content="https://img.example.com/photo.jpg">
        <meta property="og:title" content="Titre Article">
        <meta property="og:image:alt" content="Portrait officiel">
        </head><body></body></html>
        """
        with patch("utils.http_utils.requests.get", return_value=_make_response(html)):
            result = self.fn("https://example.com")
        assert result[0]["alt"] == "Portrait officiel"

    def test_img_alt_equal_to_article_title_is_cleared(self):
        html = """
        <html><head>
        <meta property="og:title" content="How Elon Musk left OpenAI, according to Greg Brockman | TechCrunch">
        </head><body>
        <img src="https://cdn.example.com/a.jpg"
             width="800"
             height="600"
             alt="How Elon Musk left OpenAI, according to Greg Brockman | TechCrunch">
        </body></html>
        """
        with patch("utils.http_utils.requests.get", return_value=_make_response(html)):
            result = self.fn("https://example.com", min_width=500)
        assert result[0]["alt"] == ""

    def test_only_absolute_urls_included(self):
        html = """
        <html><body>
        <img src="/relative/path.jpg" width="800" height="600">
        <img src="https://cdn.example.com/absolute.jpg" width="700" height="500">
        </body></html>
        """
        with patch("utils.http_utils.requests.get", return_value=_make_response(html)):
            result = self.fn("https://example.com", n=5, min_width=500)
        urls = [r["url"] for r in result]
        assert not any(u.startswith("/") for u in urls)
        assert any("absolute.jpg" in u for u in urls)

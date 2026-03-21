"""Tests pour utils/exporters/newsletter.py

Couvre :
- _sentiment_badge, _score_badge, _first_image, _truncate (helpers)
- generate_newsletter_html (génération HTML)
- generate_newsletter_from_48h (lecture fichier 48h ou fallback rglob)
- send_newsletter (SMTP)
"""

import json
import smtplib
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest


# ═════════════════════════════════════════════════════════════════════════════
# Helpers privés
# ═════════════════════════════════════════════════════════════════════════════

class TestSentimentBadge:
    def _fn(self):
        from utils.exporters.newsletter import _sentiment_badge
        return _sentiment_badge

    def test_positif(self):
        assert "badge-positif" in self._fn()({"sentiment": "positif"})

    def test_negatif(self):
        assert "badge-n" in self._fn()({"sentiment": "négatif"})  # badge-négatif (avec accent)

    def test_neutre(self):
        assert "badge-neutre" in self._fn()({"sentiment": "neutre"})

    def test_alarmiste_ton_editorial(self):
        html = self._fn()({"ton_editorial": "alarmiste"})
        assert "badge-alarmiste" in html

    def test_both_sentiment_and_ton(self):
        html = self._fn()({"sentiment": "négatif", "ton_editorial": "alarmiste"})
        assert "badge-n" in html  # badge-négatif (avec accent)
        assert "badge-alarmiste" in html

    def test_no_sentiment_returns_empty_string(self):
        assert self._fn()({}) == ""

    def test_unknown_sentiment_returns_empty(self):
        assert self._fn()({"sentiment": "bizarre"}) == ""

    def test_non_alarmiste_ton_ignored(self):
        assert "badge-alarmiste" not in self._fn()({"ton_editorial": "neutre"})


class TestScoreBadge:
    def _fn(self):
        from utils.exporters.newsletter import _score_badge
        return _score_badge

    def test_with_score_returns_badge(self):
        html = self._fn()({"score_pertinence": 85})
        assert "badge-score" in html
        assert "85" in html

    def test_without_score_returns_empty(self):
        assert self._fn()({}) == ""

    def test_score_zero_returns_badge(self):
        html = self._fn()({"score_pertinence": 0})
        assert "badge-score" in html

    def test_score_none_returns_empty(self):
        assert self._fn()({"score_pertinence": None}) == ""


class TestFirstImage:
    def _fn(self):
        from utils.exporters.newsletter import _first_image
        return _first_image

    def test_with_lowercase_url_key(self):
        html = self._fn()({"Images": [{"url": "https://a.com/img.jpg"}]})
        assert "<img" in html
        assert "https://a.com/img.jpg" in html

    def test_with_uppercase_url_key(self):
        html = self._fn()({"Images": [{"URL": "https://b.com/img.jpg"}]})
        assert "https://b.com/img.jpg" in html

    def test_empty_images_list_returns_empty(self):
        assert self._fn()({"Images": []}) == ""

    def test_missing_images_key_returns_empty(self):
        assert self._fn()({}) == ""

    def test_images_not_a_list_returns_empty(self):
        assert self._fn()({"Images": "not-a-list"}) == ""

    def test_image_without_url_returns_empty(self):
        assert self._fn()({"Images": [{"width": 1200}]}) == ""

    def test_only_first_image_used(self):
        html = self._fn()({"Images": [
            {"url": "https://first.com/img.jpg"},
            {"url": "https://second.com/img.jpg"},
        ]})
        assert "first.com" in html
        assert "second.com" not in html


class TestTruncate:
    def _fn(self):
        from utils.exporters.newsletter import _truncate
        return _truncate

    def test_short_text_unchanged(self):
        txt = "Texte court"
        assert self._fn()(txt) == txt

    def test_exactly_max_chars_unchanged(self):
        txt = "x" * 400
        assert self._fn()(txt, max_chars=400) == txt

    def test_long_text_truncated_with_ellipsis(self):
        result = self._fn()("mot " * 200, max_chars=40)
        assert result.endswith("…")

    def test_truncation_at_word_boundary(self):
        long_text = "mot " * 200
        result = self._fn()(long_text, max_chars=30)
        # Should not break mid-word
        assert not result.rstrip("…").endswith(" ")
        # Actually rsplit will remove the last partial word
        assert "…" in result

    def test_custom_max_chars(self):
        txt = "a" * 100
        result = self._fn()(txt, max_chars=50)
        # All a's → rsplit finds no space → text[:50] + "…"
        assert result == txt[:50] + "…"


# ═════════════════════════════════════════════════════════════════════════════
# generate_newsletter_html
# ═════════════════════════════════════════════════════════════════════════════

class TestGenerateNewsletterHtml:
    def _fn(self):
        from utils.exporters.newsletter import generate_newsletter_html
        return generate_newsletter_html

    def _make_article(self, **kwargs):
        base = {
            "URL": "https://example.com/article",
            "Sources": "Le Monde",
            "Date de publication": "2026-03-06T10:00:00Z",
            "Résumé": "Première ligne du résumé.\nDeuxième ligne.",
        }
        base.update(kwargs)
        return base

    def test_returns_html_string(self):
        result = self._fn()([self._make_article()])
        assert isinstance(result, str)
        assert "<!DOCTYPE html>" in result

    def test_contains_article_source(self):
        result = self._fn()([self._make_article()])
        assert "Le Monde" in result

    def test_contains_article_url(self):
        result = self._fn()([self._make_article()])
        assert "https://example.com/article" in result

    def test_custom_title_in_output(self):
        result = self._fn()([self._make_article()], title="Ma Veille Test")
        assert "Ma Veille Test" in result

    def test_default_title_used_when_not_provided(self):
        result = self._fn()([self._make_article()])
        assert "Veille WUDD.ai" in result

    def test_empty_articles_list_returns_valid_html(self):
        result = self._fn()([])
        assert "<!DOCTYPE html>" in result
        assert "0 articles" in result

    def test_max_articles_respected(self):
        articles = [self._make_article(Sources=f"Source {i}") for i in range(30)]
        result = self._fn()(articles, max_articles=5)
        # Only first 5 sources should be present
        assert "Source 0" in result
        assert "Source 4" in result
        assert "Source 5" not in result

    def test_article_count_shown(self):
        articles = [self._make_article() for _ in range(3)]
        result = self._fn()(articles, max_articles=20)
        assert "3 articles" in result

    def test_html_special_chars_escaped_in_resume(self):
        article = self._make_article(**{"Résumé": "Test & <script>alert(1)</script>"})
        result = self._fn()([article])
        assert "<script>" not in result
        assert "&amp;" in result or "&lt;" in result

    def test_first_line_of_resume_used_as_title(self):
        article = self._make_article(**{"Résumé": "Titre de la dépêche.\nSuite du texte..."})
        result = self._fn()([article])
        assert "Titre de la dépêche." in result

    def test_fallback_title_when_no_resume(self):
        article = self._make_article(**{"Résumé": "", "Sources": "AFP", "Date de publication": "2026-01-01T00:00:00Z"})
        result = self._fn()([article])
        assert "AFP" in result

    def test_sentiment_badge_shown_when_present(self):
        article = self._make_article(sentiment="positif")
        result = self._fn()([article])
        assert "badge-positif" in result

    def test_score_badge_shown_when_present(self):
        article = self._make_article(score_pertinence=90)
        result = self._fn()([article])
        assert "badge-score" in result

    def test_image_shown_when_present(self):
        article = self._make_article(**{"Images": [{"url": "https://img.com/photo.jpg"}]})
        result = self._fn()([article])
        assert "https://img.com/photo.jpg" in result

    def test_date_truncated_to_10_chars(self):
        article = self._make_article(**{"Date de publication": "2026-03-06T10:00:00Z"})
        result = self._fn()([article])
        assert "2026-03-06" in result
        # Full ISO string should NOT appear
        assert "T10:00:00" not in result

    def test_article_url_defaults_to_hash(self):
        article = {
            "Sources": "Test",
            "Date de publication": "2026-01-01",
            "Résumé": "un résumé assez long pour être utilisé",
        }
        result = self._fn()([article])
        assert 'href="#"' in result


# ═════════════════════════════════════════════════════════════════════════════
# generate_newsletter_from_48h
# ═════════════════════════════════════════════════════════════════════════════

class TestGenerateNewsletterFrom48h:
    def _fn(self):
        from utils.exporters.newsletter import generate_newsletter_from_48h
        return generate_newsletter_from_48h

    def _make_article(self, source="TestSource", date="2026-03-06T10:00:00Z", score=None):
        a = {
            "URL": f"https://example.com/{source}",
            "Sources": source,
            "Date de publication": date,
            "Résumé": f"Résumé de {source} — texte suffisamment long pour être utile.",
        }
        if score is not None:
            a["score_pertinence"] = score
        return a

    def test_reads_48h_json_when_exists(self, tmp_path):
        articles = [self._make_article("Le Monde"), self._make_article("BFMTV")]
        w_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        w_dir.mkdir(parents=True)
        (w_dir / "48-heures.json").write_text(json.dumps(articles), encoding="utf-8")

        result = self._fn()(tmp_path)
        assert "Le Monde" in result
        assert "BFMTV" in result

    def test_custom_title_used(self, tmp_path):
        w_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        w_dir.mkdir(parents=True)
        (w_dir / "48-heures.json").write_text(json.dumps([self._make_article()]), encoding="utf-8")

        result = self._fn()(tmp_path, title="Titre Personnalisé")
        assert "Titre Personnalisé" in result

    def test_auto_title_generated_when_none(self, tmp_path):
        w_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        w_dir.mkdir(parents=True)
        (w_dir / "48-heures.json").write_text("[]", encoding="utf-8")

        result = self._fn()(tmp_path, title=None)
        assert "Veille 48h" in result

    def test_fallback_rglob_when_no_48h_file(self, tmp_path):
        kw_dir = tmp_path / "data" / "articles-from-rss" / "intelligence-artificielle"
        kw_dir.mkdir(parents=True)
        articles = [self._make_article("RFI")]
        (kw_dir / "articles.json").write_text(json.dumps(articles), encoding="utf-8")

        result = self._fn()(tmp_path)
        assert "<!DOCTYPE html>" in result

    def test_sorted_by_score_when_available(self, tmp_path):
        articles = [
            self._make_article("Source-Low", score=10),
            self._make_article("Source-High", score=90),
            self._make_article("Source-Mid", score=50),
        ]
        w_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        w_dir.mkdir(parents=True)
        (w_dir / "48-heures.json").write_text(json.dumps(articles), encoding="utf-8")

        result = self._fn()(tmp_path)
        # Source-High should appear before Source-Low in the HTML
        assert result.index("Source-High") < result.index("Source-Low")

    def test_sorted_by_date_when_no_score(self, tmp_path):
        articles = [
            self._make_article("OldSource", date="2026-03-01T00:00:00Z"),
            self._make_article("NewSource", date="2026-03-06T00:00:00Z"),
        ]
        w_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        w_dir.mkdir(parents=True)
        (w_dir / "48-heures.json").write_text(json.dumps(articles), encoding="utf-8")

        result = self._fn()(tmp_path)
        assert result.index("NewSource") < result.index("OldSource")

    def test_invalid_48h_json_falls_back_to_empty(self, tmp_path):
        w_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        w_dir.mkdir(parents=True)
        (w_dir / "48-heures.json").write_text("{not: valid json}", encoding="utf-8")

        result = self._fn()(tmp_path)
        assert "<!DOCTYPE html>" in result

    def test_non_list_48h_json_handled(self, tmp_path):
        w_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        w_dir.mkdir(parents=True)
        (w_dir / "48-heures.json").write_text('{"key":"value"}', encoding="utf-8")

        result = self._fn()(tmp_path)
        assert "<!DOCTYPE html>" in result

    def test_no_data_directory_returns_html(self, tmp_path):
        result = self._fn()(tmp_path)
        assert "<!DOCTYPE html>" in result


# ═════════════════════════════════════════════════════════════════════════════
# send_newsletter
# ═════════════════════════════════════════════════════════════════════════════

class TestSendNewsletter:
    def _fn(self):
        from utils.exporters.newsletter import send_newsletter
        return send_newsletter

    def test_no_smtp_host_returns_false(self, monkeypatch):
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("SMTP_TO", raising=False)
        result = self._fn()("<html/>", "Test", smtp_host=None, to_addr="user@example.com")
        assert result is False

    def test_no_to_addr_returns_false(self, monkeypatch):
        monkeypatch.delenv("SMTP_TO", raising=False)
        result = self._fn()("<html/>", "Test", smtp_host="mail.example.com", to_addr=None)
        assert result is False

    def test_both_missing_returns_false(self, monkeypatch):
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("SMTP_TO", raising=False)
        result = self._fn()("<html/>", "Test")
        assert result is False

    def test_successful_send_returns_true(self):
        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        with patch("utils.exporters.newsletter.smtplib.SMTP", return_value=mock_server):
            result = self._fn()(
                "<html/>",
                subject="Veille",
                smtp_host="mail.example.com",
                smtp_port=587,
                smtp_user="user@example.com",
                smtp_password="secret",
                from_addr="user@example.com",
                to_addr="recipient@example.com",
            )
        assert result is True

    def test_smtp_exception_returns_false(self):
        with patch("utils.exporters.newsletter.smtplib.SMTP", side_effect=smtplib.SMTPException("error")):
            result = self._fn()(
                "<html/>",
                subject="Veille",
                smtp_host="mail.example.com",
                to_addr="r@example.com",
            )
        assert result is False

    def test_uses_env_vars_for_smtp_host(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.env.com")
        monkeypatch.setenv("SMTP_TO", "env-recipient@example.com")

        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        with patch("utils.exporters.newsletter.smtplib.SMTP", return_value=mock_server) as mock_smtp:
            result = self._fn()("<html/>", subject="Test depuis env")
        assert result is True
        call_args = mock_smtp.call_args
        assert call_args[0][0] == "smtp.env.com"

    def test_no_login_when_no_credentials(self):
        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        with patch("utils.exporters.newsletter.smtplib.SMTP", return_value=mock_server):
            result = self._fn()(
                "<html/>",
                subject="Veille",
                smtp_host="mail.example.com",
                smtp_user=None,
                smtp_password=None,
                to_addr="r@example.com",
            )
        assert result is True
        mock_server.login.assert_not_called()

    def test_connection_error_returns_false(self):
        with patch("utils.exporters.newsletter.smtplib.SMTP", side_effect=ConnectionRefusedError):
            result = self._fn()(
                "<html/>",
                subject="Test",
                smtp_host="unreachable.example.com",
                to_addr="user@example.com",
            )
        assert result is False

"""Tests pour utils/exporters/atom_feed.py et utils/exporters/webhook.py.

Couvre :
  Atom :
    _escape, _stable_id, _normalize_date_rfc3339, _article_to_entry,
    generate_atom_feed, generate_atom_from_flux
  Webhook :
    _format_alert_text, send_discord, send_slack, send_ntfy, notify_alerts
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ═════════════════════════════════════════════════════════════════════════════
# Helpers communes
# ═════════════════════════════════════════════════════════════════════════════

def _article(
    url="https://example.com/article",
    source="Le Monde",
    date="15/01/2026",
    resume="ceci est un résumé d'article sur l'intelligence artificielle",
):
    return {
        "URL": url,
        "Sources": source,
        "Date de publication": date,
        "Résumé": resume,
    }


def _alert(
    value="OpenAI",
    etype="ORG",
    niveau="modéré",
    count_24h=5,
    count_7j=12,
    ratio=2.5,
):
    return {
        "entity_value": value,
        "entity_type": etype,
        "niveau": niveau,
        "count_24h": count_24h,
        "count_7j": count_7j,
        "ratio": ratio,
    }


# ═════════════════════════════════════════════════════════════════════════════
# ATOM FEED
# ═════════════════════════════════════════════════════════════════════════════

class TestEscape:
    def _fn(self):
        from utils.exporters.atom_feed import _escape
        return _escape

    def test_plain_text_unchanged(self):
        assert self._fn()("hello world") == "hello world"

    def test_ampersand_escaped(self):
        assert "&amp;" in self._fn()("A & B")

    def test_less_than_escaped(self):
        assert "&lt;" in self._fn()("<tag>")

    def test_greater_than_escaped(self):
        assert "&gt;" in self._fn()(">")

    def test_quote_escaped(self):
        assert "&quot;" in self._fn()('"quoted"')

    def test_non_string_coerced(self):
        """Doit accepter et convertir un entier."""
        assert self._fn()(42) == "42"


class TestStableId:
    def _fn(self):
        from utils.exporters.atom_feed import _stable_id
        return _stable_id

    def test_starts_with_tag_prefix(self):
        result = self._fn()("https://example.com/art")
        assert result.startswith("tag:wudd.ai,2026:article-")

    def test_deterministic_for_same_url(self):
        url = "https://lemonde.fr/article/123"
        assert self._fn()(url) == self._fn()(url)

    def test_different_urls_produce_different_ids(self):
        assert self._fn()("https://a.com") != self._fn()("https://b.com")


class TestNormalizeDateRfc3339:
    def _fn(self):
        from utils.exporters.atom_feed import _normalize_date_rfc3339
        return _normalize_date_rfc3339

    def test_iso_format_parsed(self):
        result = self._fn()("2026-01-15T10:30:00Z")
        assert "2026-01-15" in result

    def test_date_only_parsed(self):
        result = self._fn()("2026-01-15")
        assert "2026-01-15" in result

    def test_dd_mm_yyyy_parsed(self):
        result = self._fn()("15/01/2026")
        assert "2026-01-15" in result

    def test_empty_string_returns_now(self):
        result = self._fn()("")
        assert "T" in result  # format RFC 3339 contient 'T'

    def test_unparseable_returns_now(self):
        result = self._fn()("not a date")
        assert "T" in result

    def test_result_contains_timezone_info(self):
        result = self._fn()("15/01/2026")
        assert "+" in result or "T" in result


class TestArticleToEntry:
    def _fn(self):
        from utils.exporters.atom_feed import _article_to_entry
        return _article_to_entry

    def test_returns_string(self):
        result = self._fn()(_article(), 0)
        assert isinstance(result, str)

    def test_contains_entry_tag(self):
        result = self._fn()(_article(), 0)
        assert "<entry>" in result
        assert "</entry>" in result

    def test_contains_article_url(self):
        result = self._fn()(_article(url="https://test.fr/art"), 0)
        assert "https://test.fr/art" in result

    def test_contains_source_name(self):
        result = self._fn()(_article(source="Libération"), 0)
        assert "Libération" in result or "Lib&#233;ration" in result or "Libération" in result

    def test_contains_resume_text(self):
        result = self._fn()(_article(resume="résumé important de l'article"), 0)
        assert "résumé" in result

    def test_html_chars_in_url_escaped(self):
        result = self._fn()(_article(url="https://site.com/a?x=1&y=2"), 0)
        assert "&amp;" in result

    def test_image_rendered_when_present(self):
        art = _article()
        art["Images"] = [{"url": "https://img.com/photo.jpg", "Width": 800}]
        result = self._fn()(art, 0)
        assert "https://img.com/photo.jpg" in result
        assert "<img" in result

    def test_entities_rendered_when_present(self):
        art = _article()
        art["entities"] = {"PERSON": ["Macron"], "ORG": ["OpenAI"]}
        result = self._fn()(art, 0)
        assert "Macron" in result
        assert "OpenAI" in result

    def test_sentiment_rendered_when_present(self):
        art = _article()
        art["sentiment"] = "positif"
        art["ton_editorial"] = "factuel"
        result = self._fn()(art, 0)
        assert "positif" in result
        assert "factuel" in result


class TestGenerateAtomFeed:
    def _fn(self):
        from utils.exporters.atom_feed import generate_atom_feed
        return generate_atom_feed

    def test_returns_xml_string(self):
        result = self._fn()([])
        assert isinstance(result, str)
        assert "<?xml" in result

    def test_feed_element_present(self):
        result = self._fn()([])
        assert "<feed" in result
        assert "</feed>" in result

    def test_custom_feed_title(self):
        result = self._fn__([], feed_title="Mon Flux Test") if False else \
                 self._fn()([_article()], feed_title="Mon Flux Test")
        assert "Mon Flux Test" in result

    def test_empty_articles_produces_valid_feed(self):
        result = self._fn()([])
        assert "<entry>" not in result
        assert "</feed>" in result

    def test_max_entries_respected(self):
        articles = [_article(url=f"https://x.com/{i}") for i in range(20)]
        result = self._fn()(articles, max_entries=5)
        assert result.count("<entry>") == 5

    def test_all_articles_included_when_below_max(self):
        articles = [_article(url=f"https://x.com/{i}") for i in range(3)]
        result = self._fn()(articles, max_entries=50)
        assert result.count("<entry>") == 3

    def test_custom_self_url_in_output(self):
        result = self._fn()([_article()], self_url="https://myapp.com/feed.xml")
        assert "https://myapp.com/feed.xml" in result

    def test_exception_in_one_entry_skipped(self):
        """Un article malformé ne doit pas faire échouer tout le feed."""
        articles = [
            _article(url="https://ok.com/art"),
            {"URL": None, "Sources": None, "Date de publication": None, "Résumé": None},
            _article(url="https://ok2.com/art"),
        ]
        result = self._fn()(articles)
        # Au moins les 2 articles valides doivent être présents
        assert "https://ok.com/art" in result
        assert "https://ok2.com/art" in result

    def test_custom_feed_id(self):
        result = self._fn()([_article()], feed_id="tag:myapp.com,2026:feed")
        assert "tag:myapp.com,2026:feed" in result


class TestGenerateAtomFromFlux:
    def _fn(self):
        from utils.exporters.atom_feed import generate_atom_from_flux
        return generate_atom_from_flux

    def _project(self, tmp_path, flux, articles):
        flux_dir = tmp_path / "data" / "articles" / flux
        flux_dir.mkdir(parents=True)
        (flux_dir / "articles.json").write_text(
            json.dumps(articles, ensure_ascii=False), encoding="utf-8"
        )
        return tmp_path

    def test_returns_xml_string(self, tmp_path):
        proj = self._project(tmp_path, "IA", [_article()])
        result = self._fn()(proj, "IA")
        assert "<?xml" in result

    def test_includes_articles_from_flux(self, tmp_path):
        proj = self._project(tmp_path, "IA", [_article(url="https://ia.com/art")])
        result = self._fn()(proj, "IA")
        assert "https://ia.com/art" in result

    def test_nonexistent_flux_returns_empty_feed(self, tmp_path):
        (tmp_path / "data" / "articles").mkdir(parents=True)
        result = self._fn()(tmp_path, "FluxInexistant")
        assert "<?xml" in result
        assert "<entry>" not in result

    def test_cache_files_excluded(self, tmp_path):
        flux_dir = tmp_path / "data" / "articles" / "IA"
        cache_dir = flux_dir / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "cached.json").write_text(
            json.dumps([_article(url="https://cached.com")]), encoding="utf-8"
        )
        result = self._fn()(tmp_path, "IA")
        assert "https://cached.com" not in result


# ═════════════════════════════════════════════════════════════════════════════
# WEBHOOK
# ═════════════════════════════════════════════════════════════════════════════

class TestFormatAlertText:
    def _fn(self):
        from utils.exporters.webhook import _format_alert_text
        return _format_alert_text

    def test_critique_emoji(self):
        result = self._fn()(_alert(niveau="critique"))
        assert "🔴" in result

    def test_eleve_emoji(self):
        result = self._fn()(_alert(niveau="élevé"))
        assert "🟠" in result

    def test_modere_emoji(self):
        result = self._fn()(_alert(niveau="modéré"))
        assert "🟡" in result

    def test_unknown_niveau_gets_default_emoji(self):
        result = self._fn()(_alert(niveau="unknown"))
        assert "⚪" in result

    def test_contains_entity_value(self):
        result = self._fn()(_alert(value="Emmanuel Macron"))
        assert "Emmanuel Macron" in result

    def test_contains_counts(self):
        result = self._fn()(_alert(count_24h=8, count_7j=20))
        assert "8" in result
        assert "20" in result

    def test_contains_ratio(self):
        result = self._fn()(_alert(ratio=3.5))
        assert "3.5" in result

    def test_entity_type_translated(self):
        result = self._fn()(_alert(etype="PERSON"))
        assert "Personne" in result

    def test_unknown_entity_type_kept_as_is(self):
        result = self._fn()(_alert(etype="UNKNOWN_TYPE"))
        assert "UNKNOWN_TYPE" in result

    def test_silence_rendered_distinctly(self):
        alert = _alert(count_24h=0, count_7j=21)
        alert["type"] = "silence"
        alert["baseline_avg_per_day"] = 3.0
        result = self._fn()(alert)
        assert "🔇" in result
        assert "silence" in result

    def test_nouveaute_rendered_distinctly(self):
        alert = _alert(count_24h=4, count_7j=0)
        alert["nouveaute"] = True
        result = self._fn()(alert)
        assert "🆕" in result

    def test_article_link_markdown(self):
        alert = _alert()
        alert["article_url"] = "https://ex.com/a"
        alert["article_source"] = "Le Monde"
        result = self._fn()(alert, markdown=True)
        assert "[Le Monde](https://ex.com/a)" in result

    def test_article_link_plain_for_ntfy(self):
        alert = _alert()
        alert["article_url"] = "https://ex.com/a"
        result = self._fn()(alert, markdown=False)
        assert "https://ex.com/a" in result
        assert "[" not in result

    def test_prediction_rendered(self):
        alert = _alert()
        alert["prediction_seuil_dans_minutes"] = 30
        result = self._fn()(alert)
        assert "🔮" in result and "30" in result


def _patch_session(post_impl):
    """Patche create_session_with_retries pour renvoyer une session mockée.

    ``post_impl`` peut être un callable (side_effect) ou un objet réponse
    (return_value).
    """
    import types
    mock_session = MagicMock()
    if isinstance(post_impl, (types.FunctionType, BaseException)):
        mock_session.post.side_effect = post_impl
    else:
        mock_session.post.return_value = post_impl
    return patch("utils.exporters.webhook.create_session_with_retries",
                 return_value=mock_session)


class TestSendDiscord:
    def _fn(self):
        from utils.exporters.webhook import send_discord
        return send_discord

    def test_no_url_returns_false(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_DISCORD", raising=False)
        assert self._fn()([], webhook_url="") is False

    def test_no_url_no_env_returns_false(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_DISCORD", raising=False)
        assert self._fn()([_alert()]) is False

    def test_successful_send_returns_true(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_DISCORD", raising=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with _patch_session(mock_resp) as mock_factory:
            result = self._fn()([_alert()], webhook_url="https://discord.com/webhook/123")
        assert result is True
        mock_factory.return_value.post.assert_called_once()

    def test_sends_embed_not_content(self, monkeypatch):
        """Discord doit envoyer un embed (et non un simple content)."""
        monkeypatch.delenv("WEBHOOK_DISCORD", raising=False)
        captured = {}

        def mock_post(url, json=None, timeout=None):
            captured["payload"] = json
            mock_r = MagicMock()
            mock_r.raise_for_status.return_value = None
            return mock_r

        with _patch_session(mock_post):
            self._fn()([_alert(value="OpenAI")], webhook_url="https://discord.com/wh")

        assert "embeds" in captured["payload"]
        assert "OpenAI" in captured["payload"]["embeds"][0]["description"]

    def test_http_error_returns_false(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_DISCORD", raising=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 400")
        with _patch_session(mock_resp):
            result = self._fn()([_alert()], webhook_url="https://discord.com/webhook/error")
        assert result is False

    def test_top_n_limits_alerts_sent(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_DISCORD", raising=False)
        captured = {}

        def mock_post(url, json=None, timeout=None):
            captured["text"] = json["embeds"][0]["description"]
            mock_r = MagicMock()
            mock_r.raise_for_status.return_value = None
            return mock_r

        alerts = [_alert(value=f"Entité {i}") for i in range(20)]
        with _patch_session(mock_post):
            self._fn()(alerts, webhook_url="https://discord.com/wh", top_n=3)

        # Seules 3 entités doivent apparaître dans la description envoyée
        count = sum(1 for i in range(20) if f"Entité {i}" in captured.get("text", ""))
        assert count == 3

    def test_connection_error_returns_false(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_DISCORD", raising=False)

        def _raise(*_a, **_k):
            raise ConnectionError("no route")

        with _patch_session(_raise):
            result = self._fn()([_alert()], webhook_url="https://discord.com/wh")
        assert result is False


class TestSendSlack:
    def _fn(self):
        from utils.exporters.webhook import send_slack
        return send_slack

    def test_no_url_returns_false(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_SLACK", raising=False)
        assert self._fn()([], webhook_url="") is False

    def test_successful_send_returns_true(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_SLACK", raising=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with _patch_session(mock_resp):
            result = self._fn()([_alert()], webhook_url="https://hooks.slack.com/T00/B00/xyz")
        assert result is True

    def test_http_error_returns_false(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_SLACK", raising=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 500")
        with _patch_session(mock_resp):
            result = self._fn()([_alert()], webhook_url="https://hooks.slack.com/T00/B00/error")
        assert result is False

    def test_top_n_respected(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_SLACK", raising=False)
        captured_blocks = {}

        def mock_post(url, json=None, timeout=None):
            captured_blocks["blocks"] = json.get("blocks", [])
            mock_r = MagicMock()
            mock_r.raise_for_status.return_value = None
            return mock_r

        alerts = [_alert(value=f"Entité {i}") for i in range(10)]
        with _patch_session(mock_post):
            self._fn()(alerts, webhook_url="https://hooks.slack.com/wh", top_n=4)

        # Bloc header + divider + 4 sections = 6 blocs maximum
        assert len(captured_blocks.get("blocks", [])) <= 6


class TestSendNtfy:
    def _fn(self):
        from utils.exporters.webhook import send_ntfy
        return send_ntfy

    def test_no_url_returns_false(self, monkeypatch):
        monkeypatch.delenv("NTFY_URL", raising=False)
        assert self._fn()([], ntfy_url="") is False

    def test_empty_alerts_with_url_returns_true(self, monkeypatch):
        monkeypatch.delenv("NTFY_URL", raising=False)
        # alerts vide → early return True selon l'implémentation
        result = self._fn()([], ntfy_url="https://ntfy.sh/wudd")
        assert result is True

    def test_successful_send_returns_true(self, monkeypatch):
        monkeypatch.delenv("NTFY_URL", raising=False)
        monkeypatch.delenv("NTFY_TOKEN", raising=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with _patch_session(mock_resp):
            result = self._fn()([_alert()], ntfy_url="https://ntfy.sh/wudd")
        assert result is True

    def test_token_added_to_auth_header(self, monkeypatch):
        monkeypatch.delenv("NTFY_URL", raising=False)
        monkeypatch.delenv("NTFY_TOKEN", raising=False)
        captured = {}

        def mock_post(url, data=None, headers=None, timeout=None):
            captured["headers"] = headers
            mock_r = MagicMock()
            mock_r.raise_for_status.return_value = None
            return mock_r

        with _patch_session(mock_post):
            self._fn()([_alert()], ntfy_url="https://ntfy.sh/wudd", ntfy_token="mytoken")

        assert "Authorization" in captured.get("headers", {})
        assert "mytoken" in captured["headers"]["Authorization"]

    def test_http_error_returns_false(self, monkeypatch):
        monkeypatch.delenv("NTFY_URL", raising=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("403")
        with _patch_session(mock_resp):
            result = self._fn()([_alert()], ntfy_url="https://ntfy.sh/wudd")
        assert result is False


class TestNotifyAlerts:
    def _fn(self):
        from utils.exporters.webhook import notify_alerts
        return notify_alerts

    def test_empty_alerts_returns_empty_dict(self):
        result = self._fn()([])
        assert result == {}

    def test_no_env_vars_returns_empty_dict(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_DISCORD", raising=False)
        monkeypatch.delenv("WEBHOOK_SLACK", raising=False)
        monkeypatch.delenv("NTFY_URL", raising=False)
        result = self._fn()([_alert()])
        assert result == {}

    def test_discord_called_when_env_set(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_DISCORD", "https://discord.com/wh")
        monkeypatch.delenv("WEBHOOK_SLACK", raising=False)
        monkeypatch.delenv("NTFY_URL", raising=False)
        with patch("utils.exporters.webhook.send_discord", return_value=True) as mock_disc:
            result = self._fn()([_alert()])
        assert "discord" in result
        mock_disc.assert_called_once()

    def test_slack_called_when_env_set(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_DISCORD", raising=False)
        monkeypatch.setenv("WEBHOOK_SLACK", "https://hooks.slack.com/wh")
        monkeypatch.delenv("NTFY_URL", raising=False)
        with patch("utils.exporters.webhook.send_slack", return_value=True) as mock_slack:
            result = self._fn()([_alert()])
        assert "slack" in result
        mock_slack.assert_called_once()

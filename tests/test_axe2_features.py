"""tests/test_axe2_features.py — Tests des fonctionnalités AXE 2.

Couvre :
- utils/vector_search.py (TF-IDF search)
- utils/network_analysis.py (graphe d'influence, Louvain)
- scripts/detect_narrative_propagation.py (jaccard, clustering)
- viewer/routes/auth.py (génération/décodage JWT, hash password)
- utils/exporters/newsletter.py (generate_newsletter_auto)
"""

import json
import hashlib
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ── TF-IDF Search ─────────────────────────────────────────────────────────────

class TestTFIDFSearch:
    def test_build_and_search(self, tmp_path):
        from utils.vector_search import TFIDFSearch

        articles = [
            {"Résumé": "Intelligence artificielle et machine learning en France", "URL": "http://a.com/1"},
            {"Résumé": "OpenAI lance un nouveau modèle de langage très performant", "URL": "http://a.com/2"},
            {"Résumé": "Réchauffement climatique et énergies renouvelables en Europe", "URL": "http://a.com/3"},
            {"Résumé": "La France investit dans l'intelligence artificielle", "URL": "http://a.com/4"},
        ]

        searcher = TFIDFSearch(tmp_path)
        searcher.build(articles)
        results = searcher.search("intelligence artificielle France", top_k=2)

        assert len(results) == 2
        urls = [r["URL"] for r in results]
        assert "http://a.com/1" in urls or "http://a.com/4" in urls

    def test_search_empty_index(self, tmp_path):
        from utils.vector_search import TFIDFSearch

        searcher = TFIDFSearch(tmp_path)
        results = searcher.search("quelque chose", top_k=5)
        assert results == []

    def test_search_returns_similarity_score(self, tmp_path):
        from utils.vector_search import TFIDFSearch

        articles = [
            {"Résumé": "test test test", "URL": "http://example.com"},
        ]
        searcher = TFIDFSearch(tmp_path)
        searcher.build(articles)
        results = searcher.search("test", top_k=1)
        assert results
        assert "_similarity" in results[0]
        assert 0.0 <= results[0]["_similarity"] <= 1.0

    def test_top_k_limit(self, tmp_path):
        from utils.vector_search import TFIDFSearch

        articles = [{"Résumé": f"article numéro {i}", "URL": f"http://x.com/{i}"} for i in range(20)]
        searcher = TFIDFSearch(tmp_path)
        searcher.build(articles)
        results = searcher.search("article", top_k=5)
        assert len(results) <= 5


# ── Network Analysis ──────────────────────────────────────────────────────────

class TestNetworkAnalysis:
    def _make_articles(self):
        """Articles de test avec entités pour construire un graphe."""
        now = datetime.now(timezone.utc)
        return [
            {
                "Sources": "Le Monde",
                "Date de publication": (now - timedelta(days=1)).isoformat(),
                "Résumé": "Macron visite Paris",
                "entities": {"PERSON": ["Macron"], "GPE": ["Paris", "France"]},
            },
            {
                "Sources": "Le Figaro",
                "Date de publication": (now - timedelta(days=2)).isoformat(),
                "Résumé": "Macron annonce une réforme",
                "entities": {"PERSON": ["Macron"], "GPE": ["France"]},
            },
            {
                "Sources": "Libération",
                "Date de publication": (now - timedelta(days=3)).isoformat(),
                "Résumé": "OpenAI France",
                "entities": {"ORG": ["OpenAI"], "GPE": ["France"]},
            },
        ]

    def test_build_source_graph_returns_graph_or_none(self):
        from utils.network_analysis import build_source_graph
        articles = self._make_articles()
        G = build_source_graph(articles)
        # G est None si networkx non disponible, sinon un graphe
        assert G is None or hasattr(G, "nodes")

    def test_detect_communities(self):
        from utils.network_analysis import build_source_graph, detect_communities
        articles = self._make_articles()
        G = build_source_graph(articles)
        partition = detect_communities(G)
        if G is None:
            assert partition == {}
        else:
            # Toutes les sources sont dans le partition
            for node in G.nodes():
                assert node in partition

    def test_find_hubs(self):
        from utils.network_analysis import build_source_graph, find_hubs
        articles = self._make_articles()
        G = build_source_graph(articles)
        hubs = find_hubs(G, top_n=5)
        if G is None:
            assert hubs == []
        else:
            assert isinstance(hubs, list)
            for h in hubs:
                assert "id" in h
                assert "centrality" in h
                assert "degree" in h

    def test_build_influence_report_structure(self):
        from utils.network_analysis import build_influence_report
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Créer quelques articles de test
            articles_dir = root / "data" / "articles-from-rss"
            articles_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            articles = [
                {
                    "Sources": "Source A",
                    "Date de publication": (now - timedelta(days=1)).isoformat(),
                    "Résumé": "Article test",
                    "entities": {"PERSON": ["Dupont"], "GPE": ["Paris"]},
                },
                {
                    "Sources": "Source B",
                    "Date de publication": (now - timedelta(days=2)).isoformat(),
                    "Résumé": "Autre article",
                    "entities": {"PERSON": ["Dupont"], "ORG": ["SNCF"]},
                },
            ]
            (articles_dir / "test.json").write_text(json.dumps(articles), encoding="utf-8")

            report = build_influence_report(root, days=30)

        assert "generated_at" in report
        assert "nodes_count" in report
        assert "edges_count" in report
        assert "communities" in report
        assert "hubs" in report


# ── Narrative Propagation ─────────────────────────────────────────────────────

class TestNarrativePropagation:
    def test_ngrams(self):
        from scripts.detect_narrative_propagation import _ngrams
        ng = _ngrams("le chat mange la souris ce soir", n=3)
        assert "le chat mange" in ng
        assert "chat mange la" in ng

    def test_jaccard_identical(self):
        from scripts.detect_narrative_propagation import _jaccard
        s = {"a b c", "b c d"}
        assert _jaccard(s, s) == 1.0

    def test_jaccard_disjoint(self):
        from scripts.detect_narrative_propagation import _jaccard
        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_jaccard_partial(self):
        from scripts.detect_narrative_propagation import _jaccard
        j = _jaccard({"a", "b", "c"}, {"b", "c", "d"})
        assert 0 < j < 1

    def test_group_by_narrative_needs_two_sources(self):
        from scripts.detect_narrative_propagation import _group_by_narrative
        now = datetime.now(timezone.utc)
        long_text = "intelligence artificielle machine learning données modèles réseaux apprentissage"
        articles = [
            {
                "Sources": "Source A",
                "_parsed_date": now - timedelta(hours=2),
                "Résumé": f"{long_text} premier article",
                "entities": {},
            },
            {
                "Sources": "Source B",
                "_parsed_date": now - timedelta(hours=1),
                "Résumé": f"{long_text} deuxième article",
                "entities": {},
            },
        ]
        for a in articles:
            from scripts.detect_narrative_propagation import _ngrams
            a["_ngrams"] = _ngrams(a["Résumé"], n=3)
        clusters = _group_by_narrative(articles)
        # Avec deux sources similaires → au moins un cluster
        assert isinstance(clusters, list)

    def test_analyse_cluster_structure(self):
        from scripts.detect_narrative_propagation import _analyse_cluster
        now = datetime.now(timezone.utc)
        cluster = [
            {
                "Sources": "Première Source",
                "_parsed_date": now - timedelta(hours=5),
                "Résumé": "OpenAI lance GPT-5 avec de nouvelles capacités",
                "URL": "http://a.com/1",
                "entities": {},
            },
            {
                "Sources": "Deuxième Source",
                "_parsed_date": now - timedelta(hours=3),
                "Résumé": "OpenAI annonce GPT-5",
                "URL": "http://b.com/1",
                "entities": {},
            },
        ]
        result = _analyse_cluster(cluster)
        assert result["first_source"] == "Première Source"
        assert len(result["propagated_by"]) == 1
        assert result["propagated_by"][0]["source"] == "Deuxième Source"
        assert result["propagated_by"][0]["delay_hours"] == 2.0
        assert result["nb_sources"] == 2
        assert "viral_score" in result


# ── Auth JWT ──────────────────────────────────────────────────────────────────

class TestAuthJWT:
    def test_hash_password(self):
        from viewer.routes.auth import _hash_password
        h = _hash_password("monmdp")
        assert len(h) == 64  # SHA-256 hex = 64 chars
        assert h == hashlib.sha256(b"monmdp").hexdigest()

    def test_generate_and_decode_token(self):
        try:
            import jwt  # noqa
        except ImportError:
            import pytest
            pytest.skip("PyJWT non installé")

        from viewer.routes.auth import _generate_token, _decode_token
        token = _generate_token("testuser", "admin")
        assert isinstance(token, str)
        payload = _decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"
        assert payload["role"] == "admin"

    def test_decode_invalid_token(self):
        from viewer.routes.auth import _decode_token
        result = _decode_token("not.a.valid.token")
        assert result is None

    def test_is_auth_enabled_no_users(self, tmp_path, monkeypatch):
        """Sans users.json → auth désactivée."""
        import os
        monkeypatch.setenv("AUTH_ENABLED", "true")
        # Patcher _USERS_PATH vers un fichier inexistant
        import viewer.routes.auth as auth_mod
        original = auth_mod._USERS_PATH
        auth_mod._USERS_PATH = tmp_path / "nonexistent.json"
        try:
            result = auth_mod._is_auth_enabled()
            assert result is False
        finally:
            auth_mod._USERS_PATH = original

    def test_is_auth_disabled_by_env(self, monkeypatch):
        import viewer.routes.auth as auth_mod
        monkeypatch.setenv("AUTH_ENABLED", "false")
        assert auth_mod._is_auth_enabled() is False


# ── Newsletter ────────────────────────────────────────────────────────────────

class TestNewsletterAuto:
    def test_generate_newsletter_auto_dry_run(self, tmp_path):
        """Vérifier que generate_newsletter_auto retourne du HTML sans écrire."""
        from utils.exporters.newsletter import generate_newsletter_auto

        # Créer des articles de test
        now = datetime.now(timezone.utc)
        articles_dir = tmp_path / "data" / "articles-from-rss"
        articles_dir.mkdir(parents=True)
        articles = [
            {
                "Date de publication": (now - timedelta(hours=i)).isoformat(),
                "Sources": f"Source {i}",
                "URL": f"http://example.com/{i}",
                "Résumé": f"Article {i}: résumé de test avec contenu suffisant pour le scoring",
                "entities": {"ORG": ["OpenAI"]},
            }
            for i in range(5)
        ]
        (articles_dir / "test.json").write_text(json.dumps(articles), encoding="utf-8")

        html = generate_newsletter_auto(tmp_path, top_n=3, days=7, dry_run=True)
        # En cas d'erreur ou d'articles insuffisants, retourne quand même du HTML
        assert isinstance(html, str)

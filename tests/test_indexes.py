"""tests/test_indexes.py — Tests des nouveaux modules d'indexation WUDD.ai

Couvre :
  - utils/article_index.py  (ArticleIndex, get_article_index)
  - utils/entity_index.py   (EntityIndex, get_entity_index)
  - utils/synthesis_cache.py (SynthesisCache, get_synthesis_cache)
  - utils/scoring.py         (get_scoring_engine singleton, get_top_articles_from_index)
  - scripts/generate_briefing.py (compute_top_entities O(n))
"""

import json
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# ── Fixtures partagées ────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_root(tmp_path):
    """Répertoire projet temporaire avec la structure minimale."""
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "keyword-to-search.json").write_text("[]", encoding="utf-8")
    (tmp_path / "config" / "sources_credibility.json").write_text("{}", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def sample_articles():
    """Articles de test au format interne WUDD.ai."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    old_date = "2020-01-01"
    return [
        {
            "URL": "http://test.com/1",
            "Sources": "Le Monde",
            "Date de publication": today,
            "Résumé": "Article sur l'intelligence artificielle et OpenAI.",
            "entities": {"PERSON": ["Macron", "Biden"], "ORG": ["OpenAI", "Google"]},
            "sentiment": "positif",
            "Images": [{"URL": "http://img.test/1.jpg", "Width": 600}],
        },
        {
            "URL": "http://test.com/2",
            "Sources": "Reuters",
            "Date de publication": yesterday,
            "Résumé": "Biden rencontre Macron à Paris pour discuter de l'OTAN.",
            "entities": {"PERSON": ["Biden", "Macron"], "GPE": ["France", "Paris"]},
            "sentiment": "neutre",
        },
        {
            "URL": "http://test.com/3",
            "Sources": "BBC",
            "Date de publication": old_date,
            "Résumé": "Très vieil article sans entités.",
            "entities": {},
        },
    ]


@pytest.fixture()
def articles_on_disk(tmp_root, sample_articles):
    """Écrit les articles sur disque et retourne le chemin relatif."""
    json_file = tmp_root / "data" / "articles.json"
    json_file.write_text(json.dumps(sample_articles), encoding="utf-8")
    return "data/articles.json"


# ── Tests ArticleIndex ────────────────────────────────────────────────────────

class TestArticleIndex:
    def test_update_ajoute_entrees(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        n = idx.update(sample_articles, articles_on_disk)
        assert n == 3

    def test_update_idempotent(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        n2 = idx.update(sample_articles, articles_on_disk)
        # Deuxième appel : URL déjà connues → 0 ajouts
        assert n2 == 0
        assert idx.count() == 3

    def test_get_recent_filtre_par_date(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        # Fenêtre 48h : 2 articles récents, 1 ancien (2020)
        recent = idx.get_recent(hours=48)
        assert len(recent) == 2
        for e in recent:
            assert e["date"] >= "2026-01-01"

    def test_get_recent_sans_filtre(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        all_entries = idx.get_recent(hours=0)
        assert len(all_entries) == 3

    def test_load_articles_charge_contenu_complet(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        entries = idx.get_recent(hours=48)
        loaded = idx.load_articles(entries)
        assert len(loaded) == 2
        urls = {a["URL"] for a in loaded}
        assert "http://test.com/1" in urls
        assert "http://test.com/2" in urls

    def test_champs_enrichissement_enregistres(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        entries = {e["url"]: e for e in idx.get_recent(hours=0)}
        assert entries["http://test.com/1"]["has_entities"] is True
        assert entries["http://test.com/1"]["has_sentiment"] is True
        assert entries["http://test.com/1"]["has_images"] is True
        assert entries["http://test.com/2"]["has_entities"] is True
        assert entries["http://test.com/3"]["has_entities"] is False

    def test_persistance_sur_disque(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx1 = ArticleIndex(tmp_root)
        idx1.update(sample_articles, articles_on_disk)
        # Nouvelle instance — relit le fichier
        idx2 = ArticleIndex(tmp_root)
        assert idx2.count() == 3

    def test_rebuild_depuis_zero(self, tmp_root, sample_articles):
        from utils.article_index import ArticleIndex
        # Écrire le fichier source
        (tmp_root / "data" / "articles-from-rss").mkdir()
        f = tmp_root / "data" / "articles-from-rss" / "test.json"
        f.write_text(json.dumps(sample_articles), encoding="utf-8")
        idx = ArticleIndex(tmp_root)
        total = idx.rebuild()
        assert total == 3

    def test_stats(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        s = idx.stats()
        assert s["total"] == 3
        assert s["with_entities"] == 2  # article 3 a entities={}
        assert s["with_sentiment"] == 2
        assert s["with_images"] == 1

    def test_get_articles_retourne_toutes_entrees(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        entries = idx.get_articles()
        assert len(entries) == 3
        # Les dicts sont les mêmes références (mutation directe possible)
        assert all(isinstance(e, dict) for e in entries)

    def test_get_articles_permet_ajout_champ(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        for entry in idx.get_articles():
            entry["quality_score"] = 99
        idx.save()
        # Relire depuis disque et vérifier toutes les entrées
        idx2 = ArticleIndex(tmp_root)
        assert all(e.get("quality_score") == 99 for e in idx2.get_articles())

    def test_get_by_url_trouve_article(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        entry = idx.get_by_url("http://test.com/1")
        assert entry is not None
        assert entry["source"] == "Le Monde"

    def test_get_by_url_insensible_slash(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        # Trailing slash ignoré
        entry = idx.get_by_url("http://test.com/1/")
        assert entry is not None

    def test_get_by_url_inconnu_retourne_none(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        entry = idx.get_by_url("http://unknown.com/xyz")
        assert entry is None

    def test_get_by_url_vide_retourne_none(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        assert idx.get_by_url("") is None

    def test_save_public_persiste_index(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        idx = ArticleIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        # Modifier directement une entrée et appeler save()
        idx.get_articles()[0]["quality_score"] = 42
        idx.save()
        idx2 = ArticleIndex(tmp_root)
        first = idx2.get_articles()[0]
        assert first.get("quality_score") == 42


# ── Tests EntityIndex ─────────────────────────────────────────────────────────

class TestEntityIndex:
    def test_update_cree_references(self, tmp_root, sample_articles, articles_on_disk):
        from utils.entity_index import EntityIndex
        idx = EntityIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        refs = idx.get_refs("PERSON", "Macron")
        assert len(refs) == 2

    def test_update_idempotent_sur_meme_fichier(self, tmp_root, sample_articles, articles_on_disk):
        from utils.entity_index import EntityIndex
        idx = EntityIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        idx.update(sample_articles, articles_on_disk)
        # Le fichier est remplacé → pas de doublons
        refs = idx.get_refs("PERSON", "Macron")
        assert len(refs) == 2

    def test_load_articles_pour_entite(self, tmp_root, sample_articles, articles_on_disk):
        from utils.entity_index import EntityIndex
        idx = EntityIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        arts = idx.load_articles("PERSON", "Macron")
        assert len(arts) == 2
        urls = {a["URL"] for a in arts}
        assert "http://test.com/1" in urls
        assert "http://test.com/2" in urls

    def test_entite_absente_retourne_liste_vide(self, tmp_root, sample_articles, articles_on_disk):
        from utils.entity_index import EntityIndex
        idx = EntityIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        assert idx.get_refs("PERSON", "Personne Inexistante") == []
        assert idx.load_articles("PERSON", "Personne Inexistante") == []

    def test_search_values_retourne_groupes_par_type(self, tmp_root, sample_articles, articles_on_disk):
        from utils.entity_index import EntityIndex

        idx = EntityIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)

        result = idx.search_values("open")

        assert len(result) == 1
        assert result[0]["type"] == "ORG"
        assert result[0]["mention_count"] == 1
        assert result[0]["top"][0]["value"] == "OpenAI"

    def test_deduplication_url_dans_load_articles(self, tmp_root, sample_articles, articles_on_disk):
        """Même URL dans deux fichiers → un seul article chargé."""
        from utils.entity_index import EntityIndex
        idx = EntityIndex(tmp_root)
        # Écrire le même article dans un 2e fichier
        f2 = tmp_root / "data" / "other.json"
        f2.write_text(json.dumps([sample_articles[0]]), encoding="utf-8")
        idx.update(sample_articles, articles_on_disk)
        idx.update([sample_articles[0]], "data/other.json")
        arts = idx.load_articles("PERSON", "Macron")
        urls = [a["URL"] for a in arts]
        assert urls.count("http://test.com/1") == 1

    def test_cooccurrences(self, tmp_root, sample_articles, articles_on_disk):
        from utils.entity_index import EntityIndex
        idx = EntityIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        cooc = idx.get_cooccurrences("PERSON", "Macron", top_n=10)
        assert len(cooc) > 0
        types_vals = {(c["type"], c["value"]) for c in cooc}
        # Biden co-occur avec Macron dans les 2 articles
        assert ("PERSON", "Biden") in types_vals

    def test_cooccurrences_count_correct(self, tmp_root, sample_articles, articles_on_disk):
        from utils.entity_index import EntityIndex
        idx = EntityIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        cooc = idx.get_cooccurrences("PERSON", "Macron", top_n=20)
        biden_entry = next((c for c in cooc if c["value"] == "Biden"), None)
        assert biden_entry is not None
        assert biden_entry["count"] == 2  # présent dans article 1 et 2

    def test_get_top_entities(self, tmp_root, sample_articles, articles_on_disk):
        from utils.entity_index import EntityIndex
        idx = EntityIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        top = idx.get_top_entities(top_n=5)
        assert len(top) > 0
        # Macron et Biden apparaissent 2 fois chacun → doivent être en tête
        values = [e["value"] for e in top[:4]]
        assert "Macron" in values
        assert "Biden" in values

    def test_rebuild_depuis_zero(self, tmp_root, sample_articles):
        from utils.entity_index import EntityIndex
        (tmp_root / "data" / "articles-from-rss").mkdir()
        f = tmp_root / "data" / "articles-from-rss" / "test.json"
        f.write_text(json.dumps(sample_articles), encoding="utf-8")
        idx = EntityIndex(tmp_root)
        total_refs = idx.rebuild()
        assert total_refs > 0
        assert idx.count_entities() > 0

    def test_stats(self, tmp_root, sample_articles, articles_on_disk):
        from utils.entity_index import EntityIndex
        idx = EntityIndex(tmp_root)
        idx.update(sample_articles, articles_on_disk)
        s = idx.stats()
        assert s["entities"] > 0
        assert s["references"] > 0
        assert "PERSON" in s["by_type"]

    def test_persistance_sur_disque(self, tmp_root, sample_articles, articles_on_disk):
        from utils.entity_index import EntityIndex
        idx1 = EntityIndex(tmp_root)
        idx1.update(sample_articles, articles_on_disk)
        n1 = idx1.count_entities()
        idx2 = EntityIndex(tmp_root)
        assert idx2.count_entities() == n1

    def test_migration_v1_vers_v2_automatique(self, tmp_root, sample_articles):
        """Un index v1 (clés non normalisées) doit être migré automatiquement en v2."""
        import json as _json
        from utils.entity_index import EntityIndex, _INDEX_FILENAME

        # Construire un index v1 avec des clés mixtes-casse
        index_path = tmp_root / "data" / _INDEX_FILENAME
        v1_data = {
            "version": 1,
            "index": {
                "PERSON:Emmanuel Macron": [{"file": "data/articles.json", "idx": 0, "date": "2026-01-01"}],
                "PERSON:emmanuel macron": [{"file": "data/articles.json", "idx": 1, "date": "2026-01-02"}],
                "ORG:OpenAI": [{"file": "data/articles.json", "idx": 0, "date": "2026-01-01"}],
            },
        }
        index_path.write_text(_json.dumps(v1_data), encoding="utf-8")

        idx = EntityIndex(tmp_root)
        # Après chargement, les refs doivent être fusionnées sous la clé normalisée
        refs = idx.get_refs("PERSON", "Emmanuel Macron")
        assert len(refs) == 2, f"Attendu 2 refs fusionnées, obtenu {len(refs)}"

        # Le fichier doit avoir été migré vers v2
        migrated = _json.loads(index_path.read_text(encoding="utf-8"))
        assert migrated.get("version") == 2
        assert "caps" in migrated

    def test_migration_v1_fusionne_variantes_casse(self, tmp_root):
        """Variantes de casse d'une même entité doivent être fusionnées lors de la migration."""
        import json as _json
        from utils.entity_index import EntityIndex, _INDEX_FILENAME

        index_path = tmp_root / "data" / _INDEX_FILENAME
        v1_data = {
            "version": 1,
            "index": {
                "ORG:OpenAI": [{"file": "f.json", "idx": 0, "date": "2026-01-01"}],
                "ORG:openai": [{"file": "f.json", "idx": 1, "date": "2026-01-02"}],
                "ORG:OPENAI": [{"file": "f.json", "idx": 2, "date": "2026-01-03"}],
            },
        }
        index_path.write_text(_json.dumps(v1_data), encoding="utf-8")

        idx = EntityIndex(tmp_root)
        refs = idx.get_refs("ORG", "openai")
        # Toutes les variantes doivent être dédupliquées dans la même clé normalisée
        assert len(refs) == 3

        # La forme d'affichage canonique doit être "OpenAI" (meilleur cap_score)
        display = idx.get_display_name("ORG", "openai")
        assert display == "OpenAI"


# ── Tests SynthesisCache ──────────────────────────────────────────────────────

class TestSynthesisCache:
    def test_set_et_get(self, tmp_root):
        from utils.synthesis_cache import SynthesisCache
        sc = SynthesisCache(tmp_root)
        sc.set("PERSON", "Macron", info_text="Fiche Macron", rag_text="Analyse RAG")
        entry = sc.get("PERSON", "Macron")
        assert entry is not None
        assert entry["info_text"] == "Fiche Macron"
        assert entry["rag_text"] == "Analyse RAG"
        assert entry["entity_type"] == "PERSON"
        assert entry["entity_value"] == "Macron"

    def test_entite_absente_retourne_none(self, tmp_root):
        from utils.synthesis_cache import SynthesisCache
        sc = SynthesisCache(tmp_root)
        assert sc.get("PERSON", "Inconnu") is None

    def test_invalidation(self, tmp_root):
        from utils.synthesis_cache import SynthesisCache
        sc = SynthesisCache(tmp_root)
        sc.set("ORG", "OpenAI", info_text="Fiche OpenAI")
        assert sc.get("ORG", "OpenAI") is not None
        removed = sc.invalidate("ORG", "OpenAI")
        assert removed is True
        assert sc.get("ORG", "OpenAI") is None

    def test_invalidation_entite_absente(self, tmp_root):
        from utils.synthesis_cache import SynthesisCache
        sc = SynthesisCache(tmp_root)
        assert sc.invalidate("PERSON", "Inexistant") is False

    def test_entrees_differentes_isolees(self, tmp_root):
        from utils.synthesis_cache import SynthesisCache
        sc = SynthesisCache(tmp_root)
        sc.set("PERSON", "Macron", info_text="Macron info")
        sc.set("ORG", "OpenAI", info_text="OpenAI info")
        assert sc.get("PERSON", "Macron")["info_text"] == "Macron info"
        assert sc.get("ORG", "OpenAI")["info_text"] == "OpenAI info"

    def test_persistance_sur_disque(self, tmp_root):
        from utils.synthesis_cache import SynthesisCache
        sc1 = SynthesisCache(tmp_root)
        sc1.set("GPE", "France", info_text="Fiche France")
        sc2 = SynthesisCache(tmp_root)
        entry = sc2.get("GPE", "France")
        assert entry is not None
        assert entry["info_text"] == "Fiche France"

    def test_expiration_ttl(self, tmp_root):
        from utils.synthesis_cache import SynthesisCache
        # TTL de 0 heure → toujours expiré
        sc = SynthesisCache(tmp_root, ttl_hours=0)
        sc.set("PERSON", "Macron", info_text="Test")
        # Forcer une date d'expiration dans le passé
        import hashlib
        key = hashlib.md5("PERSON:Macron".encode()).hexdigest()
        sc._data[key]["expires_at"] = "2020-01-01T00:00:00Z"
        sc._save()
        # Nouvelle instance relit le fichier
        sc2 = SynthesisCache(tmp_root)
        assert sc2.get("PERSON", "Macron") is None

    def test_purge_expired(self, tmp_root):
        from utils.synthesis_cache import SynthesisCache
        import hashlib
        sc = SynthesisCache(tmp_root)
        sc.set("PERSON", "A", info_text="ok")
        sc.set("PERSON", "B", info_text="expired")
        # Forcer l'expiration de B
        key_b = hashlib.md5("PERSON:B".encode()).hexdigest()
        sc._data[key_b]["expires_at"] = "2020-01-01T00:00:00Z"
        sc._save()
        removed = sc.purge_expired()
        assert removed == 1
        assert sc.get("PERSON", "A") is not None
        assert sc.get("PERSON", "B") is None

    def test_stats(self, tmp_root):
        from utils.synthesis_cache import SynthesisCache
        import hashlib
        sc = SynthesisCache(tmp_root)
        sc.set("PERSON", "X", info_text="valid")
        sc.set("PERSON", "Y", info_text="also valid")
        key_y = hashlib.md5("PERSON:Y".encode()).hexdigest()
        sc._data[key_y]["expires_at"] = "2020-01-01T00:00:00Z"
        sc._save()
        s = sc.stats()
        assert s["valid"] == 1
        assert s["expired"] == 1
        assert s["total"] == 2


# ── Tests ScoringEngine singleton ─────────────────────────────────────────────

class TestScoringEngineSingleton:
    def test_meme_instance_retournee(self, tmp_root):
        from utils.scoring import get_scoring_engine
        e1 = get_scoring_engine(tmp_root)
        e2 = get_scoring_engine(tmp_root)
        assert e1 is e2

    def test_instances_differentes_par_root(self, tmp_path):
        from utils.scoring import get_scoring_engine
        root1 = tmp_path / "proj1"
        root2 = tmp_path / "proj2"
        for r in (root1, root2):
            r.mkdir()
            (r / "config").mkdir()
            (r / "config" / "keyword-to-search.json").write_text("[]")
            (r / "config" / "sources_credibility.json").write_text("{}")
        e1 = get_scoring_engine(root1)
        e2 = get_scoring_engine(root2)
        assert e1 is not e2

    def test_get_top_articles_from_index(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        from utils.scoring import get_scoring_engine
        # Construire l'index
        aidx = ArticleIndex(tmp_root)
        aidx.update(sample_articles, articles_on_disk)
        engine = get_scoring_engine(tmp_root)
        top = engine.get_top_articles_from_index(top_n=5, hours=48)
        # 2 articles dans les 48h (article 3 est de 2020)
        assert len(top) == 2
        # Chaque article doit avoir un score_pertinence
        for a in top:
            assert "score_pertinence" in a
            assert 0 <= a["score_pertinence"] <= 100

    def test_fallback_si_index_absent(self, tmp_root, sample_articles, articles_on_disk):
        """Si article_index.json n'existe pas, fallback sur get_top_articles() (rglob)."""
        from utils.scoring import get_scoring_engine
        # Pas d'index créé → fallback
        engine = get_scoring_engine(tmp_root)
        # Le rglob ne trouve rien car data/articles/ n'existe pas
        top = engine.get_top_articles_from_index(top_n=5, hours=48)
        assert isinstance(top, list)

    def test_precompute_and_load_top_articles(self, tmp_root, sample_articles, articles_on_disk):
        from utils.article_index import ArticleIndex
        from utils.scoring import (
            get_scoring_engine,
            load_precomputed_top_articles,
            precompute_top_articles,
        )

        aidx = ArticleIndex(tmp_root)
        aidx.update(sample_articles, articles_on_disk)
        engine = get_scoring_engine(tmp_root)

        counts = precompute_top_articles(tmp_root, engine=engine, hours_list=(48,), top_n=10)
        loaded = load_precomputed_top_articles(tmp_root, hours=48, top_n=5, max_age_seconds=3600)

        assert counts[48] == 2
        assert loaded is not None
        assert len(loaded) == 2
        assert all("score_pertinence" in article for article in loaded)


# ── Tests compute_top_entities (generate_briefing) ────────────────────────────

class TestComputeTopEntities:
    """Vérifie le fix O(n) de generate_briefing.compute_top_entities."""

    def _make_articles(self, n: int) -> list[dict]:
        articles = []
        for i in range(n):
            articles.append({
                "entities": {
                    "PERSON": ["Macron", "Biden"] if i % 2 == 0 else ["Biden"],
                    "ORG": ["OpenAI"] if i % 3 == 0 else [],
                }
            })
        return articles

    def test_retourne_top_n(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.generate_briefing import compute_top_entities
        articles = self._make_articles(20)
        top = compute_top_entities(articles, top_n=3)
        assert len(top) <= 3

    def test_capitalisation_preservee(self):
        from scripts.generate_briefing import compute_top_entities
        articles = [
            {"entities": {"PERSON": ["Emmanuel Macron"]}},
            {"entities": {"PERSON": ["Emmanuel Macron", "Joe Biden"]}},
        ]
        top = compute_top_entities(articles, top_n=5)
        names = [name for _, name, _ in top]
        # La capitalisation originale doit être conservée
        assert "Emmanuel Macron" in names

    def test_compte_correct(self):
        from scripts.generate_briefing import compute_top_entities
        articles = [
            {"entities": {"PERSON": ["Macron"]}},
            {"entities": {"PERSON": ["Macron", "Biden"]}},
            {"entities": {"PERSON": ["Biden"]}},
            {"entities": {"ORG": ["OpenAI"]}},
        ]
        top = compute_top_entities(articles, top_n=10)
        counts = {name: count for _, name, count in top}
        assert counts["Macron"] == 2
        assert counts["Biden"] == 2
        assert counts["OpenAI"] == 1

    def test_filtre_types_non_pertinents(self):
        from scripts.generate_briefing import compute_top_entities
        articles = [
            {"entities": {
                "CARDINAL": ["42"],   # Non pertinent
                "DATE": ["2026"],     # Non pertinent
                "PERSON": ["Macron"], # Pertinent
            }}
        ]
        top = compute_top_entities(articles, top_n=10)
        types = {etype for etype, _, _ in top}
        assert "CARDINAL" not in types
        assert "DATE" not in types
        assert "PERSON" in types

    def test_articles_sans_entites(self):
        from scripts.generate_briefing import compute_top_entities
        articles = [
            {"entities": {}},
            {},
            {"entities": None},
        ]
        top = compute_top_entities(articles, top_n=5)
        assert top == []

    def test_performance_lineaire(self):
        """Vérifie que la fonction est nettement plus rapide que O(n²)."""
        from scripts.generate_briefing import compute_top_entities
        import time

        # 1000 articles avec 10 entités chacun
        articles = [
            {"entities": {"PERSON": [f"Entite{i % 50}"], "ORG": [f"Org{i % 20}"]}}
            for i in range(1000)
        ]
        t0 = time.perf_counter()
        compute_top_entities(articles, top_n=10)
        elapsed = time.perf_counter() - t0
        # O(n) sur 1000 articles doit prendre moins de 100 ms
        assert elapsed < 0.1, f"Trop lent : {elapsed:.3f}s (attendu < 0.1s)"


# ── Tests de clé MD5 unique ───────────────────────────────────────────────────

class TestClesMD5:
    def test_meme_entite_meme_cle(self):
        from utils.synthesis_cache import _make_key
        k1 = _make_key("PERSON", "Macron")
        k2 = _make_key("PERSON", "Macron")
        assert k1 == k2

    def test_entites_differentes_cles_differentes(self):
        from utils.synthesis_cache import _make_key
        assert _make_key("PERSON", "Macron") != _make_key("PERSON", "Biden")
        assert _make_key("PERSON", "X") != _make_key("ORG", "X")

    def test_cle_est_hexadecimale(self):
        from utils.synthesis_cache import _make_key
        k = _make_key("ORG", "OpenAI")
        assert len(k) == 32
        assert all(c in "0123456789abcdef" for c in k)


# ── Tests parsing de date article_index ──────────────────────────────────────

class TestParseDateIso:
    def test_format_iso_complet(self):
        from utils.article_index import _parse_date_iso
        result = _parse_date_iso("2026-03-14T10:30:00Z")
        assert result == "2026-03-14T10:30:00Z"

    def test_format_date_seule(self):
        from utils.article_index import _parse_date_iso
        result = _parse_date_iso("2026-03-14")
        assert result == "2026-03-14T00:00:00Z"

    def test_format_dd_mm_yyyy(self):
        from utils.article_index import _parse_date_iso
        result = _parse_date_iso("14/03/2026")
        assert result == "2026-03-14T00:00:00Z"

    def test_chaine_vide_retourne_none(self):
        from utils.article_index import _parse_date_iso
        assert _parse_date_iso("") is None
        assert _parse_date_iso(None) is None

    def test_format_invalide_retourne_none(self):
        from utils.article_index import _parse_date_iso
        assert _parse_date_iso("pas-une-date") is None

"""tests/test_entity_export.py — Tests du endpoint GET /api/entities/export

Couvre :
  - Réponse de base (structure JSON, champs obligatoires)
  - Filtre q (recherche partielle, insensible à la casse)
  - Filtre type (PERSON, ORG, GPE, …)
  - Paramètre limit (défaut 200, plafond 5000, valeur invalide)
  - Paramètre sort (mentions desc / value alphabétique)
  - Paramètre images=false (exclusion des images)
  - Paramètre synthesis=true (inclusion des synthèses IA)
  - Header CORS Access-Control-Allow-Origin: *
  - Fallback rglob lorsque l'entity_index est indisponible
  - Cas limites : index vide, q sans résultat, limit=1
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Racine du projet dans sys.path ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Données de test ───────────────────────────────────────────────────────────

_SAMPLE_INDEX = {
    "PERSON:Emmanuel Macron": [
        {"file": "data/articles/flux1/articles.json", "idx": 0, "date": "2026-04-01"},
        {"file": "data/articles/flux1/articles.json", "idx": 1, "date": "2026-04-02"},
        {"file": "data/articles/flux2/articles.json", "idx": 0, "date": "2026-04-03"},
    ],
    "ORG:OpenAI": [
        {"file": "data/articles/flux1/articles.json", "idx": 0, "date": "2026-04-01"},
        {"file": "data/articles/flux1/articles.json", "idx": 2, "date": "2026-04-04"},
    ],
    "GPE:France": [
        {"file": "data/articles/flux2/articles.json", "idx": 0, "date": "2026-04-03"},
    ],
    "PERSON:Joe Biden": [
        {"file": "data/articles/flux2/articles.json", "idx": 1, "date": "2026-03-28"},
    ],
}

_SAMPLE_IMAGES_CACHE = {
    "Emmanuel Macron": {"url": "https://img.example.com/macron.jpg", "width": 200, "height": 200},
    "OpenAI": {"url": "https://img.example.com/openai.png", "width": 200, "height": 200},
    "France": None,
    "Joe Biden": None,
}


def _make_mock_eidx(entries: dict | None = None):
    """Construit un mock EntityIndex retournant les entrées fournies."""
    mock = MagicMock()
    mock.get_all_entries.return_value = entries if entries is not None else _SAMPLE_INDEX
    # get_caps_map n'existe pas dans EntityIndex — on simule l'AttributeError
    mock.get_caps_map.side_effect = AttributeError("not implemented")
    return mock


# ── Fixture Flask test client ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def flask_client(tmp_path_factory):
    """Client Flask avec entity_index mocké et images_cache sur disque."""
    # Répertoire temporaire simulant PROJECT_ROOT pour les caches
    tmp_root = tmp_path_factory.mktemp("wudd_project")
    (tmp_root / "data").mkdir()

    # Écrire images_cache.json sur disque (lu par l'endpoint)
    images_cache_path = tmp_root / "data" / "images_cache.json"
    images_cache_path.write_text(
        json.dumps(_SAMPLE_IMAGES_CACHE, ensure_ascii=False), encoding="utf-8"
    )

    # Importer app après avoir patché PROJECT_ROOT dans le blueprint
    # On patche viewer.routes.entities._images_cache_mem globalement pour
    # forcer le rechargement depuis notre cache temporaire.
    import viewer.routes.entities as ent_module
    ent_module._images_cache_mem = None  # forcer le rechargement

    with patch.object(ent_module, "PROJECT_ROOT", tmp_root), \
         patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
        from viewer.app import app as flask_app
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            yield client, tmp_root


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_json(client, url):
    """Effectue un GET et retourne (status_code, dict)."""
    resp = client.get(url)
    return resp.status_code, resp.get_json()


# ── Tests structure de base ───────────────────────────────────────────────────

class TestEntityExportStructure:
    """Valide la structure JSON de la réponse."""

    def test_status_200(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            status, _ = _get_json(client, "/api/entities/export")
        assert status == 200

    def test_champs_obligatoires_presents(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export")
        assert "generated_at" in data
        assert "total" in data
        assert "returned" in data
        assert "params" in data
        assert "entities" in data
        assert isinstance(data["entities"], list)

    def test_chaque_entite_a_les_champs_de_base(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export")
        for ent in data["entities"]:
            assert "type" in ent
            assert "value" in ent
            assert "mentions" in ent

    def test_total_egal_nombre_entites_dans_index(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export")
        assert data["total"] == len(_SAMPLE_INDEX)

    def test_mentions_correctes(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export")
        macron = next(e for e in data["entities"] if e["value"] == "Emmanuel Macron")
        assert macron["mentions"] == 3  # 3 refs dans _SAMPLE_INDEX

    def test_header_cors(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            resp = client.get("/api/entities/export")
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_header_last_modified_present(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            resp = client.get("/api/entities/export")
        assert resp.status_code == 200
        assert resp.headers.get("Last-Modified")

    def test_if_modified_since_returns_304_when_not_modified(self, flask_client):
        client, tmp_root = flask_client
        data_dir = tmp_root / "data"
        data_dir.mkdir(exist_ok=True)
        idx_file = data_dir / "entity_index.json"
        idx_file.write_text(json.dumps({"entries": {}}), encoding="utf-8")

        future = datetime.now(timezone.utc) + timedelta(days=1)
        ims = format_datetime(future, usegmt=True)

        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            resp = client.get("/api/entities/export", headers={"If-Modified-Since": ims})

        assert resp.status_code == 304
        assert resp.get_data(as_text=True) == ""
        assert resp.headers.get("Cache-Control") == "no-cache"
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"


# ── Tests filtre q ────────────────────────────────────────────────────────────

class TestEntityExportFiltreQ:
    """Valide la recherche partielle par nom."""

    def test_filtre_q_macron_retourne_macron(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?q=macron")
        assert data["total"] == 1
        assert data["entities"][0]["value"] == "Emmanuel Macron"

    def test_filtre_q_insensible_casse(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data_lower = _get_json(client, "/api/entities/export?q=openai")
            _, data_upper = _get_json(client, "/api/entities/export?q=OPENAI")
        assert data_lower["total"] == data_upper["total"] == 1

    def test_filtre_q_partiel(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            # "ance" correspond à "France"
            _, data = _get_json(client, "/api/entities/export?q=ance")
        assert any(e["value"] == "France" for e in data["entities"])

    def test_filtre_q_sans_resultat(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?q=xyzinexistant")
        assert data["total"] == 0
        assert data["entities"] == []

    def test_filtre_q_vide_retourne_tout(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?q=")
        assert data["total"] == len(_SAMPLE_INDEX)


# ── Tests filtre type ─────────────────────────────────────────────────────────

class TestEntityExportFiltreType:
    """Valide le filtre par type NER."""

    def test_filtre_type_person(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?type=PERSON")
        assert all(e["type"] == "PERSON" for e in data["entities"])
        assert data["total"] == 2  # Macron + Biden

    def test_filtre_type_org(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?type=ORG")
        assert data["total"] == 1
        assert data["entities"][0]["value"] == "OpenAI"

    def test_filtre_type_gpe(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?type=GPE")
        assert data["total"] == 1
        assert data["entities"][0]["value"] == "France"

    def test_filtre_type_inexistant(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?type=ANIMAL")
        assert data["total"] == 0

    def test_filtre_type_et_q_combines(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?type=PERSON&q=biden")
        assert data["total"] == 1
        assert data["entities"][0]["value"] == "Joe Biden"


# ── Tests paramètre limit ─────────────────────────────────────────────────────

class TestEntityExportLimit:
    """Valide la pagination."""

    def test_limit_1(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?limit=1")
        assert data["returned"] == 1
        assert data["total"] == len(_SAMPLE_INDEX)  # total non tronqué
        assert len(data["entities"]) == 1

    def test_limit_defaut_200(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export")
        assert data["params"]["limit"] == 200

    def test_limit_invalide_utilise_defaut(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?limit=abc")
        assert data["params"]["limit"] == 200

    def test_limit_plafond_5000(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?limit=99999")
        assert data["params"]["limit"] == 5000


# ── Tests paramètre sort ──────────────────────────────────────────────────────

class TestEntityExportSort:
    """Valide les tris disponibles."""

    def test_sort_mentions_decroissant(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?sort=mentions")
        mentions = [e["mentions"] for e in data["entities"]]
        assert mentions == sorted(mentions, reverse=True)


class TestEntityExportMatchMode:
    """Valide la canonicalisation optionnelle de l'export."""

    def test_match_mode_canonical_fusionne_les_variantes(self, flask_client):
        client, _ = flask_client
        index_with_aliases = {
            "PERSON:Donald Trump": [
                {"file": "data/articles/f1.json", "idx": 0, "date": "2026-04-01"},
                {"file": "data/articles/f1.json", "idx": 1, "date": "2026-04-02"},
            ],
            "PERSON:Trump": [
                {"file": "data/articles/f2.json", "idx": 0, "date": "2026-04-03"},
            ],
        }

        canonicalizer = MagicMock()

        def _canonicalize(entity_type, value):
            if entity_type == "PERSON" and value in {"Trump", "Donald Trump"}:
                return "PERSON", "Donald Trump"
            return entity_type, value

        canonicalizer.canonicalize.side_effect = _canonicalize
        canonicalizer.canonical_key.side_effect = (
            lambda entity_type, value: f"{entity_type}:{str(value).lower()}"
        )

        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx(index_with_aliases)), \
             patch("viewer.routes.entities.get_entity_canonicalizer", return_value=canonicalizer):
            _, data = _get_json(client, "/api/entities/export?type=PERSON&match_mode=canonical")

        assert data["total"] == 1
        assert data["entities"][0]["value"] == "Donald Trump"
        assert data["entities"][0]["mentions"] == 3
        assert "Trump" in data["entities"][0]["aliases"]

    def test_match_mode_strict_conserve_les_variantes(self, flask_client):
        client, _ = flask_client
        index_with_aliases = {
            "PERSON:Donald Trump": [
                {"file": "data/articles/f1.json", "idx": 0, "date": "2026-04-01"},
            ],
            "PERSON:Trump": [
                {"file": "data/articles/f2.json", "idx": 0, "date": "2026-04-03"},
            ],
        }

        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx(index_with_aliases)):
            _, data = _get_json(client, "/api/entities/export?type=PERSON&match_mode=strict")

        assert data["total"] == 2

    def test_match_mode_invalide_retourne_400(self, flask_client):
        client, _ = flask_client
        status, data = _get_json(client, "/api/entities/export?match_mode=full")
        assert status == 400
        assert "match_mode invalide" in data["error"]

    def test_sort_value_alphabetique(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?sort=value")
        values = [e["value"].lower() for e in data["entities"]]
        assert values == sorted(values)

    def test_sort_inconnu_utilise_mentions(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?sort=zzz")
        # "zzz" ne correspond pas à "value", donc tombe dans le else → mentions
        mentions = [e["mentions"] for e in data["entities"]]
        assert mentions == sorted(mentions, reverse=True)


# ── Tests paramètre images ────────────────────────────────────────────────────

class TestEntityExportImages:
    """Valide l'inclusion/exclusion des images."""

    def test_images_true_champ_image_present(self, flask_client):
        client, tmp_root = flask_client
        import viewer.routes.entities as ent_module
        ent_module._images_cache_mem = None  # reset pour lire depuis disque
        with patch.object(ent_module, "PROJECT_ROOT", tmp_root), \
             patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?images=true")
        for ent in data["entities"]:
            assert "image" in ent

    def test_images_false_champ_image_absent(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?images=false")
        for ent in data["entities"]:
            assert "image" not in ent

    def test_image_macron_url_correcte(self, flask_client):
        client, tmp_root = flask_client
        import viewer.routes.entities as ent_module
        ent_module._images_cache_mem = None
        with patch.object(ent_module, "PROJECT_ROOT", tmp_root), \
             patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?images=true")
        macron = next((e for e in data["entities"] if e["value"] == "Emmanuel Macron"), None)
        assert macron is not None
        assert macron["image"] is not None
        assert macron["image"]["url"] == "https://img.example.com/macron.jpg"

    def test_image_france_null(self, flask_client):
        client, tmp_root = flask_client
        import viewer.routes.entities as ent_module
        ent_module._images_cache_mem = None
        with patch.object(ent_module, "PROJECT_ROOT", tmp_root), \
             patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?images=true")
        france = next((e for e in data["entities"] if e["value"] == "France"), None)
        assert france is not None
        assert france["image"] is None


# ── Tests paramètre synthesis ─────────────────────────────────────────────────

class TestEntityExportSynthesis:
    """Valide l'inclusion des synthèses IA depuis synthesis_cache."""

    def test_synthesis_false_champ_absent(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?synthesis=false")
        for ent in data["entities"]:
            assert "synthesis" not in ent

    def test_synthesis_true_champ_present(self, flask_client):
        client, _ = flask_client
        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # cache vide
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()), \
             patch("utils.synthesis_cache.get_synthesis_cache", return_value=mock_cache):
            _, data = _get_json(client, "/api/entities/export?synthesis=true")
        for ent in data["entities"]:
            assert "synthesis" in ent

    def test_synthesis_retourne_texte_depuis_cache(self, flask_client):
        client, _ = flask_client
        mock_cache = MagicMock()
        # Retourne une synthèse uniquement pour Macron
        def _cache_get(etype, value):
            if value == "Emmanuel Macron":
                return {"info_text": "Synthèse de Macron.", "rag_text": ""}
            return None
        mock_cache.get.side_effect = _cache_get

        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()), \
             patch("utils.synthesis_cache.get_synthesis_cache", return_value=mock_cache):
            _, data = _get_json(client, "/api/entities/export?synthesis=true")
        macron = next((e for e in data["entities"] if e["value"] == "Emmanuel Macron"), None)
        assert macron is not None
        assert macron["synthesis"] == "Synthèse de Macron."


# ── Tests cas limites ─────────────────────────────────────────────────────────

class TestEntityExportCasLimites:
    """Cas limites et robustesse."""

    def test_index_vide_retourne_liste_vide(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx({})):
            _, data = _get_json(client, "/api/entities/export")
        assert data["total"] == 0
        assert data["entities"] == []

    def test_params_reflechis_dans_reponse(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?q=macron&type=PERSON&limit=5&sort=value")
        p = data["params"]
        assert p["q"] == "macron"
        assert p["type"] == "PERSON"
        assert p["limit"] == 5
        assert p["sort"] == "value"

    def test_generated_at_format_iso8601(self, flask_client):
        import re
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export")
        # Format attendu : YYYY-MM-DDTHH:MM:SS+00:00 ou Z
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", data["generated_at"])

    def test_returned_inferieur_a_total_avec_limit(self, flask_client):
        client, _ = flask_client
        with patch("viewer.routes.entities.get_entity_index", return_value=_make_mock_eidx()):
            _, data = _get_json(client, "/api/entities/export?limit=2")
        assert data["returned"] == 2
        assert data["total"] > data["returned"]

    def test_entite_type_manquant_ignoree(self, flask_client):
        """Une clé d'index malformée (sans ':') ne doit pas faire planter l'endpoint."""
        client, _ = flask_client
        broken_index = {
            "MALFORMEE_SANS_COLON": [{"file": "x.json", "idx": 0, "date": "2026-01-01"}],
            **_SAMPLE_INDEX,
        }
        with patch("viewer.routes.entities.get_entity_index",
                   return_value=_make_mock_eidx(broken_index)):
            status, data = _get_json(client, "/api/entities/export")
        assert status == 200
        assert data["total"] == len(_SAMPLE_INDEX)  # la clé malformée est ignorée


# ── Tests fallback rglob ──────────────────────────────────────────────────────

class TestEntityExportFallbackRglob:
    """Vérifie que le fallback rglob fonctionne quand l'entity_index lève une exception."""

    def test_fallback_quand_index_leve_exception(self, tmp_path):
        """Si get_entity_index lève une exception, l'endpoint scanne les fichiers JSON."""
        # Créer un arbre de fichiers articles minimal
        arts_dir = tmp_path / "data" / "articles" / "flux1"
        arts_dir.mkdir(parents=True)
        articles = [
            {
                "URL": "http://test.com/1",
                "Sources": "Le Monde",
                "Date de publication": "2026-04-01",
                "Résumé": "Article test.",
                "entities": {"PERSON": ["Alice"], "ORG": ["ACME Corp"]},
            }
        ]
        (arts_dir / "articles.json").write_text(json.dumps(articles), encoding="utf-8")

        import viewer.routes.entities as ent_module
        ent_module._images_cache_mem = None

        def _raise(*a, **kw):
            raise RuntimeError("Index indisponible")

        with patch.object(ent_module, "PROJECT_ROOT", tmp_path), \
             patch("viewer.routes.entities.get_entity_index", side_effect=_raise):
            from viewer.app import app as flask_app
            flask_app.config["TESTING"] = True
            with flask_app.test_client() as client:
                resp = client.get("/api/entities/export")
                data = resp.get_json()

        assert resp.status_code == 200
        values = [e["value"] for e in data["entities"]]
        assert "Alice" in values
        assert "ACME Corp" in values

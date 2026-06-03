"""Tests pour scripts/enrich_summary_format.py.

Couvre :
  - _merge_write : application de Résumé_md sur la version disque la plus récente
    sans écraser les modifications concurrentes (sécurité anti-course)
  - _in_period : filtre de période
  - collect_all_json_files : exclusion des fichiers dérivés _WUDD.AI_
"""

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_spec = importlib.util.spec_from_file_location(
    "enrich_summary_format", PROJECT_ROOT / "scripts" / "enrich_summary_format.py"
)
esf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(esf)


class TestMergeWrite:
    def test_applique_sans_ecraser_concurrent(self, tmp_path):
        f = tmp_path / "kw.json"
        f.write_text(json.dumps([
            {"URL": "http://a/1", "Résumé": "x"},
            {"URL": "http://a/2", "Résumé": "y"},
        ]), encoding="utf-8")
        results = {"http://a/1": "### MD1", "http://a/2": "### MD2"}
        # Écriture concurrente AVANT le merge : sentiment ajouté + nouvel article
        f.write_text(json.dumps([
            {"URL": "http://a/1", "Résumé": "x"},
            {"URL": "http://a/2", "Résumé": "y", "sentiment": "positif"},
            {"URL": "http://a/3", "Résumé": "z"},
        ]), encoding="utf-8")

        applied = esf._merge_write(f, results)
        by = {a["URL"]: a for a in json.loads(f.read_text(encoding="utf-8"))}

        assert applied == 2
        assert by["http://a/1"]["Résumé_md"] == "### MD1"
        assert by["http://a/2"]["Résumé_md"] == "### MD2"
        assert by["http://a/2"]["sentiment"] == "positif"   # changement concurrent préservé
        assert "http://a/3" in by                            # ajout concurrent préservé
        assert len(by) == 3

    def test_url_absente_ignoree(self, tmp_path):
        f = tmp_path / "kw.json"
        f.write_text(json.dumps([{"URL": "http://a/1", "Résumé": "x"}]), encoding="utf-8")
        applied = esf._merge_write(f, {"http://absent": "### MD"})
        assert applied == 0
        assert "Résumé_md" not in json.loads(f.read_text(encoding="utf-8"))[0]


class TestInPeriod:
    def test_sans_filtre_tout_passe(self):
        assert esf._in_period({"Date de publication": "01/01/2020"}, None, None) is True

    def test_avant_since_exclu(self):
        assert esf._in_period({"Date de publication": "2026-05-31"}, date(2026, 6, 1), None) is False

    def test_dans_periode_inclus(self):
        assert esf._in_period({"Date de publication": "2026-06-02"}, date(2026, 6, 1), None) is True

    def test_date_inexploitable_exclue_si_filtre(self):
        assert esf._in_period({"Date de publication": ""}, date(2026, 6, 1), None) is False


class TestCollectExcludesWudd:
    def test_wudd_ai_exclu(self, tmp_path, monkeypatch):
        rss = tmp_path / "data" / "articles-from-rss"
        (rss / "_WUDD.AI_").mkdir(parents=True)
        (rss / "openai.json").write_text("[]", encoding="utf-8")
        (rss / "_WUDD.AI_" / "48-heures.json").write_text("[]", encoding="utf-8")

        class _Cfg:
            project_root = tmp_path
        files = esf.collect_all_json_files(_Cfg())
        names = [f.name for f in files]
        assert "openai.json" in names
        assert "48-heures.json" not in names

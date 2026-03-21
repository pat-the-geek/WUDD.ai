"""Tests pour utils/parallel.py et utils/logging.py.

Couvre :
  - process_items_parallel : résultats, erreurs, liste vide, workers
  - fetch_articles_parallel : extraction URLs depuis dicts, cas dégénérés
  - process_with_rate_limit : séquentiel avec délai respecté
  - batch_process : découpage et concaténation
  - setup_logger : retourne un Logger nommé
  - print_console : affiche et délègue selon niveau
"""

import logging
import pytest
from unittest.mock import MagicMock, patch, call


# ─────────────────────────────────────────────────────────────────────────────
# process_items_parallel
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessItemsParallel:
    def setup_method(self):
        from utils.parallel import process_items_parallel
        self.fn = process_items_parallel

    def test_empty_list_returns_empty_dict(self):
        result = self.fn([], lambda x: x)
        assert result == {}

    def test_processes_all_items(self):
        items = [1, 2, 3, 4, 5]
        result = self.fn(items, lambda x: x * 2, max_workers=3)
        assert len(result) == 5
        assert result[3] == 6

    def test_returns_dict_keyed_by_item(self):
        items = ["a", "b", "c"]
        result = self.fn(items, str.upper, max_workers=2)
        assert result["a"] == "A"
        assert result["b"] == "B"
        assert result["c"] == "C"

    def test_error_in_function_stored_as_error_string(self):
        def failing(x):
            if x == "bad":
                raise ValueError("intentional")
            return x.upper()

        items = ["ok", "bad"]
        result = self.fn(items, failing, max_workers=2)
        assert "ok" in result
        assert result["ok"] == "OK"
        assert "bad" in result
        assert "Erreur" in result["bad"] or "Error" in result["bad"]

    def test_custom_max_workers_accepted(self):
        items = list(range(10))
        result = self.fn(items, lambda x: x + 1, max_workers=10)
        assert len(result) == 10

    def test_single_item(self):
        result = self.fn(["only"], lambda x: f"done:{x}", max_workers=1)
        assert result["only"] == "done:only"

    def test_all_errors_still_returns_dict_with_all_keys(self):
        def always_fail(x):
            raise RuntimeError("boom")

        items = ["x", "y", "z"]
        result = self.fn(items, always_fail, max_workers=2)
        assert set(result.keys()) == set(items)


# ─────────────────────────────────────────────────────────────────────────────
# fetch_articles_parallel
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchArticlesParallel:
    def setup_method(self):
        from utils.parallel import fetch_articles_parallel
        self.fn = fetch_articles_parallel

    def test_empty_list_returns_empty_dict(self):
        assert self.fn([], lambda u: "text") == {}

    def test_extracts_url_key(self):
        items = [{"url": "https://a.com"}, {"url": "https://b.com"}]
        result = self.fn(items, lambda u: f"fetched:{u}", max_workers=2)
        assert "https://a.com" in result
        assert result["https://a.com"] == "fetched:https://a.com"

    def test_extracts_URL_key_uppercase(self):
        items = [{"URL": "https://c.com"}]
        result = self.fn(items, lambda u: "text", max_workers=1)
        assert "https://c.com" in result

    def test_items_without_url_skipped(self):
        items = [{"title": "no url"}, {"url": "https://d.com"}]
        result = self.fn(items, lambda u: "ok", max_workers=1)
        assert len(result) == 1
        assert "https://d.com" in result

    def test_all_items_without_url_returns_empty(self):
        items = [{"title": "a"}, {"content": "b"}]
        result = self.fn(items, lambda u: "x", max_workers=1)
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# process_with_rate_limit
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessWithRateLimit:
    def setup_method(self):
        from utils.parallel import process_with_rate_limit
        self.fn = process_with_rate_limit

    def test_empty_list_returns_empty_dict(self):
        result = self.fn([], lambda x: x)
        assert result == {}

    def test_processes_all_items_sequentially(self):
        items = [10, 20, 30]
        with patch("utils.parallel.time.sleep"):  # skip real sleeps
            result = self.fn(items, lambda x: x * 3, requests_per_second=100)
        assert result[10] == 30
        assert result[20] == 60
        assert result[30] == 90

    def test_sleep_called_between_items(self):
        items = ["a", "b", "c"]
        with patch("utils.parallel.time.sleep") as mock_sleep:
            self.fn(items, lambda x: x, requests_per_second=2.0)
        # sleep doit être appelé entre items (N-1 fois = 2 fois pour 3 items)
        assert mock_sleep.call_count == 2

    def test_error_stored_as_error_string(self):
        def fail(x):
            raise ValueError("oops")
        with patch("utils.parallel.time.sleep"):
            result = self.fn(["x"], fail)
        assert "Erreur" in result["x"]

    def test_single_item_no_sleep(self):
        with patch("utils.parallel.time.sleep") as mock_sleep:
            self.fn(["solo"], lambda x: x)
        mock_sleep.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# batch_process
# ─────────────────────────────────────────────────────────────────────────────

class TestBatchProcess:
    def setup_method(self):
        from utils.parallel import batch_process
        self.fn = batch_process

    def test_empty_list_returns_empty_list(self):
        assert self.fn([], lambda b: b) == []

    def test_results_concatenated_correctly(self):
        items = list(range(10))
        result = self.fn(items, lambda batch: [x * 2 for x in batch], batch_size=3)
        assert sorted(result) == [x * 2 for x in range(10)]

    def test_batch_size_respected(self):
        seen_batches = []

        def collector(batch):
            seen_batches.append(len(batch))
            return batch

        self.fn(list(range(7)), collector, batch_size=3)
        # Attendu : batches de taille 3, 3, 1
        assert sorted(seen_batches) == [1, 3, 3]

    def test_single_batch_when_small(self):
        calls = []

        def capture(batch):
            calls.append(batch)
            return batch

        self.fn([1, 2], capture, batch_size=10)
        assert len(calls) == 1
        assert calls[0] == [1, 2]

    def test_error_in_batch_skips_batch_gracefully(self):
        call_count = [0]

        def sometimes_fail(batch):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("batch error")
            return batch

        # 3 batches → 2e échoue, 1er et 3e réussissent
        items = list(range(9))
        result = self.fn(items, sometimes_fail, batch_size=3)
        # Au moins les 2 batchs réussis contribuent
        assert len(result) == 6


# ─────────────────────────────────────────────────────────────────────────────
# setup_logger
# ─────────────────────────────────────────────────────────────────────────────

class TestSetupLogger:
    def test_returns_logger_instance(self):
        from utils.logging import setup_logger
        logger = setup_logger("TestLogger")
        assert isinstance(logger, logging.Logger)

    def test_logger_name_matches(self):
        from utils.logging import setup_logger
        logger = setup_logger("MyTestLogger")
        assert logger.name == "MyTestLogger"

    def test_default_name_is_analyseactualites(self):
        from utils.logging import setup_logger
        logger = setup_logger()
        assert logger.name == "AnalyseActualites"

    def test_custom_level_applied_in_docker(self, monkeypatch):
        monkeypatch.setenv("DOCKER", "1")
        from utils.logging import setup_logger
        logger = setup_logger("DockerLogger")
        assert logger.level == logging.INFO


# ─────────────────────────────────────────────────────────────────────────────
# print_console
# ─────────────────────────────────────────────────────────────────────────────

class TestPrintConsole:
    def test_prints_to_stdout(self, capsys):
        from utils.logging import print_console
        print_console("message de test")
        captured = capsys.readouterr()
        assert "message de test" in captured.out

    def test_includes_timestamp(self, capsys):
        from utils.logging import print_console
        print_console("test timestamp")
        captured = capsys.readouterr()
        # Format YYYY-MM-DD HH:MM:SS
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", captured.out)

    def _get_logger(self):
        import logging as _logging
        return _logging.getLogger("AnalyseActualites")

    def test_delegates_info_level(self):
        from utils.logging import print_console
        with patch.object(self._get_logger(), "info") as mock_fn:
            print_console("test info", level="info")
        mock_fn.assert_called_once_with("test info")

    def test_delegates_warning_level(self):
        from utils.logging import print_console
        with patch.object(self._get_logger(), "warning") as mock_fn:
            print_console("test warning", level="warning")
        mock_fn.assert_called_once_with("test warning")

    def test_delegates_error_level(self):
        from utils.logging import print_console
        with patch.object(self._get_logger(), "error") as mock_fn:
            print_console("test error", level="error")
        mock_fn.assert_called_once_with("test error")

    def test_delegates_debug_level(self):
        from utils.logging import print_console
        with patch.object(self._get_logger(), "debug") as mock_fn:
            print_console("test debug", level="debug")
        mock_fn.assert_called_once_with("test debug")

    def test_delegates_critical_level(self):
        from utils.logging import print_console
        with patch.object(self._get_logger(), "critical") as mock_fn:
            print_console("test critical", level="critical")
        mock_fn.assert_called_once_with("test critical")

    def test_unknown_level_falls_back_to_info(self):
        from utils.logging import print_console
        with patch.object(self._get_logger(), "info") as mock_fn:
            print_console("test fallback", level="unknownlevel")
        mock_fn.assert_called_once_with("test fallback")

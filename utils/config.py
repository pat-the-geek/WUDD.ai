"""Module de configuration centralisée pour AnalyseActualités.

Gère le chargement et la validation des variables d'environnement
et des chemins du projet.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from .logging import default_logger

# ── Schémas JSON pour la validation des fichiers de config ────────────────────

_SCHEMA_QUOTA = {
    "type": "object",
    "required": ["enabled", "global_daily_limit"],
    "properties": {
        "enabled":                 {"type": "boolean"},
        "global_daily_limit":      {"type": "integer", "minimum": 1},
        "per_keyword_daily_limit": {"type": "integer", "minimum": 1},
        "per_source_daily_limit":  {"type": "integer", "minimum": 1},
        "per_entity_daily_limit":  {"type": "integer", "minimum": 1},
        "per_run_limit":           {"type": "integer", "minimum": 0},
        "global_source_daily_limit": {"type": "integer", "minimum": 0},
        "adaptive_sorting":        {"type": "boolean"},
        "summary_max_lines":       {"type": "integer", "minimum": 1},
        "ignored_entity_types":    {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}

_SCHEMA_ALERT_RULES = {
    "type": "object",
    "properties": {
        "global": {
            "type": "object",
            "required": ["threshold_ratio"],
            "properties": {
                "threshold_ratio":     {"type": "number", "exclusiveMinimum": 0},
                "top":                 {"type": "integer", "minimum": 1},
                "min_mentions_24h":    {"type": "integer", "minimum": 0},
                "silence_baseline_avg": {"type": "number", "minimum": 0},
                "watched_threshold_ratio": {"type": "number", "minimum": 0},
            },
        },
        "types_entites": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "enabled":         {"type": "boolean"},
                    "threshold_ratio": {"type": "number", "exclusiveMinimum": 0},
                    "min_mentions":    {"type": "integer", "minimum": 0},
                },
            },
        },
        "notifications": {
            "type": "object",
            "properties": {
                "niveaux_notifies": {"type": "array", "items": {"type": "string"}},
                "webhook_discord":  {"type": ["boolean", "string"]},
                "webhook_slack":    {"type": ["boolean", "string"]},
                "ntfy":             {"type": ["boolean", "string"]},
            },
        },
    },
    "additionalProperties": True,
}

_SCHEMA_FLUX_SOURCES = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["title", "url"],
        "properties": {
            "title":   {"type": "string", "minLength": 1},
            "url":     {"type": "string", "minLength": 1},
            "cron":    {"type": "string"},
            "timeout": {"type": "integer", "minimum": 1},
        },
        "additionalProperties": True,
    },
}

_SCHEMA_KEYWORD_SEARCH = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["keyword"],
        "properties": {
            "keyword": {"type": "string", "minLength": 1},
            "or":      {"type": "array", "items": {"type": "string"}},
            "and":     {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": True,
    },
}


class Config:
    """Configuration centralisée de l'application.
    
    Charge les variables d'environnement depuis le fichier .env
    et fournit un accès typé et validé aux paramètres de configuration.
    
    Attributes:
        project_root: Chemin racine du projet
        url: URL de l'API EurIA
        bearer: Token d'authentification API
        max_attempts: Nombre maximal de tentatives pour les requêtes
        timeout_resume: Timeout pour génération de résumés (secondes)
        timeout_rapport: Timeout pour génération de rapports (secondes)
    """
    
    def __init__(self, project_root: Optional[Path] = None):
        """Initialise la configuration.
        
        Args:
            project_root: Chemin racine du projet (détecté automatiquement si None)
        """
        # Détecter la racine du projet
        if project_root is None:
            # Remonter depuis utils/ vers la racine
            self.project_root = Path(__file__).parent.parent
        else:
            self.project_root = Path(project_root)
        
        # Charger les variables d'environnement
        env_file = self.project_root / ".env"
        try:
            env_exists = env_file.exists()
        except PermissionError:
            env_exists = False
            default_logger.warning(
                f"Permission refusée lors de l'accès à {env_file}, "
                "utilisation des variables d'environnement système."
            )
        if env_exists:
            load_dotenv(env_file)
            default_logger.info(f"Configuration chargée depuis {env_file}")
        else:
            # Pas de .env dans project_root — s'appuyer sur les variables d'environnement déjà définies
            default_logger.warning(f"Fichier .env non trouvé ou inaccessible: {env_file}")
        
        # Charger et valider les variables
        self._load_config()
        self._validate_config()
    
    def _load_config(self):
        """Charge les variables d'environnement."""
        self.url = os.getenv("URL")
        self.bearer = os.getenv("bearer")

        # Fournisseur IA actif et configuration Claude
        self.ai_provider = os.getenv("AI_PROVIDER", "euria").strip().lower()
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.claude_model_batch = os.getenv("CLAUDE_MODEL_BATCH", "claude-haiku-4-5-20251001")
        self.claude_model_synthesis = os.getenv("CLAUDE_MODEL_SYNTHESIS", "claude-sonnet-4-6")

        # Paramètres avec valeurs par défaut (clés identiques à celles du .env)
        self.max_attempts = int(os.getenv("max_attempts", "3"))
        self.timeout_resume = int(os.getenv("timeout_resume", "60"))
        self.timeout_rapport = int(os.getenv("timeout_rapport", "300"))
        self.default_error_message = os.getenv(
            "default_error_message",
            "Aucune information disponible"
        )
        
        # Taille des résumés IA — lue depuis config/quota.json (summary_max_lines)
        # Fallback sur la variable d'env SUMMARY_MAX_LINES, puis sur 20 par défaut
        self.summary_max_lines = self._load_summary_max_lines()

        # Chemins des répertoires
        self.data_articles_dir = self.project_root / "data" / "articles"
        self.data_raw_dir = self.project_root / "data" / "raw"
        self.rapports_markdown_dir = self.project_root / "rapports" / "markdown"
        self.rapports_pdf_dir = self.project_root / "rapports" / "pdf"
        self.config_dir = self.project_root / "config"
    
    def _load_summary_max_lines(self) -> int:
        """Lit summary_max_lines depuis config/quota.json.
        Fallback sur SUMMARY_MAX_LINES env var, puis sur 20."""
        import json as _json
        quota_path = self.project_root / "config" / "quota.json"
        try:
            if quota_path.exists():
                data = _json.loads(quota_path.read_text(encoding="utf-8"))
                val = data.get("summary_max_lines")
                if isinstance(val, int) and val > 0:
                    return val
        except Exception:
            pass
        try:
            return max(1, int(os.getenv("SUMMARY_MAX_LINES", "20")))
        except (ValueError, TypeError):
            return 20

    def _validate_config(self):
        """Valide que les variables obligatoires sont présentes."""
        errors = []

        if self.ai_provider == "euria":
            if not self.url:
                errors.append("Variable d'environnement manquante: URL (requis pour AI_PROVIDER=euria)")
            if not self.bearer:
                errors.append("Variable d'environnement manquante: bearer (requis pour AI_PROVIDER=euria)")
        elif self.ai_provider == "claude":
            if not self.anthropic_api_key:
                errors.append("Variable d'environnement manquante: ANTHROPIC_API_KEY (requis pour AI_PROVIDER=claude)")
        elif self.ai_provider == "ollama":
            pass  # Ollama local — pas de credentials requis
        else:
            errors.append(
                f"AI_PROVIDER invalide: '{self.ai_provider}'. Valeurs acceptées: 'euria', 'claude', 'ollama'"
            )
        
        # Validation des timeouts
        if self.timeout_resume < 10 or self.timeout_resume > 600:
            default_logger.warning(
                f"timeout_resume hors limites recommandées (10-600s): {self.timeout_resume}"
            )
        if self.timeout_rapport < 60 or self.timeout_rapport > 600:
            default_logger.warning(
                f"timeout_rapport hors limites recommandées (60-600s): {self.timeout_rapport}"
            )
        
        if errors:
            error_msg = "\n".join(errors)
            default_logger.error(f"Erreurs de configuration:\n{error_msg}")
            raise ValueError(f"Configuration invalide:\n{error_msg}")

        # Validation des fichiers JSON de config (warnings non bloquants)
        self._validate_config_files()

        default_logger.info("Configuration validée avec succès")
    
    def _validate_config_files(self) -> None:
        """Valide les fichiers JSON de configuration via jsonschema.

        Les erreurs sont des warnings (non bloquants) : un fichier mal formé
        ne doit pas empêcher le démarrage, mais doit être signalé clairement.
        jsonschema est optionnel ; si absent, la validation est silencieusement
        ignorée.
        """
        try:
            import jsonschema  # noqa: PLC0415
        except ImportError:
            return  # Validation optionnelle — jsonschema non installé

        import json as _json  # noqa: PLC0415

        checks = [
            (self.config_dir / "quota.json",              _SCHEMA_QUOTA,         "quota.json"),
            (self.config_dir / "alert_rules.json",        _SCHEMA_ALERT_RULES,   "alert_rules.json"),
            (self.config_dir / "flux_json_sources.json",  _SCHEMA_FLUX_SOURCES,  "flux_json_sources.json"),
            (self.config_dir / "keyword-to-search.json",  _SCHEMA_KEYWORD_SEARCH, "keyword-to-search.json"),
        ]

        for path, schema, label in checks:
            if not path.exists():
                continue
            try:
                data = _json.loads(path.read_text(encoding="utf-8"))
                jsonschema.validate(instance=data, schema=schema)
            except _json.JSONDecodeError as exc:
                default_logger.warning(f"[config] {label} — JSON invalide : {exc}")
            except jsonschema.ValidationError as exc:
                default_logger.warning(
                    f"[config] {label} — schéma invalide : {exc.message} "
                    f"(chemin : {' > '.join(str(p) for p in exc.absolute_path) or 'racine'})"
                )
            except Exception as exc:
                default_logger.warning(f"[config] {label} — erreur inattendue : {exc}")

    def setup_directories(self):
        """Crée les répertoires nécessaires s'ils n'existent pas."""
        directories = [
            self.data_articles_dir,
            self.data_raw_dir,
            self.rapports_markdown_dir,
            self.rapports_pdf_dir
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            default_logger.debug(f"Répertoire vérifié/créé: {directory}")
    
    def get_api_headers(self) -> dict:
        """Retourne les headers pour l'API EurIA.
        
        Returns:
            Dictionnaire avec les headers d'authentification
        """
        return {
            'Authorization': f'Bearer {self.bearer}',
            'Content-Type': 'application/json',
        }
    
    def __repr__(self) -> str:
        """Représentation string de la configuration (sans le token)."""
        return (
            f"Config(url={self.url}, "
            f"max_attempts={self.max_attempts})"
        )


# Instance globale de configuration (lazy loading)
_config_instance: Optional[Config] = None


def get_config(force_reload: bool = False) -> Config:
    """Retourne l'instance unique de configuration.
    
    Args:
        force_reload: Force le rechargement de la configuration
    
    Returns:
        Instance Config
    """
    global _config_instance
    
    if _config_instance is None or force_reload:
        _config_instance = Config()
        _config_instance.setup_directories()
    
    return _config_instance

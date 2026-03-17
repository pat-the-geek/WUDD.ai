"""Module de cache pour éviter les requêtes HTTP redondantes.

Implémente un système de cache simple basé sur fichiers JSON pour stocker
les résultats d'extraction de texte et de résumés, réduisant les appels API.

Optimisation 2.7 — TTL différenciés par type de contenu :
    Les TTL varient selon la stabilité du contenu mis en cache.
    Utiliser ``get_ttl(content_type)`` pour obtenir le TTL approprié,
    ou passer directement ttl=CACHE_TTL["entities"] à cache.get().

    Types disponibles :
      - "summary"    : 86400s  (24h)   — résumés d'articles, stables
      - "entities"   : 604800s (7j)    — entités NER, très stables
      - "sentiment"  : 604800s (7j)    — sentiment/ton, très stables
      - "synthesis"  : 3600s   (1h)    — synthèses IA, évoluent avec de nouveaux articles
      - "geocode"    : 2592000s (30j)  — coordonnées géographiques, quasi-permanentes
      - "images"     : 604800s (7j)    — images Wikidata/Wikipedia, stables
      - "html"       : 43200s  (12h)   — contenu HTML de page, peut changer
      - "report"     : 86400s  (24h)   — rapports générés, stables à court terme
"""

import json
import hashlib
from pathlib import Path
from typing import Optional, Any
from datetime import datetime, timedelta
from .logging import default_logger


# ── TTL différenciés par type de contenu (optimisation 2.7) ──────────────────

CACHE_TTL: dict[str, int] = {
    "summary":   86400,    # 24h   — résumés d'articles
    "entities":  604800,   # 7j    — entités NER (très stables)
    "sentiment": 604800,   # 7j    — sentiment/ton éditorial (très stables)
    "synthesis": 3600,     # 1h    — synthèses IA (évolue avec nouveaux articles)
    "geocode":   2592000,  # 30j   — coordonnées géographiques
    "images":    604800,   # 7j    — images Wikidata/Wikipedia
    "html":      43200,    # 12h   — contenu HTML de page web
    "report":    86400,    # 24h   — rapports générés
}


def get_ttl(content_type: str) -> int:
    """Retourne le TTL en secondes pour un type de contenu.

    Args:
        content_type : Type de contenu ("summary", "entities", "sentiment", etc.)
                       Voir CACHE_TTL pour la liste complète.

    Returns:
        TTL en secondes. Retourne 86400 (24h) si le type est inconnu.

    Example:
        cache.get(key, ttl=get_ttl("entities"))  # TTL 7j pour NER
    """
    return CACHE_TTL.get(content_type, 86400)


class Cache:
    """Système de cache basé sur fichiers JSON.
    
    Stocke les résultats de requêtes coûteuses (extraction HTML, résumés IA)
    pour éviter de les refaire si elles sont encore valides.
    
    Attributes:
        cache_dir: Répertoire de stockage du cache
        default_ttl: Durée de vie par défaut du cache en secondes
    """
    
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        default_ttl: int = 86400  # 24 heures par défaut
    ):
        """Initialise le système de cache.
        
        Args:
            cache_dir: Répertoire du cache (défaut: data/cache)
            default_ttl: Durée de vie du cache en secondes (défaut: 24h)
        """
        if cache_dir is None:
            # Utiliser data/cache par défaut
            from .config import get_config
            config = get_config()
            self.cache_dir = config.project_root / "data" / "cache"
        else:
            self.cache_dir = Path(cache_dir)
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl
        
        default_logger.info(f"Cache initialisé dans {self.cache_dir} (TTL: {default_ttl}s)")
    
    def _get_cache_key(self, key: str) -> str:
        """Génère une clé de cache unique, isolée par provider IA.

        Inclut AI_PROVIDER dans le hash pour éviter les collisions entre
        EurIA et Claude (même prompt → réponses différentes selon le modèle).

        Args:
            key: Clé originale (URL, prompt, etc.)

        Returns:
            Hash MD5 de la clé préfixée du provider
        """
        import os as _os
        provider = _os.environ.get("AI_PROVIDER", "euria").strip().lower()
        namespaced = f"{provider}:{key}"
        return hashlib.md5(namespaced.encode('utf-8')).hexdigest()
    
    def _get_cache_path(self, key: str) -> Path:
        """Retourne le chemin du fichier de cache.
        
        Args:
            key: Clé de cache
        
        Returns:
            Chemin du fichier JSON
        """
        cache_key = self._get_cache_key(key)
        return self.cache_dir / f"{cache_key}.json"
    
    def get(self, key: str, ttl: Optional[int] = None) -> Optional[Any]:
        """Récupère une valeur du cache.
        
        Args:
            key: Clé de cache (URL, prompt, etc.)
            ttl: Durée de vie en secondes (utilise default_ttl si None)
        
        Returns:
            La valeur cachée ou None si absente/expirée
        """
        cache_path = self._get_cache_path(key)
        
        if not cache_path.exists():
            default_logger.debug(f"Cache miss: {key[:50]}...")
            return None
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # Vérifier l'expiration
            ttl = ttl or self.default_ttl
            cached_time = datetime.fromisoformat(cache_data['timestamp'])
            age = (datetime.now() - cached_time).total_seconds()
            
            if age > ttl:
                default_logger.debug(
                    f"Cache expiré: {key[:50]}... (âge: {age:.0f}s, TTL: {ttl}s)"
                )
                # Supprimer le cache expiré
                cache_path.unlink()
                return None
            
            default_logger.debug(
                f"Cache hit: {key[:50]}... (âge: {age:.0f}s)"
            )
            return cache_data['value']
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            default_logger.error(f"Erreur lors de la lecture du cache: {e}")
            # Supprimer le cache corrompu
            cache_path.unlink(missing_ok=True)
            return None
    
    def set(self, key: str, value: Any) -> None:
        """Enregistre une valeur dans le cache.
        Args:
            key: Clé de cache
            value: Valeur à cacher (doit être sérialisable en JSON)
        """
        cache_path = self._get_cache_path(key)
        # S'assurer que le dossier parent existe
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'key': key[:100],  # Stocker un extrait de la clé pour debug
            'value': value
        }

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            default_logger.debug(f"Valeur cachée: {key[:50]}...")

        except (TypeError, ValueError) as e:
            default_logger.error(f"Erreur lors de l'écriture du cache: {e}")
    
    def delete(self, key: str) -> bool:
        """Supprime une entrée du cache.
        
        Args:
            key: Clé de cache
        
        Returns:
            True si l'entrée a été supprimée, False sinon
        """
        cache_path = self._get_cache_path(key)
        
        if cache_path.exists():
            cache_path.unlink()
            default_logger.debug(f"Cache supprimé: {key[:50]}...")
            return True
        
        return False
    
    def clear(self, older_than: Optional[int] = None) -> int:
        """Vide le cache.
        
        Args:
            older_than: Si spécifié, supprime uniquement les entrées plus
                       anciennes que ce nombre de secondes
        
        Returns:
            Nombre d'entrées supprimées
        """
        deleted_count = 0
        
        for cache_file in self.cache_dir.glob("*.json"):
            should_delete = False
            
            if older_than is None:
                should_delete = True
            else:
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                    
                    cached_time = datetime.fromisoformat(cache_data['timestamp'])
                    age = (datetime.now() - cached_time).total_seconds()
                    
                    if age > older_than:
                        should_delete = True
                        
                except Exception:
                    # Si on ne peut pas lire le fichier, le supprimer
                    should_delete = True
            
            if should_delete:
                cache_file.unlink()
                deleted_count += 1
        
        default_logger.info(f"Cache nettoyé: {deleted_count} entrées supprimées")
        return deleted_count
    
    def get_stats(self) -> dict:
        """Retourne des statistiques sur le cache.
        
        Returns:
            Dictionnaire avec les statistiques
        """
        cache_files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)
        
        return {
            'entries': len(cache_files),
            'total_size_mb': total_size / (1024 * 1024),
            'cache_dir': str(self.cache_dir)
        }


# Instance globale de cache
_cache_instance: Optional[Cache] = None



def get_cache(namespace: Optional[str] = None) -> Cache:
    """Retourne une instance de cache, cloisonnée par namespace (nom de flux).
    Args:
        namespace: nom du sous-répertoire de cache (ex: Intelligence-artificielle)
    Returns:
        Instance Cache
    """
    if namespace:
        from .config import get_config
        config = get_config()
        cache_dir = config.project_root / "data" / "articles" / "cache" / namespace
        return Cache(cache_dir=cache_dir)
    else:
        global _cache_instance
        if _cache_instance is None:
            _cache_instance = Cache()
        return _cache_instance

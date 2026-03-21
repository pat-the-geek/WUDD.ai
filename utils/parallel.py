"""Module de traitement parallèle pour améliorer les performances.

Fournit des fonctions pour traiter les articles en parallèle avec ThreadPoolExecutor,
réduisant considérablement le temps d'exécution pour les tâches I/O-bound.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Callable, Any, Optional
from .logging import default_logger


def process_items_parallel(
    items: List[Any],
    process_function: Callable[[Any], Any],
    max_workers: int = 5,
    description: str = "Traitement"
) -> Dict[Any, Any]:
    """Traite une liste d'éléments en parallèle.
    
    Utilise ThreadPoolExecutor pour traiter plusieurs éléments simultanément,
    particulièrement utile pour les opérations I/O-bound comme les requêtes HTTP.
    
    Args:
        items: Liste d'éléments à traiter
        process_function: Fonction à appliquer à chaque élément
        max_workers: Nombre maximal de threads (défaut: 5)
        description: Description de la tâche pour les logs
    
    Returns:
        Dictionnaire mappant chaque élément à son résultat
    
    Example:
        >>> urls = ['https://site1.com', 'https://site2.com']
        >>> results = process_items_parallel(
        ...     urls,
        ...     fetch_and_extract_text,
        ...     max_workers=3,
        ...     description="Extraction de texte"
        ... )
    """
    if not items:
        default_logger.warning(f"{description}: Liste vide, aucun traitement")
        return {}
    
    results = {}
    total = len(items)
    completed = 0
    
    default_logger.info(
        f"{description}: Démarrage du traitement de {total} éléments "
        f"avec {max_workers} workers"
    )
    
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Soumettre toutes les tâches
        future_to_item = {
            executor.submit(process_function, item): item
            for item in items
        }
        
        # Traiter les résultats au fur et à mesure qu'ils arrivent
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            completed += 1
            
            try:
                result = future.result()
                results[item] = result
                
                if completed % 10 == 0 or completed == total:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    default_logger.info(
                        f"{description}: {completed}/{total} traités "
                        f"({rate:.1f} items/s)"
                    )
                    
            except Exception as e:
                default_logger.error(
                    f"{description}: Erreur lors du traitement de {item}: {e}"
                )
                results[item] = f"Erreur: {str(e)}"
    
    elapsed_time = time.time() - start_time
    default_logger.info(
        f"{description}: Terminé en {elapsed_time:.2f}s "
        f"({len(results)} résultats, {elapsed_time/total:.2f}s/item en moyenne)"
    )
    
    return results


def fetch_articles_parallel(
    items: List[Dict],
    fetch_function: Callable[[str], str],
    max_workers: int = 5
) -> Dict[str, str]:
    """Récupère le texte de plusieurs articles en parallèle.
    
    Wrapper spécialisé pour extraire le texte d'articles depuis leurs URLs
    en utilisant le traitement parallèle.
    
    Args:
        items: Liste de dictionnaires contenant les URLs des articles
        fetch_function: Fonction pour extraire le texte (ex: fetch_and_extract_text)
        max_workers: Nombre maximal de threads parallèles (défaut: 5)
    
    Returns:
        Dictionnaire mappant URL -> texte extrait
    """
    if not items:
        return {}
    
    # Extraire les URLs
    urls = [item.get('url', item.get('URL')) for item in items]
    urls = [url for url in urls if url]  # Filtrer les None
    
    if not urls:
        default_logger.warning("Aucune URL valide trouvée dans les items")
        return {}
    
    # Traiter en parallèle
    return process_items_parallel(
        urls,
        fetch_function,
        max_workers=max_workers,
        description="Extraction de texte des articles"
    )


def process_with_rate_limit(
    items: List[Any],
    process_function: Callable[[Any], Any],
    requests_per_second: float = 2.0,
    description: str = "Traitement avec rate limit"
) -> Dict[Any, Any]:
    """Traite des éléments avec un rate limiting pour éviter la surcharge.
    
    Utile pour respecter les limites d'API ou éviter d'être bloqué par des serveurs.
    
    Args:
        items: Liste d'éléments à traiter
        process_function: Fonction à appliquer à chaque élément
        requests_per_second: Nombre maximal de requêtes par seconde (défaut: 2.0)
        description: Description de la tâche pour les logs
    
    Returns:
        Dictionnaire mappant chaque élément à son résultat
    """
    if not items:
        default_logger.warning(f"{description}: Liste vide, aucun traitement")
        return {}
    
    results = {}
    total = len(items)
    delay = 1.0 / requests_per_second
    
    default_logger.info(
        f"{description}: Traitement de {total} éléments "
        f"(max {requests_per_second} req/s, délai={delay:.2f}s)"
    )
    
    start_time = time.time()
    
    for i, item in enumerate(items, 1):
        try:
            result = process_function(item)
            results[item] = result
            
            if i % 10 == 0 or i == total:
                elapsed = time.time() - start_time
                default_logger.info(
                    f"{description}: {i}/{total} traités "
                    f"({i/elapsed:.1f} items/s)"
                )
            
            # Attendre le délai entre requêtes (sauf pour le dernier)
            if i < total:
                time.sleep(delay)
                
        except Exception as e:
            default_logger.error(
                f"{description}: Erreur lors du traitement de {item}: {e}"
            )
            results[item] = f"Erreur: {str(e)}"
    
    elapsed_time = time.time() - start_time
    default_logger.info(
        f"{description}: Terminé en {elapsed_time:.2f}s "
        f"({len(results)} résultats)"
    )
    
    return results


def batch_process(
    items: List[Any],
    process_function: Callable[[List[Any]], List[Any]],
    batch_size: int = 10,
    description: str = "Traitement par batch"
) -> List[Any]:
    """Traite des éléments par lots (batches).
    
    Utile pour optimiser la mémoire ou traiter des éléments par groupes.
    
    Args:
        items: Liste d'éléments à traiter
        process_function: Fonction qui traite un batch et retourne les résultats
        batch_size: Taille de chaque batch (défaut: 10)
        description: Description de la tâche pour les logs
    
    Returns:
        Liste de tous les résultats concaténés
    """
    if not items:
        return []
    
    results = []
    total_batches = (len(items) + batch_size - 1) // batch_size
    
    default_logger.info(
        f"{description}: Traitement de {len(items)} éléments "
        f"en {total_batches} batches de {batch_size}"
    )
    
    for i in range(0, len(items), batch_size):
        batch_num = i // batch_size + 1
        batch = items[i:i + batch_size]
        
        try:
            batch_results = process_function(batch)
            results.extend(batch_results)
            
            default_logger.info(
                f"{description}: Batch {batch_num}/{total_batches} traité "
                f"({len(batch)} éléments)"
            )
            
        except Exception as e:
            default_logger.error(
                f"{description}: Erreur lors du traitement du batch {batch_num}: {e}"
            )
    
    default_logger.info(
        f"{description}: Terminé, {len(results)} résultats au total"
    )
    
    return results


def run_parallel(
    func: Callable[[Any], Any],
    items: List[Any],
    max_workers: int = 5,
) -> List[Any]:
    """Applique ``func`` à chaque élément de ``items`` en parallèle.

    Signature simplifiée (func-first) utilisée par ``async_enricher`` en mode
    fallback synchrone.  Contrairement à ``process_items_parallel``, retourne
    une **liste ordonnée** de résultats (même ordre que ``items``).

    Args:
        func       : Fonction à appliquer à chaque élément.
        items      : Liste d'éléments à traiter.
        max_workers: Nombre maximal de threads (défaut : 5).

    Returns:
        Liste des valeurs renvoyées par ``func`` pour chaque élément d'``items``.
    """
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(func, items))

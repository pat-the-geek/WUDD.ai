"""Module utilitaires HTTP pour AnalyseActualités.

Fournit des fonctions robustes pour les requêtes HTTP avec:
- Gestion cohérente des timeouts
- Retry automatique avec backoff exponentiel
- Extraction de texte HTML
- Validation des réponses
"""

import time
import requests
from bs4 import BeautifulSoup
from typing import Optional, Tuple
from .logging import default_logger

# Headers standard pour la récupération de flux RSS.
# Certains sites (ex. laliberte.ch, france24.com) retournent un 403 si User-Agent est absent
# ou si les headers ressemblent trop à un robot.
RSS_FEED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "DNT": "1",
}

# Headers pour la visite de la page d'accueil (récupération de cookies)
_HOMEPAGE_HEADERS = {
    **RSS_FEED_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}

# Longueur minimale (caractères) en dessous de laquelle le texte extrait est
# considéré comme « contenu non récupéré » (mur JavaScript, redirection vide,
# page de consentement). En dessous, on ne résume pas : on retombe sur la
# description RSS d'origine côté appelant.
MIN_ARTICLE_TEXT_LENGTH = 200

# Signatures de pages de blocage servies en HTTP 200 à la place du contenu réel
# de l'article : murs JavaScript, anti-bot, captcha, consentement cookies.
# Ces tournures n'apparaissent quasiment jamais dans le corps d'un article, donc
# la détection est indépendante de la longueur (un faux positif fait simplement
# retomber l'appelant sur la description RSS — dégradation gracieuse, pas de perte).
_BLOCK_PAGE_SIGNATURES = (
    "veuillez activer javascript",
    "activer le javascript",
    "activez javascript",
    "javascript est désactivé",
    "javascript doit être activé",
    "javascript is disabled",
    "please enable javascript",
    "enable javascript to",
    "you need to enable javascript",
    "pour utiliser mastodon",
    "êtes-vous un robot",
    "are you a robot",
    "verifying you are human",
    "vérifie que vous êtes humain",
    "checking your browser before",
    "merci de vérifier que vous n'êtes pas un robot",
    "veuillez activer les cookies",
    "activez les cookies",
)


# Motifs de chemin/URL trahissant une photo d'auteur / byline / avatar plutôt
# qu'un visuel d'article. Sur certains médias (Mashable, etc.) la photo de la
# journaliste est servie en très haute résolution (2000×2000) et l'emporte sur
# l'image d'illustration au tri par surface → on l'écarte explicitement.
_AUTHOR_IMAGE_URL_PATTERNS = (
    "/authors/",
    "/author/",
    "/imagery/authors",
    "/contributors/",
    "/contributor/",
    "/avatars/",
    "/avatar/",
    "/byline",
    "/staff/",
    "/profiles/",
    "/profile-",
    "gravatar.com",
)


def is_author_image(url: str) -> bool:
    """Vrai si l'URL d'image pointe vers une photo d'auteur / byline / avatar
    (à exclure des visuels d'article)."""
    if not isinstance(url, str):
        return False
    low = url.lower()
    return any(p in low for p in _AUTHOR_IMAGE_URL_PATTERNS)


def is_block_page_text(text: str) -> bool:
    """Détecte si un texte est en réalité une page de blocage (mur JavaScript,
    anti-bot, captcha, mur de consentement) servie à la place du contenu réel.

    Détection par signatures uniquement (indépendante de la longueur), pour
    pouvoir s'appliquer aussi bien au texte HTML brut qu'à un résumé déjà généré
    qui aurait paraphrasé un message de blocage.
    """
    if not isinstance(text, str):
        return False
    lowered = text.lower()
    return any(sig in lowered for sig in _BLOCK_PAGE_SIGNATURES)


def fetch_rss_feed(url: str, timeout: int = 15) -> requests.Response:
    """Récupère un flux RSS avec stratégie anti-403.

    1. Tentative rapide avec RSS_FEED_HEADERS.
    2. Si 403, fallback : session + visite de la page d'accueil pour obtenir
       les cookies du WAF/CDN, puis nouvelle tentative.

    Raises:
        requests.exceptions.HTTPError: si le flux reste inaccessible après les deux tentatives.
    """
    # Tentative directe
    try:
        r = requests.get(url, timeout=timeout, headers=RSS_FEED_HEADERS)
        if r.status_code != 403:
            r.raise_for_status()
            return r
    except requests.exceptions.HTTPError:
        if r.status_code != 403:
            raise

    # Fallback : session avec cookies de la page d'accueil
    default_logger.info(f"[RSS] 403 sur {url} — fallback session+cookies")
    session = requests.Session()
    domain = "/".join(url.split("/")[:3])
    try:
        session.get(domain, timeout=20, headers=_HOMEPAGE_HEADERS)
    except Exception:
        pass  # On continue même si la homepage échoue
    r = session.get(url, timeout=timeout, headers=RSS_FEED_HEADERS)
    r.raise_for_status()
    return r


class HTTPError(Exception):
    """Exception levée lors d'erreurs HTTP."""
    pass


def create_session_with_retries(
    total_retries: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: Tuple[int, ...] = (429, 500, 502, 503, 504)
) -> requests.Session:
    """Crée une session requests avec stratégie de retry.
    
    Args:
        total_retries: Nombre total de tentatives
        backoff_factor: Facteur multiplicateur pour le backoff (0.5 = 0.5s, 1s, 2s...)
        status_forcelist: Codes HTTP qui déclenchent un retry
    
    Returns:
        Session requests configurée
    """
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    
    session = requests.Session()
    retry_strategy = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session


def fetch_and_extract_text(
    url: str,
    timeout: int = 10,
    max_retries: int = 3
) -> str:
    """Récupère le contenu HTML d'une URL et extrait le texte brut.
    
    Effectue une requête HTTP GET avec retry automatique, parse le HTML 
    avec BeautifulSoup, et extrait le texte visible en nettoyant les espaces.
    
    Args:
        url: L'adresse HTTP/HTTPS de la page à récupérer
        timeout: Délai d'attente maximal en secondes (défaut: 10)
        max_retries: Nombre maximal de tentatives (défaut: 3)
    
    Returns:
        Le texte extrait de la page. En cas d'erreur, retourne un message
        d'erreur descriptif.
    
    Example:
        >>> text = fetch_and_extract_text('https://example.com/article')
        >>> print(text[:100])
        'Ceci est le contenu de l'article...'
    """
    if not url or not isinstance(url, str):
        return "Erreur: URL invalide ou manquante"
    
    # Validation URL HTTPS recommandée
    if not url.startswith(('http://', 'https://')):
        default_logger.warning(f"URL sans protocole HTTP(S): {url}")
        return f"Erreur: URL invalide (pas de protocole HTTP): {url}"
    
    for attempt in range(max_retries):
        try:
            # Utiliser RSS_FEED_HEADERS (Chrome user-agent) pour éviter les 403
            # sur les sites protégés par WAF/CDN (laliberte.ch, etc.)
            response = requests.get(url, timeout=timeout, headers=RSS_FEED_HEADERS)
            response.raise_for_status()
            
            # Parser le HTML et extraire le texte
            soup = BeautifulSoup(response.content, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)

            # Garde-fou : un HTTP 200 peut servir une page de blocage (mur JS,
            # anti-bot, captcha, consentement) ou un contenu vide. La résumer
            # produirait un faux résumé (« Veuillez activer JavaScript… »).
            # On renvoie une erreur explicite : les appelants retombent alors
            # sur la description RSS d'origine (cf. flux_watcher / get-keyword).
            if is_block_page_text(text):
                default_logger.warning(f"Page de blocage détectée (mur JS / anti-bot) pour {url} — texte ignoré.")
                return f"Erreur: page de blocage (JavaScript/anti-bot) détectée pour {url}"
            if len(text) < MIN_ARTICLE_TEXT_LENGTH:
                default_logger.warning(
                    f"Contenu trop court ({len(text)} car.) pour {url} — probablement non récupéré, ignoré."
                )
                return f"Erreur: contenu indisponible ou trop court ({len(text)} car.) pour {url}"

            default_logger.debug(f"Texte extrait de {url}: {len(text)} caractères")
            return text
            
        except requests.exceptions.Timeout:
            default_logger.warning(f"Timeout lors de la récupération de {url} (tentative {attempt+1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Backoff exponentiel
            else:
                return f"Erreur: Timeout après {max_retries} tentatives pour {url}"
                
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 'inconnu'
            default_logger.error(f"Erreur HTTP {status_code} pour {url}")
            return f"Erreur HTTP {status_code}: {url}"
            
        except requests.exceptions.ConnectionError:
            default_logger.error(f"Erreur de connexion pour {url} (tentative {attempt+1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                return f"Erreur: Impossible de se connecter à {url}"
                
        except Exception as e:
            default_logger.error(f"Erreur inattendue pour {url}: {type(e).__name__}: {e}")
            return f"Erreur: {type(e).__name__}: {str(e)}"
    
    return "Erreur: Échec après toutes les tentatives"


def extract_top_n_largest_images(
    url: str,
    n: int = 3,
    min_width: int = 500,
    timeout: int = 10
) -> list[dict] | dict:
    """Extrait les N plus grandes images d'une page web.

    Utilise une cascade de sources par ordre de fiabilité :
    1. Métadonnées Open Graph (og:image) — choisies explicitement par l'éditeur
    2. Twitter Card (twitter:image) — fallback secondaire
    3. Balises <img> avec attributs width/height explicites

    Args:
        url: L'adresse de la page web à analyser
        n: Nombre d'images à retourner (défaut: 3)
        min_width: Largeur minimale en pixels (défaut: 500)
        timeout: Délai d'attente maximal en secondes (défaut: 10)

    Returns:
        Une liste de N dictionnaires maximum, chacun contenant:
            - url: URL de l'image
            - title: Attribut title de l'image
            - alt: Attribut alt de l'image
            - width: Largeur en pixels
            - height: Hauteur en pixels
            - area: Surface calculée (width * height)
        En cas d'erreur, retourne un dictionnaire avec une clé 'error'.
    """
    try:
        # Utiliser RSS_FEED_HEADERS pour éviter les 403 (laliberte.ch, etc.)
        response = requests.get(url, timeout=timeout, headers=RSS_FEED_HEADERS)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        def _norm_text(value: str) -> str:
            return " ".join((value or "").strip().lower().split())

        article_title = ""
        og_title_tag = soup.find('meta', property='og:title')
        if og_title_tag:
            article_title = (og_title_tag.get('content') or '').strip()
        if not article_title and soup.title:
            article_title = (soup.title.get_text() or '').strip()

        seen_urls: set = set()
        images = []

        # ── 1. Open Graph ──────────────────────────────────────────────────────
        og_image = soup.find('meta', property='og:image')
        if og_image:
            og_url = og_image.get('content', '').strip()
            if og_url.startswith(('http://', 'https://')) and not is_author_image(og_url):
                try:
                    og_w = int(
                        soup.find('meta', property='og:image:width', content=True)
                        and soup.find('meta', property='og:image:width').get('content', 0)
                        or 1200
                    )
                    og_h = int(
                        soup.find('meta', property='og:image:height', content=True)
                        and soup.find('meta', property='og:image:height').get('content', 0)
                        or 630
                    )
                except (ValueError, TypeError, AttributeError):
                    og_w, og_h = 1200, 630

                og_w = og_w or 1200
                og_h = og_h or 630

                og_alt = ''
                og_alt_tag = soup.find('meta', property='og:image:alt')
                if og_alt_tag:
                    og_alt = (og_alt_tag.get('content') or '').strip()
                if _norm_text(og_alt) == _norm_text(article_title):
                    og_alt = ''

                images.append({
                    'url': og_url,
                    'title': article_title,
                    'alt': og_alt,
                    'width': og_w,
                    'height': og_h,
                    'area': og_w * og_h,
                })
                seen_urls.add(og_url)

        # ── 2. Twitter Card ────────────────────────────────────────────────────
        for twitter_attr in ({'name': 'twitter:image'}, {'property': 'twitter:image'}):
            tc_tag = soup.find('meta', attrs=twitter_attr)
            if tc_tag:
                tc_url = tc_tag.get('content', '').strip()
                if (tc_url.startswith(('http://', 'https://')) and tc_url not in seen_urls
                        and not is_author_image(tc_url)):
                    images.append({
                        'url': tc_url,
                        'title': '',
                        'alt': '',
                        'width': 1200,
                        'height': 630,
                        'area': 1200 * 630,
                    })
                    seen_urls.add(tc_url)
                break

        # ── 3. Balises <img> avec dimensions explicites ────────────────────────
        for img in soup.find_all('img'):
            src = img.get('src', '').strip()
            if not src.startswith(('http://', 'https://')) or src in seen_urls:
                continue
            if is_author_image(src):
                continue  # photo d'auteur / byline / avatar — pas un visuel d'article
            title = img.get('title', '').strip()
            alt = img.get('alt', '').strip()
            if _norm_text(alt) == _norm_text(article_title):
                alt = ''
            try:
                width = int(img.get('width') or 0)
                height = int(img.get('height') or 0)
            except (ValueError, TypeError):
                width = height = 0
            if width > min_width:
                area = width * height
                images.append({
                    'url': src,
                    'title': title,
                    'alt': alt,
                    'width': width,
                    'height': height,
                    'area': area,
                })
                seen_urls.add(src)

        # Trier par surface décroissante et retourner les N premières
        images.sort(key=lambda x: x['area'], reverse=True)
        return images[:n]

    except requests.exceptions.Timeout:
        default_logger.error(f"Timeout lors de l'extraction d'images de {url}")
        return []
    except requests.exceptions.RequestException as e:
        default_logger.error(f"Erreur réseau lors de l'extraction d'images: {e}")
        return []
    except Exception as e:
        default_logger.error(f"Erreur inattendue lors de l'extraction d'images: {e}")
        return []

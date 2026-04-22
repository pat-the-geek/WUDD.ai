# Plan : Intégration Claude comme fournisseur IA alternatif à EurIA

## Contexte

WUDD.ai utilise exclusivement l'API EurIA (Infomaniak / Qwen/Qwen3.5-122B-A10B-FP8). L'objectif est d'ajouter Claude (Anthropic) comme fournisseur IA alternatif, sélectionnable dans le panneau Environnement des Réglages, sans rien casser du fonctionnement EurIA actuel.

**Stratégie modèles Claude** (basée sur l'analyse des prompts) :
- **Haiku 4.5** (`claude-haiku-4-5-20251001`) pour les tâches batch volumineuses : résumé, NER, sentiment
- **Sonnet 4.6** (`claude-sonnet-4-6`) pour les synthèses user-facing : rapport, RAG, encyclopédique

---

## Fichiers à modifier (6 fichiers + 12 scripts)

### 1. `.env.example` — 4 nouvelles variables

```
# Fournisseur IA actif : "euria" (défaut) ou "claude"
AI_PROVIDER=euria

# Anthropic Claude (requis si AI_PROVIDER=claude)
ANTHROPIC_API_KEY=
CLAUDE_MODEL_BATCH=claude-haiku-4-5-20251001
CLAUDE_MODEL_SYNTHESIS=claude-sonnet-4-6
```

---

### 2. `utils/config.py` — Validation conditionnelle

**Ajouter dans `_load_config()`** après `self.bearer` :
```python
self.ai_provider = os.getenv("AI_PROVIDER", "euria").strip().lower()
self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
self.claude_model_batch = os.getenv("CLAUDE_MODEL_BATCH", "claude-haiku-4-5-20251001")
self.claude_model_synthesis = os.getenv("CLAUDE_MODEL_SYNTHESIS", "claude-sonnet-4-6")
```

**Remplacer la validation URL/bearer inconditionnelle** par :
```python
if self.ai_provider == "euria":
    if not self.url:    errors.append("URL manquante (requis pour AI_PROVIDER=euria)")
    if not self.bearer: errors.append("bearer manquant (requis pour AI_PROVIDER=euria)")
elif self.ai_provider == "claude":
    if not self.anthropic_api_key:
        errors.append("ANTHROPIC_API_KEY manquante (requis pour AI_PROVIDER=claude)")
else:
    errors.append(f"AI_PROVIDER invalide: '{self.ai_provider}'. Valeurs: 'euria', 'claude'")
```

---

### 3. `utils/api_client.py` — Classe `ClaudeClient` + factory `get_ai_client()`

#### Nouvelle constante
```python
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
```

#### Classe `ClaudeClient` (après `EurIAClient`)

Méthodes miroir avec même signature que `EurIAClient` :

| Méthode | Modèle | max_tokens |
|---------|--------|-----------|
| `ask(prompt, timeout, max_tokens)` | passé en param | param |
| `generate_summary()` | `model_batch` (Haiku) | 512 |
| `generate_entities()` | `model_batch` (Haiku) | 800 |
| `generate_sentiment()` | `model_batch` (Haiku) | 150 |
| `generate_report()` | `model_synthesis` (Sonnet) | 4096 |
| `synthesize_topic()` | `model_synthesis` (Sonnet) | 2048 |

**Différences techniques vs EurIA** :
- Request body : `{"model": ..., "max_tokens": ..., "messages": [...]}` (max_tokens OBLIGATOIRE)
- Response body : `{"content": [{"type": "text", "text": "..."}]}`
- Pas de `enable_web_search` (paramètre ignoré en no-op)
- Réutilise `_parse_entities_response()` et `_parse_sentiment_response()` (fonctions internes existantes)
- Réutilise les mêmes prompts que EurIA (prompts 1-4 identiques)

#### Factory `get_ai_client()`
```python
def get_ai_client():
    """Retourne EurIAClient ou ClaudeClient selon AI_PROVIDER dans .env."""
    provider = get_config().ai_provider
    if provider == "claude":
        return ClaudeClient()
    return EurIAClient()
```

---

### 4. Les 12 scripts — Remplacement minimal

Dans chaque script, 2 changements uniquement :

```python
# Avant
from utils.api_client import EurIAClient
client = EurIAClient()

# Après
from utils.api_client import get_ai_client
client = get_ai_client()
```

Scripts concernés :
- `scripts/Get_data_from_JSONFile_AskSummary_v2.py`
- `scripts/scheduler_articles.py`
- `scripts/flux_watcher.py`
- `scripts/get-keyword-from-rss.py`
- `scripts/enrich_entities.py`
- `scripts/enrich_sentiment.py`
- `scripts/repair_failed_summaries.py`
- `scripts/generate_keyword_reports.py`
- `scripts/generate_48h_report.py`
- `scripts/generate_morning_digest.py`
- `scripts/generate_briefing.py`
- `scripts/radar_wudd.py`

> Note : les cas `EurIAClient(enable_web_search=False)` → `get_ai_client()` (le paramètre est un no-op pour Claude).

---

### 5. `viewer/app.py` — Routes SSE + clé sensible

#### `_SENSITIVE_KEYS` (ligne 2993)
```python
_SENSITIVE_KEYS = {"bearer", "SMTP_PASSWORD", "NTFY_TOKEN", "ANTHROPIC_API_KEY"}
```

#### Helper `_build_sse_call(prompt, stream, use_web_search)` (nouvelle fonction interne)

Retourne `(api_url, payload, headers, provider)` selon `AI_PROVIDER` :
- `"euria"` → URL+bearer existants, payload EurIA, Qwen/Qwen3.5-122B-A10B-FP8
- `"claude"` → `CLAUDE_API_URL`, ANTHROPIC_API_KEY, `claude-sonnet-4-6` (ces routes sont user-facing → Sonnet)

#### Normalisation SSE Claude → format OpenAI

Claude envoie :
```
event: content_block_delta
data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}
event: message_stop
data: {"type": "message_stop"}
```

Le frontend lit le format OpenAI (`choices[0].delta.content`). Ajouter une fonction :
```python
def _normalize_claude_sse(line: str) -> str | None:
    """Convertit un événement SSE Claude au format OpenAI attendu par le frontend."""
```

#### Routes à mettre à jour

**`/api/entities/info`** (prompt 5 — Sonnet) :
- Utilise `_build_sse_call()` selon provider
- Normalise les lignes SSE avec `_normalize_claude_sse()` si `provider == "claude"`

**`/api/synthesize-topic`** (prompt 6 — Sonnet) :
- Même pattern

> Les autres routes de `app.py` n'appellent pas EurIA directement → pas de changement.

---

### 6. `viewer/src/components/SettingsPanel.jsx` — UI sélecteur IA

#### Nouveau composant `AiProviderSelector`

Deux boutons radio-style en haut de `EnvTab` :
```
┌────────────────────────────────────────────────────┐
│  FOURNISSEUR IA ACTIF                              │
│  [● EurIA · Infomaniak/Qwen3.5-122B-A10B-FP8]  [ Claude · Anthropic]│
└────────────────────────────────────────────────────┘
```
- Lit `vars.find(v => v.key === 'AI_PROVIDER')?.value`
- Au clic : appelle `saveVar('AI_PROVIDER', 'euria'|'claude')` (réutilise la fonction existante)

#### `ENV_GROUPS` mis à jour

```javascript
const ENV_GROUPS = [
  { label: 'IA EurIA (Infomaniak)',  keys: ['URL', 'bearer'] },
  { label: 'IA Claude (Anthropic)',  keys: ['ANTHROPIC_API_KEY', 'CLAUDE_MODEL_BATCH', 'CLAUDE_MODEL_SYNTHESIS'] },
]
```
`AI_PROVIDER` est ajouté à `groupedKeys` pour être **masqué de la table** (géré uniquement par le sélecteur).

#### Affichage conditionnel des groupes

Les deux groupes de variables restent visibles en permanence, mais le groupe du fournisseur **actif** est mis en évidence (bordure bleue, fond légèrement coloré) et le groupe inactif est **grisé** (`opacity-50`). Cela guide l'utilisateur vers les champs à remplir selon son choix.

#### Alerte de configuration incomplète

Si le fournisseur actif n'a pas sa clé renseignée, afficher une bannière d'avertissement sous le sélecteur :

```
⚠️  Claude est sélectionné mais ANTHROPIC_API_KEY est vide.
    Les traitements IA échoueront jusqu'à ce que la clé soit renseignée.
```
```
⚠️  EurIA est sélectionné mais URL ou bearer est vide.
    Les traitements IA échoueront jusqu'à ce que les champs soient renseignés.
```

Cette vérification est purement front-end (lecture des `entries` déjà chargées).

#### Messages d'erreur dans les routes Flask

Les routes SSE retournent actuellement `"Configuration API EurIA manquante (.env)"`.
→ Mettre à jour en fonction du fournisseur actif :
```python
if provider == "claude":
    return jsonify({"error": "ANTHROPIC_API_KEY manquante dans .env (AI_PROVIDER=claude)"}), 503
else:
    return jsonify({"error": "URL ou bearer manquant dans .env (AI_PROVIDER=euria)"}), 503
```

---

## Points d'attention

1. **Rétrocompatibilité totale** : si `AI_PROVIDER` est absent du `.env`, EurIA fonctionne comme avant sans aucune régression.

2. **`max_tokens` obligatoire pour Claude** : l'API Anthropic le requiert, l'API EurIA (OpenAI-compatible) ne le requiert pas. `ClaudeClient.ask()` force une valeur adaptée à chaque méthode.

3. **Pas de web search pour Claude** (prompts 1–4) : EurIA active `enable_web_search: true` par défaut. Claude n'a pas d'équivalent simple — les synthèses (prompts 5–6) compensent par la connaissance du modèle Sonnet.

4. **Annotations de type dans les scripts** : les quelques scripts avec `client: EurIAClient` en signature de fonction seront simplifiés en supprimant l'annotation de type.

5. **Aucun changement frontend** dans EntityArticlePanel, SearchOverlay, etc. : le frontend lit toujours le même format SSE OpenAI — la normalisation est transparente côté Flask.

---

## Vérification

1. Avec `AI_PROVIDER=euria` : comportement identique à aujourd'hui — aucune régression
2. Avec `AI_PROVIDER=claude` + `ANTHROPIC_API_KEY` valide :
   - Lancer `scripts/enrich_entities.py --dry-run` → log montre ClaudeClient + Haiku
   - Ouvrir le viewer, onglet Info d'une entité → synthèse générée via Claude Sonnet en streaming
   - Onglet RAG → synthèse RAG via Claude Sonnet en streaming
3. Basculer dans Réglages → Environnement → bouton EurIA → retour EurIA immédiat

---

*Auteur : Patrick Ostertag — généré avec Claude Code*
*Date : 2026-03-08*

## 🛑 Fichiers à ignorer dans GitHub

Le dossier `data/` (et tout son contenu) doit être ignoré dans le contrôle de version GitHub. Ajoutez ou vérifiez la présence de la ligne suivante dans le fichier `.gitignore` à la racine du projet :

```
data/
```

Cela évite de versionner des données volumineuses, sensibles ou générées automatiquement.
<!-- Copilot instructions for the AnalyseActualités workspace -->

# Assistant guidelines for `AnalyseActualités`

**Version:** 2.0 (post-restructuration 23/01/2026)  
**Purpose:** Help contributors and AI coding agents be immediately productive in this repository.

## 🎯 Big Picture

Pipeline ETL automatisé qui collecte des flux RSS/JSON d'actualités, extrait le contenu HTML, génère des résumés via l'API EurIA d'Infomaniak (modèle Qwen3), et produit des sorties structurées (JSON + rapports Markdown). Architecture modulaire avec scripts Python CLI/GUI.

## 📁 Structure du projet (IMPORTANT)

```
AnalyseActualités/
├── scripts/           # Scripts Python exécutables
├── config/            # Configuration (sources, catégories, prompts)
├── data/
│   ├── articles/      # JSON structurés avec résumés IA
│   └── raw/           # Données brutes (HTML/texte)
├── rapports/
│   ├── markdown/      # Rapports générés
│   └── pdf/           # Exports PDF
├── archives/          # Anciennes versions de scripts
└── tests/             # Tests unitaires (à développer)
```

## 🔧 Composants clés

### Scripts principaux (dans `scripts/`)

1. **`Get_data_from_JSONFile_AskSummary.py`** (script central)
   - Lit flux JSON depuis `REEDER_JSON_URL` (variable .env)
   - Extrait HTML de chaque article
   - Génère résumés via API EurIA
   - Extrait top 3 images (largeur > 500px)
   - Sauvegarde dans `data/articles/articles_generated_YYYY-MM-DD_YYYY-MM-DD.json`
   - Génère rapport Markdown dans `rapports/markdown/`
   - **Nouveauté v2.0:** Utilise chemins absolus via détection automatique `__file__`

2. **`Get_htmlText_From_JSONFile.py`**
   - Extrait texte brut depuis flux JSON
   - Sortie: `data/raw/all_articles.txt` (format: source, date, url, texte)

3. **`articles_json_to_markdown.py`**
   - Convertit JSON → Markdown formaté
   - Entrée: fichiers dans `data/articles/`
   - Sortie: rapports Markdown personnalisés

4. **`analyse_thematiques.py`**
   - Analyse les thématiques sociétales des articles collectés
   - Lit tous les JSON du répertoire `data/articles/`
   - Génère un rapport console avec statistiques détaillées
   - Utilise les mots-clés définis dans `config/thematiques_societales.json`

### Configuration (dans `config/`)

- **`sites_actualite.json`** : 133 sources RSS/JSON avec `Titre` et `URL`
- **`categories_actualite.json`** : 215 catégories prédéfinies
- **`prompt-rapport.txt`** : Template de prompt pour génération de rapports IA
- **`thematiques_societales.json`** : 12 thématiques sociétales avec mots-clés, statistiques et rangs d'importance

- **Data shapes & conventions (important):**
  - Input feed JSONs commonly include an `items` array where each item has at least `url`, `date_published` (ISO 8601-like `YYYY-MM-DDTHH:MM:SSZ`), and `authors` (list with `name`). Example: `item['date_published'] == "2025-11-29T10:13:19Z"`.
  - Output `articles.json` is a list of objects with keys in French: `Date de publication`, `Sources`, `URL`, `Résumé`.
  - Dates are parsed with `datetime.strptime(..., "%Y-%m-%dT%H:%M:%SZ")`. Preserve this format unless you update parsing logic.
  - Content is primarily French; keep summaries and messages in French for consistency.

## ⚙️ Environnement technique

### Dépendances
- **Python:** 3.10+ (testé avec 3.14)
- **Packages:** `requests`, `beautifulsoup4`, `python-dotenv`
- **Installation:** `pip install -r requirements.txt`
- **GUI:** `tkinter` (stdlib) pour sélection fichiers

### Variables d'environnement (.env à la racine)
```env
URL=https://api.infomaniak.com/euria/v1/chat/completions
bearer=VOTRE_TOKEN_API_INFOMANIAK
REEDER_JSON_URL=https://votre-flux.json
## 📊 Conventions de données

### Format d'entrée (flux JSON)
```json
{
  "items": [
    {
      "url": "https://source.com/article",
      "date_published": "2026-01-23T10:00:00Z",  // ISO 8601 strict
      "authors": [{"name": "Nom Auteur"}]
    }
  ]
}
```

### Format de sortie (JSON structuré)
```json
[
  {
    "Date de publication": "2026-01-23T10:00:00Z",
    "Sources": "Nom de la source",
    "URL": "https://...",
    "Résumé": "Résumé en français (max 20 lignes)",
    "Images": [
      {
        "url": "https://image.jpg",
        "width": 1200,
        "height": 800,
        "area": 960000
      }
    ]
  }
]
```

### Parsing de dates
```python
datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
```
⚠️ Format strict — beaucoup d'erreurs viennent de dates mal formatées

## 🛠️ Patterns et contraintes du projet

### Langue française obligatoire
- Clés JSON : `Date de publication`, `Sources`, `URL`, `Résumé`
- Messages de log en français
- Prompts IA en français
- **Ne JAMAIS modifier ces clés sans mettre à jour tous les scripts**

### API EurIA (Infomaniak)
```python
# Appel standard
response = requests.post(
    URL,
    json={
        "messages": [{"content": prompt, "role": "user"}],
        "model": "qwen3",
        "enable_web_search": True
    },
    headers={'Authorization': f'Bearer {BEARER}'},
    timeout=60
)
# Réponse attendue
content = response.json()['choices'][0]['message']['content']
```

**Prompts utilisés** :

1. **Résumé d'article** (60s timeout, 3 tentatives) :
   ```
   faire un résumé de ce texte sur maximum 20 lignes en français, 
   ne donne que le résumé, sans commentaire ni remarque : {texte}
   ```

2. **Génération de rapport** (300s timeout, 3 tentatives) :
   ```
   Analyse le fichier ce fichier JSON et fait une synthèse des actualités. 
   Affiche la date de publication et les sources lorsque tu cites un article. 
   Groupe les acticles par catégories que tu auras identifiées. 
   En fin de synthèse fait un tableau avec les références.
   Inclus des images pertinentes (<img src='URL' />).
   ```

- Retry automatique : 3 tentatives par défaut
- Timeouts : 60s (résumé), 300s (rapport)
- Fallback : Message d'erreur standardisé si échec complet

### Workflow GUI vs CLI
- `Get_htmlText_From_JSONFile.py` et `articles_json_to_markdown.py` : GUI `tkinter`
- `Get_data_from_JSONFile_AskSummary.py` : CLI avec arguments optionnels
- Pour automatisation : modifier les scripts pour accepter CLI args ou passer chemins directement

### Images
- Critères : `width > 500px` ET URLs absolues (`https://...`)
- Tri : Par surface décroissante (`width × height`)
- Top 3 uniquement

## 🔍 Debugging et développement

### Logs
```python
print_console(msg)  # Format: "YYYY-MM-DD HH:MM:SS msg"
```
✅ Utiliser systématiquement au lieu de `print()`

### Points de défaillance courants
1. **Dates mal formatées** → Vérifier format ISO 8601
2. **Chemins relatifs** → Utiliser `SCRIPT_DIR`, `PROJECT_ROOT`
3. **Timeout API** → Augmenter paramètre timeout
4. **Images non trouvées** → Vérifier critère largeur 500px

### Tests (à développer)
```bash
pytest tests/  # Pas encore implémenté
```

## 🔐 Politique de sauvegarde (CRITIQUE)

**TOUJOURS créer une sauvegarde avant modification** :
```bash
cp "scripts/script.py" "archives/script_$(date +%Y%m%d_%H%M%S).py"
```
Appliqué à TOUS les fichiers `.py` du projet.

## ⚠️ Règles strictes pour AI agents


### À NE JAMAIS FAIRE
- ❌ Modifier les clés JSON françaises sans mise à jour globale
- ❌ Utiliser chemins relatifs au lieu des constantes `*_DIR`
- ❌ Hardcoder credentials (toujours via `.env`)
- ❌ Changer format de dates sans adapter le parsing
- ❌ Supprimer la fonction `print_console()`
- ❌ Déplacer ou supprimer README.md ou tout fichier critique (requirements.txt, .env.example, etc.) du top niveau du projet. Ces fichiers doivent toujours rester à la racine pour la clarté, la portabilité et la compatibilité CI/CD.

### À TOUJOURS FAIRE
- ✅ Créer backup dans `archives/` avant modification
- ✅ Utiliser chemins absolus via `PROJECT_ROOT`
- ✅ Préserver langue française dans messages
- ✅ Tester avec/sans arguments CLI
- ✅ Documenter changements dans CHANGELOG.md

## 📚 Documentation de référence

- **Architecture complète :** `ARCHITECTURE.md` (diagrammes, flux, décisions)
- **Structure détaillée :** `STRUCTURE.md` (organisation fichiers)
- **Guide utilisateur :** `README.md` (installation, usage)
- **Guide scripts :** `scripts/USAGE.md` (commandes détaillées)
- **Historique :** `CHANGELOG.md` (restructuration v2.0)

## 🚀 Évolutions en cours / à venir

- [ ] Tests unitaires (pytest)
- [ ] Parallélisation (asyncio)
- [ ] CLI unifié avec argparse
- [ ] Migration PostgreSQL
- [ ] CI/CD GitHub Actions

Pour questions ou clarifications, référez-vous aux fichiers de documentation ou contactez : patrick.ostertag@gmail.com
cd /chemin/vers/AnalyseActualités
python3 scripts/Get_data_from_JSONFile_AskSummary.py 2026-01-01 2026-01-31
```

### Script principal (dates par défaut : 1er du mois → aujourd'hui)
```bash
python3 scripts/Get_data_from_JSONFile_AskSummary.py
```

### Extraction texte brut
```bash
python3 scripts/Get_htmlText_From_JSONFile.py
# Ouvre dialog GUI pour sélectionner flux JSON
```

### Conversion JSON → Markdown
```bash
python3 scripts/articles_json_to_markdown.py
# Dialog GUI pour sélectionner fichier JSON source
```

- **Project-specific patterns and constraints:**
  - GUI-first workflow: most scripts expect interactive file selection. If automating, adapt the script to accept CLI args or bypass `tkinter`.
  - Hardcoded output names: scripts commonly write fixed outputs like `articles.json` or `all_articles.txt`. When changing filenames, update callers and documentation.
  - French keys and messages: keys such as `Résumé` and `Date de publication` are used across scripts — rename carefully.
  - LLM usage: `Get_data_from_JSONFile_AskSummary.py` calls Infomaniak's EurIA API (Qwen3 model) via HTTP POST and expects `choices[0].message.content` in the response. Follow the existing retry/backoff approach when modifying.

- **Debugging & development tips:**
  - Use `print_console()` (defined in scripts) to add timestamped logs instead of ad-hoc prints.
  - For parsing issues, check `date_published` formatting first — many errors stem from unexpected date strings.
  - To run headless CI tests, modify or wrap `tkinter` usage; for quick debugging you can pass paths by editing the `filedialog` calls.

- **Backup policy:**
  - **ALWAYS create a backup** before modifying any Python file. Copy the file to `Anciennes versions/` with a timestamp suffix.
  - Command template: `cp "file.py" "Anciennes versions/file_$(date +%Y%m%d_%H%M%S).py"`
  - This applies to all `.py` files in the repository root and subdirectories.

- **What to avoid / merge rules for AI agents:**
  - Do not change the public JSON keys (`Date de publication`, `Résumé`, `URL`, `Sources`) without updating all scripts that read/write them.
  - Preserve French messages and date formats in outputs unless instructed otherwise.
  - When adding dependencies (e.g., `requirements.txt`), mention install steps in this file.

If anything is missing or you want agents to follow a stricter workflow (CLI-only, add tests, or CI), tell me which direction and I will update this document.
